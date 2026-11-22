"""Construção e carga do índice do RAG (persistido em config.INDEX_DIR).

Arquivos gerados:
  manifest.json  assinatura (hash da base + produtos + modo) — evita reindexar à toa
  chunks.json    chunks com metadados
  hype.json      perguntas hipotéticas (HyPE) por chunk
  graph.json     grafo networkx (node-link)
  vectors.pkl    embedder (TF-IDF ou fastembed) + matrizes de chunks e de perguntas HyPE
O BM25 é reconstruído na carga a partir dos tokens (rápido, ~100 chunks).
"""
from __future__ import annotations

import hashlib
import json
import logging
import pickle
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

import networkx as nx
from rank_bm25 import BM25Okapi

from .. import config, llm
from . import hype as hype_mod
from .chunking import RawChunk, chunk_all
from .embeddings import Embedder, make_embedder
from .graph import build_graph
from .text import tokens

log = logging.getLogger(__name__)

INDEX_VERSION = "gas-revgas-2"
_lock = threading.RLock()
_STATE: "IndexState | None" = None


@dataclass
class IndexState:
    chunks: list[RawChunk]
    hype: dict[str, list[str]]
    hype_pairs: list[tuple[str, str]]  # (chunk_id, pergunta)
    bm25: BM25Okapi
    bm25_hype: BM25Okapi | None
    embedder: Embedder
    mat_chunks: object
    mat_hype: object
    graph: nx.Graph
    produtos: list[dict]
    signature: str
    by_id: dict[str, RawChunk] = field(default_factory=dict)
    pos: dict[str, int] = field(default_factory=dict)

    @property
    def nomes_por_sku(self) -> dict[str, str]:
        return {p["sku"].upper(): p["nome"] for p in self.produtos}


def _index_dir() -> Path:
    return Path(config.INDEX_DIR)


def _knowledge_dir() -> Path:
    return Path(config.KNOWLEDGE_DIR)


def load_produtos() -> list[dict]:
    """Produtos do ERP local (SQLite) para o grafo e a reescrita. Falha => lista vazia."""
    try:
        from ..db.connection import get_readonly_conn

        conn = get_readonly_conn()
        try:
            rows = conn.execute(
                "SELECT p.sku, p.nome, p.descricao, p.marca, c.nome AS categoria, p.ativo, "
                "p.revgas_id, p.container_revgas_id "
                "FROM produtos p JOIN categorias c ON c.id = p.categoria_id ORDER BY p.id"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as e:
        log.warning("RAG: não consegui ler produtos do banco (%s); grafo só com a base de conhecimento", e)
        return []


def _signature(produtos: list[dict]) -> str:
    h = hashlib.sha256()
    h.update(INDEX_VERSION.encode())
    for p in sorted(_knowledge_dir().glob("*.md")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    h.update(json.dumps(produtos, sort_keys=True, ensure_ascii=False, default=str).encode())
    h.update(f"{(config.EMBEDDINGS or 'auto').lower()}|{config.LLM_MODE}".encode())
    return h.hexdigest()[:16]


def _assemble(chunks, hype, embedder, mat_chunks, mat_hype, graph, produtos, signature) -> IndexState:
    pairs = [(cid, q) for cid, qs in hype.items() for q in qs]
    bm25 = BM25Okapi([tokens(c.texto + " " + " ".join(c.tags)) or ["_"] for c in chunks])
    bm25_h = BM25Okapi([tokens(q) or ["_"] for _, q in pairs]) if pairs else None
    st = IndexState(chunks=chunks, hype=hype, hype_pairs=pairs, bm25=bm25, bm25_hype=bm25_h,
                    embedder=embedder, mat_chunks=mat_chunks, mat_hype=mat_hype, graph=graph,
                    produtos=produtos, signature=signature)
    st.by_id = {c.id: c for c in chunks}
    st.pos = {c.id: i for i, c in enumerate(chunks)}
    return st


def _load_from_disk(signature: str) -> IndexState | None:
    d = _index_dir()
    try:
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("signature") != signature:
            return None
        chunks = [RawChunk(**c) for c in json.loads((d / "chunks.json").read_text(encoding="utf-8"))]
        hype = json.loads((d / "hype.json").read_text(encoding="utf-8"))
        graph = nx.node_link_graph(json.loads((d / "graph.json").read_text(encoding="utf-8")), edges="links")
        with open(d / "vectors.pkl", "rb") as f:
            vec = pickle.load(f)
        produtos = json.loads((d / "produtos.json").read_text(encoding="utf-8"))
        return _assemble(chunks, hype, vec["embedder"], vec["mat_chunks"], vec["mat_hype"], graph,
                         produtos, signature)
    except FileNotFoundError:
        return None
    except Exception as e:
        log.warning("RAG: índice em disco inválido (%s); reconstruindo", e)
        return None


def _build(produtos: list[dict], signature: str) -> IndexState:
    docs, chunks = chunk_all(_knowledge_dir())
    hype = hype_mod.generate(chunks)
    embedder = make_embedder()
    mat_chunks = embedder.fit([c.texto for c in chunks])
    pairs = [q for c in chunks for q in hype.get(c.id, [])]
    mat_hype = embedder.encode(pairs) if pairs else None
    graph = build_graph(docs, chunks, produtos)

    d = _index_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "chunks.json").write_text(json.dumps([asdict(c) for c in chunks], ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    (d / "hype.json").write_text(json.dumps(hype, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "graph.json").write_text(json.dumps(nx.node_link_data(graph, edges="links"), ensure_ascii=False),
                                  encoding="utf-8")
    (d / "produtos.json").write_text(json.dumps(produtos, ensure_ascii=False, default=str), encoding="utf-8")
    with open(d / "vectors.pkl", "wb") as f:
        pickle.dump({"embedder": embedder, "mat_chunks": mat_chunks, "mat_hype": mat_hype}, f)
    (d / "manifest.json").write_text(json.dumps({
        "signature": signature, "versao": INDEX_VERSION, "chunks": len(chunks), "documentos": len(docs),
        "perguntas_hype": len(pairs), "nos_grafo": graph.number_of_nodes(), "arestas_grafo": graph.number_of_edges(),
        "embeddings": embedder.backend, "modo_llm": "mock" if llm.is_mock() else "anthropic",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("RAG: índice construído (%d chunks, %d perguntas HyPE, embeddings=%s)",
             len(chunks), len(pairs), embedder.backend)
    return _assemble(chunks, hype, embedder, mat_chunks, mat_hype, graph, produtos, signature)


def build_index(force: bool = False) -> None:
    """Chunking + BM25 + embeddings + perguntas HyPE + grafo; persiste em config.INDEX_DIR.

    Sem `force`, reaproveita o índice em disco se a base de conhecimento/produtos não mudaram.
    """
    global _STATE
    with _lock:
        produtos = load_produtos()
        sig = _signature(produtos)
        if not force:
            if _STATE is not None and _STATE.signature == sig:
                return
            st = _load_from_disk(sig)
            if st is not None:
                _STATE = st
                return
        _STATE = _build(produtos, sig)


def get_state() -> IndexState:
    """Índice em memória (constrói/carrega na primeira chamada)."""
    global _STATE
    if _STATE is None:
        with _lock:
            if _STATE is None:
                build_index(force=False)
    assert _STATE is not None
    return _STATE


def reset_cache() -> None:
    """Esquece o índice em memória (usado nos testes ao trocar INDEX_DIR)."""
    global _STATE
    with _lock:
        _STATE = None


def info() -> dict:
    try:
        return json.loads((_index_dir() / "manifest.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
