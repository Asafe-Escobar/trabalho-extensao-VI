"""Wrapper único para o Claude (Anthropic SDK) com modo MOCK offline.

Todos os módulos (rag/, agent/) devem chamar o LLM SOMENTE por aqui.

- complete(system, user, mock=...)          -> str
- structured(system, user, Schema, mock=...) -> instância Pydantic validada
- create_message(**kwargs)                   -> resposta crua (tool calling); levanta MockModeError em modo mock

Em modo mock (sem ANTHROPIC_API_KEY), `complete`/`structured` usam o callable `mock`
fornecido pelo chamador (heurística determinística). Assim o projeto roda na
apresentação mesmo sem chave de API.
"""
from __future__ import annotations

from typing import Callable, Optional, Type, TypeVar

from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)

_client = None
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class MockModeError(RuntimeError):
    """Levantada quando se tenta chamar a API real estando em modo mock."""


def is_mock() -> bool:
    return config.LLM_MODE == "mock"


def client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def _text_of(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text").strip()


def complete(
    system: str,
    user: str,
    *,
    max_tokens: int = 2048,
    mock: Optional[Callable[[str], str]] = None,
) -> str:
    """Geração de texto simples (ex.: HyDE, reescrita de consulta, resumo)."""
    if is_mock():
        return mock(user) if mock else ""
    resp = client().beta.messages.create(
        model=config.LLM_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": config.LLM_EFFORT},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        return ""
    return _text_of(resp)


def structured(
    system: str,
    user: str,
    schema: Type[T],
    *,
    max_tokens: int = 2048,
    mock: Optional[Callable[[str], T]] = None,
) -> T:
    """Saída estruturada validada por Pydantic (intenção, entidades, SQL, etc.)."""
    if is_mock():
        return mock(user) if mock else schema()
    resp = client().messages.parse(
        model=config.LLM_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": config.LLM_EFFORT},
        output_format=schema,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        return mock(user) if mock else schema()
    return resp.parsed_output


def create_message(**kwargs):
    """Chamada crua para o loop de tool calling (Agentic RAG).

    Aceita os mesmos kwargs de messages.create (system, messages, tools, max_tokens...).
    Use tool_choice={"type": "auto"} (any/tool não são suportados no Opus 5.5).
    """
    if is_mock():
        raise MockModeError("LLM em modo mock: use o roteador por regras.")
    kwargs.setdefault("model", config.LLM_MODEL)
    kwargs.setdefault("max_tokens", 4096)
    kwargs.setdefault("output_config", {"effort": config.LLM_EFFORT})
    return client().beta.messages.create(
        betas=[FALLBACK_BETA], fallbacks="default", **kwargs
    )


text_of = _text_of
