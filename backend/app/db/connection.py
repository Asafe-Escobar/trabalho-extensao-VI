"""Conexões SQLite do Flow Assistente.

- get_conn()           -> conexão leitura/escrita (row_factory=Row, foreign_keys ON).
                          Cria o banco a partir de schema.sql + seed se ainda não existir.
- get_readonly_conn()  -> conexão somente-leitura (URI `mode=ro`), usada pelas
                          ferramentas do ERP e pelo Text-to-SQL.
- init_db(reset=False) -> cria (ou recria, se reset=True) o banco.

O caminho do banco é lido de `config.DB_PATH` a cada chamada (os testes trocam esse valor).
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .. import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_init_lock = threading.Lock()


def _db_path() -> Path:
    return Path(config.DB_PATH)


def _configure(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _connect_rw(path: Path) -> sqlite3.Connection:
    # check_same_thread=False: o FastAPI executa rotas síncronas em threadpool.
    return _configure(sqlite3.connect(str(path), check_same_thread=False, timeout=10))


def _schema_desatualizado(conn: sqlite3.Connection) -> bool:
    """Banco criado antes da virada para gás/RevGás (sem revgas_id ou vendas_revgas)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(produtos)")}
    tem_vendas = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vendas_revgas'").fetchone()
    return "revgas_id" not in cols or not tem_vendas


def _is_initialized(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(str(path), timeout=10)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='produtos'"
            ).fetchone()
            if not row:
                return False
            if _schema_desatualizado(conn):
                return False
            return conn.execute("SELECT COUNT(*) FROM produtos").fetchone()[0] > 0
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False


def init_db(reset: bool = False) -> None:
    """Cria o banco (schema + seed). Com reset=True apaga e recria do zero."""
    from . import seed as seed_mod

    path = _db_path()
    with _init_lock:
        if not reset and path.exists() and path.stat().st_size > 0:
            try:
                c = sqlite3.connect(str(path), timeout=10)
                try:
                    has_prod = c.execute("SELECT 1 FROM sqlite_master WHERE name='produtos'").fetchone()
                    if has_prod and _schema_desatualizado(c):
                        reset = True  # banco da versão antiga (tecnologia): recria com o seed de gás
                finally:
                    c.close()
            except sqlite3.DatabaseError:
                reset = True
        if reset and path.exists():
            path.unlink()
            for suf in ("-wal", "-shm", "-journal"):
                extra = path.with_name(path.name + suf)
                if extra.exists():
                    extra.unlink()
        if not reset and _is_initialized(path):
            # Garante que views/índices novos do schema existam (idempotente).
            conn = _connect_rw(path)
            try:
                conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
                conn.commit()
            finally:
                conn.close()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect_rw(path)
        try:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            seed_mod.seed(conn)
            conn.commit()
        finally:
            conn.close()


def _ensure_db() -> Path:
    path = _db_path()
    if not _is_initialized(path):
        init_db(reset=False)
    return path


def get_conn() -> sqlite3.Connection:
    """Conexão leitura/escrita. Cria o banco se ainda não existir."""
    return _connect_rw(_ensure_db())


def get_readonly_conn() -> sqlite3.Connection:
    """Conexão somente-leitura (`file:...?mode=ro`). Qualquer escrita levanta OperationalError."""
    path = _ensure_db()
    uri = path.resolve().as_uri() + "?mode=ro"
    return _configure(sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=10))
