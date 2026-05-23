"""
Corpus loader. Walks data/ and yields documents typed by their kind.

This is intentionally framework-light: it returns plain dicts that the
retrieval layer (LlamaIndex / ChromaDB / whatever) wraps into its own
document type. Keeps the corpus loader portable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

DocType = Literal["adr", "postmortem", "service", "sample_pr"]


@dataclass
class Document:
    doc_id: str               # ADR-014, INC-2025-02, service:billing-api, pr:pr_001
    doc_type: DocType
    title: str
    body: str                 # full text for embedding
    metadata: dict            # extra fields used by retrieval filters


def _load_md_docs(directory: Path, doc_type: DocType, id_prefix: str) -> list[Document]:
    """Load every .md file in a directory as a Document, parsing the leading ID from the filename."""
    docs: list[Document] = []
    for p in sorted(directory.glob("*.md")):
        stem = p.stem
        if not stem.startswith(id_prefix):
            continue
        # ADR-014-idempotency-keys → ADR-014
        parts = stem.split("-")
        doc_id = "-".join(parts[:2]) if doc_type == "adr" else "-".join(parts[:3])
        body = p.read_text(encoding="utf-8")
        # Title = first H1 line if present, else filename stem
        title = stem
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        docs.append(Document(
            doc_id=doc_id,
            doc_type=doc_type,
            title=title,
            body=body,
            metadata={"source_path": str(p.relative_to(ROOT))},
        ))
    return docs


def load_adrs() -> list[Document]:
    return _load_md_docs(DATA / "adrs", "adr", "ADR-")


def load_postmortems() -> list[Document]:
    return _load_md_docs(DATA / "postmortems", "postmortem", "INC-")


def load_service_catalog() -> list[Document]:
    """Each service in service_catalog.json becomes one Document."""
    catalog = json.loads((DATA / "service_catalog.json").read_text(encoding="utf-8"))
    out: list[Document] = []
    for svc in catalog["services"]:
        body_parts = [
            f"Service: {svc['name']}",
            f"Team: {svc['team']}  Owner role: {svc['owner_role']}",
            f"Depends on: {', '.join(svc.get('depends_on') or ['—'])}",
            f"Depended on by: {', '.join(svc.get('depended_on_by') or ['—'])}",
            f"Compliance scope: {', '.join(svc.get('compliance_scope') or ['—'])}",
            f"Related ADRs: {', '.join(svc.get('related_adrs') or ['—'])}",
        ]
        out.append(Document(
            doc_id=f"service:{svc['name']}",
            doc_type="service",
            title=f"Service catalog — {svc['name']}",
            body="\n".join(body_parts),
            metadata={"service_name": svc["name"], "owner_role": svc["owner_role"]},
        ))
    return out


def load_all() -> list[Document]:
    """Return every document the assessor will retrieve over."""
    return load_adrs() + load_postmortems() + load_service_catalog()
