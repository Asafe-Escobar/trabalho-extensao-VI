"""retrieve(): pipeline completo de recuperação.

  pergunta ─► Query Rewriting (memória) ─► Multi-Query (3) ─► Query Expansion ─► HyDE
          ─► buscas paralelas: BM25 · vetorial · HyDE(vetorial) · HyPE · GraphRAG
          ─► Reciprocal Rank Fusion ─► Reranking ─► top-k Chunks + RetrievalTrace
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .. import llm
from . import query as qmod
from .embeddings import similarity
from .fusion import cross_score, llm_rerank, rrf
from .graph import search as graph_search
from .index import IndexState, get_state
from .models import Chunk, RetrievalTrace
from .text import tokens

log = logging.getLogger(__name__)

TECNICAS = ("rewrite", "multi_query", "expansion", "hyde", "hype", "graph", "hybrid", "rerank")
TOP_LISTA = 20
TOP_RERANK = 15


def _bm25_rank(st: IndexState, texto: str, n: int = TOP_LISTA) -> list[str]:
    toks = tokens(texto)
    if not toks:
        return []
    scores = st.bm25.get_scores(toks)
    idx = np.argsort(-scores)[:n]
    return [st.chunks[i].id for i in idx if scores[i] > 0]


def _vec_rank(st: IndexState, texto: str, n: int = TOP_LISTA, minimo: float = 0.02) -> list[str]:
    q = st.embedder.encode([texto])
    sims = similarity(st.mat_chunks, q)
    idx = np.argsort(-sims)[:n]
    return [st.chunks[i].id for i in idx if sims[i] > minimo]


def _hype_rank(st: IndexState, texto: str, n: int = TOP_LISTA) -> tuple[list[str], dict[str, float], list[str]]:
    """Pergunta do cliente × perguntas hipotéticas: (ranking de chunks, melhor similaridade, perguntas casadas)."""
    if not st.hype_pairs or st.mat_hype is None:
        return [], {}, []
    sims = similarity(st.mat_hype, st.embedder.encode([texto]))
    toks = tokens(texto)
    if st.bm25_hype is not None and toks:
        b = st.bm25_hype.get_scores(toks)
        if b.max() > 0:
            sims = 0.7 * sims + 0.3 * (b / b.max())
    melhor: dict[str, float] = {}
    pergunta: dict[str, str] = {}
    for i in np.argsort(-sims):
        if sims[i] <= 0.05:
            break
        cid, q = st.hype_pairs[i]
        if cid not in melhor:
            melhor[cid] = float(sims[i])
            pergunta[cid] = q
        if len(melhor) >= n:
            break
    ranking = list(melhor)
    return ranking, melhor, [pergunta[c] for c in ranking[:3]]


def _extra_seeds(st: IndexState, contexto: dict | None) -> dict[str, float]:
    seeds: dict[str, float] = {}
    if not contexto:
        return seeds
    sku = contexto.get("produto_sku") or contexto.get("sku")
    if sku:
        seeds[f"produto:{str(sku).upper()}"] = 1.5
    for item in contexto.get("carrinho") or []:
        if isinstance(item, dict):
            rid = item.get("revgas_id")
            for p in st.produtos:
                if rid and p.get("revgas_id") == rid:
                    seeds[f"produto:{p['sku']}"] = 1.0
    return seeds


def retrieve(query: str, *, k: int = 5, contexto: dict | None = None,
             tecnicas: set[str] | None = None) -> tuple[list[Chunk], RetrievalTrace]:
    ativas = set(TECNICAS) if tecnicas is None else set(tecnicas) & set(TECNICAS)
    st = get_state()
    trace = RetrievalTrace(original=query, embeddings=st.embedder.backend)
    usadas: list[str] = []

    # 1) Query Rewriting (depende da memória) -------------------------------------------
    q = query
    if "rewrite" in ativas:
        rw = qmod.rewrite(query, contexto, st.nomes_por_sku)
        if rw:
            q = rw
            trace.reescrita = rw
            usadas.append("rewrite")

    # 2) Multi-Query, Expansion e HyDE (independentes -> em paralelo quando há LLM) -------
    tarefas = {}
    if "multi_query" in ativas:
        tarefas["multi_query"] = qmod.multi_query
    if "expansion" in ativas:
        tarefas["expansion"] = qmod.expansion
    if "hyde" in ativas:
        tarefas["hyde"] = qmod.hyde
    res: dict = {}
    if tarefas and not llm.is_mock():
        with ThreadPoolExecutor(max_workers=len(tarefas)) as ex:
            futs = {nome: ex.submit(fn, q) for nome, fn in tarefas.items()}
            res = {nome: f.result() for nome, f in futs.items()}
    else:
        res = {nome: fn(q) for nome, fn in tarefas.items()}

    multi = res.get("multi_query") or []
    expansao = res.get("expansion") or []
    hyde_doc = res.get("hyde")
    trace.multi_queries = multi
    trace.expansao = expansao
    trace.hyde_doc = hyde_doc
    for nome, chave in (("multi_query", multi), ("expansion", expansao), ("hyde", hyde_doc)):
        if chave:
            usadas.append(nome)

    # 3) Buscas ------------------------------------------------------------------------
    listas: list[tuple[str, list[str], float]] = []
    principal = q + (" " + " ".join(expansao) if expansao else "")
    hybrid = "hybrid" in ativas
    listas.append(("bm25", _bm25_rank(st, principal), 1.0))
    if hybrid:
        listas.append(("vetorial", _vec_rank(st, principal), 1.0))
    for mq in multi:
        listas.append(("bm25", _bm25_rank(st, mq), 0.6))
        if hybrid:
            listas.append(("vetorial", _vec_rank(st, mq), 0.6))
    if hyde_doc:
        listas.append(("vetorial", _vec_rank(st, hyde_doc), 0.8))
    if hybrid:
        usadas.append("hybrid")

    hype_sim: dict[str, float] = {}
    if "hype" in ativas:
        rk, hype_sim, perguntas = _hype_rank(st, q)
        if rk:
            listas.append(("hype", rk, 1.0))
            trace.hype_perguntas = perguntas
            usadas.append("hype")

    if "graph" in ativas:
        ranked, entidades = graph_search(st.graph, q, extra_seeds=_extra_seeds(st, contexto))
        if ranked:
            listas.append(("grafo", [cid for cid, _ in ranked if cid in st.by_id], 1.0))
            trace.grafo_entidades = entidades[:8]
            usadas.append("graph")

    # 4) Fusão RRF -------------------------------------------------------------------------
    score_rrf, fonte = rrf([l for l in listas if l[1]])
    trace.candidatos = len(score_rrf)
    if not score_rrf:
        trace.tecnicas = usadas
        return [], trace
    ordenados = sorted(score_rrf, key=lambda c: -score_rrf[c])
    max_rrf = score_rrf[ordenados[0]]

    # 5) Reranking -------------------------------------------------------------------------
    finais: list[tuple[str, float]]
    if "rerank" in ativas:
        cands = ordenados[:TOP_RERANK]
        ordem_llm = llm_rerank(q, [(cid, st.by_id[cid].texto) for cid in cands])
        heur = {cid: cross_score(q, expansao, st.by_id[cid].texto, st.by_id[cid].texto.split("\n", 1)[0],
                                 score_rrf[cid] / max_rrf, hype_sim.get(cid, 0.0)) for cid in cands}
        if ordem_llm:
            n = len(ordem_llm)
            finais = [(cid, round(0.5 * (1 - i / max(n, 1)) + 0.5 * heur[cid], 4))
                      for i, cid in enumerate(ordem_llm)]
        else:
            finais = sorted(heur.items(), key=lambda x: -x[1])
        usadas.append("rerank")
    else:
        finais = [(cid, round(score_rrf[cid] / max_rrf, 4)) for cid in ordenados]

    # 6) Top-k -------------------------------------------------------------------------------
    out: list[Chunk] = []
    for cid, s in finais[:k]:
        c = st.by_id[cid]
        out.append(Chunk(id=c.id, doc_id=c.doc_id, titulo=c.titulo, tipo=c.tipo, texto=c.texto,
                         score=float(s), fonte=fonte.get(cid, "bm25")))
    trace.tecnicas = usadas
    return out, trace
