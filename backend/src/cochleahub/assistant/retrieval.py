"""Hybrid retrieval over the project documentation (D19).

RAG [Lewis2020] retrieves with a dense retriever only. We fuse two rankings instead:

- BM25 [Robertson2009]: lexical, so exact codes and names (OUT_OF_PUBLISHED_RANGE, D14,
  Zahara2019) are matched literally.
- Dense embeddings (BGE small [Xiao2024], run locally with fastembed): paraphrases ("how close is
  the nerve to the cochlea") match "facial nerve to scala tympani".

BEIR [Thakur2021] showed that dense retrievers often fall behind BM25 outside their training
domain, and our corpus is a narrow technical domain. Reciprocal Rank Fusion [Cormack2009]
combines both rankings without tuning score scales.

Everything runs locally: no document text leaves the machine to build or query the index.
"""

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from cochleahub.config import REPO_ROOT, settings

# Corpus: what the assistant may cite for concepts, methods and decisions.
CORPUS = [
    "docs/knowledge/measurements.md",
    "docs/knowledge/dataset.md",
    "docs/knowledge/user-guide.md",
    "docs/DECISIONS.md",
    "docs/REFERENCES.md",
    "docs/validation/zeta.md",
]

RRF_K = 60  # [Cormack2009]
BM25_K1, BM25_B = 1.2, 0.75  # common defaults within the range discussed in [Robertson2009]
MAX_CHUNK_CHARS = 1800

TOKEN = re.compile(r"[a-z0-9_]+")


@dataclass
class Chunk:
    id: str  # e.g. "docs/DECISIONS.md#d5"
    path: str
    title: str  # "file title › section heading"
    text: str


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def chunk_markdown(path: str, text: str) -> list[Chunk]:
    """One chunk per `##` section (with its `###` subsections); long sections are split on
    paragraph boundaries. Each chunk keeps the document and section title, so a retrieved
    passage is understandable on its own."""
    lines = text.splitlines()
    doc_title = next((ln[2:].strip() for ln in lines if ln.startswith("# ")), Path(path).stem)
    sections: list[tuple[str, list[str]]] = [(doc_title, [])]
    for ln in lines:
        if ln.startswith("## "):
            sections.append((ln[3:].strip(), []))
        elif not ln.startswith("# "):
            sections[-1][1].append(ln)

    chunks = []
    for heading, body in sections:
        body_text = "\n".join(body).strip()
        if not body_text:
            continue
        parts, current = [], ""
        for para in re.split(r"\n\s*\n", body_text):
            if current and len(current) + len(para) > MAX_CHUNK_CHARS:
                parts.append(current)
                current = para
            else:
                current = f"{current}\n\n{para}" if current else para
        parts.append(current)
        for i, part in enumerate(parts):
            anchor = slug(heading) + (f"-{i + 1}" if len(parts) > 1 else "")
            title = doc_title if heading == doc_title else f"{doc_title} › {heading}"
            chunks.append(Chunk(id=f"{path}#{anchor}", path=path, title=title, text=part))
    return chunks


def load_corpus(root: Path = REPO_ROOT, files: list[str] = CORPUS) -> list[Chunk]:
    chunks = []
    for rel in files:
        chunks.extend(chunk_markdown(rel, (root / rel).read_text(encoding="utf-8")))
    return chunks


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = BM25_K1, b: float = BM25_B):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=float)
        self.avg = float(self.len.mean()) if len(docs) else 0.0
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        s = np.zeros(len(self.tf))
        for i, tf in enumerate(self.tf):
            norm = self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)
            for t in query:
                if t in tf:
                    s[i] += self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + norm)
        return s


def rrf(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return fused


class Embedder:
    """Local ONNX embedding model; downloaded once into data/models."""

    def __init__(self, model: str | None = None):
        from fastembed import TextEmbedding

        self.name = model or settings.embedding_model
        cache = settings.output_path / "models"
        cache.mkdir(parents=True, exist_ok=True)
        self.model = TextEmbedding(self.name, cache_dir=str(cache))

    def documents(self, texts: list[str]) -> np.ndarray:
        return normalise(np.array(list(self.model.passage_embed(texts))))

    def query(self, text: str) -> np.ndarray:
        return normalise(np.array(list(self.model.query_embed(text))))[0]


def normalise(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


@dataclass
class Hit:
    chunk: Chunk
    score: float
    bm25_rank: int | None
    dense_rank: int | None


class Index:
    def __init__(self, chunks: list[Chunk], vectors: np.ndarray | None, embedder=None):
        self.chunks = chunks
        self.vectors = vectors
        self.embedder = embedder
        self.bm25 = BM25([tokenize(f"{c.title}\n{c.text}") for c in chunks])

    def search(self, query: str, k: int = 5, candidates: int = 20) -> list[Hit]:
        lexical = self.bm25.scores(tokenize(query))
        bm25_rank = [int(i) for i in np.argsort(-lexical)[:candidates] if lexical[i] > 0]
        rankings = [bm25_rank]
        dense_rank: list[int] = []
        if self.vectors is not None and self.embedder is not None:
            sims = self.vectors @ self.embedder.query(query)
            dense_rank = [int(i) for i in np.argsort(-sims)[:candidates]]
            rankings.append(dense_rank)
        fused = rrf(rankings)
        best = sorted(fused, key=fused.get, reverse=True)[:k]
        return [
            Hit(
                chunk=self.chunks[i],
                score=fused[i],
                bm25_rank=bm25_rank.index(i) + 1 if i in bm25_rank else None,
                dense_rank=dense_rank.index(i) + 1 if i in dense_rank else None,
            )
            for i in best
        ]


def corpus_hash(chunks: list[Chunk], model: str) -> str:
    h = hashlib.sha256(model.encode())
    for c in chunks:
        h.update(c.id.encode())
        h.update(c.text.encode())
    return h.hexdigest()[:16]


def build_index(index_dir: Path | None = None, dense: bool = True) -> Index:
    """Load the corpus and its embeddings, re-embedding only when the corpus or model changed."""
    chunks = load_corpus()
    if not dense:
        return Index(chunks, None)
    embedder = Embedder()
    index_dir = index_dir or settings.output_path / "assistant"
    index_dir.mkdir(parents=True, exist_ok=True)
    key = corpus_hash(chunks, embedder.name)
    vec_path, meta_path = index_dir / f"vectors-{key}.npy", index_dir / f"chunks-{key}.json"
    if vec_path.exists() and meta_path.exists():
        vectors = np.load(vec_path)
    else:
        vectors = embedder.documents([f"{c.title}\n{c.text}" for c in chunks])
        np.save(vec_path, vectors)
        meta_path.write_text(json.dumps([asdict(c) for c in chunks], indent=1), encoding="utf-8")
    return Index(chunks, vectors, embedder)
