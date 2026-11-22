"""Modelos de resposta do /api/chat — formato EXATO consumido pelo frontend (CONTRACT.md)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ChunkDebug(BaseModel):
    titulo: str
    score: float
    fonte: str
    trecho: str


class FerramentaDebug(BaseModel):
    nome: str
    entrada: dict[str, Any] = Field(default_factory=dict)
    saida_resumo: str = ""


class HandoffDebug(BaseModel):
    id: int
    resumo: str


class DebugInfo(BaseModel):
    intencao: str = "outro"
    confianca: float = 0.0
    entidades: dict[str, Any] = Field(default_factory=dict)
    memoria: dict[str, Any] = Field(default_factory=dict)
    retrieval: Optional[dict[str, Any]] = None
    chunks: list[ChunkDebug] = Field(default_factory=list)
    ferramentas: list[FerramentaDebug] = Field(default_factory=list)
    sql: Optional[str] = None
    guardrails: list[dict[str, Any]] = Field(default_factory=list)
    handoff: Optional[HandoffDebug] = None
    venda: Optional[dict[str, Any]] = None  # {numero, status, total, itens, endereco, pagamento, payload}
    tecnicas: list[str] = Field(default_factory=list)
    latencia_ms: int = 0
    modo_llm: str = "mock"


class ChatResponse(BaseModel):
    resposta: str
    status_conversa: str = "bot"
    sugestoes: list[str] = Field(default_factory=list)
    debug: Optional[DebugInfo] = None
