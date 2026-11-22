"""Ponte para os módulos DATABASE (app.db.connection) e RAG (app.rag).

Os dois módulos são escritos por outros agentes. Aqui importamos pelas assinaturas
do CONTRACT.md de forma *preguiçosa* (a cada chamada, até conseguir) e, se ainda não
existirem, caímos num stub local mínimo. Assim o backend sobe e os testes rodam
mesmo com o restante do projeto em construção. Ver NOTES-backend.md.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel

from .. import config

SCHEMA_PATH = config.BASE_DIR / "db" / "schema.sql"


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def _db_module():
    try:
        from ..db import connection  # type: ignore

        return connection
    except ImportError:
        return None


def _stub_connect(readonly: bool = False) -> sqlite3.Connection:
    path = Path(config.DB_PATH)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(path))
        c.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        c.commit()
        c.close()
    if readonly:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_conn() -> sqlite3.Connection:
    mod = _db_module()
    return mod.get_conn() if mod else _stub_connect()


def get_readonly_conn() -> sqlite3.Connection:
    mod = _db_module()
    return mod.get_readonly_conn() if mod else _stub_connect(readonly=True)


def init_db(reset: bool = False) -> None:
    mod = _db_module()
    if mod:
        mod.init_db(reset=reset)
    else:
        _stub_connect().close()


@contextmanager
def conn_rw() -> Iterator[sqlite3.Connection]:
    """Conexão de escrita com commit/rollback e fechamento garantidos."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def conn_ro() -> Iterator[sqlite3.Connection]:
    conn = get_readonly_conn()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# RAG
# ---------------------------------------------------------------------------
class StubChunk(BaseModel):
    id: str
    doc_id: str
    titulo: str
    tipo: str = ""
    texto: str
    score: float = 0
    fonte: str = "bm25"


class StubTrace(BaseModel):
    original: str
    reescrita: str | None = None
    multi_queries: list[str] = []
    expansao: list[str] = []
    hyde_doc: str | None = None
    candidatos: int = 0
    tecnicas: list[str] = []


def _rag_module():
    try:
        from .. import rag  # type: ignore

        if hasattr(rag, "retrieve"):
            return rag
    except ImportError:
        pass
    return None


def rag_disponivel() -> bool:
    return _rag_module() is not None


def normalizar(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt.lower())
    return "".join(c for c in txt if not unicodedata.combining(c))


_STOP = set(
    "a o e de da do das dos em no na nos nas um uma para por com que se eu me meu minha "
    "voces voce vcs qual quais como quanto tem ter e os as ao aos isso esse essa".split()
)


def tokens(txt: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", normalizar(txt)) if t not in _STOP and len(t) > 1]


def _stub_retrieve(query: str, k: int = 5):
    """Busca por sobreposição de termos nos .md da base de conhecimento (sem índice)."""
    q = set(tokens(query))
    chunks: list[StubChunk] = []
    for md in sorted(config.KNOWLEDGE_DIR.glob("*.md")):
        raw = md.read_text(encoding="utf-8")
        titulo = md.stem.replace("-", " ").title()
        m = re.search(r"^titulo:\s*(.+)$", raw, re.M)
        if m:
            titulo = m.group(1).strip().strip("\"'")
        corpo = re.sub(r"^---.*?---\s*", "", raw, flags=re.S)
        for i, par in enumerate(p for p in re.split(r"\n\s*\n", corpo) if len(p.strip()) > 40):
            t = set(tokens(par))
            s = len(q & t) / (len(q) or 1)
            if s > 0:
                chunks.append(StubChunk(id=f"{md.stem}#{i}", doc_id=md.stem, titulo=titulo, texto=par.strip(), score=round(s, 3)))
    chunks.sort(key=lambda c: c.score, reverse=True)
    trace = StubTrace(original=query, candidatos=len(chunks), tecnicas=["bm25_stub"])
    return chunks[:k], trace


def retrieve(query: str, *, k: int = 5, contexto: dict | None = None, tecnicas: set[str] | None = None):
    mod = _rag_module()
    if mod:
        return mod.retrieve(query, k=k, contexto=contexto, tecnicas=tecnicas)
    return _stub_retrieve(query, k=k)


def build_index(force: bool = False) -> bool:
    mod = _rag_module()
    if mod and hasattr(mod, "build_index"):
        mod.build_index(force=force)
        return True
    return False
