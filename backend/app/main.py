"""Flow Assistente — aplicação FastAPI.

Rodar (dentro de backend/):  .\\.venv\\Scripts\\python -m uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config, llm
from .agent.deps import build_index, init_db
from .api.routes import router
from .api.vendas import router as vendas_router

log = logging.getLogger("flow")


def _aquecer_indice() -> None:
    try:
        build_index(force=False)
    except Exception as e:  # o RAG nunca pode derrubar a API
        log.warning("Falha ao montar o índice do RAG: %s", e)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db(reset=False)
    # índice em segundo plano: a API sobe na hora; retrieve() monta sob demanda se preciso
    threading.Thread(target=_aquecer_indice, daemon=True).start()
    log.info("Flow Assistente no ar (modo LLM: %s)", "mock" if llm.is_mock() else "anthropic")
    yield


app = FastAPI(
    title="Flow Assistente API",
    description="Chatbot de vendas e relacionamento da Flow — projeto de extensão.",
    version="1.0.0",
    lifespan=lifespan,
)

origens = list(dict.fromkeys([o.strip() for o in config.CORS_ORIGINS if o.strip()] + ["http://localhost:5173", "http://127.0.0.1:5173"]))
app.add_middleware(
    CORSMiddleware,
    allow_origins=origens,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(vendas_router)


@app.get("/")
def raiz():
    return {"app": "Flow Assistente", "docs": "/docs", "health": "/api/health"}
