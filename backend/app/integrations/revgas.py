"""Adaptador da API RevGás (ERP real da Flow). Ver docs/revgas-api.md.

Modos (`config.REVGAS_MODO`):
- dryrun  (padrão): GET /products real se houver chave (cache 5 min, fallback snapshot);
                    criar_venda NÃO faz POST: valida o payload e grava em `vendas_revgas` como 'DRYRUN'.
- real:             único modo que faz POST /sales de verdade.
- offline:          nenhuma chamada de rede; catálogo do snapshot.

Segurança: a chave só sai de `config.REVGAS_API_KEY` para o header `Authorization` (sem "Bearer").
Ela nunca é logada, devolvida, nem incluída em payload/debug.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from .. import config

log = logging.getLogger("flow.revgas")

SNAPSHOT_PATH = Path(__file__).resolve().parent / "revgas_catalogo_snapshot.json"
CACHE_TTL = 300  # 5 minutos
PAGAMENTOS = {"MONEY": "Dinheiro", "PIX": "Pix", "CARTAO_DE_DEBITO": "Cartão de débito",
              "CARTAO_DE_CREDITO": "Cartão de crédito"}
PREVISAO_ENTREGA = "30 a 60 minutos"

# Preços de referência em Teresina quando nem o snapshot nem o seed trazem preço (R$)
PRECOS_PADRAO: list[tuple[str, float]] = [
    (r"^GLP 13KG", 125.0), (r"^GLP 20KG", 300.0), (r"^GLP 45KG", 480.0), (r"^GLP 2KG", 45.0), (r"^GLP 5KG", 70.0),
    (r"^GLP 7KG", 85.0), (r"^GLP 10KG", 105.0), (r"^GLP 16KG", 160.0), (r"^GLP 90KG", 950.0),
    (r"^VASILHAME 13KG", 160.0), (r"^VASILHAME 20KG", 50.0), (r"^VASILHAME 45KG", 350.0), (r"^VASILHAME AGUA", 35.0),
    (r"^VASILHAME", 120.0),
    (r"^AGUA .*20L", 12.0), (r"^AGUA .*10L", 9.0), (r"^AGUA .*FD", 18.0), (r"^AGUA", 5.0),
    (r"^KIT REGULADOR", 100.0), (r"^REGULADOR", 45.0), (r"^MANGUEIRA", 25.0), (r"^ADAPTADOR", 15.0),
    (r"^CARV", 25.0), (r"^GELO", 10.0), (r"^VELA", 5.0), (r"^BOMBA", 40.0),
]
# Itens "canônicos" para pedidos do dia a dia
CANONICOS = {"glp13": 26717, "glp20": 28117, "glp45": 23974, "agua20": 26255, "regulador": 26276,
             "mangueira": 28534, "vasilhame13": 26718}
_LIXO = re.compile(r"TESTE|TESTA|AAAA|2222|SADASD|BARA BARA|QUEBRADO|LLLL|FEIA|TIGRINHO|21321312|CARLOS", re.I)

_cache: dict[str, Any] = {"ts": 0.0, "produtos": None, "fonte": None}
_lock = threading.Lock()


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def modo() -> str:
    m = config.REVGAS_MODO
    return m if m in {"dryrun", "real", "offline"} else "dryrun"


def chave_configurada() -> bool:
    return bool(config.REVGAS_API_KEY)


def _headers() -> dict:
    return {"Authorization": config.REVGAS_API_KEY, "Content-Type": "application/json"}


def _verify():
    """TLS verificado pelo repositório de certificados do SISTEMA (Windows), via `truststore`.

    O bundle do certifi falha em algumas máquinas Windows (antivírus/proxy com CA própria).
    Nunca desligamos a verificação: sem truststore, cai no padrão do httpx.
    """
    try:
        import ssl

        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return True


def _categoria(desc: str) -> str:
    d = desc.upper()
    if d.startswith("GLP"):
        return "Gás GLP"
    if d.startswith("VASILHAME"):
        return "Vasilhames"
    if d.startswith("AGUA"):
        return "Água"
    if re.match(r"(KIT REGULADOR|REGULADOR|MANGUEIRA|ADAPTADOR|ABRA|TORNEIRA|SUPORTE|FURADOR|BOMBA)", d):
        return "Acessórios"
    return "Outros"


def _preco_padrao(desc: str) -> float | None:
    for padrao, valor in PRECOS_PADRAO:
        if re.search(padrao, desc.upper()):
            return valor
    return None


def _precos_locais() -> dict[int, float]:
    """Preço do seed (SQLite produtos.revgas_id), se a coluna já existir."""
    try:
        from ..agent.deps import conn_ro

        with conn_ro() as c:
            rows = c.execute("SELECT revgas_id, preco FROM produtos WHERE revgas_id IS NOT NULL").fetchall()
        return {int(r[0]): float(r[1]) for r in rows if r[1]}
    except Exception:
        return {}


def _normalizar(p: dict, precos_ref: dict[int, float], precos_locais: dict[int, float]) -> dict:
    pid = int(p["id"])
    desc = (p.get("descricao") or p.get("description") or "").strip()
    padrao = _preco_padrao(desc)
    ref = precos_ref.get(pid) or p.get("preco_referencia")
    if ref and padrao and ref < 0.5 * padrao:  # amostra pequena de vendas (ex.: P45 a R$ 100)
        ref = None
    preco = precos_locais.get(pid) or ref or padrao
    estoque = p.get("estoque", p.get("stock_quantity", 0)) or 0
    inativo = bool(p.get("inactive", False))
    return {
        "revgas_id": pid,
        "nome": desc,
        "rotulo": rotulo(desc),
        "categoria": _categoria(desc),
        "estoque": int(estoque),
        "container_id": p.get("container_id"),
        "preco": round(float(preco), 2) if preco else None,
        "recomendavel": (not inativo) and int(estoque) > 0 and not _LIXO.search(desc),
    }


def rotulo(desc: str) -> str:
    """Nome amigável para o cliente: 'GLP 13KG' -> 'Botijão de gás P13 (13 kg)'."""
    d = desc.upper()
    def _variacao(resto: str) -> str:
        resto = resto.strip()
        return f" — {resto.title()}" if resto else ""

    m = re.match(r"^GLP (\d+)KG(.*)$", d)
    if m:
        return f"Botijão de gás P{m.group(1)} ({m.group(1)} kg){_variacao(m.group(2))}"
    m = re.match(r"^VASILHAME (\d+)KG(.*)$", d)
    if m:
        return f"Vasilhame P{m.group(1)} (botijão vazio){_variacao(m.group(2))}"
    if re.match(r"^AGUA 20L$", d):
        return "Água mineral galão 20 L"
    if d.startswith("KIT REGULADOR"):
        return "Kit regulador de pressão"
    if d.startswith("MANGUEIRA"):
        return "Mangueira para gás"
    return desc.title()


def _snapshot_bruto() -> list[dict]:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["produtos"]


def _buscar_api() -> list[dict]:
    import httpx

    produtos, pagina = [], 1
    with httpx.Client(base_url=config.REVGAS_API_URL, headers=_headers(), timeout=8, verify=_verify()) as cli:
        while pagina <= 20:
            r = cli.get("/products", params={"page": pagina, "page_size": 100})
            r.raise_for_status()
            corpo = r.json()
            produtos += corpo.get("data", [])
            if not corpo.get("pagination", {}).get("has_next"):
                break
            pagina += 1
    return produtos


def listar_produtos(*, forcar: bool = False) -> list[dict]:
    """Catálogo normalizado: {revgas_id, nome, categoria, estoque, container_id, preco, recomendavel}."""
    with _lock:
        if not forcar and _cache["produtos"] is not None and time.time() - _cache["ts"] < CACHE_TTL:
            return _cache["produtos"]
        snap = _snapshot_bruto()
        precos_ref = {int(p["id"]): p["preco_referencia"] for p in snap if p.get("preco_referencia")}
        brutos, fonte = snap, "snapshot"
        if modo() != "offline" and chave_configurada():
            try:
                brutos, fonte = _buscar_api(), "api"
            except Exception as e:  # nunca inclui headers/chave na mensagem
                log.warning("RevGás GET /products falhou (%s); usando snapshot.", type(e).__name__)
        locais = _precos_locais()
        produtos = [_normalizar(p, precos_ref, locais) for p in brutos]
        _cache.update(ts=time.time(), produtos=produtos, fonte=fonte)
        return produtos


def fonte_catalogo() -> str:
    listar_produtos()
    return _cache["fonte"] or "snapshot"


def obter(revgas_id: int) -> dict | None:
    return next((p for p in listar_produtos() if p["revgas_id"] == revgas_id), None)


# ---------------------------------------------------------------------------
# Busca por linguagem natural
# ---------------------------------------------------------------------------
def _canonico(n: str) -> str | None:
    if re.search(r"\b(vasilhame|casco|botijao vazio)\b", n):
        return "vasilhame13" if re.search(r"\b(13|p13|p-13)\b", n) or not re.search(r"\d", n) else None
    if re.search(r"\b(p\s?-?45|45 ?kg|45 quilos|de 45|central)\b", n):
        return "glp45"
    if re.search(r"\b(p\s?-?20|20 ?kg|20 quilos|botijao de 20|gas de 20|empilhadeira)\b", n):
        return "glp20"
    if re.search(r"\b(p\s?-?13|13 ?kg|13 quilos|de 13|botij\w*|gas de cozinha|gas)\b", n) and not re.search(r"\bagua\b", n):
        return "glp13"
    if re.search(r"\b(gal(ao|oes)|agua mineral|agua de 20|20 ?l(itros)?|garrafao|agua)\b", n) and not re.search(r"\b(1,5|500|350|330|10 ?l)\b", n):
        return "agua20"
    if re.search(r"\bregulador\w*\b|\bkit\b", n):
        return "regulador"
    if re.search(r"\bmangueira\w*\b", n):
        return "mangueira"
    return None


def buscar_produtos(texto: str, limite: int = 5) -> list[dict]:
    n = _norm(texto)
    catalogo = listar_produtos()
    can = _canonico(n)
    resultado: list[dict] = []
    if can:
        p = obter(CANONICOS[can])
        if p:
            resultado.append(p)
    q = [t for t in re.findall(r"[a-z0-9,]+", n) if len(t) > 1 and t not in {"de", "do", "da", "um", "uma", "tem", "quanto", "ta", "o", "a"}]
    pont = []
    for p in catalogo:
        if not p["recomendavel"] or any(p["revgas_id"] == r["revgas_id"] for r in resultado):
            continue
        nome = _norm(p["nome"])
        s = sum(2 for t in q if re.search(rf"\b{re.escape(t)}", nome))
        if s:
            pont.append((s, p))
    pont.sort(key=lambda x: (-x[0], -(x[1]["preco"] is not None), -x[1]["estoque"]))
    resultado += [p for _, p in pont]
    return resultado[:limite]


def buscar_produto(texto: str) -> dict | None:
    r = buscar_produtos(texto, limite=1)
    return r[0] if r else None


# ---------------------------------------------------------------------------
# Venda
# ---------------------------------------------------------------------------
_DDL_VENDAS = """CREATE TABLE IF NOT EXISTS vendas_revgas (
    id INTEGER PRIMARY KEY, numero_local TEXT NOT NULL UNIQUE, revgas_id INTEGER, conversa_id TEXT,
    cliente_id INTEGER, payload_json TEXT NOT NULL, resposta_json TEXT,
    status TEXT NOT NULL CHECK (status IN ('DRYRUN', 'ENVIADA', 'ERRO')), total REAL NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')))"""


class VendaInvalida(ValueError):
    pass


def montar_payload(dados: dict) -> dict:
    """dados: {carrinho:[{revgas_id,nome,qtd,preco}], endereco:{rua,numero,bairro,cidade,uf}, pagamento, troco_para, observacao}"""
    carrinho = dados.get("carrinho") or []
    if not carrinho:
        raise VendaInvalida("Carrinho vazio.")
    end = dados.get("endereco") or {}
    faltando = [k for k in ("rua", "numero", "bairro") if not end.get(k)]
    if faltando:
        raise VendaInvalida(f"Endereço incompleto: falta {', '.join(faltando)}.")
    pagamento = dados.get("pagamento")
    if pagamento not in PAGAMENTOS:
        raise VendaInvalida("Forma de pagamento inválida.")
    produtos = []
    for it in carrinho:
        qtd, preco = int(it.get("qtd") or 0), float(it.get("preco") or 0)
        if qtd <= 0 or qtd > 50:
            raise VendaInvalida(f"Quantidade inválida para {it.get('nome')}.")
        if preco <= 0:
            raise VendaInvalida(f"Produto sem preço: {it.get('nome')}.")
        produtos.append({"product_id": int(it["revgas_id"]), "quantity": qtd, "value": round(preco, 2), "discount": 0})
    total = round(sum(p["quantity"] * p["value"] for p in produtos), 2)
    obs = ["Pedido via Flow Assistente (chatbot)."]
    if dados.get("troco_para"):
        obs.append(f"Troco para {float(dados['troco_para']):.2f}.")
    if dados.get("observacao"):
        obs.append(str(dados["observacao"])[:200])
    return {
        "channel": "WHATSAPP",
        "location": end["rua"], "number": str(end["numero"]), "neighborhood": end["bairro"],
        "city": end.get("cidade") or "Teresina", "state_federation": end.get("uf") or "PI",
        "observation": " ".join(obs),
        "products": produtos,
        "payments": [{"payment_type": pagamento, "value": total, "date": date.today().isoformat()}],
    }


def _gravar(conn, numero: str, revgas_id, dados: dict, payload: dict, resposta, status: str, total: float) -> None:
    conn.execute(
        "INSERT INTO vendas_revgas (numero_local, revgas_id, conversa_id, cliente_id, payload_json, resposta_json, status, total) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (numero, revgas_id, dados.get("conversa_id"), dados.get("cliente_id"), json.dumps(payload, ensure_ascii=False),
         json.dumps(resposta, ensure_ascii=False) if resposta is not None else None, status, total))


def criar_venda(dados: dict) -> dict:
    """Cria a venda. Retorna {numero, revgas_id, status, total, payload}. Levanta VendaInvalida se faltar dado."""
    from ..agent.deps import conn_rw

    payload = montar_payload(dados)
    total = payload["payments"][0]["value"]
    m = modo()
    with conn_rw() as c:
        c.execute(_DDL_VENDAS)
        if m in {"dryrun", "offline"}:
            n = c.execute("SELECT COUNT(*) FROM vendas_revgas WHERE numero_local LIKE 'RV-DRY-%'").fetchone()[0] + 1
            numero = f"RV-DRY-{n:04d}"
            while c.execute("SELECT 1 FROM vendas_revgas WHERE numero_local = ?", (numero,)).fetchone():
                n += 1
                numero = f"RV-DRY-{n:04d}"
            _gravar(c, numero, None, dados, payload, None, "DRYRUN", total)
            return {"numero": numero, "revgas_id": None, "status": "DRYRUN", "total": total, "payload": payload}

    # modo real: POST /sales de verdade
    if not chave_configurada():
        raise VendaInvalida("REVGAS_API_KEY não configurada para o modo real.")
    import httpx

    try:
        r = httpx.post(f"{config.REVGAS_API_URL}/sales", headers=_headers(), json=payload, timeout=15, verify=_verify())
        corpo = r.json() if r.content else {}
        r.raise_for_status()
        rid = (corpo.get("data") or corpo).get("id") if isinstance(corpo, dict) else None
        numero, status = (f"RV-{rid}" if rid else f"RV-SEMID-{int(time.time())}"), "ENVIADA"
    except Exception as e:
        rid, numero, status = None, f"RV-ERRO-{int(time.time())}", "ERRO"
        corpo = {"erro": type(e).__name__, "status_code": getattr(getattr(e, "response", None), "status_code", None)}
    with conn_rw() as c:
        c.execute(_DDL_VENDAS)
        _gravar(c, numero, rid, dados, payload, corpo, status, total)
    return {"numero": numero, "revgas_id": rid, "status": status, "total": total, "payload": payload}


def listar_vendas(limite: int = 100) -> list[dict]:
    from ..agent.deps import conn_rw

    with conn_rw() as c:
        c.execute(_DDL_VENDAS)
        rows = c.execute("SELECT * FROM vendas_revgas ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    nomes = {p["revgas_id"]: p["nome"] for p in listar_produtos()}
    out = []
    for r in rows:
        payload = json.loads(r["payload_json"] or "{}")
        out.append({
            "numero_local": r["numero_local"], "revgas_id": r["revgas_id"], "status": r["status"], "total": r["total"],
            "itens": [{"nome": nomes.get(p["product_id"], str(p["product_id"])), "qtd": p["quantity"], "preco": p["value"]}
                      for p in payload.get("products", [])],
            "criado_em": r["criado_em"],
        })
    return out


def status() -> dict:
    try:
        n = len(listar_produtos())
    except Exception:
        n = 0
    return {"modo": modo(), "chave_configurada": chave_configurada(), "produtos": n}
