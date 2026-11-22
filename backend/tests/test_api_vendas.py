"""API REST de vendas (/api/v1) em modo offline: nada sai para a rede, nenhuma venda real."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="flow-vendas-")
os.environ["FLOW_DB_PATH"] = os.path.join(_tmp, "t.db")
os.environ["FLOW_INDEX_DIR"] = os.path.join(_tmp, "idx")
os.environ["REVGAS_MODO"] = "offline"
os.environ.setdefault("LLM_MODE", "mock")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402

config.REVGAS_MODO = "offline"  # caso config já tenha sido importado por outro teste
from app.main import app  # noqa: E402

PEDIDO = {
    "itens": [{"produto": "botijão de 13", "quantidade": 2}, {"produto": "galão de água", "quantidade": 1}],
    "tem_botijao_para_troca": False,
    "endereco": {"rua": "Rua Augusto Freire", "numero": "2003", "bairro": "Centro"},
    "pagamento": "MONEY",
    "troco_para": 1000,
}


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as cli:
        yield cli


def test_status_nao_expoe_chave(c):
    j = c.get("/api/v1/status").json()
    assert j["modo"] == "offline"
    assert "BA7E" not in str(j) and "key" not in {k.lower() for k in j}


def test_busca_p13(c):
    r = c.get("/api/v1/produtos", params={"q": "p13"})
    assert r.status_code == 200
    assert r.json()[0]["revgas_id"] == 26717


def test_catalogo_sem_itens_de_teste(c):
    nomes = [p["nome"] for p in c.get("/api/v1/produtos").json()]
    assert nomes and not any("TESTE" in n or "AAAA" in n for n in nomes)


def test_cotacao_adiciona_vasilhame_e_calcula_troco(c):
    j = c.post("/api/v1/vendas/cotacao", json=PEDIDO).json()
    ids = {i["revgas_id"]: i for i in j["itens"]}
    assert 26718 in ids and ids[26718]["adicionado_automaticamente"] and ids[26718]["quantidade"] == 2
    assert j["total"] == round(sum(i["subtotal"] for i in j["itens"]), 2)
    assert j["troco"] == round(1000 - j["total"], 2)
    assert j["payload_revgas"]["channel"] == "WHATSAPP"


def test_preco_vem_do_servidor(c):
    body = dict(PEDIDO, itens=[{"revgas_id": 26717, "quantidade": 1, "preco": 1}])
    j = c.post("/api/v1/vendas/cotacao", json=body).json()
    assert j["itens"][0]["preco"] > 1


def test_criar_venda_dryrun_e_idempotencia(c):
    h = {"Idempotency-Key": "teste-idem-1"}
    r1 = c.post("/api/v1/vendas", json=PEDIDO, headers=h)
    r2 = c.post("/api/v1/vendas", json=PEDIDO, headers=h)
    assert r1.status_code == 201
    assert r1.json()["status"] == "DRYRUN" and r1.json()["numero"].startswith("RV-DRY-")
    assert r2.json()["numero"] == r1.json()["numero"]
    det = c.get(f"/api/v1/vendas/{r1.json()['numero']}").json()
    assert det["payload_revgas"]["products"][0]["product_id"] == 26717


@pytest.mark.parametrize("mudanca,codigo", [
    ({"pagamento": "BITCOIN"}, 422),
    ({"troco_para": 10}, 422),
    ({"itens": [{"produto": "notebook dell"}]}, 422),
    ({"itens": [{"revgas_id": 26717, "quantidade": 999}]}, 422),
    ({"endereco": {"rua": "R", "numero": "", "bairro": "C"}}, 422),
])
def test_validacoes(c, mudanca, codigo):
    assert c.post("/api/v1/vendas", json=dict(PEDIDO, **mudanca)).status_code == codigo


def test_venda_inexistente(c):
    assert c.get("/api/v1/vendas/RV-NAO-EXISTE").status_code == 404
