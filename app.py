"""
Streamlit UI for the Change Impact Assessor.

Three views:
  1. Input — pick a sample PR or paste your own (sidebar) + change form (main)
  2. Live assessment — st.status() showing LangGraph nodes executing
  3. Results — hero risk card + 5 collapsible sections + Markdown download

Mock mode: if the LangGraph nodes are still stubs, the UI falls back to a
hard-coded mock assessment so the design can be reviewed before the graph
is fully implemented.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

# Page config MUST be the first Streamlit call
st.set_page_config(
    page_title="Change Impact Assessor",
    page_icon="🔍",
    layout="wide",
)

# Env loading (after page config so st.secrets is allowed)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

_SECRETS = Path(__file__).parent / ".streamlit" / "secrets.toml"
if _SECRETS.exists():
    try:
        for _k, _v in st.secrets.items():
            os.environ.setdefault(_k, str(_v))
    except Exception:
        pass

from assessor import cache
from assessor.llm import active_backend_params
from assessor.report import render_markdown
from assessor.schema import (
    ChangeInput, ImpactAssessment, RiskLevel, RollbackComplexity,
    AffectedSystem, HistoricalIncident, Approver, RegressionTest, SourceCitation,
)


# Hide file-uploader chip (consistent with Sprint Analyzer)
st.markdown(
    """<style>
    [data-testid="stFileUploaderFileData"],
    [data-testid="stFileUploaderFile"] { display: none; }
    </style>""",
    unsafe_allow_html=True,
)


DATA = Path(__file__).parent / "data"
SAMPLE_PRS_DIR = DATA / "sample_prs"

RISK_COLOURS = {
    "LOW": ("🟢", "#16a34a"),
    "MEDIUM": ("🟡", "#eab308"),
    "MEDIUM-HIGH": ("🟠", "#f97316"),
    "HIGH": ("🔴", "#dc2626"),
}


# ─── State init ──────────────────────────────────────────────────────────────

if "active_pr" not in st.session_state:
    st.session_state["active_pr"] = None
if "assessment" not in st.session_state:
    st.session_state["assessment"] = None


# ─── Sidebar ────────────────────────────────────────────────────────────────

st.sidebar.title("🔍 Change Impact Assessor")

# Sample PRs
st.sidebar.markdown("##### Sample PRs")
sample_dirs = sorted([p for p in SAMPLE_PRS_DIR.iterdir() if p.is_dir()]) if SAMPLE_PRS_DIR.exists() else []
if not sample_dirs:
    st.sidebar.caption("No sample PRs yet — drop one under data/sample_prs/<name>/")
for pr_dir in sample_dirs:
    is_active = st.session_state["active_pr"] == pr_dir.name
    if st.sidebar.button(
        ("▶ " if is_active else "📄 ") + pr_dir.name,
        key=f"pr_{pr_dir.name}",
        use_container_width=True,
    ):
        st.session_state["active_pr"] = pr_dir.name
        st.session_state["assessment"] = None
        st.rerun()

# Paste your own
st.sidebar.markdown("##### Or paste your own")
uploaded_diff = st.sidebar.file_uploader("Upload .patch or .diff", type=["patch", "diff", "txt"],
                                          label_visibility="collapsed")

st.sidebar.markdown("---")
st.sidebar.markdown("##### Backend")
for label, value in active_backend_params():
    st.sidebar.markdown(f"**{label}**  \n{value}")

# Previously analyzed (persistent disk cache)
_cached_entries = cache.list_entries()
if _cached_entries:
    st.sidebar.markdown("---")
    st.sidebar.markdown("##### 📦 Previously analyzed")
    for entry in _cached_entries[:10]:
        risk_icon = RISK_COLOURS.get(entry["risk_level"], ("⚪", "#666"))[0]
        label = f"{risk_icon} {entry['summary'][:40]}"
        if st.sidebar.button(label, key=f"cache_{entry['key']}", use_container_width=True):
            loaded = cache.load_by_key(entry["key"])
            if loaded is not None:
                st.session_state["assessment"] = loaded
                st.session_state["active_pr"] = None
                st.rerun()


# ─── Main: input view ──────────────────────────────────────────────────────

def _load_sample_pr(pr_name: str) -> ChangeInput | None:
    pr_path = SAMPLE_PRS_DIR / pr_name / "pr.json"
    if not pr_path.exists():
        return None
    data = json.loads(pr_path.read_text(encoding="utf-8"))
    return ChangeInput(**data)


# Pre-fill from sample if one is active
prefill: ChangeInput | None = None
if st.session_state["active_pr"]:
    prefill = _load_sample_pr(st.session_state["active_pr"])
elif uploaded_diff is not None:
    prefill = ChangeInput(title="Uploaded change", description="", diff=uploaded_diff.read().decode("utf-8", errors="replace"))


st.title("🔍 Change Impact Assessor")
st.caption(
    "Provide a proposed change to receive a structured impact assessment grounded in "
    "Fintora's incident history. pandas-grounded RAG · LangGraph orchestration · "
    "Pydantic-validated structured output."
)

with st.form("change_form"):
    title = st.text_input("PR title", value=prefill.title if prefill else "")
    description = st.text_area("PR description",
                                value=prefill.description if prefill else "",
                                height=120,
                                placeholder="What does the change do? Reference ADRs / incidents if known.")
    diff_text = st.text_area("Diff (paste or upload)",
                              value=prefill.diff if prefill else "",
                              height=180,
                              placeholder="diff --git a/... b/...")
    submitted = st.form_submit_button("⚡ Assess Impact", type="primary", use_container_width=True)


# ─── Mock assessment (until LangGraph nodes are filled in) ──────────────────

def _mock_assessment(change: ChangeInput) -> ImpactAssessment:
    """Hard-coded mock so the UI is usable before the graph is built."""
    return ImpactAssessment(
        summary=change.title or "Refactor billing webhook for idempotency",
        risk_level=RiskLevel.MEDIUM_HIGH,
        risk_drivers=[
            "Touches payment processing path",
            "Three production incidents in the past 12 months in adjacent code (INC-2023-09, INC-2025-02)",
            "Modifies financial-data audit emission semantics",
        ],
        affected_systems=[
            AffectedSystem(
                name="billing-api", retrieval_confidence=0.92, llm_confidence=0.95,
                reason="Direct code change to webhook handler",
                sources=[SourceCitation(document_id="ADR-014", document_type="adr",
                                         excerpt="All payment-mutating and webhook endpoints must implement idempotency...",
                                         relevance_note="Direct ADR governing this change")],
            ),
            AffectedSystem(
                name="subscription-service", retrieval_confidence=0.71, llm_confidence=0.68,
                reason="Consumes webhook events; depends on idempotency contract",
                sources=[],
            ),
            AffectedSystem(
                name="audit-log", retrieval_confidence=0.42, llm_confidence=0.55,
                reason="Receives the idempotency-hit flag in audit emissions",
                sources=[],
            ),
        ],
        historical_incidents=[
            HistoricalIncident(
                incident_id="INC-2025-02",
                title="Duplicate billing webhook delivery",
                date="2025-02-14",
                affected_systems=["billing-api", "subscription-service", "audit-log"],
                relevance_note="Identical handler — this PR is the direct follow-up fix.",
            ),
        ],
        required_approvers=[
            Approver(role="Billing Engineering Lead",
                     reason="Code change in billing-api webhook handler"),
            Approver(role="Compliance Officer",
                     reason="Audit emission semantics modified — HKMA SR-2024-08 scope"),
        ],
        regression_tests=[
            RegressionTest(target="billing-integration-suite",
                            rationale="Verifies end-to-end webhook idempotency contract"),
            RegressionTest(target="audit-log-replay-tests",
                            rationale="Confirms the idempotency-hit flag is emitted correctly"),
        ],
        rollback_complexity=RollbackComplexity.MODERATE,
        rollback_notes=[
            "Code revert is simple — middleware can be disabled via decorator removal",
            "Redis-cached idempotency entries persist for 24h after rollback; consider explicit cache flush",
            "Audit-log schema change is forward-compatible; rollback safe without coordinated change",
        ],
        provider=active_backend_params()[0][1],
        model=active_backend_params()[1][1],
        elapsed_seconds=8.2,
    )


# ─── Run assessment (form submitted) ────────────────────────────────────────

# Map LangGraph node names → human-readable progress labels.
_NODE_LABELS = {
    "extract_targets":           "Extracted change targets",
    "retrieve_dependency_ctx":   "Retrieved dependency context (ADRs + service catalog)",
    "retrieve_incident_ctx":     "Retrieved incident history",
    "score_blast_radius":        "Scored blast radius",
    "identify_approvers":        "Identified approvers",
    "suggest_tests":             "Suggested regression tests",
    "assemble":                  "Assembled assessment",
}

# Mock mode is retained as a safety fallback when no API key is present.
_HAS_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def _run_real_assessment(change, status_container):
    """
    Run the LangGraph end-to-end, streaming per-node progress to the UI.
    Returns the final ImpactAssessment, or None on failure.
    """
    from assessor.graph import build_graph
    import time

    graph = build_graph()
    started = time.time()
    initial_state: dict = {"change": change, "started_at": started}

    final_state: dict = {}
    try:
        for event in graph.stream(initial_state):
            # `event` is a dict {node_name: partial_state_update}
            for node_name, partial in event.items():
                label = _NODE_LABELS.get(node_name, node_name)
                status_container.write(f"✅ {label}")
                if isinstance(partial, dict):
                    final_state.update(partial)
    except Exception as e:
        status_container.error(f"Assessment failed: {e}")
        return None

    assessment = final_state.get("assessment")
    if assessment is not None:
        assessment.elapsed_seconds = round(time.time() - started, 2)
    return assessment


if submitted:
    if not title.strip():
        st.error("PR title is required.")
        st.stop()
    change = ChangeInput(title=title, description=description, diff=diff_text or None)

    with st.status("🔄 Assessing impact...", expanded=True) as status:
        cached = cache.load(change) if _HAS_API_KEY else None
        if cached is not None:
            status.write("📦 Identical change + backend already assessed — loaded from cache")
            st.session_state["assessment"] = cached
            status.update(label="✅ Loaded from cache", state="complete")
        elif _HAS_API_KEY:
            assessment = _run_real_assessment(change, status)
            if assessment is not None:
                cache.save(change, assessment)
                st.session_state["assessment"] = assessment
                status.update(label=f"✅ Assessment complete ({assessment.elapsed_seconds or 0:.1f}s)",
                              state="complete")
            else:
                status.update(label="❌ Assessment failed — see error above", state="error")
        else:
            # Mock mode fallback — no API key configured.
            status.write("⚠️ No API key set — running in mock mode")
            for label in _NODE_LABELS.values():
                status.write(f"🧪 {label} (mocked)")
            st.session_state["assessment"] = _mock_assessment(change)
            status.update(label="✅ Mock assessment complete", state="complete")


# ─── Results view ──────────────────────────────────────────────────────────

assessment: ImpactAssessment | None = st.session_state.get("assessment")

if assessment is not None:
    # Hero card
    icon, _colour = RISK_COLOURS.get(assessment.risk_level.value, ("⚪", "#666"))
    st.markdown("---")
    st.markdown(
        f"""
        ### 📊 Risk Level: {icon} **{assessment.risk_level.value}**
        **{assessment.summary}**

        {len(assessment.affected_systems)} affected systems  ·  {len(assessment.historical_incidents)} historical incidents  ·  {len(assessment.required_approvers)} approvers  ·  Rollback: **{assessment.rollback_complexity.value}**

        ⏱ Generated in {assessment.elapsed_seconds or 0:.1f}s
        """
    )

    # Affected Systems
    st.markdown("#### 🎯 Affected Systems")
    for s in assessment.affected_systems:
        dot = "🔴" if max(s.retrieval_confidence, s.llm_confidence) > 0.85 else (
              "🟠" if max(s.retrieval_confidence, s.llm_confidence) > 0.65 else (
              "🟡" if max(s.retrieval_confidence, s.llm_confidence) > 0.45 else "🟢"))
        with st.container():
            cols = st.columns([3, 2, 2])
            cols[0].markdown(f"{dot} **{s.name}**")
            cols[1].markdown(f"📡 Retrieval: `{int(s.retrieval_confidence * 100)}%`")
            cols[2].markdown(f"🤖 LLM: `{int(s.llm_confidence * 100)}%`")
            st.caption(s.reason)
            if s.sources:
                with st.expander(f"📎 Sources ({len(s.sources)})"):
                    for src in s.sources:
                        st.markdown(f"**{src.document_id}** ({src.document_type})")
                        st.code(src.excerpt, language="text")
                        if src.relevance_note:
                            st.caption(src.relevance_note)

    # Historical Incidents
    if assessment.historical_incidents:
        st.markdown("#### 📜 Historical Incidents")
        for inc in assessment.historical_incidents:
            with st.expander(f"⚠️ **{inc.incident_id}** — {inc.title}  ·  {inc.date}"):
                st.markdown(f"_Relevance:_ {inc.relevance_note}")
                if inc.excerpt:
                    st.code(inc.excerpt, language="text")
                if inc.affected_systems:
                    st.caption(f"Affected: {', '.join(inc.affected_systems)}")

    # Approvers
    if assessment.required_approvers:
        with st.expander(f"👤 Required Approvers ({len(assessment.required_approvers)})", expanded=True):
            for a in assessment.required_approvers:
                st.markdown(f"▸ **{a.role}**  \n{a.reason}")

    # Regression Tests
    if assessment.regression_tests:
        with st.expander(f"🧪 Regression Test Targets ({len(assessment.regression_tests)})"):
            for t in assessment.regression_tests:
                st.markdown(f"▸ **{t.target}**  \n{t.rationale}")

    # Rollback
    with st.expander(f"↩️ Rollback Considerations  ·  {assessment.rollback_complexity.value}"):
        for note in assessment.rollback_notes:
            st.markdown(f"- {note}")

    # Footer actions
    st.markdown("---")
    json_bytes = assessment.model_dump_json(indent=2).encode("utf-8")
    cols = st.columns([1, 1, 6])
    cols[0].download_button(
        "📋 Download JSON", data=json_bytes,
        file_name="impact_assessment.json", mime="application/json",
    )

    md = render_markdown(assessment)
    cols[1].download_button(
        "⬇ Download Markdown", data=md.encode("utf-8"),
        file_name="impact_assessment.md", mime="text/markdown",
    )
else:
    st.info("Pick a sample PR from the sidebar or paste your own change, then click **Assess Impact**.")
