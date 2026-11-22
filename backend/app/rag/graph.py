"""GraphRAG — grafo de conhecimento produto–vasilhame–acessório–categoria–marca–política–termo (networkx).

Nós:  produto:<SKU> | categoria:<nome> | marca:<nome> | doc:<doc_id> (políticas, manuais, FAQ...)
      termo:<termo> | chunk:<chunk_id>
Arestas:
  produto–categoria (pertence_a), produto–marca (da_marca),
  produto–vasilhame (usa_vasilhame: GLP P13 -> Vasilhame P13, via container_revgas_id da RevGás),
  acessório–produto (compativel_com: regulador -> P13, pig tail -> P45, bomba -> galão 20L),
  chunk–doc (parte_de), doc–termo (trata_de, pelas tags),
  chunk–produto/categoria/marca/termo (menciona).

Consulta: liga entidades da pergunta a nós (inclusive gírias: botijão -> P13, galão -> água 20L,
P45 -> cilindro 45 kg) e roda PageRank personalizado a partir delas; os chunks com maior massa
formam a lista "grafo" que entra na fusão RRF.
"""
from __future__ import annotations

import re

import networkx as nx

from .chunking import Doc, RawChunk
from .text import canonicos, content_words, normalize, stem

# palavras-chave por categoria do ERP (normalizadas)
CATEGORIA_TERMOS = {
    "Gás GLP": ["gas", "glp", "botijao", "botijoes", "bujao", "cilindro", "p13", "p45", "p20", "gas de cozinha"],
    "Vasilhames": ["vasilhame", "casco", "botijao vazio", "galao vazio", "comodato"],
    "Água": ["agua", "galao", "garrafao", "agua mineral", "20l", "bebedouro"],
    "Acessórios": ["regulador", "mangueira", "pig tail", "abracadeira", "registro", "bomba", "torneira",
                   "suporte para galao", "adaptador", "acessorio", "acessorios"],
    "Outros": ["carvao", "gelo", "vela"],
}

TERMOS = ["seguranca", "vazamento", "cheiro de gas", "193", "registro", "espuma de sabao", "lacre",
          "vasilhame", "troca", "primeira compra", "comodato", "entrega", "prazo", "bairro", "entrega gratis",
          "pix", "dinheiro", "troco", "cartao", "boleto", "segunda via", "desconto", "alcada", "lgpd",
          "privacidade", "fidelidade", "selos", "contrato mensal", "faturamento", "pedido minimo", "cnpj",
          "restaurante", "condominio", "central de gas", "validade", "inmetro", "garantia", "defeito",
          "higienizacao", "bebedouro", "nota fiscal", "atendente", "horario", "filial", "gasolina"]


_GENERICAS = {"gas", "glp", "agua", "mineral", "vasilhame", "saco", "para", "com"}


def _has(texto_norm: str, termo: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(termo) + r"(?![a-z0-9])", texto_norm) is not None


def _nome_chave(nome: str) -> str:
    """Forma curta do nome do produto para casar menções (ex.: 'gas glp p13', 'agua mineral 20l')."""
    n = normalize(re.sub(r"\(.*?\)", "", nome))
    return " ".join(n.split()[:4])


def _codigo(nome: str) -> str | None:
    """Código curto do tamanho (p13, p45, p20...) quando houver."""
    m = re.search(r"\bp(\d{1,2})\b", normalize(nome))
    return f"p{m.group(1)}" if m else None


def build_graph(docs: list[Doc], chunks: list[RawChunk], produtos: list[dict]) -> nx.Graph:
    g = nx.Graph()
    for cat in CATEGORIA_TERMOS:
        g.add_node(f"categoria:{cat}", tipo="categoria", label=cat)
    for t in TERMOS:
        g.add_node(f"termo:{t}", tipo="termo", label=t)

    produtos = [p for p in produtos if p.get("ativo", 1)]
    chaves: dict[str, str] = {}
    por_revgas: dict[int, str] = {}
    for p in produtos:
        pid = f"produto:{p['sku']}"
        g.add_node(pid, tipo="produto", label=p["nome"], sku=p["sku"], nome=p["nome"],
                   codigo=_codigo(p["nome"]), categoria=p.get("categoria"))
        chaves[pid] = _nome_chave(p["nome"])
        if p.get("revgas_id"):
            por_revgas[int(p["revgas_id"])] = pid
        cat = p.get("categoria")
        if cat:
            g.add_node(f"categoria:{cat}", tipo="categoria", label=cat)
            g.add_edge(pid, f"categoria:{cat}", rel="pertence_a", weight=1.0)
        if p.get("marca"):
            mid = f"marca:{normalize(p['marca'])}"
            g.add_node(mid, tipo="marca", label=p["marca"])
            g.add_edge(pid, mid, rel="da_marca", weight=0.3)
    # produto -> vasilhame (RevGás container_id)
    for p in produtos:
        cont = p.get("container_revgas_id")
        if cont and int(cont) in por_revgas:
            g.add_edge(f"produto:{p['sku']}", por_revgas[int(cont)], rel="usa_vasilhame", weight=2.0)
    # acessório -> produto ("Compatível com <nome>" na descrição)
    for p in produtos:
        desc = normalize(re.sub(r"\(.*?\)", "", p.get("descricao") or ""))
        for outro, chave in chaves.items():
            if (outro != f"produto:{p['sku']}" and chave and len(chave.split()) >= 3 and chave in desc
                    and not g.has_edge(f"produto:{p['sku']}", outro)):  # não sobrescreve usa_vasilhame
                g.add_edge(f"produto:{p['sku']}", outro, rel="compativel_com", weight=2.0)

    for d in docs:
        g.add_node(f"doc:{d.doc_id}", tipo="doc", label=d.titulo, doc_tipo=d.tipo)
        for tag in d.tags:
            tn = normalize(tag)
            if f"termo:{tn}" in g:
                g.add_edge(f"doc:{d.doc_id}", f"termo:{tn}", rel="trata_de", weight=1.0)

    marcas = [n for n, data in g.nodes(data=True) if data.get("tipo") == "marca"]
    for c in chunks:
        cid = f"chunk:{c.id}"
        g.add_node(cid, tipo="chunk", label=f"{c.titulo} — {c.secao}")
        g.add_edge(cid, f"doc:{c.doc_id}", rel="parte_de", weight=0.5)
        tn = normalize(re.sub(r"\(.*?\)", "", c.texto))
        tn_full = normalize(c.texto)
        for pid, chave in chaves.items():
            sku = g.nodes[pid]["sku"].lower()
            if sku in tn_full or (chave and len(chave.split()) >= 2 and chave in tn):
                g.add_edge(cid, pid, rel="menciona", weight=1.5)
        for cat, termos in CATEGORIA_TERMOS.items():
            if any(_has(tn_full, t) for t in termos):
                g.add_edge(cid, f"categoria:{cat}", rel="menciona", weight=0.5)
        for t in TERMOS:
            if _has(tn_full, t):
                g.add_edge(cid, f"termo:{t}", rel="menciona", weight=0.8)
        for m in marcas:
            nome_marca = m.split(":", 1)[1]
            if nome_marca not in ("flow", "flow gas", "flow agua") and _has(tn_full, nome_marca):
                g.add_edge(cid, m, rel="menciona", weight=0.5)
    return g


def link_entities(g: nx.Graph, query: str) -> dict[str, float]:
    """Entidades da pergunta -> nós semente (com peso)."""
    expandida = query + " " + " ".join(canonicos(query))  # botijão -> P13, galão -> água 20L...
    qn = normalize(expandida)
    qstems = {stem(w) for w in content_words(expandida)}
    codigos = set(re.findall(r"\bp\d{1,2}\b", qn))
    seeds: dict[str, float] = {}
    for n, data in g.nodes(data=True):
        tipo = data.get("tipo")
        if tipo == "produto":
            if data["sku"].lower() in qn:
                seeds[n] = 3.0
                continue
            if data.get("codigo"):
                if data["codigo"] in codigos:
                    # P13 citado -> produto de gás pesa mais que o vasilhame
                    seeds[n] = 2.0 if data.get("categoria") == "Gás GLP" else 1.0
                continue  # produto com código (P2, P45...) só entra se o código for citado
            nome_words = [w for w in content_words(re.sub(r"\(.*?\)", "", data["nome"]))
                          if not w.isdigit() and len(w) > 2 and w not in _GENERICAS]
            hits = sum(1 for w in nome_words if stem(w) in qstems)
            if nome_words and hits >= min(2, len(nome_words)) and hits / len(nome_words) >= 0.5:
                seeds[n] = 1.0 + hits / len(nome_words)
        elif tipo == "marca":
            nome = n.split(":", 1)[1]
            if nome not in ("flow", "flow gas", "flow agua") and _has(qn, nome):
                seeds[n] = 1.0
        elif tipo == "categoria":
            if any(_has(qn, t) for t in CATEGORIA_TERMOS.get(data["label"], [])):
                seeds[n] = 0.7
        elif tipo == "termo":
            t = data["label"]
            if _has(qn, t) or (" " not in t and len(t) > 3 and stem(t) in qstems):
                seeds[n] = 1.0
    return seeds


def search(g: nx.Graph, query: str, extra_seeds: dict[str, float] | None = None,
           top: int = 15) -> tuple[list[tuple[str, float]], list[str]]:
    """Retorna ([(chunk_id, score)], [rótulos das entidades encontradas])."""
    seeds = link_entities(g, query)
    for n, w in (extra_seeds or {}).items():
        if n in g:
            seeds[n] = max(seeds.get(n, 0), w)
    if not seeds:
        return [], []
    total = sum(seeds.values())
    pers = {n: w / total for n, w in seeds.items()}
    try:
        pr = nx.pagerank(g, alpha=0.75, personalization=pers, weight="weight", max_iter=200, tol=1e-8)
    except Exception:
        pr = {}
        for s, w in seeds.items():  # fallback: vizinhança de 2 saltos
            for n, dist in nx.single_source_shortest_path_length(g, s, cutoff=2).items():
                pr[n] = pr.get(n, 0) + w / (1 + dist)
    ranked = sorted(((n[6:], s) for n, s in pr.items() if n.startswith("chunk:") and s > 0),
                    key=lambda x: -x[1])[:top]
    labels = [g.nodes[n].get("label", n) for n in sorted(seeds, key=lambda x: -seeds[x])]
    return ranked, labels


def vizinhos_produto(g: nx.Graph, sku: str) -> dict[str, list[str]]:
    """Relações de um produto no grafo (útil para o agente: vasilhame e acessórios compatíveis)."""
    pid = f"produto:{sku}"
    out: dict[str, list[str]] = {}
    if pid not in g:
        return out
    for viz in g.neighbors(pid):
        rel = g.edges[pid, viz].get("rel", "")
        if viz.startswith("produto:"):
            out.setdefault(rel, []).append(g.nodes[viz]["sku"])
    return out
