# INC-2023-09 — Duplicate charge from non-idempotent payment retry

- **Severity**: P1
- **Date**: 2023-09-18
- **Duration**: 3h 45m (detected 14:02 HKT; mitigated 17:47 HKT)
- **Customer impact**: 412 customers double-charged for one-off purchases
- **Affected systems**: `billing-api`, `payments-svc`, `audit-log`
- **Detected by**: customer support (8 tickets within 20 min)

## Summary

A network blip between `billing-api` and `payments-svc` caused a payment
request to time out at the HTTP layer despite the downstream charge
having succeeded. The retry in `billing-api` then issued a second
charge for the same order. The handler in `payments-svc` was not
idempotent — no `X-Request-Id` deduplication — so it processed the
retry as a fresh request.

## Root cause

The team had assumed that "transient network errors are rare; retries
are safe enough." No deduplication at the payment-creation endpoint.

## Contributing factors

- Implicit timeout retry policy in the HTTP client (`requests==2.x` default)
- No `X-Request-Id` propagation across services
- The audit-log captured both charges as legitimately distinct events;
  the duplication was invisible to compliance until customers reported

## Action items

| # | Action | Owner | Status |
|---|---|---|---|
| 1 | Design idempotency policy for all payment-mutating endpoints | Payments + Billing | Done → ADR-014 |
| 2 | Add metric `payment.duplicate.suspected` based on customer-id + amount + 60s window | Data Eng | Done 2023-11-04 |
| 3 | Document the network-blip → retry → duplicate path in onboarding | Payments | Done 2023-12-01 |

## Related

- ADR-014: Idempotency keys (this incident motivated the ADR)
- INC-2023-12 (similar root cause, different endpoint)
- INC-2025-02 (regression of the same class — see postmortem)
