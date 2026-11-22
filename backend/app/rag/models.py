"""Modelos públicos do RAG (contrato em CONTRACT.md)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    id: str
    doc_id: str
    titulo: str
    tipo: str
    texto: str
    score: float = 0
    fonte: str = ""  # "bm25" | "vetorial" | "grafo" | "hype"


class RetrievalTrace(BaseModel):
    original: str
    reescrita: str | None = None
    multi_queries: list[str] = Field(default_factory=list)
    expansao: list[str] = Field(default_factory=list)
    hyde_doc: str | None = None
    candidatos: int = 0
    tecnicas: list[str] = Field(default_factory=list)
    # Extras opcionais (não fazem parte do contrato mínimo; úteis no painel "Por dentro do bot")
    grafo_entidades: list[str] = Field(default_factory=list)
    hype_perguntas: list[str] = Field(default_factory=list)
    embeddings: str = ""
