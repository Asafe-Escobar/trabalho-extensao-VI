"""Testes do RAG (modo mock, TF-IDF, banco e índice temporários — sem rede).

Rodar: cd backend; .\\.venv\\Scripts\\python -m pytest tests/test_rag.py -v
"""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["LLM_MODE"] = "mock"

from app import config  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def ambiente(tmp_path_factory):
    antigos = (config.DB_PATH, config.INDEX_DIR, config.LLM_MODE, config.EMBEDDINGS)
    base = tmp_path_factory.mktemp("rag")
    config.DB_PATH, config.INDEX_DIR = base / "flow.db", base / "index"
    config.LLM_MODE, config.EMBEDDINGS = "mock", "tfidf"
    from app import rag
    from app.db.connection import init_db

    init_db(reset=True)
    rag.reset_cache()
    rag.build_index(force=True)
    yield
    rag.reset_cache()
    (config.DB_PATH, config.INDEX_DIR, config.LLM_MODE, config.EMBEDDINGS) = antigos


def docs(chunks):
    return [c.doc_id for c in chunks]


# --- contrato ----------------------------------------------------------------
def test_exports_do_contrato():
    from app import rag

    for nome in ("Chunk", "RetrievalTrace", "build_index", "retrieve"):
        assert hasattr(rag, nome)
    campos = set(rag.RetrievalTrace.model_fields)
    assert {"original", "reescrita", "multi_queries", "expansao", "hyde_doc", "candidatos", "tecnicas"} <= campos
    assert {"id", "doc_id", "titulo", "tipo", "texto", "score", "fonte"} <= set(rag.Chunk.model_fields)


def test_index_persistido():
    from app import rag

    for f in ("manifest.json", "chunks.json", "hype.json", "graph.json", "vectors.pkl"):
        assert (Path(config.INDEX_DIR) / f).exists(), f
    info = rag.index_info()
    assert info["chunks"] >= 50 and info["perguntas_hype"] >= info["chunks"]
    assert info["embeddings"] == "tfidf" and info["modo_llm"] == "mock"


def test_build_index_sem_force_reaproveita():
    from app import rag

    t = time.time()
    rag.reset_cache()
    rag.build_index()  # carrega do disco (assinatura igual)
    assert time.time() - t < 2.0


def test_retrieve_formato_e_todas_as_tecnicas():
    from app import rag

    chunks, tr = rag.retrieve("Posso pedir gás sem ter botijão vazio?", k=5)
    assert 1 <= len(chunks) <= 5
    assert tr.original == "Posso pedir gás sem ter botijão vazio?"
    assert len(tr.multi_queries) == 3 and tr.expansao and tr.hyde_doc
    assert tr.candidatos >= len(chunks)
    assert {"multi_query", "expansion", "hyde", "hype", "graph", "hybrid", "rerank"} <= set(tr.tecnicas)
    assert all(c.fonte in {"bm25", "vetorial", "grafo", "hype"} for c in chunks)
    scores = [c.score for c in chunks]
    assert scores == sorted(scores, reverse=True) and all(0 <= s <= 1 for s in scores)
    assert chunks[0].doc_id == "vasilhame-troca-compra"


def test_tecnicas_subconjunto():
    from app import rag

    chunks, tr = rag.retrieve("Vocês aceitam pix?", tecnicas={"hybrid"})
    assert tr.tecnicas == ["hybrid"]
    assert tr.multi_queries == [] and tr.expansao == [] and tr.hyde_doc is None and tr.reescrita is None
    assert chunks and {c.fonte for c in chunks} <= {"bm25", "vetorial"}


# --- perguntas da demo --------------------------------------------------------
@pytest.mark.parametrize("pergunta,doc_esperado", [
    ("Quanto tá o botijão de 13?", {"catalogo-gas-glp", "faq"}),
    ("Tô sentindo cheiro de gás", {"seguranca-glp"}),
    ("Vocês aceitam pix?", {"faq", "pagamentos-boleto-segunda-via"}),
    ("Tem P45 em Parnaíba?", {"faq", "catalogo-gas-glp"}),
    ("Como limpar o galão de água?", {"agua-mineral-20l"}),
    ("Vocês vendem gasolina?", {"faq", "catalogo-gas-glp"}),
    ("Qual a validade do regulador?", {"regulador-mangueira-validade", "faq"}),
    ("Restaurante pode comprar com boleto faturado?", {"atendimento-b2b", "pagamentos-boleto-segunda-via"}),
    ("Como funciona o 10º botijão grátis?", {"programa-fidelidade", "faq"}),
    ("Me dá um desconto no gás?", {"politica-comercial-descontos", "faq"}),
])
def test_top1_por_pergunta(pergunta, doc_esperado):
    from app import rag

    chunks, _ = rag.retrieve(pergunta, k=3)
    assert chunks[0].doc_id in doc_esperado, (pergunta, docs(chunks))


def test_cheiro_de_gas_traz_instrucoes_193():
    from app import rag

    chunks, _ = rag.retrieve("Tô sentindo cheiro de gás na cozinha", k=3)
    assert any("193" in c.texto for c in chunks)


# --- técnicas específicas ---------------------------------------------------
def test_query_rewriting_com_memoria():
    from app import rag

    chunks, tr = rag.retrieve("E esse tem validade?", contexto={"produto_sku": "ACE-KIT-REG", "cpf_cnpj": "12345678909"})
    assert tr.reescrita and "Kit regulador" in tr.reescrita
    assert "12345678909" not in tr.reescrita  # nunca vaza CPF na consulta
    assert "rewrite" in tr.tecnicas
    assert chunks[0].doc_id == "regulador-mangueira-validade"


def test_rewrite_ancora_pedido_da_memoria():
    from app.rag.query import rewrite_mock

    r = rewrite_mock("Quando chega meu pedido?", {"pedido_numero": "FL-2026-00042"}, {})
    assert r and "FL-2026-00042" in r


def test_sem_contexto_nao_reescreve():
    from app import rag

    _, tr = rag.retrieve("Vocês aceitam pix?")
    assert tr.reescrita is None and "rewrite" not in tr.tecnicas


def test_expansao_sinonimos_de_dominio():
    from app.rag.query import expansion_mock

    assert "P13" in expansion_mock("quanto custa o botijão?")
    assert "P13" in expansion_mock("preciso de gás de cozinha")
    assert "água 20L" in expansion_mock("tem galão?")
    assert "cilindro 45 kg" in expansion_mock("preço do P45")
    gasolina = expansion_mock("vocês vendem gasolina?")
    assert "GLP" not in gasolina and "P13" not in gasolina  # gás de cozinha != gasolina


def test_multi_query_tres_variacoes_distintas():
    from app.rag.query import multi_query_mock

    mq = multi_query_mock("Posso devolver o botijão com lacre rompido?")
    assert len(mq) == 3 and len({m.lower() for m in mq}) == 3


def test_hyde_documento_hipotetico():
    from app.rag.query import hyde_mock

    doc = hyde_mock("Estou sentindo cheiro de gás")
    assert "193" in doc and len(doc) > 100


def test_hype_perguntas_geradas_e_casadas():
    from app import rag
    from app.rag.index import get_state

    st = get_state()
    assert all(st.hype.get(c.id) for c in st.chunks)
    _, tr = rag.retrieve("Estou sentindo cheiro de gás, o que eu faço?", tecnicas={"hype"})
    assert tr.tecnicas == ["hype"] and tr.hype_perguntas


def test_grafo_produto_vasilhame_acessorio():
    from app.rag.graph import vizinhos_produto
    from app.rag.index import get_state

    g = get_state().graph
    v13 = vizinhos_produto(g, "GLP-P13")
    assert "VAS-P13" in v13.get("usa_vasilhame", [])
    assert "ACE-KIT-REG" in v13.get("compativel_com", [])
    v45 = vizinhos_produto(g, "GLP-P45")
    assert "VAS-P45" in v45.get("usa_vasilhame", []) and "ACE-MANG-PIGTAIL" in v45.get("compativel_com", [])
    assert "ACE-BOMBA" in vizinhos_produto(g, "AGUA-20L").get("compativel_com", [])
    # produtos legados (ativo=0) ficam fora do grafo
    assert "produto:GLP-P13-NORMAL" not in g


def test_graphrag_entidades_e_fonte_grafo():
    from app import rag

    chunks, tr = rag.retrieve("Quais acessórios combinam com o botijão P13?", k=5)
    assert "graph" in tr.tecnicas
    assert any("P13" in e for e in tr.grafo_entidades)
    # BM25 é a linha de base sempre ativa; com tecnicas={"graph"} o grafo soma a sua lista na fusão
    so_grafo, tr2 = rag.retrieve("Quais acessórios combinam com o botijão P13?", k=5, tecnicas={"graph"})
    assert tr2.tecnicas == ["graph"]
    assert any(c.fonte == "grafo" for c in so_grafo)
    assert any(c.doc_id in {"catalogo-agua-acessorios", "regulador-mangueira-validade", "manual-instalar-regulador"}
               for c in so_grafo)


def test_grafo_carrinho_da_memoria_vira_semente():
    from app.rag.graph import search
    from app.rag.index import get_state

    st = get_state()
    ranked, ents = search(st.graph, "e o que mais eu preciso?", extra_seeds={"produto:GLP-P45": 1.5})
    assert ranked and any("P45" in e for e in ents)


def test_rrf_formula():
    from app.rag.fusion import RRF_K, rrf

    score, fonte = rrf([("bm25", ["a", "b"], 1.0), ("vetorial", ["b", "c"], 1.0)])
    assert score["b"] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert max(score, key=score.get) == "b"
    assert fonte["a"] == "bm25" and fonte["b"] == "vetorial" and fonte["c"] == "vetorial"


def test_rerank_muda_ordem_vs_rrf_puro():
    from app import rag

    com, _ = rag.retrieve("Qual a validade da mangueira do gás?", k=5)
    sem, _ = rag.retrieve("Qual a validade da mangueira do gás?", k=5,
                          tecnicas={"multi_query", "expansion", "hyde", "hype", "graph", "hybrid"})
    assert com[0].doc_id == "regulador-mangueira-validade"
    assert [c.id for c in com] != [c.id for c in sem] or com[0].score != sem[0].score


def test_latencia_mock():
    from app import rag

    t = time.time()
    for q in ["Quanto tá o botijão de 13?", "Tem P45 em Parnaíba?", "Vocês aceitam pix?"]:
        rag.retrieve(q)
    assert (time.time() - t) / 3 < 1.0
