"""Transformações de consulta: Query Rewriting, Multi-Query, Query Expansion e HyDE.

Cada função tem caminho LLM (via app.llm) e caminho mock determinístico (heurísticas + dicionário
de domínio). Em caso de erro do LLM, cai no mock — a recuperação nunca quebra por causa do LLM.
"""
from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from .. import llm
from .text import SINONIMOS_PALAVRA, TOPICOS, canonicos, content_words, match_topicos, normalize

log = logging.getLogger(__name__)

_ANAFORA = re.compile(
    r"\b(esse produto|este produto|esse modelo|este modelo|esse aparelho|esse item|"
    r"esse|essa|este|esta|ele|ela|dele|dela|nele|nela|isso|isto|aquele|aquela|o mesmo|a mesma)\b",
    re.IGNORECASE,
)
_PEDIDO = re.compile(r"\b(pedido|compra|encomenda|entrega|chega|chegar|rastreio|enviado)\b", re.IGNORECASE)


def _safe(fn, fallback):
    try:
        return fn()
    except Exception as e:  # pragma: no cover - depende de rede
        log.warning("LLM falhou em %s: %s", getattr(fn, "__name__", "?"), e)
        return fallback()


# ---------------------------------------------------------------------------
# Query Rewriting
# ---------------------------------------------------------------------------
def _contexto_produto(contexto: dict, nomes_por_sku: dict[str, str]) -> str | None:
    for k in ("produto_nome", "produto"):
        v = contexto.get(k)
        if isinstance(v, dict):
            v = v.get("nome") or v.get("sku")
        if v:
            return nomes_por_sku.get(str(v).upper(), str(v))
    sku = contexto.get("produto_sku") or contexto.get("sku")
    if sku:
        return nomes_por_sku.get(str(sku).upper(), str(sku))
    return None


def _contexto_pedido(contexto: dict) -> str | None:
    v = contexto.get("pedido_numero") or contexto.get("pedido") or contexto.get("numero_pedido")
    if isinstance(v, dict):
        v = v.get("numero")
    return str(v) if v else None


def rewrite_mock(query: str, contexto: dict, nomes_por_sku: dict[str, str]) -> str | None:
    q = query.strip()
    produto = _contexto_produto(contexto, nomes_por_sku)
    pedido = _contexto_pedido(contexto)
    novo = q
    if produto and _ANAFORA.search(novo) and normalize(produto) not in normalize(novo):
        novo = _ANAFORA.sub(lambda m: f"o {produto}", novo, count=1)
        novo = re.sub(r"^\s*e\s+(?=o )", "", novo, flags=re.IGNORECASE)
        novo = re.sub(r"\b(d|n)o o ", lambda m: m.group(1) + "o ", novo)
        novo = novo[0].upper() + novo[1:]
    elif produto and len(content_words(q)) <= 4 and normalize(produto) not in normalize(q):
        # pergunta curta e elíptica ("E a garantia?") -> ancora no produto da conversa
        novo = re.sub(r"^\s*e\s+", "", q, flags=re.IGNORECASE).rstrip("?").strip()
        novo = f"{novo[0].upper() + novo[1:]} do {produto}?" if novo else q
    if pedido and _PEDIDO.search(q) and pedido not in novo:
        novo = f"{novo.rstrip('?').rstrip()} (pedido {pedido})?"
    return novo if novo != q else None


_SYS_REWRITE = (
    "Você reescreve a última mensagem de um cliente da Flow (revenda de gás GLP e água mineral) como uma consulta "
    "autossuficiente para busca, resolvendo pronomes ('esse', 'ele', 'isso') com o contexto da conversa. "
    "Não inclua CPF/CNPJ nem dados pessoais. Responda SOMENTE com a consulta reescrita, em português."
)


def rewrite(query: str, contexto: dict | None, nomes_por_sku: dict[str, str]) -> str | None:
    contexto = {k: v for k, v in (contexto or {}).items() if v not in (None, "", [], {})}
    if not contexto:
        return None
    mock = rewrite_mock(query, contexto, nomes_por_sku)
    if llm.is_mock():
        return mock
    seguro = {k: v for k, v in contexto.items() if k not in ("cpf_cnpj", "cliente_id", "cpf", "cnpj")}
    produto = _contexto_produto(contexto, nomes_por_sku)
    if produto:
        seguro["produto"] = produto
    user = f"Contexto da conversa: {seguro}\nMensagem: {query}"

    def _llm():
        r = llm.complete(_SYS_REWRITE, user, max_tokens=200, mock=lambda _u: mock or query).strip()
        return r.strip('"') if r and normalize(r) != normalize(query) else None

    return _safe(_llm, lambda: mock)


# ---------------------------------------------------------------------------
# Multi-Query
# ---------------------------------------------------------------------------
class Consultas(BaseModel):
    consultas: list[str] = Field(default_factory=list)


def multi_query_mock(query: str) -> list[str]:
    palavras = content_words(query)
    chave = " ".join(palavras) or query
    topicos = match_topicos(query)
    out: list[str] = []
    # 1) versão por palavras-chave
    out.append(chave)
    # 2) reformulação "política/regra" orientada ao tópico
    if topicos:
        out.append(f"Qual é a política da Flow sobre {topicos[0]['nome']}? {chave}")
    else:
        out.append(f"Informações da Flow sobre {chave}")
    # 3) troca por sinônimos de domínio
    sin = list(canonicos(query))
    for t in topicos[:2]:
        sin.extend(t["sinonimos"][:3])
    for w in palavras:
        sin.extend(SINONIMOS_PALAVRA.get(w, []))
    if sin:
        out.append(f"{chave} {' '.join(dict.fromkeys(sin))}")
    else:
        out.append(f"Dúvida de cliente: {query.strip()}")
    vistos, final = {normalize(query)}, []
    for q in out:
        if normalize(q) not in vistos:
            vistos.add(normalize(q))
            final.append(q)
    while len(final) < 3:
        final.append(f"Como a Flow responde: {query.strip()} ({len(final) + 1})")
    return final[:3]


_SYS_MQ = (
    "Gere exatamente 3 reformulações diferentes da pergunta de um cliente da Flow (revenda de gás GLP "
    "e água mineral; botijão = P13 = gás de cozinha; galão = água 20L; P45 = cilindro 45 kg) "
    "para melhorar a busca na base de conhecimento: uma com palavras-chave, uma formal "
    "(como estaria escrita numa política) e uma com sinônimos. Português do Brasil."
)


def multi_query(query: str) -> list[str]:
    if llm.is_mock():
        return multi_query_mock(query)

    def _llm():
        r = llm.structured(_SYS_MQ, query, Consultas, max_tokens=400,
                           mock=lambda _u: Consultas(consultas=multi_query_mock(query)))
        qs = [q.strip() for q in r.consultas if q and q.strip()][:3]
        return qs if len(qs) == 3 else (qs + multi_query_mock(query))[:3]

    return _safe(_llm, lambda: multi_query_mock(query))


# ---------------------------------------------------------------------------
# Query Expansion
# ---------------------------------------------------------------------------
class Termos(BaseModel):
    termos: list[str] = Field(default_factory=list)


def expansion_mock(query: str) -> list[str]:
    termos: list[str] = list(canonicos(query))  # botijão -> P13, galão -> água 20L, ...
    for t in match_topicos(query):
        termos.extend(t["sinonimos"])
    for w in content_words(query):
        termos.extend(SINONIMOS_PALAVRA.get(w, []))
    qn = normalize(query)
    out = []
    for t in dict.fromkeys(termos):
        if normalize(t) not in qn:
            out.append(t)
    return out[:10]


_SYS_EXP = (
    "Liste de 3 a 6 termos ou sinônimos do domínio de revenda de gás GLP e água mineral (produtos, "
    "políticas, pagamentos; 'gás' aqui é GLP de cozinha, nunca gasolina) que ajudam a encontrar a resposta para a pergunta do cliente. Português do Brasil, "
    "termos curtos, sem repetir palavras da pergunta."
)


def expansion(query: str) -> list[str]:
    base = expansion_mock(query)
    if llm.is_mock():
        return base

    def _llm():
        r = llm.structured(_SYS_EXP, query, Termos, max_tokens=200, mock=lambda _u: Termos())
        extra = [t.strip() for t in r.termos if t and t.strip()]
        return list(dict.fromkeys(base + extra))[:10]

    return _safe(_llm, lambda: base)


# ---------------------------------------------------------------------------
# HyDE
# ---------------------------------------------------------------------------
def hyde_mock(query: str) -> str:
    topicos = match_topicos(query)
    pergunta = query.strip().rstrip("?")
    if topicos:
        corpo = " ".join(t["hyde"] for t in topicos[:2])
    else:
        corpo = ("A Flow responde a esta dúvida na sua base de conhecimento: catálogo comentado, políticas "
                 "de troca, garantia, frete e pagamento, FAQ e manuais dos produtos.")
    return f"Pergunta: {pergunta}. Resposta: {corpo}"


_SYS_HYDE = (
    "Escreva um parágrafo curto (até 90 palavras), em português do Brasil, que seria a resposta ideal "
    "encontrada na base de conhecimento de uma revenda de gás GLP e água mineral (Flow, filiais em Teresina, "
    "Parnaíba e São Luís) para a pergunta. Escreva como trecho de política/FAQ, sem saudações. "
    "Pode ser hipotético: ele será usado apenas para busca semântica."
)


def hyde(query: str) -> str:
    if llm.is_mock():
        return hyde_mock(query)

    def _llm():
        return llm.complete(_SYS_HYDE, query, max_tokens=300, mock=hyde_mock) or hyde_mock(query)

    return _safe(_llm, lambda: hyde_mock(query))


__all__ = ["rewrite", "multi_query", "expansion", "hyde", "TOPICOS"]
