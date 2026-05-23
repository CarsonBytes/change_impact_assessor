# INC-2025-02 — Duplicate billing webhook delivery

- **Severity**: P1
- **Date**: 2025-02-14
- **Duration**: 4h 12m (incident detected at 11:23 HKT; mitigated at 15:35 HKT)
- **Customer impact**: 218 customers double-charged subscription renewals
- **Affected systems**: `billing-api`, `subscription-service`, `audit-log`
- **Detected by**: Customer support escalation (4 tickets within 12 minutes)

## Summary

A partner webhook for subscription renewals was re-delivered by the
partner after a 504 timeout. `billing-api`'s subscription renewal
handler was not idempotent despite ADR-014's mandate, and the retried
delivery resulted in a second ledger entry and a second charge to
each affected customer.

## Root cause

The `/webhooks/billing/subscription-renewal` endpoint was implemented in
2023-Q4, before ADR-014 was ratified (2024-03-22). It was missed during
the post-ADR audit of existing endpoints because the ADR's grandfathering
exception list (`ADR-014-grandfather.yaml`) was not enforced by CI — it
existed as documentation only.

When the partner's webhook delivery system retried after the upstream
504 (caused by an unrelated `payments-svc` GC pause), the handler
processed the retry as a new event, creating duplicate ledger entries
in `audit-log`.

## Timeline

| Time (HKT) | Event |
|---|---|
| 11:14 | Partner sends initial renewal webhook for batch B-2025-02-14-001 |
| 11:14 | `payments-svc` GC pause causes downstream 504 |
| 11:15 | Partner system retries delivery (same X-Request-Id NOT honoured) |
| 11:15 | `billing-api` processes both deliveries; 218 duplicate charges issued |
| 11:23 | First customer support ticket received |
| 11:31 | On-call engineer paged |
| 12:05 | Root cause identified |
| 13:40 | Hotfix deployed: short-circuit handler if `X-Request-Id` seen in last 24h |
| 15:35 | All duplicate charges reversed; customers notified |

## Contributing factors

- **ADR-014 enforcement was advisory, not mechanical.** No CI check
  validated that all `/webhooks/*` endpoints implemented the
  idempotency middleware.
- **`audit-log` did not raise on duplicate emissions.** The hash chain
  was valid for both events (they were distinct events to the audit
  service); the *business duplication* was invisible to audit-log.
- **No canary or replay tests** for partner-driven webhook flows in
  the regression suite.

## Action items

| # | Action | Owner | Status |
|---|---|---|---|
| 1 | Add CI check enforcing idempotency middleware on `/webhooks/*` | Billing | Done 2025-02-21 |
| 2 | Audit all webhook endpoints predating ADR-014 | Billing + Platform | Done 2025-03-04 |
| 3 | Add `business.duplicate.detected` metric to audit-log | Data Eng | Done 2025-03-12 |
| 4 | Add replay-based regression test for subscription renewal | Billing | Done 2025-04-02 |
| 5 | Document `audit-log`'s blindspot in INC-2025-09 retrospective | Compliance | Done 2025-09-22 |

## Related

- ADR-014: Idempotency keys
- ADR-021: Audit log retention
- INC-2023-09 (original idempotency motivating incident)
- INC-2025-09 (audit-log blindspot revisited)
