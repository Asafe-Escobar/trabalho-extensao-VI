"""Configuração central lida de variáveis de ambiente (.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent          # backend/app
BACKEND_DIR = BASE_DIR.parent                        # backend
load_dotenv(BACKEND_DIR / ".env")

DB_PATH = Path(os.getenv("FLOW_DB_PATH", BACKEND_DIR / "data" / "flow.db"))
KNOWLEDGE_DIR = BASE_DIR / "db" / "knowledge"
INDEX_DIR = Path(os.getenv("FLOW_INDEX_DIR", BACKEND_DIR / "data" / "index"))

LLM_MODEL = os.getenv("LLM_MODEL", "claude-opus-5-5")
LLM_EFFORT = os.getenv("LLM_EFFORT", "low")  # chat de atendimento: baixa latência

# "anthropic" | "mock" | "auto" (auto = anthropic se houver ANTHROPIC_API_KEY)
_mode = os.getenv("LLM_MODE", "auto").lower()
if _mode == "auto":
    _mode = "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "mock"
LLM_MODE = _mode

EMBEDDINGS = os.getenv("EMBEDDINGS", "auto")  # "fastembed" | "tfidf" | "auto"
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

# --- RevGás (ERP real) — ver docs/revgas-api.md. A chave NUNCA vai para código/logs. ---
REVGAS_API_URL = os.getenv("REVGAS_API_URL") or "https://api.revgas.com/v1"
REVGAS_API_KEY = os.getenv("REVGAS_API_KEY", "")
# "dryrun" (padrão: não faz POST /sales) | "real" (único que grava venda) | "offline" (sem rede)
REVGAS_MODO = (os.getenv("REVGAS_MODO") or "dryrun").lower()

# --- n8n / automações ---
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")
N8N_HANDOFF_WEBHOOK_URL = os.getenv("N8N_HANDOFF_WEBHOOK_URL", "")
FLOW_AUTOMACAO_TOKEN = os.getenv("FLOW_AUTOMACAO_TOKEN", "")
