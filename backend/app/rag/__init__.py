"""RAG do Flow Assistente (revenda de gás GLP e água mineral).

API pública (CONTRACT.md):
    Chunk, RetrievalTrace
    build_index(force=False) -> None
    retrieve(query, *, k=5, contexto=None, tecnicas=None) -> (list[Chunk], RetrievalTrace)

Técnicas: rewrite, multi_query, expansion, hyde, hype, graph, hybrid (BM25 + vetorial com RRF), rerank.
Funciona 100% offline em modo mock (sem ANTHROPIC_API_KEY): TF-IDF + templates + heurísticas.
"""
from .index import build_index, info as index_info, reset_cache
from .models import Chunk, RetrievalTrace
from .retriever import TECNICAS, retrieve

__all__ = ["Chunk", "RetrievalTrace", "build_index", "retrieve", "TECNICAS", "index_info", "reset_cache"]
