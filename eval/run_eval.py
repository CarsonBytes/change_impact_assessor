"""
Eval harness. Runs the assessor against each sample PR and scores against
its expected.json file.

Usage:
    python -m eval.run_eval --split dev      # evaluate on dev set (default)
    python -m eval.run_eval --split test     # evaluate on held-out test set
    python -m eval.run_eval --split all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assessor.schema import ChangeInput
from assessor.graph import run_assessment


DATA = ROOT / "data" / "sample_prs"
RESULTS = ROOT / "eval" / "results.md"

_ADR_REF_RE = re.compile(r"\bADR-\d{3}\b")


def _load_pr(pr_dir: Path) -> tuple[ChangeInput, dict]:
    pr = json.loads((pr_dir / "pr.json").read_text(encoding="utf-8"))
    expected = json.loads((pr_dir / "expected.json").read_text(encoding="utf-8"))
    return ChangeInput(**pr), expected


def _cited_adr_ids(actual) -> set[str]:
    """ADR IDs referenced anywhere in the assessment: a risk_driver citation
    (required by score_blast_radius's prompt) or a source attached to an
    affected system."""
    cited: set[str] = set()
    for driver in actual.risk_drivers:
        cited.update(_ADR_REF_RE.findall(driver))
    for sys_ in actual.affected_systems:
        for src in sys_.sources:
            if src.document_type == "adr":
                cited.add(src.document_id)
    return cited


def _score_case(actual, expected: dict) -> dict:
    """
    Three genuinely different failure modes, scored separately rather than
    collapsed into one falsely-precise number:

      - recall  (system / incident / approver / ADR): did required facts
        get surfaced at all.
      - precision (system): claiming a service is affected when the fixture
        says it plainly isn't — without this, a run that over-claims every
        service in the catalog scores identically to a precise one.
      - classification (risk_level / rollback_complexity): did the headline
        judgment match, checked as exact match against the fixture.

    `overall` is an UNWEIGHTED mean of all of the above — a rough
    single-number gut-check for sorting cases, not a validated composite
    metric. The weighting (equal, 7-way) has no business justification
    behind it; read the per-dimension breakdown, not this number, when
    deciding whether a change to a node made things better or worse. See
    README "Eval → Limitations" for what this harness does not capture
    (annotator agreement, confidence calibration, sample size).
    """
    affected_names = {s.name for s in actual.affected_systems}
    incident_ids = {i.incident_id for i in actual.historical_incidents}
    approver_roles = {a.role for a in actual.required_approvers}
    adr_ids = _cited_adr_ids(actual)

    def _recall(required, got):
        if not required:
            return 1.0
        hit = sum(1 for r in required if r in got)
        return hit / len(required)

    def _precision(forbidden, got):
        if not forbidden:
            return 1.0, []
        violations = [f for f in forbidden if f in got]
        return 1.0 - (len(violations) / len(forbidden)), violations

    sys_recall = _recall(expected.get("must_mention_systems", []), affected_names)
    inc_recall = _recall(expected.get("must_mention_incidents", []), incident_ids)
    app_recall = _recall(expected.get("must_mention_approvers", []), approver_roles)
    adr_recall = _recall(expected.get("must_mention_adrs", []), adr_ids)
    sys_precision, false_positives = _precision(
        expected.get("must_not_mention_systems", []), affected_names,
    )

    expected_risk = expected.get("risk_level")
    risk_correct = expected_risk is None or actual.risk_level.value == expected_risk
    expected_rollback = expected.get("rollback_complexity")
    rollback_correct = (
        expected_rollback is None or actual.rollback_complexity.value == expected_rollback
    )

    all_terms = [
        sys_recall, inc_recall, app_recall, adr_recall, sys_precision,
        1.0 if risk_correct else 0.0,
        1.0 if rollback_correct else 0.0,
    ]

    return {
        "system_recall": sys_recall,
        "incident_recall": inc_recall,
        "approver_recall": app_recall,
        "adr_recall": adr_recall,
        "system_precision": sys_precision,
        "false_positives": false_positives,
        "risk_level_correct": risk_correct,
        "rollback_complexity_correct": rollback_correct,
        "overall": sum(all_terms) / len(all_terms),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    args = parser.parse_args()

    pr_dirs = sorted([p for p in DATA.iterdir() if p.is_dir()])
    cases: list[tuple[Path, ChangeInput, dict]] = []
    for d in pr_dirs:
        try:
            change, exp = _load_pr(d)
        except FileNotFoundError:
            continue
        if args.split == "all" or exp.get("split") == args.split:
            cases.append((d, change, exp))

    if not cases:
        print(f"No PRs in split={args.split}")
        return

    print(f"Running {len(cases)} case(s) [split={args.split}]")
    rows: list[dict] = []
    for d, change, exp in cases:
        try:
            final = run_assessment(change)
            assessment = final["assessment"]
            scores = _score_case(assessment, exp)
        except Exception as e:
            scores = {"error": str(e)}
        rows.append({"case": d.name, "split": exp.get("split"), **scores})
        print(f"  • {d.name}: {scores}")

    # Write results.md
    lines = ["# Eval results\n"]
    lines.append(f"Split: **{args.split}**\n")
    lines.append(
        "| Case | Sys recall | Inc recall | Appr recall | ADR recall | "
        "Sys precision | Risk correct | Rollback correct | Overall* |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['case']} | ERROR: {r['error']} | | | | | | | |")
        else:
            fp_note = f" ({', '.join(r['false_positives'])})" if r["false_positives"] else ""
            lines.append(
                f"| {r['case']} | {r['system_recall']:.2f} | {r['incident_recall']:.2f} | "
                f"{r['approver_recall']:.2f} | {r['adr_recall']:.2f} | "
                f"{r['system_precision']:.2f}{fp_note} | "
                f"{'✓' if r['risk_level_correct'] else '✗'} | "
                f"{'✓' if r['rollback_complexity_correct'] else '✗'} | {r['overall']:.2f} |"
            )
    overall = [r["overall"] for r in rows if "overall" in r]
    if overall:
        lines.append(f"\n**Mean overall: {sum(overall)/len(overall):.2f}**")
    lines.append(
        "\n\\* Unweighted mean of all 7 dimensions — a sorting convenience, "
        "not a validated composite metric. Read the columns, not this number; "
        "see README \"Eval → Limitations\"."
    )
    RESULTS.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {RESULTS}")


if __name__ == "__main__":
    main()
