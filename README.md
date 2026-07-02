---
title: Change Impact Assessor
emoji: 🔍
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Change Impact Assessor

Produces a structured, retrieval-grounded impact assessment for a proposed code or infrastructure change.

Given a PR (title, description, optional diff), it returns:

- Affected systems with two confidence signals (retrieval similarity + LLM self-rating)
- Historical incidents from the company's postmortem corpus that are relevant
- Required approver roles
- Suggested regression test targets
- Rollback complexity rating with specific notes

Output is structured JSON validated against a Pydantic schema. A Markdown report is generated for paste into PR descriptions or CAB tickets.

---

## Status

This project is built in phases. The current state and what remains are below.

### Phase 0 — Scaffold (complete)

- Pydantic schema and graph state types — `assessor/schema.py`
- LlamaIndex retrieval layer with per-doc-type metadata filters — `assessor/retrieval.py`
- Multi-provider LLM abstraction (Anthropic + OpenAI-compatible) — `assessor/llm.py`
- LangGraph state machine wiring — `assessor/graph.py`
- `extract_targets` node — reference implementation
- `assemble` node — final composition + rollback LLM call + incident-ID invariant
- Markdown report renderer — `assessor/report.py`
- Streamlit UI with mock-mode fallback — `app.py`
- Corpus validator — `eval/validate_corpus.py`
- Eval harness with dev/test split — `eval/run_eval.py`
- pytest suite (schema + corpus validator); runs without API keys

### Phase 1 — Live execution (complete)

- `score_blast_radius` node — LLM-prompt, two confidence signals (retrieval + LLM), risk classification with cited drivers
- `identify_approvers` node — deterministic catalog lookup, no LLM call
- `suggest_tests` node — LLM-prompt, suite-naming convention enforced
- UI switched from mock to real via `graph.stream()` — per-node progress shown live in `st.status()`; mock-mode retained as a fallback when no API key is set
- 3 ADRs · 3 postmortems · 9 services · 5 sample PRs (3 dev, 2 held-out test)

Run `python -m eval.run_eval --split test` against the held-out set to populate `eval/results.md`.

### Phase 1.5 — Hardening (complete)

The reasoning nodes shipped in Phase 1 had no direct test coverage — only
schema shape and corpus consistency were tested. This phase closes that gap
rather than adding new capability:

- Unit tests for `identify_approvers` (all 3 rules, dedup, catalog allow-list) — the node backing the "defensible, not plausible" approver claim had zero tests before this
- Unit tests for the anti-hallucination guarantees in `extract_targets` (catalog allow-list) and `assemble` (incident-ID invariant, rollback fallback-not-retry behaviour)
- Deduped the retry-on-validation-failure pattern, hand-copied into 3 nodes, into `llm.call_llm_json_validated`
- GitHub Actions CI running the pytest suite + `eval.validate_corpus` on every push/PR — `eval/validate_corpus.py`'s own docstring claimed this before it actually existed
- Persistent disk cache for LLM-generated assessments (`assessor/cache.py`) — keyed on `(title, description, diff, provider, model)`; a sidebar lists past runs for one-click reload without re-running the graph
- Deployed via Docker SDK on Hugging Face Spaces (native Streamlit SDK isn't offered by Spaces' current create-flow; Docker running `streamlit run app.py` is the equivalent) — see `Dockerfile`
- Eval harness scoring gap closed — `risk_level` and `rollback_complexity` sat in every fixture as ground truth but were never scored; see **Eval** below

### Phase 1.6 — Human-in-the-loop approval gate (complete)

HIGH-risk changes now pause the graph rather than just being labeled HIGH and moving on:

- New `await_approval` node; the graph compiles with `interrupt_before=["await_approval"]` plus a checkpointer, so a HIGH-risk run stops immediately before that node instead of running to completion unattended
- `assemble` sets `ImpactAssessment.human_approved = (risk_level != HIGH)` — non-HIGH assessments are auto-clear; HIGH ones start `False`
- The Streamlit UI shows the fully-computed report with a pending-approval banner and an **Acknowledge & Finalize** button; resuming the graph (`graph.invoke(None, config)`) flips the flag and reaches `END` without re-running any node
- The persistent cache only writes **after** approval — a paused HIGH-risk assessment is never cached, so loading it later from the sidebar can't silently skip the gate
- `graph.py`'s checkpointer is an in-memory `MemorySaver`, one per Streamlit session — a pending approval does not survive an app restart (see **Known limitations**)
- `tests/test_graph_approval_gate.py` exercises the interrupt → pause → resume cycle at the graph level (mocked LLM + retrieval, no network)

### Phase 2 — Optional extensions (not started)

- GitHub Actions integration — webhook in, PR comment out
- Trend analysis across many assessments (aggregate the structured outputs)
- Confidence calibration trained on user accept/reject feedback

---

## The problem

Engineering managers in regulated industries (banking, payments, logistics) do change impact assessment manually on every non-trivial PR: which systems are affected, who needs to approve, what tests to re-run, whether similar changes have caused incidents recently. Off-the-shelf AI code-review tools (CodeRabbit, Greptile, Sourcery) review code; they don't produce a structured blast-radius assessment grounded in the organisation's own incident history.

This project demonstrates that pattern.

---

## Architecture

```
┌────────────────────────────────┐
│  Streamlit UI (change input)   │
└──────────────┬─────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│  LangGraph state machine                                         │
│                                                                  │
│           extract_targets                                        │
│                  │                                               │
│       ┌──────────┴───────────┐                                   │
│       ▼                      ▼                                   │
│  retrieve_dep_ctx     retrieve_inc_ctx     ← parallel RAG calls  │
│       │                      │                                   │
│       └──────────┬───────────┘                                   │
│                  ▼                                               │
│          score_blast_radius                                      │
│                  │                                               │
│       ┌──────────┴───────────┐                                   │
│       ▼                      ▼                                   │
│ identify_approvers    suggest_tests        ← parallel branches   │
│       │                      │                                   │
│       └──────────┬───────────┘                                   │
│                  ▼                                               │
│              assemble       → ImpactAssessment (Pydantic)        │
│                  │                                               │
│           risk_level == HIGH?                                    │
│       ┌─────yes───┴───no──────┐                                  │
│       ▼                        ▼                                 │
│ await_approval                END                                │
│ (graph interrupts here —                                         │
│  resumes only on human ack)                                      │
│       │                                                          │
│       ▼                                                          │
│      END                                                         │
└──────────────────────────────────────────────────────────────────┘
               │
               ▼
        Structured JSON
        + Markdown report
```

Retrieval is grounded in a closed corpus of architecture decisions (ADRs), postmortems, and a service catalog for a fictional HK fintech ("Fintora"). Every claim in the output cites the source document(s) that supported it.

---

## Architecture decisions

### Structured Pydantic output, not free-form text
At PR-review scale, free-form text is unreviewable. Structured JSON is filterable, sortable, and machine-checkable. The Pydantic schema is the contract the LLM must conform to — validation failures fail loudly rather than produce malformed output.

### RAG, not pure LLM
A general-purpose LLM produces generic blast-radius advice. Retrieval over the company's own postmortems and ADRs produces specific output: *"INC-2025-02 was a similar idempotency-omission incident four months ago."*

### Two confidence signals per affected system, unblended
`retrieval_confidence` (objective, from similarity score) and `llm_confidence` (the LLM's self-rating) are shown side by side in the UI. Combining them into one weighted score would require justifying weights that would be hand-picked, not learned. Keeping them separate preserves the difference between objective evidence and model certainty.

### LangGraph rather than asyncio + functions
For v1, two fan-out / fan-in points — `asyncio.gather()` could express this. LangGraph earns its place from Phase 1.6: the human-in-the-loop approval gate on HIGH-risk changes runs on `interrupt_before` plus a checkpointer, LangGraph-specific primitives with no equivalent in plain async functions.

### Synthetic Fintora corpus, not public OSS data
The use case requires cross-referenced internal artifacts: ADRs cited by postmortems, services with named owners, incidents with affected-system lists. Public projects don't publish these in linked form. Cross-references are validated programmatically — see `eval/validate_corpus.py`.

### No Modal / self-hosted GPU
A companion project (RAG Knowledge Base) runs a self-hosted model on Modal because the use case is chat-latency Q&A over user-uploaded documents. This project's workload is different: ~20 documents, indexed once, batch-style multi-second assessment per change, with output quality more important than per-token latency. Local LlamaIndex with a hosted LLM API is the right architecture. Modal here would be cargo-cult reuse.

What is reused from the companion projects: the LlamaIndex framework, the BGE-small embedding model, and the multi-provider LLM abstraction.

---

## Known limitations

- The corpus is synthetic. Real production data is unavailable for IP/confidentiality reasons.
- The eval set is small — five sample PRs (three dev, two held-out test). See **Eval → Limitations** for what this does and doesn't prove.
- Pydantic validation retry is single-shot, centralised in `llm.call_llm_json_validated`. If invalid JSON returns twice, the caller gets the exception (the UI surfaces an error); the `assemble` node's rollback sub-call is the one exception — it degrades to a safe default instead of retrying (see `assessor/nodes/assemble.py`).
- No auth or rate-limiting on the public demo — it spends real API credits per request. Fine for a portfolio demo, not fine for anything beyond it.
- The persistent cache (`assessor/cache.py`) is local-disk. On Hugging Face Spaces' free tier it survives a simple restart but not a rebuild (triggered by every push) — nothing depends on it surviving, but don't expect a warm cache after a deploy.
- The human-in-the-loop approval gate's checkpointer (`MemorySaver`) is in-memory and scoped to one Streamlit session. A HIGH-risk assessment left pending survives page reloads within the session but not an app restart or a second browser session — there is no shared/persistent thread store. The gate demonstrates the LangGraph mechanism; it is not a durable approval queue.
- The gate is advisory, not enforcing. This tool doesn't integrate with GitHub/CI, so there is nothing outside itself for "pending approval" to actually block — clicking Acknowledge finalizes the record, it doesn't gate a real merge.

---

## Non-goals

- GitHub PR auto-fetching
- CI integration as a built-in feature
- Team-customisable Pydantic schema
- Authentication / multi-tenant scoping
- A "fix the change" agent — output is advisory

---

## Quick start

```bash
git clone <repo>
cd p2
python -m venv venv
venv\Scripts\activate                  # (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt

cp .env.example .env
# Set LLM_PROVIDER + ANTHROPIC_API_KEY (or OPENAI_API_KEY)

python -m eval.validate_corpus         # corpus consistency
pytest tests/ -v                       # unit tests
streamlit run app.py                   # launch UI
```

After Phase 1 is complete:

```bash
python -m eval.run_eval --split test   # held-out test set
```

---

## Repository layout

| Path | Purpose |
|---|---|
| `app.py` | Streamlit UI (mock mode in Phase 0; live in Phase 1) |
| `assessor/schema.py` | Pydantic models |
| `assessor/corpus.py` | Loads ADRs / postmortems / service catalog |
| `assessor/retrieval.py` | LlamaIndex RAG with per-doc-type filtering |
| `assessor/llm.py` | Multi-provider abstraction |
| `assessor/graph.py` | LangGraph state machine |
| `assessor/nodes/` | 8 node functions — each `(state) → partial state update` |
| `assessor/report.py` | Markdown report renderer |
| `assessor/cache.py` | Persistent disk cache for LLM-generated assessments |
| `data/adrs/` | Fintora ADRs |
| `data/postmortems/` | Fintora postmortems |
| `data/service_catalog.json` | Services with owners, dependencies, compliance scope |
| `data/sample_prs/` | Sample PRs with expected assessments for eval |
| `eval/validate_corpus.py` | Cross-reference consistency check |
| `eval/run_eval.py` | Recall + precision + classification-accuracy evaluation |
| `tests/` | pytest suite — runs without API keys |
| `Dockerfile` | Hugging Face Spaces deployment (Docker SDK, runs `streamlit run app.py`) |
| `.github/workflows/ci.yml` | pytest + corpus validation on every push/PR |

---

## Tech stack

| Layer | Choice |
|---|---|
| Orchestration | LangGraph |
| Structured output | Pydantic v2 with single retry on validation failure |
| Retrieval | LlamaIndex over a single VectorStoreIndex with metadata filters |
| Embeddings | BAAI/bge-small-en-v1.5 (CPU) |
| LLM | Anthropic Claude Sonnet 4.5 (default), or any OpenAI-compatible endpoint |
| UI | Streamlit |
| Tests | pytest with mocked LLM clients |
| Deployment | Docker SDK on Hugging Face Spaces (Spaces' create-flow doesn't offer a native Streamlit SDK; Docker running `streamlit run app.py` is the equivalent) |
| CI | GitHub Actions — pytest + corpus validation on push/PR |

---

## Eval

```bash
python -m eval.run_eval --split dev    # development set
python -m eval.run_eval --split test   # held-out test set (Phase 1)
```

Each sample PR is scored on three genuinely different failure modes, reported separately rather than collapsed into one number:

| Dimension | What it catches | Fixture field |
|---|---|---|
| Recall (system / incident / approver / ADR) | A required fact never got surfaced | `must_mention_*` |
| Precision (system) | A system is claimed affected that plainly isn't | `must_not_mention_systems` |
| Classification accuracy (risk level / rollback complexity) | The headline judgment is wrong even though recall is perfect | `risk_level`, `rollback_complexity` |

`overall` in `eval/results.md` is an **unweighted mean of all 7 dimensions** — a sorting convenience for "did this get better or worse," not a validated composite metric. Read the per-dimension columns when deciding whether a prompt or node change actually helped.

### Limitations

This eval harness is a reasonable starting point for a solo-authored demo, not a rigorous measurement instrument. Specifically:

- **Fixtures are single-annotator.** `expected.json` for each sample PR was written by the same person who wrote the code being evaluated, with no independent review and no inter-annotator agreement measurement. "Must mention" and "must not mention" are judgment calls, not ground truth handed down from a labeling process.
- **n = 5** (3 dev, 2 held-out test). Nowhere near enough for statistical confidence in any single number.
- **No confidence calibration.** `llm_confidence` (the model's self-rated certainty per affected system) is never checked against actual accuracy — with 5 cases there isn't enough data to bin a calibration curve meaningfully.
- **The 7-way equal weighting is not business-validated.** Whether a missed Compliance Officer approval (a compliance failure) should cost more than an imprecise rollback note is a real question this harness doesn't answer — it treats them identically. In a real deployment, weighting and what counts as "must mention" should come from whoever owns the cost of getting it wrong (compliance/security for approver recall, SRE for incident relevance), not from the person who wrote the retrieval code.

None of these are fixed by writing more scoring code — they need more annotators, more cases, and a domain owner, which is out of scope for a demo project authored by one person.
