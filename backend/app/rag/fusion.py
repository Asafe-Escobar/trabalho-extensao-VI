"""Reciprocal Rank Fusion e Reranking (LLM em lista ou cross-score heurístico no mock)."""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from .. import llm
from .text import bigrams, tokens

log = logging.getLogger(__name__)

RRF_K = 60
# desempate de fonte quando duas listas dão a mesma contribuição
_PRIORIDADE = {"bm25": 0, "vetorial": 1, "hype": 2, "grafo": 3}


def rrf(listas: list[tuple[str, list[str], float]]) -> tuple[dict[str, float], dict[str, str]]:
    """listas: [(fonte, [chunk_id em ordem], peso)] -> (score_rrf, fonte_principal).

    score(d) = Σ peso / (RRF_K + rank). A fonte do chunk é a lista que mais contribuiu.
    """
    score: dict[str, float] = {}
    melhor: dict[str, tuple[float, int, str]] = {}
    for fonte, ids, peso in listas:
        for rank, cid in enumerate(ids, start=1):
            contrib = peso / (RRF_K + rank)
            score[cid] = score.get(cid, 0.0) + contrib
            chave = (contrib, -_PRIORIDADE.get(fonte, 9), fonte)
            if cid not in melhor or chave[:2] > melhor[cid][:2]:
                melhor[cid] = chave
    return score, {cid: m[2] for cid, m in melhor.items()}


# ---------------------------------------------------------------------------
def cross_score(query: str, expansao: list[str], texto: str, cabecalho: str, rrf_norm: float,
                hype_sim: float = 0.0) -> float:
    """Pontuação heurística 0..1 que imita um cross-encoder: sobreposição de termos, bigramas,
    título/seção, termos expandidos, posição na fusão e casamento com pergunta HyPE."""
    qt = tokens(query)
    q = set(qt)
    if not q:
        return rrf_norm
    ct = tokens(texto)
    c = set(ct)
    h = set(tokens(cabecalho))
    e = set(tokens(" ".join(expansao)))
    overlap = len(q & c) / len(q)
    titulo = len(q & h) / len(q)
    qb = bigrams(qt)
    bi = len(qb & bigrams(ct)) / len(qb) if qb else 0.0
    exp = len(e & c) / len(e) if e else 0.0
    s = 0.34 * rrf_norm + 0.28 * overlap + 0.14 * titulo + 0.10 * bi + 0.06 * exp + 0.08 * min(1.0, hype_sim)
    return round(min(1.0, s), 4)


class Ordem(BaseModel):
    ordem: list[int] = Field(default_factory=list, description="índices dos trechos, do mais ao menos relevante")


_SYS_RERANK = (
    "Você é um reranqueador. Ordene os trechos numerados pela utilidade para responder à pergunta do "
    "cliente de uma revenda de gás GLP e água mineral. Devolva apenas a lista de índices, do mais relevante ao menos "
    "relevante, incluindo só trechos úteis."
)


def llm_rerank(query: str, candidatos: list[tuple[str, str]]) -> list[str] | None:
    """candidatos: [(chunk_id, texto)] -> chunk_ids reordenados (ou None se falhar)."""
    if llm.is_mock() or not candidatos:
        return None
    linhas = [f"[{i}] {t[:350].replace(chr(10), ' ')}" for i, (_, t) in enumerate(candidatos)]
    user = f"Pergunta: {query}\n\nTrechos:\n" + "\n".join(linhas)
    try:
        r = llm.structured(_SYS_RERANK, user, Ordem, max_tokens=300, mock=lambda _u: Ordem())
        vistos, out = set(), []
        for i in r.ordem:
            if 0 <= i < len(candidatos) and i not in vistos:
                vistos.add(i)
                out.append(candidatos[i][0])
        return out or None
    except Exception as e:  # pragma: no cover - rede
        log.warning("rerank via LLM falhou: %s", e)
        return None
