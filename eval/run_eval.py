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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assessor.schema import ChangeInput
from assessor.graph import run_assessment


DATA = ROOT / "data" / "sample_prs"
RESULTS = ROOT / "eval" / "results.md"


def _load_pr(pr_dir: Path) -> tuple[ChangeInput, dict]:
    pr = json.loads((pr_dir / "pr.json").read_text(encoding="utf-8"))
    expected = json.loads((pr_dir / "expected.json").read_text(encoding="utf-8"))
    return ChangeInput(**pr), expected


def _score_case(actual, expected: dict) -> dict:
    """Recall-prioritized scoring — missing required mentions is the failure mode."""
    affected_names = {s.name for s in actual.affected_systems}
    incident_ids = {i.incident_id for i in actual.historical_incidents}
    approver_roles = {a.role for a in actual.required_approvers}

    def _recall(required, got):
        if not required:
            return 1.0
        hit = sum(1 for r in required if r in got)
        return hit / len(required)

    sys_recall = _recall(expected.get("must_mention_systems", []), affected_names)
    inc_recall = _recall(expected.get("must_mention_incidents", []), incident_ids)
    app_recall = _recall(expected.get("must_mention_approvers", []), approver_roles)

    return {
        "system_recall": sys_recall,
        "incident_recall": inc_recall,
        "approver_recall": app_recall,
        "overall": (sys_recall + inc_recall + app_recall) / 3,
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
    lines.append("| Case | System recall | Incident recall | Approver recall | Overall |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['case']} | ERROR: {r['error']} | | | |")
        else:
            lines.append(
                f"| {r['case']} | {r['system_recall']:.2f} | {r['incident_recall']:.2f} | "
                f"{r['approver_recall']:.2f} | {r['overall']:.2f} |"
            )
    overall = [r["overall"] for r in rows if "overall" in r]
    if overall:
        lines.append(f"\n**Mean overall recall: {sum(overall)/len(overall):.2f}**")
    RESULTS.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {RESULTS}")


if __name__ == "__main__":
    main()
