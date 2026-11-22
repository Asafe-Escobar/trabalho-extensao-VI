"""Passo 2 — Conversation Memory (slots persistidos na tabela `memoria`)."""
from __future__ import annotations

import copy
import json
import uuid
from typing import Any

from .deps import conn_rw
from .guardrails import mascarar_doc, mascarar_texto

SLOTS_PADRAO: dict[str, Any] = {
    "cliente_id": None,
    "cliente_nome": None,
    "cpf_cnpj": None,
    "cpf_verificado": False,
    "pedido_numero": None,
    "produto_sku": None,
    "produto_nome": None,
    "filial": None,
    "intencao_anterior": None,
    "resumo": "",
    "historico_intencoes": [],
    "falhas_seguidas": 0,
    "lead_id": None,
    # fluxo de venda (fazer_pedido)
    "carrinho": [],                 # [{revgas_id, nome, qtd, preco, container_id, eh_vasilhame}]
    "tem_botijao_para_troca": None,  # True = troca (só o gás); False = leva o vasilhame
    "endereco": {},                 # {rua, numero, bairro, cidade, uf}
    "endereco_cadastro": None,      # sugestão vinda do CRM local
    "pagamento": None,              # MONEY | PIX | CARTAO_DE_DEBITO | CARTAO_DE_CREDITO
    "troco_para": None,             # 0 = sem troco
    "etapa_venda": None,            # o que o bot perguntou por último
    "venda_confirmada": False,
    "ultima_venda": None,
}


# ---------------------------------------------------------------------------
# Conversas e mensagens
# ---------------------------------------------------------------------------
def criar_conversa(canal: str = "web") -> str:
    cid = str(uuid.uuid4())
    with conn_rw() as c:
        c.execute("INSERT INTO conversas (id, canal, status) VALUES (?, ?, 'bot')", (cid, canal))
        c.execute("INSERT INTO memoria (conversa_id, estado_json) VALUES (?, '{}')", (cid,))
    return cid


def obter_conversa(conversa_id: str) -> dict | None:
    with conn_rw() as c:
        row = c.execute("SELECT * FROM conversas WHERE id = ?", (conversa_id,)).fetchone()
    return dict(row) if row else None


def garantir_conversa(conversa_id: str, canal: str = "web") -> dict:
    conv = obter_conversa(conversa_id)
    if conv:
        return conv
    with conn_rw() as c:
        c.execute("INSERT INTO conversas (id, canal, status) VALUES (?, ?, 'bot')", (conversa_id, canal))
    return obter_conversa(conversa_id)  # type: ignore[return-value]


def definir_status(conversa_id: str, status: str) -> None:
    with conn_rw() as c:
        c.execute("UPDATE conversas SET status = ? WHERE id = ?", (status, conversa_id))


def salvar_mensagem(conversa_id: str, papel: str, conteudo: str, meta: dict | None = None) -> None:
    # PII nunca vai para o histórico em claro (LGPD)
    with conn_rw() as c:
        c.execute(
            "INSERT INTO mensagens (conversa_id, papel, conteudo, meta_json) VALUES (?, ?, ?, ?)",
            (conversa_id, papel, mascarar_texto(conteudo), json.dumps(meta, ensure_ascii=False, default=str) if meta else None),
        )


def listar_mensagens(conversa_id: str, limite: int | None = None) -> list[dict]:
    with conn_rw() as c:
        rows = c.execute(
            "SELECT papel, conteudo, criado_em, meta_json FROM mensagens WHERE conversa_id = ? ORDER BY id",
            (conversa_id,),
        ).fetchall()
    msgs = [dict(r) for r in rows]
    return msgs[-limite:] if limite else msgs


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------
def carregar(conversa_id: str) -> dict:
    with conn_rw() as c:
        row = c.execute("SELECT estado_json FROM memoria WHERE conversa_id = ?", (conversa_id,)).fetchone()
    estado = json.loads(row["estado_json"]) if row and row["estado_json"] else {}
    slots = {**copy.deepcopy(SLOTS_PADRAO), **estado}
    slots["historico_intencoes"] = list(slots.get("historico_intencoes") or [])
    return slots


def salvar(conversa_id: str, slots: dict) -> None:
    estado = json.dumps(slots, ensure_ascii=False, default=str)
    with conn_rw() as c:
        c.execute(
            """INSERT INTO memoria (conversa_id, estado_json, atualizado_em) VALUES (?, ?, datetime('now'))
               ON CONFLICT(conversa_id) DO UPDATE SET estado_json = excluded.estado_json,
               atualizado_em = excluded.atualizado_em""",
            (conversa_id, estado),
        )
        if slots.get("cliente_id"):
            c.execute("UPDATE conversas SET cliente_id = ? WHERE id = ? AND cliente_id IS NULL",
                      (slots["cliente_id"], conversa_id))


def para_debug(slots: dict) -> dict:
    """Visão dos slots para o painel: CPF/CNPJ mascarado, vazios omitidos."""
    out = {}
    for k in ("cliente_id", "cliente_nome", "cpf_cnpj", "cpf_verificado", "pedido_numero", "produto_sku",
              "produto_nome", "filial", "intencao_anterior", "carrinho", "tem_botijao_para_troca", "endereco",
              "pagamento", "troco_para", "etapa_venda", "ultima_venda", "resumo"):
        v = slots.get(k)
        if v in (None, "", [], {}) or (v is False and k != "tem_botijao_para_troca"):
            continue
        if k == "carrinho":
            v = [{"nome": i["nome"], "qtd": i["qtd"], "preco": i["preco"]} for i in v]
        out[k] = mascarar_doc(v) if k == "cpf_cnpj" else v
    if slots.get("etapa_venda"):
        out["aguardando"] = slots["etapa_venda"]  # o front mostra o card de confirmação quando == "confirmacao"
    return out


def atualizar_resumo(slots: dict, intencao: str) -> None:
    hist = slots["historico_intencoes"]
    if not hist or hist[-1] != intencao:
        hist.append(intencao)
    slots["historico_intencoes"] = hist[-8:]
    partes = []
    if slots.get("cliente_nome"):
        partes.append(f"Cliente {slots['cliente_nome']}")
    if slots.get("pedido_numero"):
        partes.append(f"pedido {slots['pedido_numero']}")
    if slots.get("produto_nome"):
        partes.append(f"produto de interesse: {slots['produto_nome']}")
    if slots.get("carrinho"):
        partes.append("carrinho: " + ", ".join(f"{i['qtd']}x {i['nome']}" for i in slots["carrinho"]))
    if slots.get("ultima_venda"):
        partes.append(f"venda criada: {slots['ultima_venda']}")
    partes.append("assuntos: " + ", ".join(slots["historico_intencoes"]))
    slots["resumo"] = "; ".join(partes)
