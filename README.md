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
- 3 anchor ADRs, 1 postmortem, service catalog, 1 sample PR with expected output
- pytest suite (schema + corpus validator); runs without API keys

The Streamlit UI is demo-able today using mock data. Live LLM execution requires Phase 1.

### Phase 1 — Live execution (TODO)

| Task | File | Notes |
|---|---|---|
| Implement `score_blast_radius` | `assessor/nodes/score_blast_radius.py` | LLM-prompt node; follow `extract_targets.py` pattern. Detailed checklist in the file docstring. |
| Implement `identify_approvers` | `assessor/nodes/identify_approvers.py` | Can be deterministic (service-catalog lookup) or LLM-based. Both approaches noted in the docstring. |
| Implement `suggest_tests` | `assessor/nodes/suggest_tests.py` | LLM-prompt node; same pattern as `extract_targets`. |
| Switch UI from mock to real | `app.py` | Replace `_mock_assessment(change)` with `run_assessment(change)` from `assessor.graph`. |
| Add 4 more sample PRs (2 dev, 2 held-out test) | `data/sample_prs/` | Each needs `pr.json` and `expected.json`. |
| Run eval against held-out test set | `eval/run_eval.py --split test` | Writes `eval/results.md`. |

### Phase 2 — Optional extensions (not started)

- Human-in-the-loop interrupt at HIGH risk (LangGraph `interrupt` primitive)
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
For v1, two fan-out / fan-in points — `asyncio.gather()` could express this. LangGraph is used because the planned Phase 2 extension (interrupt the graph at HIGH risk for human approval) requires its checkpoint/resume primitives. Phase 0/1 uses basic features only.

### Synthetic Fintora corpus, not public OSS data
The use case requires cross-referenced internal artifacts: ADRs cited by postmortems, services with named owners, incidents with affected-system lists. Public projects don't publish these in linked form. Cross-references are validated programmatically — see `eval/validate_corpus.py`.

### No Modal / self-hosted GPU
A companion project (RAG Knowledge Base) runs a self-hosted model on Modal because the use case is chat-latency Q&A over user-uploaded documents. This project's workload is different: ~20 documents, indexed once, batch-style multi-second assessment per change, with output quality more important than per-token latency. Local LlamaIndex with a hosted LLM API is the right architecture. Modal here would be cargo-cult reuse.

What is reused from the companion projects: the LlamaIndex framework, the BGE-small embedding model, and the multi-provider LLM abstraction.

---

## Known limitations

- The corpus is synthetic. Real production data is unavailable for IP/confidentiality reasons.
- The eval set is small — five sample PRs (three dev, two held-out test).
- Pydantic validation retry is single-shot. If invalid JSON returns twice, the UI surfaces an error and a manual retry button.
- The UI runs in mock mode until Phase 1 is complete.

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
| `assessor/nodes/` | 7 node functions — each `(state) → partial state update` |
| `assessor/report.py` | Markdown report renderer |
| `data/adrs/` | Fintora ADRs |
| `data/postmortems/` | Fintora postmortems |
| `data/service_catalog.json` | Services with owners, dependencies, compliance scope |
| `data/sample_prs/` | Sample PRs with expected assessments for eval |
| `eval/validate_corpus.py` | Cross-reference consistency check |
| `eval/run_eval.py` | Recall-prioritised evaluation |
| `tests/` | pytest suite — runs without API keys |

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

---

## Eval

```bash
python -m eval.run_eval --split dev    # development set
python -m eval.run_eval --split test   # held-out test set (Phase 1)
```

Recall-prioritised: missing an affected system is the failure mode that matters in change management. Results written to `eval/results.md`.
