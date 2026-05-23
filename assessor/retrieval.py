"""
Retrieval layer over the Fintora corpus.

Default backend: LlamaIndex + the corpus loaded into a single VectorStoreIndex
with per-doc-type metadata so individual nodes can filter retrieval to
'adr', 'postmortem', or 'service' subsets independently.

This module is intentionally minimal — it exposes one `retrieve(query, *, doc_types, k)`
function. The LangGraph nodes call into it with different `doc_types` filters
to get scoped context.

The first time you run, it ingests; subsequent runs reuse the persisted index.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .corpus import Document, load_all


INDEX_DIR = Path(__file__).resolve().parent.parent / ".index"


@dataclass
class RetrievedChunk:
    doc_id: str
    doc_type: str
    title: str
    excerpt: str
    score: float       # similarity in [0, 1] (normalised)
    metadata: dict


# ─── Lazy index init ──────────────────────────────────────────────────────────

_index = None  # cached VectorStoreIndex


def _ensure_index():
    """Build the index on first call, persist for subsequent calls."""
    global _index
    if _index is not None:
        return _index

    from llama_index.core import VectorStoreIndex, StorageContext, Document as LIDocument
    from llama_index.core import load_index_from_storage
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")

    if (INDEX_DIR / "docstore.json").exists():
        storage = StorageContext.from_defaults(persist_dir=str(INDEX_DIR))
        _index = load_index_from_storage(storage, embed_model=embed_model)
        return _index

    docs = [
        LIDocument(
            text=d.body,
            id_=d.doc_id,
            metadata={
                "doc_id": d.doc_id,
                "doc_type": d.doc_type,
                "title": d.title,
                **d.metadata,
            },
        )
        for d in load_all()
    ]
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    _index = VectorStoreIndex.from_documents(docs, embed_model=embed_model)
    _index.storage_context.persist(persist_dir=str(INDEX_DIR))
    return _index


# ─── Public API ──────────────────────────────────────────────────────────────

def retrieve(
    query: str,
    *,
    doc_types: Optional[list[str]] = None,
    k: int = 5,
) -> list[RetrievedChunk]:
    """
    Retrieve k chunks from the corpus, optionally filtered by document type.

    Args:
        query: natural-language query
        doc_types: filter to a subset, e.g. ['adr', 'service'] or ['postmortem']
        k: top-k chunks to return
    """
    from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterCondition

    index = _ensure_index()

    filters = None
    if doc_types:
        filters = MetadataFilters(
            filters=[MetadataFilter(key="doc_type", value=dt) for dt in doc_types],
            condition=FilterCondition.OR if len(doc_types) > 1 else FilterCondition.AND,
        )

    retriever = index.as_retriever(similarity_top_k=k, filters=filters)
    nodes = retriever.retrieve(query)

    out: list[RetrievedChunk] = []
    for n in nodes:
        meta = n.node.metadata or {}
        out.append(RetrievedChunk(
            doc_id=meta.get("doc_id", n.node.id_),
            doc_type=meta.get("doc_type", "unknown"),
            title=meta.get("title", ""),
            excerpt=n.node.get_content()[:500],
            score=float(n.score) if n.score is not None else 0.0,
            metadata=meta,
        ))
    return out
