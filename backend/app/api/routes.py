"""Rotas /api/* — formato exato do CONTRACT.md (o frontend consome literalmente)."""
from __future__ import annotations

import json
import re
import time
from typing import Literal, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .. import config, llm
from ..integrations import revgas
from ..agent import handoff, memory, orchestrator, text_to_sql
from ..agent.deps import build_index, conn_rw
from ..agent.schemas import ChatResponse

router = APIRouter(prefix="/api")


class NovaConversa(BaseModel):
    canal: str = "web"


class ChatIn(BaseModel):
    conversa_id: str = Field(..., min_length=1, max_length=64)
    mensagem: str = Field(..., min_length=1, max_length=2000)


class SqlIn(BaseModel):
    pergunta: str = Field(..., min_length=3, max_length=500)


def _modo() -> str:
    return "mock" if llm.is_mock() else "anthropic"


@router.get("/health")
def health():
    return {"ok": True, "modo_llm": _modo()}


@router.post("/conversas")
def criar_conversa(body: Optional[NovaConversa] = Body(None)):
    canal = (body.canal if body else "web") or "web"
    return {"conversa_id": memory.criar_conversa(canal=canal)}


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatIn):
    return orchestrator.handle_message(body.conversa_id, body.mensagem)


@router.get("/conversas/{conversa_id}")
def obter_conversa(conversa_id: str):
    conv = memory.obter_conversa(conversa_id)
    if not conv:
        raise HTTPException(404, "Conversa não encontrada.")
    return conv


@router.get("/conversas/{conversa_id}/mensagens")
def mensagens(conversa_id: str):
    if not memory.obter_conversa(conversa_id):
        raise HTTPException(404, "Conversa não encontrada.")
    out = []
    for m in memory.listar_mensagens(conversa_id):
        item = {"papel": m["papel"], "conteudo": m["conteudo"], "criado_em": m["criado_em"]}
        if m["papel"] != "user":  # campo opcional para o front (bot | atendente | sistema)
            try:
                autor = json.loads(m["meta_json"] or "{}").get("autor")
            except ValueError:
                autor = None
            item["autor"] = autor or ("sistema" if m["papel"] == "system" else "bot")
        out.append(item)
    return out


@router.get("/handoffs")
def listar_handoffs(status: Optional[Literal["pendente", "em_atendimento", "resolvido"]] = Query(None)):
    return handoff.listar(status)


def _mudar(hid: int, status: str):
    h = handoff.mudar_status(hid, status)
    if not h:
        raise HTTPException(404, "Handoff não encontrado.")
    return h


@router.post("/handoffs/{hid}/assumir")
def assumir(hid: int):
    return _mudar(hid, "em_atendimento")


@router.post("/handoffs/{hid}/resolver")
def resolver(hid: int):
    return _mudar(hid, "resolvido")


@router.post("/atendente/mensagem")
def mensagem_atendente(body: ChatIn):
    if not memory.obter_conversa(body.conversa_id):
        raise HTTPException(404, "Conversa não encontrada.")
    memory.definir_status(body.conversa_id, "humano")
    memory.salvar_mensagem(body.conversa_id, "assistant", body.mensagem, meta={"autor": "atendente"})
    return {"ok": True, "conversa_id": body.conversa_id, "status_conversa": "humano"}


@router.get("/leads")
def leads():
    with conn_rw() as c:
        rows = c.execute(
            "SELECT id, nome, telefone, email, interesse, origem, estagio, score, criado_em, atualizado_em "
            "FROM leads ORDER BY atualizado_em DESC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/metricas")
def metricas():
    with conn_rw() as c:
        conversas = c.execute("SELECT COUNT(*) FROM conversas").fetchone()[0]
        pend = c.execute("SELECT COUNT(*) FROM handoffs WHERE status = 'pendente'").fetchone()[0]
        estagios = {r["estagio"]: r["qtd"] for r in c.execute(
            "SELECT estagio, COUNT(*) AS qtd FROM leads GROUP BY estagio").fetchall()}
        metas = c.execute(
            "SELECT meta_json FROM mensagens WHERE papel = 'assistant' AND meta_json IS NOT NULL").fetchall()
    contagem: dict[str, int] = {}
    for (mj,) in metas:
        try:
            it = json.loads(mj).get("intencao")
        except (ValueError, AttributeError):
            continue
        if it:
            contagem[it] = contagem.get(it, 0) + 1
    for e in ("novo", "qualificado", "proposta", "ganho", "perdido"):
        estagios.setdefault(e, 0)
    top = sorted(contagem.items(), key=lambda x: -x[1])[:10]
    return {"conversas": conversas, "handoffs_pendentes": pend, "leads_por_estagio": estagios,
            "intencoes_top": [{"intencao": i, "qtd": q} for i, q in top]}


@router.post("/sql")
def sql(body: SqlIn):
    try:
        res = text_to_sql.executar(body.pergunta, views_permitidas=text_to_sql.VIEWS_TODAS)
    except text_to_sql.SQLInvalido as e:
        raise HTTPException(400, f"Consulta bloqueada pelo validador: {e}")
    return res


# ---------------------------------------------------------------------------
# RevGás
# ---------------------------------------------------------------------------
@router.get("/vendas-revgas")
def vendas_revgas():
    return revgas.listar_vendas()


@router.get("/revgas/status")
def revgas_status():
    return revgas.status()  # nunca devolve a chave, só se ela existe


# ---------------------------------------------------------------------------
# Integração n8n
# ---------------------------------------------------------------------------
class LeadPatch(BaseModel):
    estagio: Literal["novo", "qualificado", "proposta", "ganho", "perdido"]


@router.patch("/leads/{lead_id}")
def atualizar_lead(lead_id: int, body: LeadPatch):
    with conn_rw() as c:
        cur = c.execute("UPDATE leads SET estagio = ?, atualizado_em = datetime('now') WHERE id = ?", (body.estagio, lead_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "Lead não encontrado.")
        r = c.execute("SELECT id, nome, telefone, email, interesse, origem, estagio, score, criado_em, atualizado_em "
                      "FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return dict(r)


# acessório sugerido no pós-venda, pela categoria/porte do primeiro item (relação produto → acessório)
_SUGESTOES_POS_VENDA = [
    (r"P45|45 ?KG|P20|20 ?KG|CENTRAL", ["ACE-MANG-PIGTAIL", "ACE-KIT-REG-DUPLO"]),
    (r"GLP|G[AÁ]S|BOTIJ|P13|13 ?KG", ["ACE-KIT-REG", "ACE-REG", "ACE-MANG"]),
    (r"[AÁ]GUA|GAL[AÃ]O", ["ACE-BOMBA", "ACE-SUPORTE", "ACE-TORNEIRA"]),
]


def _sugestao(c, itens: list[dict]) -> dict | None:
    if not itens:
        return None
    skus_pedido = {i["sku"] for i in itens}
    nome = (itens[0]["nome"] or "").upper()
    for padrao, skus in _SUGESTOES_POS_VENDA:
        if re.search(padrao, nome):
            for sku in skus:
                if sku in skus_pedido:
                    continue
                r = c.execute("SELECT sku, nome, preco FROM produtos WHERE sku = ? AND ativo = 1", (sku,)).fetchone()
                if r:
                    return dict(r)
    return None


@router.get("/automacoes/pedidos-entregues")
def pedidos_entregues(dias: int = Query(1, ge=1, le=90), x_flow_token: Optional[str] = Header(None)):
    if config.FLOW_AUTOMACAO_TOKEN and x_flow_token != config.FLOW_AUTOMACAO_TOKEN:
        raise HTTPException(401, "Token de automação inválido.")
    with conn_rw() as c:
        ref = c.execute("SELECT MAX(COALESCE(previsao_entrega, criado_em)) FROM pedidos WHERE status = 'entregue'").fetchone()[0]
        if not ref:
            return {"pedidos": []}
        rows = c.execute(
            """SELECT pe.id, pe.numero, cl.nome AS cliente_nome, cl.email, cl.telefone
               FROM pedidos pe JOIN clientes cl ON cl.id = pe.cliente_id
               WHERE pe.status = 'entregue'
                 AND datetime(COALESCE(pe.previsao_entrega, pe.criado_em)) > datetime(?, ?)
               ORDER BY COALESCE(pe.previsao_entrega, pe.criado_em) DESC""",
            (ref, f"-{dias} days")).fetchall()
        out = []
        for r in rows:
            itens = [dict(i) for i in c.execute(
                """SELECT p.sku, p.nome, i.quantidade FROM itens_pedido i JOIN produtos p ON p.id = i.produto_id
                   WHERE i.pedido_id = ? ORDER BY i.id""", (r["id"],)).fetchall()]
            out.append({"numero": r["numero"], "cliente_nome": r["cliente_nome"], "email": r["email"],
                        "telefone": r["telefone"], "itens": itens, "sugestao": _sugestao(c, itens)})
    return {"pedidos": out}


@router.post("/admin/reindex")
def reindex():
    t0 = time.perf_counter()
    ok = build_index(force=True)
    return {"ok": ok, "segundos": round(time.perf_counter() - t0, 2),
            "detalhe": None if ok else "Módulo RAG indisponível (usando busca simples)."}
