# INC-2025-09 — Audit log replay storm during region failover

- **Severity**: P2
- **Date**: 2025-09-22
- **Duration**: 1h 50m
- **Customer impact**: No direct customer impact; ~6 hours of audit ingestion lag
- **Affected systems**: `audit-log`, `kafka-cluster` (Kafka MSK), downstream consumers (`billing-api`, `payments-svc`, `kyc-service`)
- **Detected by**: alerting (audit-chain reconciliation alarm — RUNBOOK-015)

## Summary

During a planned Kafka cluster maintenance, the consumer group offsets
for `audit-log`'s ClickHouse ingester were reset to earliest. The
ingester then replayed ~6h of `audit.events.v1` events from scratch.

ClickHouse correctly inserted the events (idempotent on `event_id`),
but the hash-chain reconciliation job interpreted the replay as a
chain break and paged on-call. Investigation took 90 minutes before
the root cause (operator-induced offset reset) was identified.

## Root cause

Maintenance runbook step "RESET CONSUMER OFFSET" was intended to
recover from a specific failure mode but was followed unconditionally
during the planned maintenance — operator error compounded by an
unclear runbook.

## Why this matters for change reviews

This incident is the visible artefact of an `audit-log` blind spot
the team already knew about (mentioned in INC-2025-02 action item #5):
the system has no way to distinguish *replay of legitimate events*
from *chain corruption*. Any change touching audit-log retention,
replay, or chain validation should explicitly address this.

## Contributing factors

- Runbook step ambiguity (operator action conditional on a state not
  programmatically checkable)
- Hash-chain validation alarm has no replay-vs-corruption distinguisher
- No rate-limit on consumer-group offset resets (any operator can do it)

## Action items

| # | Action | Owner | Status |
|---|---|---|---|
| 1 | Rewrite RUNBOOK-015 to make offset-reset conditional and require dual approval | Data Eng + Compliance | Done 2025-10-15 |
| 2 | Add replay-detection flag to hash-chain validator (suppress alarm during known replay) | Data Eng | In progress |
| 3 | Rate-limit offset resets in MSK IAM policy | Platform | Done 2025-11-01 |

## Related

- ADR-021: Audit log retention and access
- INC-2025-02 (referenced this blind spot in its action items)
