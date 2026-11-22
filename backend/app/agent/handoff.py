"""Passo 7 — Human Handoff: grava em `handoffs` com resumo + dados coletados e põe a conversa em 'humano'."""
from __future__ import annotations

import json

from .. import config, llm
from .deps import conn_rw
from .guardrails import mascarar_doc, mascarar_texto
from .memory import definir_status, listar_mensagens, salvar_mensagem
from .tools_erp import disparar_webhook

SYSTEM_RESUMO = """Resuma para um atendente humano da Flow, em até 4 linhas em português, a conversa abaixo:
quem é o cliente (se identificado), o que ele quer, o que o bot já respondeu e o que falta resolver.
Nunca inclua CPF/CNPJ completo."""


def _resumo_mock(historico: str, slots: dict, motivo: str) -> str:
    partes = [f"Motivo: {motivo}."]
    if slots.get("cliente_nome"):
        partes.append(f"Cliente identificado: {slots['cliente_nome']} ({mascarar_doc(slots.get('cpf_cnpj'))}).")
    else:
        partes.append("Cliente ainda não identificado.")
    if slots.get("pedido_numero"):
        partes.append(f"Pedido em discussão: {slots['pedido_numero']}.")
    if slots.get("produto_nome"):
        partes.append(f"Produto de interesse: {slots['produto_nome']}.")
    if slots.get("carrinho"):
        partes.append("Carrinho: " + ", ".join(f"{i['qtd']}x {i['nome']}" for i in slots["carrinho"]) + ".")
    if slots.get("historico_intencoes"):
        partes.append("Assuntos tratados: " + ", ".join(slots["historico_intencoes"]) + ".")
    ultimas = [l for l in historico.splitlines() if l.startswith("Cliente:")][-2:]
    if ultimas:
        partes.append("Últimas falas: " + " | ".join(u.removeprefix("Cliente: ") for u in ultimas))
    return " ".join(partes)


def criar_handoff(conversa_id: str, motivo: str, slots: dict) -> dict:
    msgs = listar_mensagens(conversa_id, limite=12)
    historico = "\n".join(f"{'Cliente' if m['papel'] == 'user' else 'Bot'}: {m['conteudo'][:300]}" for m in msgs)
    resumo = llm.complete(SYSTEM_RESUMO, f"Motivo da transferência: {motivo}\n\n{historico}", max_tokens=400,
                          mock=lambda _u: _resumo_mock(historico, slots, motivo)) or _resumo_mock(historico, slots, motivo)
    resumo = mascarar_texto(resumo)
    dados = {
        "cliente_id": slots.get("cliente_id"), "cliente_nome": slots.get("cliente_nome"),
        "cpf_cnpj": mascarar_doc(slots.get("cpf_cnpj")), "pedido_numero": slots.get("pedido_numero"),
        "produto_sku": slots.get("produto_sku"), "produto_nome": slots.get("produto_nome"),
        "filial": slots.get("filial"), "intencoes": slots.get("historico_intencoes"), "lead_id": slots.get("lead_id"),
        "carrinho": [f"{i['qtd']}x {i['nome']}" for i in slots.get("carrinho") or []] or None,
        "endereco": slots.get("endereco"), "pagamento": slots.get("pagamento"), "ultima_venda": slots.get("ultima_venda"),
        "prioridade": "URGENTE" if motivo.upper().startswith("URGENTE") else None,
    }
    dados = {k: v for k, v in dados.items() if v not in (None, "", [])}
    with conn_rw() as c:
        # evita duplicar: reaproveita handoff ainda pendente da mesma conversa
        row = c.execute("SELECT id FROM handoffs WHERE conversa_id = ? AND status = 'pendente'", (conversa_id,)).fetchone()
        if row:
            hid = row["id"]
            c.execute("UPDATE handoffs SET motivo = ?, resumo = ?, dados_json = ? WHERE id = ?",
                      (motivo, resumo, json.dumps(dados, ensure_ascii=False), hid))
        else:
            hid = c.execute("INSERT INTO handoffs (conversa_id, motivo, resumo, dados_json) VALUES (?, ?, ?, ?)",
                            (conversa_id, motivo, resumo, json.dumps(dados, ensure_ascii=False))).lastrowid
    definir_status(conversa_id, "humano")
    disparar_webhook(config.N8N_HANDOFF_WEBHOOK_URL,
                     {"id": hid, "conversa_id": conversa_id, "motivo": motivo, "resumo": resumo, "dados": dados})
    return {"id": hid, "resumo": resumo, "dados": dados, "motivo": motivo}


def _row(r) -> dict:
    d = dict(r)
    d["dados"] = json.loads(d.pop("dados_json") or "null")
    return d


def listar(status: str | None = None) -> list[dict]:
    with conn_rw() as c:
        if status:
            rows = c.execute("SELECT * FROM handoffs WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM handoffs ORDER BY id DESC").fetchall()
    return [_row(r) for r in rows]


def obter(hid: int) -> dict | None:
    with conn_rw() as c:
        r = c.execute("SELECT * FROM handoffs WHERE id = ?", (hid,)).fetchone()
    return _row(r) if r else None


def mudar_status(hid: int, status: str) -> dict | None:
    h = obter(hid)
    if not h:
        return None
    with conn_rw() as c:
        c.execute("UPDATE handoffs SET status = ? WHERE id = ?", (status, hid))
    if status == "resolvido":
        definir_status(h["conversa_id"], "bot")  # bot volta a atender a conversa
        # mensagem 'system' no fim da conversa: o chat do cliente volta ao modo bot
        salvar_mensagem(h["conversa_id"], "system", "Atendimento humano encerrado. O Flow Assistente voltou a atender.",
                        meta={"autor": "sistema"})
    elif status == "em_atendimento":
        definir_status(h["conversa_id"], "humano")
    return obter(hid)
