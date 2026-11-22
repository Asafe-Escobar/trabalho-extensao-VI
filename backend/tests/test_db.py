"""Testes do módulo DATABASE (schema, seed de gás/RevGás, conexões e base de conhecimento).

Rodar: cd backend; .\\.venv\\Scripts\\python -m pytest tests/test_db.py -v
Usa banco temporário; não toca em backend/data/flow.db nem em rede.
"""
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["LLM_MODE"] = "mock"

from app import config  # noqa: E402
from app.db import seed as seed_mod  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def banco(tmp_path_factory):
    antigo = config.DB_PATH
    config.DB_PATH = tmp_path_factory.mktemp("db") / "flow_test.db"
    from app.db.connection import init_db

    init_db(reset=True)
    yield
    config.DB_PATH = antigo


@pytest.fixture
def conn():
    from app.db.connection import get_conn

    c = get_conn()
    yield c
    c.close()


def count(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


# --- conexões ----------------------------------------------------------------
def test_get_conn_row_factory_e_foreign_keys(conn):
    assert conn.row_factory is sqlite3.Row
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_readonly_bloqueia_escrita():
    from app.db.connection import get_readonly_conn

    ro = get_readonly_conn()
    try:
        assert count(ro, "SELECT COUNT(*) FROM produtos") > 0
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("DELETE FROM leads")
    finally:
        ro.close()


def test_get_conn_cria_banco_se_nao_existir(tmp_path):
    from app.db.connection import get_conn

    antigo = config.DB_PATH
    config.DB_PATH = tmp_path / "novo" / "flow.db"
    try:
        c = get_conn()
        assert count(c, "SELECT COUNT(*) FROM clientes") >= 25
        c.close()
    finally:
        config.DB_PATH = antigo


def test_banco_antigo_de_tecnologia_e_recriado(tmp_path):
    """Banco sem revgas_id (versão de tecnologia) é recriado com o seed de gás."""
    from app.db.connection import get_conn

    antigo = config.DB_PATH
    config.DB_PATH = tmp_path / "velho.db"
    try:
        v = sqlite3.connect(str(config.DB_PATH))
        v.executescript("CREATE TABLE produtos (id INTEGER PRIMARY KEY, sku TEXT, nome TEXT);"
                        "INSERT INTO produtos VALUES (1, 'NB-DEL-001', 'Notebook Dell');")
        v.commit()
        v.close()
        c = get_conn()
        assert count(c, "SELECT COUNT(*) FROM produtos WHERE sku='GLP-P13'") == 1
        assert count(c, "SELECT COUNT(*) FROM produtos WHERE sku LIKE 'NB-%'") == 0
        c.close()
    finally:
        config.DB_PATH = antigo


# --- schema --------------------------------------------------------------------
TABELAS = ["filiais", "categorias", "produtos", "estoque", "clientes", "pedidos", "itens_pedido", "financeiro",
           "trocas", "leads", "conversas", "mensagens", "handoffs", "memoria", "vendas_revgas"]


@pytest.mark.parametrize("tabela", TABELAS)
def test_tabelas_existem(conn, tabela):
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)).fetchone()


def test_colunas_novas_revgas(conn):
    prod = {r[1] for r in conn.execute("PRAGMA table_info(produtos)")}
    assert {"revgas_id", "container_revgas_id", "preco_minimo"} <= prod
    cli = {r[1] for r in conn.execute("PRAGMA table_info(clientes)")}
    assert {"endereco", "numero", "bairro"} <= cli
    vend = {r[1] for r in conn.execute("PRAGMA table_info(vendas_revgas)")}
    assert vend == {"id", "numero_local", "revgas_id", "conversa_id", "cliente_id", "payload_json",
                    "resposta_json", "status", "total", "criado_em"}


def test_vendas_revgas_status_e_numero_unico(conn):
    conn.execute("INSERT INTO vendas_revgas (numero_local, payload_json, status, total) VALUES "
                 "('RV-DRY-9999', '{}', 'DRYRUN', 125)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO vendas_revgas (numero_local, payload_json, status) VALUES ('RV-DRY-9999','{}','DRYRUN')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO vendas_revgas (numero_local, payload_json, status) VALUES ('RV-X','{}','PENDENTE')")
    conn.rollback()


VIEWS = {
    "vw_catalogo": ["sku", "nome", "categoria", "marca", "preco", "garantia_meses"],
    "vw_estoque": ["sku", "produto", "filial", "cidade", "quantidade"],
    "vw_vendas_resumo": ["mes", "filial", "qtd_pedidos", "faturamento"],
}


@pytest.mark.parametrize("view,colunas", VIEWS.items())
def test_views_colunas_exatas_sem_sensiveis(conn, view, colunas):
    cur = conn.execute(f"SELECT * FROM {view} LIMIT 1")
    nomes = [d[0] for d in cur.description]
    assert nomes == colunas
    assert not {"preco_minimo", "cpf_cnpj", "email", "telefone", "linha_digitavel", "endereco"} & set(nomes)


def test_vw_catalogo_so_ativos(conn):
    assert count(conn, "SELECT COUNT(*) FROM vw_catalogo") == count(conn, "SELECT COUNT(*) FROM produtos WHERE ativo=1")
    assert count(conn, "SELECT COUNT(*) FROM vw_catalogo WHERE sku='GLP-P13-NORMAL'") == 0


# --- seed: catálogo RevGás -------------------------------------------------------
def test_produtos_vem_do_snapshot_sem_teste(conn):
    snap = seed_mod.carregar_snapshot()
    rows = conn.execute("SELECT revgas_id, nome, descricao FROM produtos").fetchall()
    assert len(rows) >= 30
    for r in rows:
        assert r["revgas_id"] in snap, r["nome"]
        original = snap[r["revgas_id"]]["descricao"].upper()
        assert not re.search(r"TESTE|AAAA|2222|SADASD|BARA BARA|LLLL", original), original


def test_produtos_principais_e_vasilhames(conn):
    p = {r["sku"]: r for r in conn.execute("SELECT * FROM produtos")}
    assert p["GLP-P13"]["revgas_id"] == 26717 and p["GLP-P13"]["preco"] == 125.0
    assert p["GLP-P13"]["container_revgas_id"] == 26718 and p["VAS-P13"]["revgas_id"] == 26718
    assert p["GLP-P45"]["revgas_id"] == 23974 and p["GLP-P45"]["container_revgas_id"] == 23975
    assert p["GLP-P20"]["preco"] == 300.0 and p["VAS-P20"]["preco"] == 50.01  # preco_referencia do snapshot
    assert p["AGUA-20L"]["container_revgas_id"] == p["VAS-AGUA-20L"]["revgas_id"]
    assert p["ACE-KIT-REG"]["preco"] == 100.0
    # todo container aponta para um produto existente
    ids = {r["revgas_id"] for r in p.values()}
    for r in p.values():
        if r["container_revgas_id"]:
            assert r["container_revgas_id"] in ids, r["sku"]


def test_categorias_de_gas(conn):
    nomes = {r[0] for r in conn.execute("SELECT nome FROM categorias")}
    assert nomes == {"Gás GLP", "Vasilhames", "Água", "Acessórios", "Outros"}
    assert count(conn, "SELECT COUNT(*) FROM produtos WHERE nome LIKE '%otebook%' OR nome LIKE '%mpressora%'") == 0


def test_preco_minimo_abaixo_do_preco(conn):
    assert count(conn, "SELECT COUNT(*) FROM produtos WHERE preco_minimo > preco OR preco_minimo <= 0") == 0


def test_estoque_demo_p45_parnaiba(conn):
    q = conn.execute("SELECT quantidade FROM vw_estoque WHERE sku='GLP-P45' AND cidade='Parnaíba'").fetchone()
    assert q and q[0] > 0
    # sem estoque na RevGás => zero em todas as filiais
    assert count(conn, "SELECT SUM(quantidade) FROM vw_estoque WHERE sku='GLP-P10'") == 0


# --- seed: volumes e clientes-demo ---------------------------------------------------
def test_volumes_minimos(conn):
    assert count(conn, "SELECT COUNT(*) FROM filiais") == 3
    assert count(conn, "SELECT COUNT(*) FROM clientes") >= 25
    assert count(conn, "SELECT COUNT(*) FROM pedidos") >= 60
    assert count(conn, "SELECT COUNT(*) FROM leads") >= 15
    status = {r[0] for r in conn.execute("SELECT DISTINCT status FROM pedidos")}
    assert status == {"aguardando_pagamento", "pago", "separacao", "enviado", "entregue", "cancelado"}
    fin = {r[0] for r in conn.execute("SELECT DISTINCT status FROM financeiro WHERE tipo='boleto'")}
    assert {"aberto", "vencido"} <= fin


def test_documentos_validos_e_enderecos(conn):
    for r in conn.execute("SELECT tipo, cpf_cnpj, endereco, numero, bairro FROM clientes"):
        assert r["cpf_cnpj"].isdigit()
        ok = seed_mod.cpf_valido(r["cpf_cnpj"]) if r["tipo"] == "PF" else seed_mod.cnpj_valido(r["cpf_cnpj"])
        assert ok, r["cpf_cnpj"]
        assert r["endereco"] and r["numero"] and r["bairro"]


def test_cliente_demo_maria(conn):
    c = conn.execute("SELECT * FROM clientes WHERE cpf_cnpj='12345678909'").fetchone()
    assert c["nome"] == "Maria Souza" and c["tipo"] == "PF" and c["cidade"] == "Teresina"
    p = conn.execute("SELECT * FROM pedidos WHERE numero='FL-2026-00042'").fetchone()
    assert p["cliente_id"] == c["id"] and p["status"] == "enviado"  # saiu para entrega
    itens = {r[0] for r in conn.execute(
        "SELECT pr.sku FROM itens_pedido i JOIN produtos pr ON pr.id=i.produto_id WHERE i.pedido_id=?", (p["id"],))}
    assert "GLP-P13" in itens
    assert count(conn, "SELECT COUNT(*) FROM financeiro WHERE cliente_id=? AND tipo='boleto' AND status='aberto'",
                 c["id"]) >= 1


def test_cliente_demo_alfa_b2b_p45(conn):
    c = conn.execute("SELECT * FROM clientes WHERE cpf_cnpj='11222333000181'").fetchone()
    assert c["nome"] == "Escritório Alfa Ltda" and c["tipo"] == "PJ"
    p = conn.execute("SELECT * FROM pedidos WHERE numero='FL-2026-00043'").fetchone()
    assert p["cliente_id"] == c["id"] and p["status"] == "separacao"
    itens = {r[0] for r in conn.execute(
        "SELECT pr.sku FROM itens_pedido i JOIN produtos pr ON pr.id=i.produto_id WHERE i.pedido_id=?", (p["id"],))}
    assert "GLP-P45" in itens


def test_valor_total_confere_com_itens(conn):
    rows = conn.execute("SELECT p.valor_total, SUM(i.quantidade*i.preco_unitario) FROM pedidos p "
                        "JOIN itens_pedido i ON i.pedido_id=p.id GROUP BY p.id").fetchall()
    assert all(abs(a - b) < 0.01 for a, b in rows)


def test_seed_sem_chave_revgas():
    """A chave da RevGás nunca pode estar no código/snapshot do módulo DATABASE."""
    chave = os.getenv("REVGAS_API_KEY") or ""
    db_dir = Path(seed_mod.__file__).parent
    textos = [p.read_text(encoding="utf-8") for p in db_dir.rglob("*") if p.suffix in (".py", ".sql", ".md")]
    textos.append(seed_mod.SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if chave:
        assert all(chave not in t for t in textos)


# --- base de conhecimento ------------------------------------------------------------
KNOW = config.KNOWLEDGE_DIR


def test_base_de_conhecimento_front_matter():
    from app.rag.chunking import parse_front_matter

    arquivos = sorted(KNOW.glob("*.md"))
    assert len(arquivos) >= 12
    for p in arquivos:
        meta, corpo = parse_front_matter(p.read_text(encoding="utf-8"))
        assert meta.get("titulo") and meta.get("tipo") and isinstance(meta.get("tags"), list), p.name
        assert len(corpo) > 400, p.name


def test_base_sem_tecnologia():
    for p in KNOW.glob("*.md"):
        t = p.read_text(encoding="utf-8").lower()
        assert not re.search(r"notebook|impressora|monitor lg|tp-link|laserjet", t), p.name


def test_base_cobre_topicos_do_contrato():
    tudo = " ".join(p.read_text(encoding="utf-8").lower() for p in KNOW.glob("*.md"))
    for termo in ["cheiro de gás", "193", "vasilhame", "regulador", "5 anos", "mangueira", "água mineral 20l",
                  "higieniza", "p45", "contrato mensal", "nunca concede desconto", "lgpd", "10º botijão",
                  "central de gás", "pix", "troco"]:
        assert termo in tudo, termo
    assert (KNOW / "manual-instalar-regulador.md").exists()
    assert (KNOW / "manual-trocar-botijao.md").exists()
    assert (KNOW / "manual-central-gas-p45.md").exists()


def test_faq_tem_25_perguntas():
    faq = (KNOW / "faq.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^\*\*\d+\.", faq, re.M)) >= 25


def test_skus_citados_na_base_existem(conn):
    skus = {r[0] for r in conn.execute("SELECT sku FROM produtos")}
    for p in KNOW.glob("*.md"):
        for sku in re.findall(r"\b(?:GLP|VAS|AGUA|ACE|OUT)-[A-Z0-9-]+\b", p.read_text(encoding="utf-8")):
            assert sku in skus, f"{p.name}: {sku}"


def test_precos_da_base_batem_com_o_banco(conn):
    preco = {r["nome"]: r["preco"] for r in conn.execute("SELECT nome, preco FROM produtos WHERE ativo=1")}
    texto = (KNOW / "catalogo-gas-glp.md").read_text(encoding="utf-8") + \
        (KNOW / "catalogo-agua-acessorios.md").read_text(encoding="utf-8")
    for nome in ["Gás GLP P13 (botijão 13 kg)", "Gás GLP P45 (cilindro 45 kg)", "Água mineral 20L (galão)",
                 "Kit regulador de pressão (regulador + mangueira)"]:
        m = re.search(re.escape(nome) + r"\*\*[^\n]*?R\$ ([\d.]+,\d{2})", texto)
        assert m, nome
        assert float(m.group(1).replace(".", "").replace(",", ".")) == preco[nome], nome
