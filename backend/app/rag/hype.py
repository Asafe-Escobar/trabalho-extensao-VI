"""HyPE — Hypothetical Prompt Embeddings.

Na indexação, cada chunk ganha perguntas hipotéticas que ele responde. Na consulta, a pergunta
do cliente é comparada com essas perguntas (pergunta × pergunta casa melhor do que pergunta ×
texto de política). Em modo mock as perguntas vêm de templates; com o Claude, do LLM.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from .. import llm
from .chunking import RawChunk

log = logging.getLogger(__name__)

MAX_PERGUNTAS = 5


class PerguntasHipoteticas(BaseModel):
    perguntas: list[str] = Field(default_factory=list, description="3 a 5 perguntas de clientes")


_SYSTEM = (
    "Você indexa a base de conhecimento da Flow (revenda de gás GLP e água mineral no PI/MA). "
    "Dado um trecho, escreva de 3 a 5 perguntas curtas, em português do Brasil, no tom de um cliente "
    "real no chat, que este trecho responde diretamente. Não invente fatos fora do trecho."
)


def _bolds(texto: str) -> list[str]:
    return [b.strip().rstrip(":.") for b in re.findall(r"\*\*([^*]{3,90})\*\*", texto)]


def template_questions(c: RawChunk) -> list[str]:
    secao = c.secao
    sl = secao[0].lower() + secao[1:] if secao else ""
    corpo = c.texto.split("\n", 1)[-1]
    qs: list[str] = []
    if c.tipo == "faq":
        m = re.search(r"\*\*\d+\.\s*([^*]+)\*\*", corpo)
        if m:
            q = m.group(1).strip()
            qs.append(q)
            base = q.rstrip("?")
            qs.append(f"Queria saber: {base[0].lower() + base[1:]}?")
        qs.append(f"Dúvida sobre {sl}")
    elif c.tipo == "catalogo":
        for nome in _bolds(corpo)[:2]:
            if len(nome) < 8 or nome.startswith("R$"):
                continue
            qs.append(f"Quanto tá o {nome}?")
            qs.append(f"Vocês têm {nome} para entregar hoje?")
        qs.append(f"Quais opções de {sl} a Flow vende?")
    elif c.tipo == "manual":
        assunto = re.sub(r"^Manual( rápido)? — ", "", c.titulo)
        qs.append(f"{assunto[0].upper() + assunto[1:]}?")
        qs.append(f"{secao} — {assunto}")
        for b in _bolds(corpo)[:3]:
            qs.append(f"{b}: o que fazer?")
    elif c.tipo == "seguranca":
        qs.append(f"{secao}: o que fazer?")
        qs.append("Estou sentindo cheiro de gás, o que eu faço?")
        for b in _bolds(corpo)[:2]:
            qs.append(f"Por que {b.lower()}?")
    else:
        qs.append(f"Como funciona {sl} na Flow?")
        qs.append(f"Qual a regra da {c.titulo} sobre {sl}?")
        for b in _bolds(corpo)[:2]:
            qs.append(f"O que é {b.lower()}?")
    if c.tags:
        qs.append(f"Pergunta sobre {', '.join(c.tags[:3])}")
    vistos, out = set(), []
    for q in qs:
        k = q.lower()
        if k not in vistos:
            vistos.add(k)
            out.append(q)
    return out[:MAX_PERGUNTAS]


def _llm_questions(c: RawChunk) -> list[str]:
    try:
        r = llm.structured(_SYSTEM, f"Trecho ({c.titulo} — {c.secao}):\n{c.texto[:1500]}",
                           PerguntasHipoteticas, max_tokens=400, mock=lambda _u: PerguntasHipoteticas())
        qs = [q.strip() for q in r.perguntas if q and q.strip()]
        return qs[:MAX_PERGUNTAS] or template_questions(c)
    except Exception as e:  # rede, limite de taxa, etc.
        log.warning("HyPE via LLM falhou para %s: %s", c.id, e)
        return template_questions(c)


def generate(chunks: list[RawChunk]) -> dict[str, list[str]]:
    """chunk_id -> perguntas hipotéticas."""
    if llm.is_mock():
        return {c.id: template_questions(c) for c in chunks}
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(_llm_questions, chunks))
    return {c.id: qs for c, qs in zip(chunks, res)}
