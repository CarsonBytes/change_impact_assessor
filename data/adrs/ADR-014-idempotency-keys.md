# ADR-014: Idempotency Keys for Payment & Webhook Endpoints

- **Status**: Accepted
- **Date**: 2024-03-22
- **Deciders**: Payments Lead, Billing Engineering, Compliance
- **Tags**: payments, idempotency, webhooks, billing

## Context

Two production incidents in late 2023 (INC-2023-09, INC-2023-12) stemmed
from non-idempotent handling of retried payment and webhook events. In
both cases, network blips or upstream timeouts caused legitimate retries
that resulted in duplicate ledger entries — INC-2023-09 affected 412
customers and required manual remediation.

Affected services: `billing-api`, `payments-svc`, `subscription-service`,
and any consumer of partner billing webhooks.

## Decision

All payment-mutating and webhook endpoints **must** implement idempotency
using a client-supplied `X-Request-Id` header (UUID v4), with the
following contract:

1. The server persists a `(endpoint, x_request_id) → response` mapping
   for **24 hours**.
2. A repeated request with the same `X-Request-Id` returns the **exact
   prior response body and HTTP status**, not a re-execution.
3. The idempotency cache is stored in Redis with a 24h TTL; cache misses
   are treated as new requests and proceed to normal processing.
4. Endpoints exempt from this rule must be documented in
   `service_catalog.json` under the `idempotency_exempt` field, with
   a written justification.

## Consequences

**Positive**:

- Eliminates the failure mode behind INC-2023-09 and INC-2023-12
- Provides a uniform pattern for partner integrations to retry safely

**Negative**:

- Adds Redis as a hard dependency for any payment-mutating endpoint;
  Redis outages now block payments
- 24h cache window is opinionated; some partners request 7-day windows
  which we currently reject

**Operational**:

- Implementation reference: `billing-api/src/middleware/idempotency.py`
- Owners: Billing Engineering team
- Audit log: every idempotency hit is logged to `audit-log` with the
  cached response hash (see ADR-021 for retention)

## Related

- ADR-021: Audit log retention and access
- INC-2023-09, INC-2023-12 (motivating incidents)
- INC-2025-02 (subsequent regression — see postmortem)
