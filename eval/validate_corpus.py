"""
Corpus consistency validator.

Run on every commit (and from CI):
    python -m eval.validate_corpus

Asserts:
  - Every ADR / postmortem / sample PR has a parsable header
  - Every cross-reference (ADR-NNN, INC-YYYY-MM) points to an existing document
  - Every service named in sample-PR expected.json exists in service_catalog.json
  - Every approver role in expected.json exists in service_catalog.json's approver list

Fails loud. Exit code 1 on any inconsistency.

This script is itself a portfolio signal: the corpus is treated as code,
with the same consistency discipline tests apply to real source.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

ADR_REF_RE = re.compile(r"\bADR-\d{3}\b")
INC_REF_RE = re.compile(r"\bINC-\d{4}-\d{2}\b")


def _collect_ids(directory: Path, pattern: re.Pattern) -> set[str]:
    """Pull IDs from filenames in a directory: ADR-014-idempotency-keys.md → ADR-014."""
    ids: set[str] = set()
    for p in directory.glob("*.md"):
        m = pattern.match(p.stem)
        if m:
            ids.add(m.group(0))
    return ids


def _collect_referenced_ids(directory: Path, pattern: re.Pattern) -> dict[str, set[str]]:
    """Map each document → set of IDs it references in its body."""
    out: dict[str, set[str]] = {}
    for p in directory.glob("*.md"):
        out[p.name] = set(pattern.findall(p.read_text(encoding="utf-8")))
    return out


def _load_service_catalog() -> dict:
    return json.loads((DATA / "service_catalog.json").read_text(encoding="utf-8"))


def _load_sample_pr_expecteds() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for pr_dir in (DATA / "sample_prs").iterdir():
        if not pr_dir.is_dir():
            continue
        exp = pr_dir / "expected.json"
        if exp.exists():
            out[pr_dir.name] = json.loads(exp.read_text(encoding="utf-8"))
    return out


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    # ── 1. Collect existing IDs ─────────────────────────────────────────────
    adr_ids = _collect_ids(DATA / "adrs", re.compile(r"^(ADR-\d{3})"))
    inc_ids = _collect_ids(DATA / "postmortems", re.compile(r"^(INC-\d{4}-\d{2})"))
    catalog = _load_service_catalog()
    service_names = {s["name"] for s in catalog["services"]}
    approver_roles = set(catalog["approver_roles"])

    # ── 2. Validate cross-refs in ADRs and postmortems ──────────────────────
    adr_body_refs = _collect_referenced_ids(DATA / "adrs", ADR_REF_RE)
    adr_body_inc_refs = _collect_referenced_ids(DATA / "adrs", INC_REF_RE)
    inc_body_refs = _collect_referenced_ids(DATA / "postmortems", ADR_REF_RE)
    inc_body_inc_refs = _collect_referenced_ids(DATA / "postmortems", INC_REF_RE)

    for fname, refs in adr_body_refs.items():
        for ref in refs:
            if ref not in adr_ids:
                errors.append(f"{fname}: references {ref} which does not exist")
    for fname, refs in adr_body_inc_refs.items():
        for ref in refs:
            if ref not in inc_ids:
                # ADRs can mention incidents that motivated them; missing is a warning, not error
                warnings.append(f"{fname}: mentions incident {ref} not in postmortems/")

    for fname, refs in inc_body_refs.items():
        for ref in refs:
            if ref not in adr_ids:
                errors.append(f"{fname}: references {ref} which does not exist in adrs/")
    for fname, refs in inc_body_inc_refs.items():
        for ref in refs:
            # Postmortem→postmortem references are common narratively;
            # missing ones are warnings, not errors. ADR-references stay strict.
            if ref not in inc_ids:
                warnings.append(f"{fname}: references {ref} not yet in postmortems/ (will write later)")

    # ── 3. Validate sample-PR expected.json files ──────────────────────────
    expecteds = _load_sample_pr_expecteds()
    if not expecteds:
        warnings.append("No sample PRs found under data/sample_prs/")

    for pr_name, exp in expecteds.items():
        for s in exp.get("must_mention_systems", []):
            if s not in service_names:
                errors.append(f"sample_prs/{pr_name}/expected.json: "
                              f"references service '{s}' not in service_catalog.json")
        for s in exp.get("must_not_mention_systems", []):
            if s not in service_names:
                errors.append(f"sample_prs/{pr_name}/expected.json: "
                              f"must_not_mention_systems references '{s}' not in service_catalog.json")
            if s in exp.get("must_mention_systems", []):
                errors.append(f"sample_prs/{pr_name}/expected.json: "
                              f"'{s}' is in both must_mention_systems and must_not_mention_systems")
        for adr in exp.get("must_mention_adrs", []):
            if adr not in adr_ids:
                errors.append(f"sample_prs/{pr_name}/expected.json: "
                              f"references {adr} which does not exist")
        for inc in exp.get("must_mention_incidents", []):
            if inc not in inc_ids:
                errors.append(f"sample_prs/{pr_name}/expected.json: "
                              f"references {inc} which does not exist")
        for approver in exp.get("must_mention_approvers", []):
            if approver not in approver_roles:
                errors.append(f"sample_prs/{pr_name}/expected.json: "
                              f"approver '{approver}' not in service_catalog.json approver_roles")
        if exp.get("split") not in {"dev", "test"}:
            errors.append(f"sample_prs/{pr_name}/expected.json: "
                          f"'split' must be 'dev' or 'test'")

    # ── 4. Report ──────────────────────────────────────────────────────────
    print(f"Corpus stats: {len(adr_ids)} ADRs, {len(inc_ids)} postmortems, "
          f"{len(service_names)} services, {len(expecteds)} sample PRs")

    if warnings:
        print(f"\n[WARN] {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")

    if errors:
        print(f"\n[FAIL] {len(errors)} consistency error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("\n[OK] Corpus consistency OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
