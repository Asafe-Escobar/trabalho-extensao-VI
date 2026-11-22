"""Leitura dos .md da base de conhecimento (front-matter) e chunking por seção."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_CHARS = 1100


@dataclass
class Doc:
    doc_id: str
    titulo: str
    tipo: str
    tags: list[str]
    corpo: str
    caminho: str


@dataclass
class RawChunk:
    id: str
    doc_id: str
    titulo: str
    tipo: str
    secao: str
    texto: str
    tags: list[str] = field(default_factory=list)


def parse_front_matter(raw: str) -> tuple[dict, str]:
    """Front-matter YAML simples (chave: valor; listas em [a, b] ou '- item')."""
    meta: dict = {}
    if not raw.startswith("---"):
        return meta, raw
    partes = raw.split("---", 2)
    if len(partes) < 3:
        return meta, raw
    cabecalho, corpo = partes[1], partes[2]
    chave_lista = None
    for linha in cabecalho.splitlines():
        if not linha.strip():
            continue
        if linha.lstrip().startswith("- ") and chave_lista:
            meta[chave_lista].append(linha.strip()[2:].strip().strip("'\""))
            continue
        if ":" in linha:
            k, v = linha.split(":", 1)
            k, v = k.strip(), v.strip()
            if v.startswith("[") and v.endswith("]"):
                meta[k] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
                chave_lista = None
            elif v == "":
                meta[k] = []
                chave_lista = k
            else:
                meta[k] = v.strip("'\"")
                chave_lista = None
    return meta, corpo.lstrip("\n")


def load_docs(knowledge_dir: Path) -> list[Doc]:
    docs = []
    for p in sorted(Path(knowledge_dir).glob("*.md")):
        meta, corpo = parse_front_matter(p.read_text(encoding="utf-8"))
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        docs.append(Doc(doc_id=p.stem, titulo=meta.get("titulo", p.stem), tipo=meta.get("tipo", "geral"),
                        tags=tags, corpo=corpo, caminho=str(p)))
    return docs


def _split_long(texto: str, limite: int = MAX_CHARS) -> list[str]:
    if len(texto) <= limite:
        return [texto]
    blocos = re.split(r"\n(?=\s*\n)|\n(?=- |\d+\. |\| )", texto)
    partes, atual = [], ""
    for b in blocos:
        b = b.strip("\n")
        if not b.strip():
            continue
        if atual and len(atual) + len(b) + 1 > limite:
            partes.append(atual.strip())
            atual = ""
        atual += ("\n" if atual else "") + b
    if atual.strip():
        partes.append(atual.strip())
    return partes


def chunk_doc(doc: Doc) -> list[RawChunk]:
    corpo = re.sub(r"^# .*\n", "", doc.corpo.strip() + "\n", count=1)
    secoes: list[tuple[str, str]] = []
    atual_titulo, atual = "Visão geral", []
    for linha in corpo.splitlines():
        if linha.startswith("## "):
            if "".join(atual).strip():
                secoes.append((atual_titulo, "\n".join(atual).strip()))
            atual_titulo, atual = linha[3:].strip(), []
        else:
            atual.append(linha)
    if "".join(atual).strip():
        secoes.append((atual_titulo, "\n".join(atual).strip()))

    chunks: list[RawChunk] = []
    for secao, texto in secoes:
        if doc.tipo == "faq":
            # Uma pergunta por chunk (mais precisão para FAQ)
            perguntas = re.split(r"\n(?=\*\*\d+\.)", "\n" + texto)
            pedacos = [p.strip() for p in perguntas if p.strip()]
        else:
            if len(texto) < 60 and not chunks and len(secoes) > 1:
                continue
            pedacos = _split_long(texto)
        for ped in pedacos:
            cid = f"{doc.doc_id}#{len(chunks)}"
            cabecalho = f"{doc.titulo} — {secao}"
            chunks.append(RawChunk(id=cid, doc_id=doc.doc_id, titulo=doc.titulo, tipo=doc.tipo,
                                   secao=secao, texto=f"{cabecalho}\n{ped}", tags=list(doc.tags)))
    return chunks


def chunk_all(knowledge_dir: Path) -> tuple[list[Doc], list[RawChunk]]:
    docs = load_docs(knowledge_dir)
    chunks = [c for d in docs for c in chunk_doc(d)]
    return docs, chunks
