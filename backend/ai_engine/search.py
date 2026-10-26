"""Hybrid code search: BM25 keywords + FAISS semantic similarity, merged with Reciprocal Rank Fusion.

Ranking approach (simple enough to explain in an interview):
  * Run BM25 and FAISS separately; each produces a ranked list of chunks.
  * Reciprocal Rank Fusion gives every chunk the score  sum(1 / (60 + rank))  over the lists it appears in.
  * Chunks found by both methods float to the top; scores from different methods never need to be compared.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .indexing import SemanticSearchUnavailable, embed_texts

RRF_K = 60
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
STOPWORDS = {"the", "a", "an", "is", "are", "of", "to", "in", "and", "or", "how", "does", "do", "where", "what",
             "which", "this", "that", "it", "for", "on", "with", "i", "my", "can", "be", "by", "as", "at"}


def tokenize(text: str) -> list[str]:
    """Code-aware tokenizer: keeps identifiers and also splits snake_case / camelCase."""
    tokens: list[str] = []
    for word in _WORD.findall(text):
        low = word.lower()
        if low not in STOPWORDS:
            tokens.append(low)
        pieces = [p.lower() for part in word.split("_") for p in _CAMEL.findall(part)]
        if len(pieces) > 1:
            tokens.extend(p for p in pieces if p not in STOPWORDS)
    return tokens


@dataclass
class IndexData:
    chunks: list[dict]
    bm25: object
    faiss_index: object | None


_cache: dict[str, tuple[float, IndexData]] = {}


def load_index(index_dir: Path) -> IndexData:
    index_dir = Path(index_dir)
    chunks_file = index_dir / "chunks.json"
    if not chunks_file.exists():
        raise FileNotFoundError("This repository has not been analyzed yet.")
    mtime = chunks_file.stat().st_mtime
    cached = _cache.get(str(index_dir))
    if cached and cached[0] == mtime:
        return cached[1]
    from rank_bm25 import BM25Okapi

    chunks = json.loads(chunks_file.read_text(encoding="utf-8"))
    corpus = [tokenize(f"{c['path']} {c.get('symbol', '')} {c['text']}") or ["_empty_"] for c in chunks]
    faiss_index = None
    faiss_file = index_dir / "faiss.index"
    if faiss_file.exists():
        try:
            import faiss

            faiss_index = faiss.read_index(str(faiss_file))
        except Exception:
            faiss_index = None
    data = IndexData(chunks=chunks, bm25=BM25Okapi(corpus), faiss_index=faiss_index)
    _cache[str(index_dir)] = (mtime, data)
    return data


def keyword_search(data: IndexData, query: str, top_k: int) -> list[int]:
    tokens = tokenize(query)
    if not tokens:
        return []
    scores = data.bm25.get_scores(tokens)
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return [i for i in ranked[:top_k] if scores[i] > 0]


def semantic_search(data: IndexData, query: str, top_k: int, embedder=None, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> list[int]:
    if data.faiss_index is None:
        raise SemanticSearchUnavailable("No semantic index exists for this repository.")
    vector = embed_texts([query], embedder, model_name)
    _, ids = data.faiss_index.search(vector, min(top_k, len(data.chunks)))
    return [int(i) for i in ids[0] if i >= 0]


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def hybrid_search(index_dir: Path, query: str, top_k: int = 8, mode: str = "hybrid", embedder=None,
                  model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> dict:
    """Search a repository index. `mode` is 'hybrid', 'keyword' or 'semantic'.

    The response says which mode was really used, so the UI never claims semantic
    results when only keyword search was possible.
    """
    data = load_index(index_dir)
    pool = max(top_k * 3, 20)
    note = ""
    keyword_ranked: list[int] = []
    semantic_ranked: list[int] = []
    mode_used = mode
    if mode in ("hybrid", "keyword"):
        keyword_ranked = keyword_search(data, query, pool)
    if mode in ("hybrid", "semantic"):
        try:
            semantic_ranked = semantic_search(data, query, pool, embedder, model_name)
        except SemanticSearchUnavailable as exc:
            note = f"Semantic search is unavailable ({exc}) - showing keyword results only."
            mode_used = "keyword"
            keyword_ranked = keyword_ranked or keyword_search(data, query, pool)
        except Exception as exc:
            note = f"Semantic search failed ({type(exc).__name__}) - showing keyword results only."
            mode_used = "keyword"
            keyword_ranked = keyword_ranked or keyword_search(data, query, pool)
    fused = reciprocal_rank_fusion([r for r in (keyword_ranked, semantic_ranked) if r])
    kw_rank = {cid: r for r, cid in enumerate(keyword_ranked, 1)}
    sem_rank = {cid: r for r, cid in enumerate(semantic_ranked, 1)}
    results = []
    for chunk_id, score in fused[:top_k]:
        chunk = data.chunks[chunk_id]
        results.append({**chunk, "score": round(score, 5), "keyword_rank": kw_rank.get(chunk_id), "semantic_rank": sem_rank.get(chunk_id)})
    return {"query": query, "mode_requested": mode, "mode_used": mode_used, "note": note, "results": results}
