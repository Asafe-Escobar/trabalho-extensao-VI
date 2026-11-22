"""Busca vetorial: fastembed (multilíngue, opcional) ou TF-IDF (fallback padrão, offline).

`config.EMBEDDINGS`: "fastembed" | "tfidf" | "auto" (auto = fastembed se instalado).
Os vetores são L2-normalizados; similaridade = produto interno (cosseno).
"""
from __future__ import annotations

import logging

import numpy as np

from .. import config
from .text import normalize, tokens

log = logging.getLogger(__name__)

FASTEMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _word_analyzer(text: str) -> list[str]:
    toks = tokens(text)
    return toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]


class Embedder:
    """Interface comum: fit(textos) -> matriz; encode(textos) -> matriz (linhas normalizadas)."""

    backend = "tfidf"

    def fit(self, textos: list[str]):  # pragma: no cover - interface
        raise NotImplementedError

    def encode(self, textos: list[str]):  # pragma: no cover - interface
        raise NotImplementedError


class TfidfEmbedder(Embedder):
    backend = "tfidf"

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer

        # palavras com stemming + bigramas  e  n-gramas de caracteres (robusto a flexões/erros)
        self.word = TfidfVectorizer(analyzer=_word_analyzer, sublinear_tf=True, min_df=1)
        self.char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), preprocessor=normalize,
                                    sublinear_tf=True, min_df=1, max_features=60000)

    def _combine(self, a, b):
        from scipy.sparse import hstack
        from sklearn.preprocessing import normalize as l2

        return l2(hstack([a * 0.6, b * 0.4]).tocsr())

    def fit(self, textos):
        return self._combine(self.word.fit_transform(textos), self.char.fit_transform(textos))

    def encode(self, textos):
        return self._combine(self.word.transform(textos), self.char.transform(textos))


class FastEmbedder(Embedder):
    backend = "fastembed"

    def __init__(self):
        from fastembed import TextEmbedding  # noqa: F401 - erro aqui => fallback

        self._model = None

    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=FASTEMBED_MODEL)
        return self._model

    def __getstate__(self):
        return {"_model": None}

    def __setstate__(self, state):
        self._model = None

    def encode(self, textos):
        vecs = np.array(list(self.model.embed(list(textos))), dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.maximum(norms, 1e-9)

    def fit(self, textos):
        return self.encode(textos)


def make_embedder() -> Embedder:
    escolha = (config.EMBEDDINGS or "auto").lower()
    if escolha in ("fastembed", "auto"):
        try:
            emb = FastEmbedder()
            emb.encode(["teste"])  # força download/carga; falha => TF-IDF
            return emb
        except Exception as e:  # ImportError, rede, etc.
            if escolha == "fastembed":
                log.warning("fastembed indisponível (%s); usando TF-IDF", e)
    return TfidfEmbedder()


def similarity(matriz, consulta) -> np.ndarray:
    """Cosseno entre cada linha de `matriz` e o vetor (1 x d) `consulta`."""
    sims = matriz @ consulta.T
    if hasattr(sims, "toarray"):
        sims = sims.toarray()
    return np.asarray(sims).ravel()
