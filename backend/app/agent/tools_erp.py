"""Passo 4 — Ferramentas do ERP para o Agentic RAG (tool calling).

ERP = API RevGás (via `app.integrations.revgas`), com fallback no SQLite local.
Regras de segurança aplicadas AQUI (e não no prompt), valendo nos dois modos:
- leitura local sempre por `get_readonly_conn`; só lead, handoff e venda escrevem;
- nenhuma consulta devolve `preco_minimo`;
- pedido/financeiro exigem CPF/CNPJ verificado na memória e só retornam dados DO PRÓPRIO cliente;
- `criar_venda` só executa com carrinho + endereço + pagamento completos E confirmação explícita do cliente.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import config
from ..integrations import revgas
from .deps import conn_ro, conn_rw, normalizar, retrieve
from .guardrails import formatar_brl, mascarar_doc
from .nlu import cnpj_valido, cpf_valido, so_digitos

STATUS_PEDIDO = {
    "aguardando_pagamento": "aguardando pagamento",
    "pago": "pagamento confirmado",
    "separacao": "em separação",
    "enviado": "saiu para entrega",
    "entregue": "entregue",
    "cancelado": "cancelado",
}


@dataclass
class Contexto:
    """Estado compartilhado entre as ferramentas durante UMA mensagem."""
    conversa_id: str
    slots: dict
    canal: str = "web"
    ferramentas: list[dict] = field(default_factory=list)
    chunks: list[Any] = field(default_factory=list)
    retrieval: Any = None
    sql: str | None = None
    guardrails: list[dict] = field(default_factory=list)
    handoff: dict | None = None
    lead: dict | None = None
    venda: dict | None = None
    precos_minimos: list[float] = field(default_factory=list)
    tecnicas: list[str] = field(default_factory=list)

    def tec(self, *nomes: str) -> None:
        for n in nomes:
            if n not in self.tecnicas:
                self.tecnicas.append(n)


# ---------------------------------------------------------------------------
# Catálogo (RevGás → fallback SQLite)
# ---------------------------------------------------------------------------
def _publico(p: dict) -> dict:
    preco = p.get("preco")
    return {"revgas_id": p["revgas_id"], "nome": p.get("rotulo") or p["nome"], "descricao_revgas": p["nome"],
            "categoria": p.get("categoria"), "preco": preco, "preco_formatado": formatar_brl(preco) if preco else "sob consulta",
            "estoque_central": p.get("estoque"), "container_id": p.get("container_id")}


def _buscar_local(termo: str, limite: int) -> list[dict]:
    """Fallback: catálogo do SQLite (seed), no mesmo formato do adaptador."""
    try:
        with conn_ro() as c:
            rows = c.execute(
                "SELECT p.revgas_id, p.nome, p.preco, p.container_revgas_id, c.nome AS categoria FROM produtos p "
                "JOIN categorias c ON c.id = p.categoria_id WHERE p.ativo = 1").fetchall()
    except Exception:
        return []
    q = [t for t in re.findall(r"[a-z0-9]+", normalizar(termo)) if len(t) > 1]
    pont = []
    for r in rows:
        nome = normalizar(r["nome"])
        s = sum(1 for t in q if t in nome)
        if s and r["revgas_id"]:
            pont.append((s, {"revgas_id": r["revgas_id"], "nome": r["nome"], "rotulo": r["nome"], "categoria": r["categoria"],
                             "preco": r["preco"], "estoque": None, "container_id": r["container_revgas_id"]}))
    pont.sort(key=lambda x: -x[0])
    return [p for _, p in pont[:limite]]


def buscar_produtos(termo: str, limite: int = 5) -> list[dict]:
    try:
        r = revgas.buscar_produtos(termo, limite=limite)
    except Exception:
        r = []
    return r or _buscar_local(termo, limite)


def _estoque_filiais(revgas_id: int) -> list[dict]:
    try:
        with conn_ro() as c:
            rows = c.execute(
                """SELECT f.nome AS filial, f.cidade, e.quantidade FROM estoque e
                   JOIN filiais f ON f.id = e.filial_id JOIN produtos p ON p.id = e.produto_id
                   WHERE p.revgas_id = ? ORDER BY f.id""", (revgas_id,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _precos_minimos(revgas_ids: list[int]) -> list[float]:
    """Uso INTERNO do guardrail de saída (nunca vai para o cliente nem para o LLM)."""
    if not revgas_ids:
        return []
    try:
        with conn_ro() as c:
            q = f"SELECT preco_minimo FROM produtos WHERE revgas_id IN ({','.join('?' * len(revgas_ids))})"
            return [r[0] for r in c.execute(q, revgas_ids).fetchall() if r[0]]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------
def t_buscar_conhecimento(ctx: Contexto, consulta: str, k: int = 4) -> dict:
    contexto = {"cliente": ctx.slots.get("cliente_nome"), "pedido": ctx.slots.get("pedido_numero"),
                "produto": ctx.slots.get("produto_nome"), "filial": ctx.slots.get("filial")}
    chunks, trace = retrieve(consulta, k=k, contexto={k_: v for k_, v in contexto.items() if v})
    ctx.chunks.extend(chunks)
    ctx.retrieval = trace
    ctx.tec("agentic_rag")
    return {"trechos": [{"titulo": c.titulo, "texto": c.texto[:1200], "score": round(float(c.score), 3)} for c in chunks]}


def t_consultar_cliente(ctx: Contexto, cpf_cnpj: str) -> dict:
    doc = so_digitos(cpf_cnpj)
    # verificação: o documento precisa ter sido informado pelo próprio usuário nesta conversa
    if doc != so_digitos(ctx.slots.get("cpf_cnpj") or ""):
        return {"erro": "Documento não informado pelo cliente nesta conversa. Peça o CPF/CNPJ ao cliente."}
    if not (cpf_valido(doc) or cnpj_valido(doc)):
        return {"erro": "CPF/CNPJ inválido (dígito verificador não confere)."}
    with conn_ro() as c:
        r = c.execute("SELECT * FROM clientes WHERE cpf_cnpj = ?", (doc,)).fetchone()
    if not r:
        return {"encontrado": False, "mensagem": "Nenhum cadastro com esse documento."}
    r = dict(r)
    ctx.slots.update(cliente_id=r["id"], cliente_nome=r["nome"], cpf_verificado=True)
    # endereço cadastrado vira sugestão para o fluxo de venda (CRM local)
    if r.get("endereco") and r.get("numero") and not ctx.slots.get("endereco_cadastro"):
        ctx.slots["endereco_cadastro"] = {"rua": r["endereco"], "numero": r["numero"], "bairro": r.get("bairro"),
                                          "cidade": r.get("cidade"), "uf": r.get("uf")}
    return {"encontrado": True, "nome": r["nome"], "tipo": r["tipo"], "cidade": r.get("cidade"), "uf": r.get("uf"),
            "documento": mascarar_doc(doc)}


def _exige_cliente(ctx: Contexto) -> dict | None:
    if not (ctx.slots.get("cpf_verificado") and ctx.slots.get("cliente_id")):
        return {"erro": "autenticacao_necessaria",
                "mensagem": "Para consultar pedidos e boletos preciso do CPF/CNPJ do titular."}
    return None


def t_consultar_pedido(ctx: Contexto, numero_pedido: str | None = None) -> dict:
    if (e := _exige_cliente(ctx)):
        return e
    cid = ctx.slots["cliente_id"]
    with conn_ro() as c:
        if numero_pedido:
            r = c.execute(
                """SELECT pe.id, pe.numero, pe.status, pe.valor_total, pe.criado_em, pe.previsao_entrega,
                          pe.codigo_rastreio, f.nome AS filial
                   FROM pedidos pe JOIN filiais f ON f.id = pe.filial_id
                   WHERE pe.numero = ? AND pe.cliente_id = ?""",
                (numero_pedido.upper(), cid),
            ).fetchone()
            if not r:
                # não revela se o pedido existe para outra pessoa
                return {"encontrado": False, "mensagem": f"Não encontrei o pedido {numero_pedido} no seu cadastro."}
            itens = c.execute(
                """SELECT p.nome, i.quantidade, i.preco_unitario FROM itens_pedido i
                   JOIN produtos p ON p.id = i.produto_id WHERE i.pedido_id = ?""", (r["id"],)
            ).fetchall()
            ctx.slots["pedido_numero"] = r["numero"]
            d = dict(r)
            d.pop("id")
            d["status_descricao"] = STATUS_PEDIDO.get(d["status"], d["status"])
            d["itens"] = [dict(i) for i in itens]
            return {"encontrado": True, "pedido": d}
        rows = c.execute(
            """SELECT numero, status, valor_total, criado_em, previsao_entrega FROM pedidos
               WHERE cliente_id = ? ORDER BY criado_em DESC LIMIT 5""", (cid,)
        ).fetchall()
    return {"encontrado": bool(rows), "pedidos": [dict(r) | {"status_descricao": STATUS_PEDIDO.get(r["status"], r["status"])} for r in rows]}


def t_consultar_estoque(ctx: Contexto, produto: str, filial: str | None = None) -> dict:
    prods = buscar_produtos(produto, limite=3)
    if not prods:
        return {"encontrado": False, "mensagem": f"Não encontrei '{produto}' no catálogo."}
    ctx.precos_minimos += _precos_minimos([p["revgas_id"] for p in prods])
    out = []
    for p in prods[:2]:
        est = _estoque_filiais(p["revgas_id"])
        if filial:
            fn = normalizar(filial)
            est = [e for e in est if fn in normalizar(e["cidade"]) or fn in normalizar(e["filial"])] or est
        out.append(_publico(p) | {"estoque_filiais": est})
    ctx.slots.update(produto_sku=str(prods[0]["revgas_id"]), produto_nome=prods[0].get("rotulo") or prods[0]["nome"])
    if filial:
        ctx.slots["filial"] = filial
    return {"encontrado": True, "fonte": revgas.fonte_catalogo(), "produtos": out}


def t_consultar_preco(ctx: Contexto, produto: str) -> dict:
    prods = buscar_produtos(produto, limite=4)
    if not prods:
        return {"encontrado": False, "mensagem": f"Não encontrei '{produto}' no catálogo."}
    ctx.precos_minimos += _precos_minimos([p["revgas_id"] for p in prods])
    ctx.slots.update(produto_sku=str(prods[0]["revgas_id"]), produto_nome=prods[0].get("rotulo") or prods[0]["nome"])
    publicos = [_publico(p) for p in prods]
    vas = None
    if prods[0].get("container_id"):
        v = revgas.obter(int(prods[0]["container_id"]))
        if v and v.get("preco"):
            vas = _publico(v)
    return {"encontrado": True, "fonte": revgas.fonte_catalogo(), "produtos": publicos, "vasilhame": vas}


def t_consultar_financeiro(ctx: Contexto) -> dict:
    if (e := _exige_cliente(ctx)):
        return e
    with conn_ro() as c:
        rows = c.execute(
            """SELECT fi.tipo, fi.valor, fi.vencimento, fi.status, fi.linha_digitavel, pe.numero AS pedido
               FROM financeiro fi LEFT JOIN pedidos pe ON pe.id = fi.pedido_id
               WHERE fi.cliente_id = ? AND fi.status IN ('aberto', 'vencido') ORDER BY fi.vencimento""",
            (ctx.slots["cliente_id"],),
        ).fetchall()
    return {"titulos_em_aberto": [dict(r) for r in rows]}


def calcular_score(interesse: str, *, quantidade: int | None = None, tem_contato: bool = False, pj: bool = False) -> int:
    n = normalizar(interesse or "")
    s = 10
    if pj or re.search(r"\b(empresa|cnpj|restaurante|lanchonete|condominio|padaria|hotel|escola|clinica|ltda)\b", n):
        s += 25
    qtd = quantidade
    if qtd is None:
        m = re.search(r"\b(\d{1,4})\b", n)
        qtd = int(m.group(1)) if m else 1
    s += 30 if qtd >= 10 else 20 if qtd >= 5 else 10 if qtd >= 2 else 0
    if re.search(r"\b(orcamento|cotacao|contrato|mensal|proposta|p45|central)\b", n):
        s += 15
    if re.search(r"\b(urgente|hoje|amanha|essa semana|esta semana)\b", n):
        s += 10
    if tem_contato:
        s += 10
    return min(s, 100)


def disparar_webhook(url: str, payload: dict) -> bool:
    """POST JSON para o n8n (timeout 3s). Falha silenciosa: automação nunca derruba o chat."""
    if not url:
        return False
    try:
        import httpx

        httpx.post(url, json=payload, timeout=3)
        return True
    except Exception:
        return False


def payload_lead(lead_id: int) -> dict | None:
    with conn_rw() as c:
        r = c.execute("SELECT id, nome, telefone, email, interesse, origem, score, estagio FROM leads WHERE id = ?",
                      (lead_id,)).fetchone()
    return dict(r) if r else None


def t_registrar_lead(ctx: Contexto, interesse: str, nome: str | None = None, telefone: str | None = None,
                     email: str | None = None, quantidade: int | None = None) -> dict:
    nome = nome or ctx.slots.get("cliente_nome")
    pj = len(so_digitos(ctx.slots.get("cpf_cnpj") or "")) == 14
    score = calcular_score(interesse, quantidade=quantidade, tem_contato=bool(telefone or email), pj=pj)
    estagio = "qualificado" if score >= 60 else "novo"
    with conn_rw() as c:
        lead_id = ctx.slots.get("lead_id")
        if lead_id:
            c.execute("""UPDATE leads SET interesse = ?, score = MAX(score, ?), estagio = CASE WHEN estagio = 'novo' THEN ? ELSE estagio END,
                         nome = COALESCE(?, nome), telefone = COALESCE(?, telefone), email = COALESCE(?, email),
                         atualizado_em = datetime('now') WHERE id = ?""",
                      (interesse, score, estagio, nome, telefone, email, lead_id))
        else:
            cur = c.execute(
                "INSERT INTO leads (nome, telefone, email, interesse, origem, estagio, score) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (nome, telefone, email, interesse, f"chatbot-{ctx.canal}", estagio, score))
            lead_id = cur.lastrowid
            c.execute("UPDATE conversas SET lead_id = ? WHERE id = ?", (lead_id, ctx.conversa_id))
    ctx.slots["lead_id"] = lead_id
    enviado = disparar_webhook(config.N8N_WEBHOOK_URL, payload_lead(lead_id) or {})
    ctx.lead = {"id": lead_id, "score": score, "estagio": estagio}
    ctx.tec("lead_scoring")
    return {"lead_id": lead_id, "score": score, "estagio": estagio, "webhook_n8n": enviado}


def t_consulta_sql(ctx: Contexto, pergunta: str) -> dict:
    from . import text_to_sql

    views = text_to_sql.VIEWS_TODAS if ctx.canal in {"gestor", "atendente", "interno"} else text_to_sql.VIEWS_PUBLICAS
    try:
        res = text_to_sql.executar(pergunta, views_permitidas=views)
    except text_to_sql.SQLInvalido as e:
        ctx.guardrails.append({"regra": "text_to_sql_validacao", "acao": "bloqueado", "detalhe": str(e)})
        return {"erro": str(e)}
    ctx.sql = res["sql"]
    ctx.tec("text_to_sql")
    return {"sql": res["sql"], "colunas": res["colunas"], "linhas": res["linhas"][:20]}


def t_transferir_atendente(ctx: Contexto, motivo: str) -> dict:
    from . import handoff

    h = handoff.criar_handoff(ctx.conversa_id, motivo, ctx.slots)
    ctx.handoff = {"id": h["id"], "resumo": h["resumo"]}
    ctx.tec("human_handoff")
    return {"handoff_id": h["id"], "status": "pendente"}


# ---- Fluxo de venda ---------------------------------------------------------
def venda_pendencias(slots: dict) -> list[str]:
    """O que ainda falta para fechar a venda, na ordem em que o bot pergunta."""
    falta = []
    carrinho = slots.get("carrinho") or []
    if not carrinho:
        return ["carrinho"]
    if any(i.get("container_id") for i in carrinho if not i.get("eh_vasilhame")) and slots.get("tem_botijao_para_troca") is None:
        falta.append("troca")
    end = slots.get("endereco") or {}
    if not (end.get("rua") and end.get("numero")):
        falta.append("endereco")
    elif not end.get("bairro"):
        falta.append("bairro")
    pag = slots.get("pagamento")
    if pag not in revgas.PAGAMENTOS:
        falta.append("pagamento_cartao" if pag == "CARTAO" else "pagamento")
    elif pag == "MONEY" and slots.get("troco_para") is None:
        falta.append("troco")
    return falta


def t_criar_venda(ctx: Contexto, confirmado: bool = False) -> dict:
    """Cria a venda na RevGás com o carrinho/endereço/pagamento da memória."""
    s = ctx.slots
    falta = venda_pendencias(s)
    if falta:
        return {"erro": "dados_incompletos", "falta": falta}
    if not (confirmado and s.get("venda_confirmada")):
        return {"erro": "confirmacao_necessaria", "mensagem": "Mostre o resumo e peça confirmação explícita ao cliente."}
    end = dict(s["endereco"])
    if not end.get("cidade"):
        cidade = s.get("filial") or "Teresina"
        end["cidade"], end["uf"] = cidade, {"Teresina": "PI", "Parnaíba": "PI", "São Luís": "MA"}.get(cidade, "PI")
    dados = {"carrinho": s["carrinho"], "endereco": end, "pagamento": s["pagamento"],
             "troco_para": s.get("troco_para") or None, "conversa_id": ctx.conversa_id, "cliente_id": s.get("cliente_id")}
    try:
        res = revgas.criar_venda(dados)
    except revgas.VendaInvalida as e:
        return {"erro": "venda_invalida", "mensagem": str(e)}
    ctx.venda = {
        "numero": res["numero"], "status": res["status"], "total": res["total"],
        "itens": [{"nome": i["nome"], "qtd": i["qtd"], "preco": i["preco"], "revgas_id": i["revgas_id"]} for i in s["carrinho"]],
        "endereco": end, "pagamento": revgas.PAGAMENTOS[s["pagamento"]], "payload": res["payload"],
        "troco_para": s.get("troco_para") or None, "previsao": revgas.PREVISAO_ENTREGA,
    }
    ctx.tec("criar_venda")
    return {"numero": res["numero"], "status": res["status"], "total": res["total"], "previsao": revgas.PREVISAO_ENTREGA}


# ---------------------------------------------------------------------------
# Catálogo para o tool calling (schemas Anthropic) + despachante
# ---------------------------------------------------------------------------
def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


TOOLS: list[dict] = [
    {"name": "buscar_conhecimento", "description": "Busca na base de conhecimento da Flow (segurança com gás, troca x compra de vasilhame, áreas e prazos de entrega, pagamento, regulador/mangueira, água, B2B, descontos, LGPD, fidelidade, FAQ, manuais).",
     "input_schema": _schema({"consulta": {"type": "string"}}, ["consulta"])},
    {"name": "consultar_cliente", "description": "Verifica o cadastro do cliente pelo CPF/CNPJ que ELE informou nesta conversa. Necessário antes de consultar pedido ou financeiro.",
     "input_schema": _schema({"cpf_cnpj": {"type": "string"}}, ["cpf_cnpj"])},
    {"name": "consultar_pedido", "description": "Status e previsão de entrega de um pedido do cliente verificado. Sem número, lista os últimos pedidos dele.",
     "input_schema": _schema({"numero_pedido": {"type": "string", "description": "Formato FL-AAAA-NNNNN"}}, [])},
    {"name": "consultar_estoque", "description": "Estoque de um produto (RevGás + por filial: Teresina, Parnaíba, São Luís).",
     "input_schema": _schema({"produto": {"type": "string"}, "filial": {"type": "string"}}, ["produto"])},
    {"name": "consultar_preco", "description": "Preço de tabela de produtos (botijões P13/P20/P45, água 20L, regulador, mangueira...) e do vasilhame associado.",
     "input_schema": _schema({"produto": {"type": "string"}}, ["produto"])},
    {"name": "consultar_financeiro", "description": "Boletos/títulos em aberto ou vencidos do cliente verificado (2ª via).",
     "input_schema": _schema({}, [])},
    {"name": "registrar_lead", "description": "Registra oportunidade comercial (B2B, contrato mensal, P45, grande quantidade) para nutrição.",
     "input_schema": _schema({"interesse": {"type": "string"}, "nome": {"type": "string"}, "telefone": {"type": "string"},
                              "email": {"type": "string"}, "quantidade": {"type": "integer"}}, ["interesse"])},
    {"name": "consulta_sql", "description": "Consulta analítica somente-leitura (Text-to-SQL) sobre catálogo, estoque e, para usuários internos, vendas.",
     "input_schema": _schema({"pergunta": {"type": "string"}}, ["pergunta"])},
    {"name": "transferir_atendente", "description": "Transfere a conversa para um atendente humano.",
     "input_schema": _schema({"motivo": {"type": "string"}}, ["motivo"])},
    {"name": "criar_venda", "description": "Cria a venda na RevGás com o carrinho, endereço e pagamento da memória. SÓ chame depois que o cliente respondeu 'sim' ao resumo do pedido.",
     "input_schema": _schema({"confirmado": {"type": "boolean"}}, ["confirmado"])},
]

_FUNCOES: dict[str, Callable[..., dict]] = {
    "buscar_conhecimento": t_buscar_conhecimento, "consultar_cliente": t_consultar_cliente,
    "consultar_pedido": t_consultar_pedido, "consultar_estoque": t_consultar_estoque,
    "consultar_preco": t_consultar_preco, "consultar_financeiro": t_consultar_financeiro,
    "registrar_lead": t_registrar_lead, "consulta_sql": t_consulta_sql,
    "transferir_atendente": t_transferir_atendente, "criar_venda": t_criar_venda,
}


def _resumo_saida(nome: str, saida: dict) -> str:
    if "erro" in saida:
        return f"erro: {saida.get('mensagem') or saida.get('falta') or saida['erro']}"
    if nome == "criar_venda":
        return f"{saida['numero']} ({saida['status']}) · total {formatar_brl(saida['total'])}"
    if "trechos" in saida:
        return f"{len(saida['trechos'])} trecho(s): " + "; ".join(t["titulo"] for t in saida["trechos"][:3])
    if "produtos" in saida:
        return f"[{saida.get('fonte', '')}] " + "; ".join(f"{p['nome']} ({p['preco_formatado']})" for p in saida["produtos"][:3])
    if "pedido" in saida:
        p = saida["pedido"]
        return f"{p['numero']}: {p['status_descricao']}"
    if "pedidos" in saida:
        return f"{len(saida['pedidos'])} pedido(s)"
    if "titulos_em_aberto" in saida:
        return f"{len(saida['titulos_em_aberto'])} título(s) em aberto"
    if "linhas" in saida:
        return f"{len(saida['linhas'])} linha(s)"
    return json.dumps(saida, ensure_ascii=False, default=str)[:160]


def executar(ctx: Contexto, nome: str, entrada: dict) -> dict:
    fn = _FUNCOES.get(nome)
    if not fn:
        saida = {"erro": f"ferramenta desconhecida: {nome}"}
    else:
        try:
            saida = fn(ctx, **(entrada or {}))
        except TypeError as e:
            saida = {"erro": f"parâmetros inválidos: {e}"}
    entrada_dbg = dict(entrada or {})
    if "cpf_cnpj" in entrada_dbg:
        entrada_dbg["cpf_cnpj"] = mascarar_doc(entrada_dbg["cpf_cnpj"])
    if nome == "criar_venda" and ctx.venda:
        entrada_dbg["payload_revgas"] = ctx.venda["payload"]  # payload enviado (sem chave: ela só vai no header)
    ctx.ferramentas.append({"nome": nome, "entrada": entrada_dbg, "saida_resumo": _resumo_saida(nome, saida)})
    ctx.tec("tool_calling")
    return saida
