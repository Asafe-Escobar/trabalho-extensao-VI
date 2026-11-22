"""API REST de Vendas — Flow Gás × RevGás.

Camada direta (sem conversa) para criar e consultar vendas na RevGás: usada pelo n8n, pelo front
ou por qualquer outro sistema. Reaproveita o adaptador `app.integrations.revgas` (modos offline/dryrun/real).

Regras:
- O preço vem SEMPRE do catálogo (servidor); o cliente da API não envia preço nem desconto.
- Gás sem botijão para troca → o vasilhame (container) entra automaticamente no pedido.
- `POST /vendas` aceita `Idempotency-Key`: repetir a mesma chave devolve a mesma venda (não duplica).
- Se `FLOW_API_KEY` estiver definida no .env, todas as rotas exigem o header `X-API-Key`.
"""
from __future__ import annotations

import json
import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator

from .. import config
from ..agent.deps import conn_rw
from ..integrations import revgas

FLOW_API_KEY = getattr(config, "FLOW_API_KEY", None) or os.getenv("FLOW_API_KEY", "")


def exigir_chave(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> None:
    if FLOW_API_KEY and x_api_key != FLOW_API_KEY:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-API-Key ausente ou inválida.")


router = APIRouter(prefix="/api/v1", tags=["Vendas RevGás"], dependencies=[Depends(exigir_chave)])

Pagamento = Literal["MONEY", "PIX", "CARTAO_DE_DEBITO", "CARTAO_DE_CREDITO"]


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class Produto(BaseModel):
    revgas_id: int
    nome: str
    rotulo: str
    categoria: str
    estoque: int
    preco: Optional[float]
    container_id: Optional[int] = None
    disponivel: bool


class ItemIn(BaseModel):
    revgas_id: Optional[int] = Field(None, description="id do produto na RevGás")
    produto: Optional[str] = Field(None, description="ou o nome em texto livre: 'botijão de 13', 'galão de água'")
    quantidade: int = Field(1, ge=1, le=50)

    @model_validator(mode="after")
    def _um_dos_dois(self):
        if self.revgas_id is None and not (self.produto or "").strip():
            raise ValueError("Informe revgas_id ou produto.")
        return self


class EnderecoIn(BaseModel):
    rua: str = Field(..., min_length=2, max_length=120)
    numero: str = Field(..., min_length=1, max_length=10)
    bairro: str = Field(..., min_length=2, max_length=80)
    cidade: str = Field("Teresina", max_length=60)
    uf: str = Field("PI", min_length=2, max_length=2)
    complemento: Optional[str] = Field(None, max_length=80)


class ClienteIn(BaseModel):
    nome: str = Field(..., min_length=2, max_length=80)
    telefone: Optional[str] = Field(None, max_length=20)


class VendaIn(BaseModel):
    itens: list[ItemIn] = Field(..., min_length=1, max_length=20)
    tem_botijao_para_troca: bool = Field(True, description="false = cobra o vasilhame junto com o gás")
    endereco: EnderecoIn
    pagamento: Pagamento
    troco_para: Optional[float] = Field(None, gt=0)
    cliente: Optional[ClienteIn] = None
    observacao: Optional[str] = Field(None, max_length=150)

    model_config = {"json_schema_extra": {"example": {
        "itens": [{"produto": "botijão de 13", "quantidade": 2}, {"revgas_id": 26255, "quantidade": 1}],
        "tem_botijao_para_troca": True,
        "endereco": {"rua": "Rua Augusto Freire", "numero": "2003", "bairro": "Centro", "cidade": "Teresina", "uf": "PI"},
        "pagamento": "PIX",
        "cliente": {"nome": "Maria Souza", "telefone": "86999990000"},
    }}}


class ItemOut(BaseModel):
    revgas_id: int
    nome: str
    quantidade: int
    preco: float
    subtotal: float
    adicionado_automaticamente: bool = False


class Cotacao(BaseModel):
    itens: list[ItemOut]
    total: float
    pagamento: str
    troco: Optional[float]
    avisos: list[str]
    payload_revgas: dict


class VendaOut(Cotacao):
    numero: str
    revgas_id: Optional[int]
    status: Literal["DRYRUN", "ENVIADA", "ERRO"]
    modo: str
    previsao_entrega: str


# ---------------------------------------------------------------------------
# Regras
# ---------------------------------------------------------------------------
def _produto_out(p: dict) -> Produto:
    return Produto(revgas_id=p["revgas_id"], nome=p["nome"], rotulo=p["rotulo"], categoria=p["categoria"],
                   estoque=p["estoque"], preco=p["preco"], container_id=p.get("container_id"),
                   disponivel=p["recomendavel"])


def _resolver(item: ItemIn) -> dict:
    p = revgas.obter(item.revgas_id) if item.revgas_id is not None else revgas.buscar_produto(item.produto or "")
    if not p:
        alvo = item.revgas_id if item.revgas_id is not None else f"'{item.produto}'"
        raise HTTPException(422, f"Produto {alvo} não encontrado no catálogo RevGás.")
    return p


def _cotar(v: VendaIn) -> tuple[dict, Cotacao]:
    itens: list[ItemOut] = []
    avisos: list[str] = []

    def adicionar(p: dict, qtd: int, auto: bool = False) -> None:
        if not p.get("preco"):
            raise HTTPException(422, f"{p['nome']} está sem preço cadastrado; fale com um atendente.")
        if not p["recomendavel"]:
            raise HTTPException(409, f"{p['rotulo']} está indisponível no momento.")
        if p["estoque"] < qtd:
            raise HTTPException(409, f"Estoque insuficiente de {p['rotulo']} (disponível: {p['estoque']}).")
        existente = next((i for i in itens if i.revgas_id == p["revgas_id"]), None)
        if existente:
            existente.quantidade += qtd
            existente.subtotal = round(existente.quantidade * existente.preco, 2)
            return
        itens.append(ItemOut(revgas_id=p["revgas_id"], nome=p["rotulo"], quantidade=qtd, preco=p["preco"],
                             subtotal=round(qtd * p["preco"], 2), adicionado_automaticamente=auto))

    for it in v.itens:
        p = _resolver(it)
        adicionar(p, it.quantidade)
        if not v.tem_botijao_para_troca and p["categoria"] == "Gás GLP" and p.get("container_id"):
            vas = revgas.obter(int(p["container_id"]))
            if vas and vas.get("preco"):
                adicionar(vas, it.quantidade, auto=True)
                avisos.append(f"Incluído {vas['rotulo']} porque o cliente não tem botijão para troca.")

    total = round(sum(i.subtotal for i in itens), 2)
    troco = None
    if v.troco_para is not None:
        if v.pagamento != "MONEY":
            avisos.append("Troco só se aplica a pagamento em dinheiro; ignorado.")
        elif v.troco_para < total:
            raise HTTPException(422, f"Troco para R$ {v.troco_para:.2f} é menor que o total R$ {total:.2f}.")
        else:
            troco = round(v.troco_para - total, 2)

    obs = []
    if v.cliente:
        obs.append(f"Cliente: {v.cliente.nome}" + (f" ({v.cliente.telefone})" if v.cliente.telefone else ""))
    if v.endereco.complemento:
        obs.append(f"Compl.: {v.endereco.complemento}")
    if v.observacao:
        obs.append(v.observacao)
    dados = {
        "carrinho": [{"revgas_id": i.revgas_id, "nome": i.nome, "qtd": i.quantidade, "preco": i.preco} for i in itens],
        "endereco": v.endereco.model_dump(),
        "pagamento": v.pagamento,
        "troco_para": v.troco_para if v.pagamento == "MONEY" else None,
        "observacao": " | ".join(obs) or None,
    }
    try:
        payload = revgas.montar_payload(dados)
    except revgas.VendaInvalida as e:
        raise HTTPException(422, str(e))
    return dados, Cotacao(itens=itens, total=total, pagamento=revgas.PAGAMENTOS[v.pagamento], troco=troco,
                          avisos=avisos, payload_revgas=payload)


_DDL_IDEMP = """CREATE TABLE IF NOT EXISTS api_idempotencia (
    chave TEXT PRIMARY KEY, numero_local TEXT NOT NULL, resposta_json TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')))"""


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
@router.get("/produtos", response_model=list[Produto], summary="Catálogo RevGás (preço e estoque)")
def listar_produtos(q: Optional[str] = Query(None, description="busca em texto livre: 'p13', 'galão'"),
                    categoria: Optional[str] = Query(None, description="Gás GLP | Vasilhames | Água | Acessórios | Outros"),
                    todos: bool = Query(False, description="inclui itens indisponíveis/de teste")):
    produtos = revgas.buscar_produtos(q, limite=20) if q else revgas.listar_produtos()
    if categoria:
        produtos = [p for p in produtos if p["categoria"].lower() == categoria.lower()]
    if not todos:
        produtos = [p for p in produtos if p["recomendavel"]]
    return [_produto_out(p) for p in produtos]


@router.get("/produtos/{revgas_id}", response_model=Produto, summary="Um produto pelo id RevGás")
def obter_produto(revgas_id: int):
    p = revgas.obter(revgas_id)
    if not p:
        raise HTTPException(404, "Produto não encontrado.")
    return _produto_out(p)


@router.post("/vendas/cotacao", response_model=Cotacao, summary="Calcula o pedido sem gravar nada")
def cotar(venda: VendaIn):
    return _cotar(venda)[1]


@router.post("/vendas", response_model=VendaOut, status_code=201, summary="Cria a venda na RevGás")
def criar_venda(venda: VendaIn, idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
                                                                       max_length=100)):
    if idempotency_key:
        with conn_rw() as c:
            c.execute(_DDL_IDEMP)
            row = c.execute("SELECT resposta_json FROM api_idempotencia WHERE chave = ?", (idempotency_key,)).fetchone()
        if row:
            return VendaOut(**json.loads(row[0]))

    dados, cot = _cotar(venda)
    r = revgas.criar_venda(dados)
    out = VendaOut(**cot.model_dump(), numero=r["numero"], revgas_id=r["revgas_id"], status=r["status"],
                   modo=revgas.modo(), previsao_entrega=revgas.PREVISAO_ENTREGA)
    if r["status"] == "ERRO":
        raise HTTPException(502, {"mensagem": "A RevGás recusou ou não respondeu; venda registrada como ERRO.",
                                  "numero": r["numero"]})
    if idempotency_key:
        with conn_rw() as c:
            c.execute(_DDL_IDEMP)
            c.execute("INSERT OR IGNORE INTO api_idempotencia (chave, numero_local, resposta_json) VALUES (?, ?, ?)",
                      (idempotency_key, out.numero, out.model_dump_json()))
    return out


@router.get("/vendas", summary="Vendas criadas pelo Flow (chat + API)")
def listar_vendas(limite: int = Query(50, ge=1, le=200), status_venda: Optional[str] = Query(None, alias="status")):
    vendas = revgas.listar_vendas(limite)
    if status_venda:
        vendas = [v for v in vendas if v["status"] == status_venda.upper()]
    return vendas


@router.get("/vendas/{numero}", summary="Detalhe de uma venda pelo número (RV-...)")
def obter_venda(numero: str):
    with conn_rw() as c:
        try:
            row = c.execute("SELECT * FROM vendas_revgas WHERE numero_local = ?", (numero,)).fetchone()
        except Exception:
            row = None
    if not row:
        raise HTTPException(404, "Venda não encontrada.")
    return {"numero": row["numero_local"], "revgas_id": row["revgas_id"], "status": row["status"],
            "total": row["total"], "criado_em": row["criado_em"],
            "payload_revgas": json.loads(row["payload_json"] or "{}"),
            "resposta_revgas": json.loads(row["resposta_json"]) if row["resposta_json"] else None}


@router.get("/status", summary="Modo da integração (não expõe a chave)")
def status_integracao():
    s = revgas.status()
    return {**s, "fonte_catalogo": revgas.fonte_catalogo(), "exige_api_key": bool(FLOW_API_KEY)}
