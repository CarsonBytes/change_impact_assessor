# ADR-021: Audit Log Retention, Access, and Schema

- **Status**: Accepted
- **Date**: 2024-09-05
- **Deciders**: Compliance Officer, Platform Engineering, Data Engineering
- **Tags**: audit, compliance, hkma, retention

## Context

HKMA SR-2024-08 ("Operational Risk Management — Audit Trail Requirements
for Authorised Institutions") requires that all financial-data-handling
events be logged in an append-only audit trail with the following
properties:

- Retention of **90 days hot, 7 years cold**
- Immutability — no UPDATE or DELETE permitted on audit records
- Cryptographic integrity (hash-chained records)
- Searchable by `customer_id`, `transaction_id`, and `event_type`

Fintora's previous audit log (Postgres table in the `billing-api`
database) failed compliance review on two counts: deletes were
technically possible (only convention prevented them), and the
7-year cold tier did not exist.

## Decision

Adopt a dedicated **`audit-log` service** owning its own data tier:

- **Hot tier**: ClickHouse cluster (3 nodes, AZ-distributed), 90 days
- **Cold tier**: S3 Glacier with manifest in DynamoDB, 7 years
- **Append-only enforcement**: IAM policy denies all UPDATE / DELETE
  operations; writes go through a single Kafka topic `audit.events.v1`
- **Hash chain**: each record includes `prev_hash` (SHA-256 of prior record);
  a daily reconciliation job validates the chain
- **Read API**: only via the `audit-log` service; no direct DB access
  even from internal services

All services that mutate financial data MUST emit audit events to the
Kafka topic. Failure to emit is a P1 compliance defect.

## Schema (audit.events.v1)

```json
{
  "event_id":       "uuid",
  "event_type":     "string (e.g. 'payment.created')",
  "customer_id":    "string | null",
  "transaction_id": "string | null",
  "actor":          "string (system or user identifier)",
  "payload":        "object (event-specific)",
  "prev_hash":      "string (SHA-256)",
  "occurred_at":    "ISO 8601 timestamp"
}
```

## Consequences

**Positive**:

- Passes HKMA SR-2024-08 compliance review
- Dedicated service insulates audit availability from billing outages

**Negative**:

- Cross-team coordination overhead: every service emitting financial
  events now has a Kafka dependency
- The hash chain validation job is a new operational concern (alarms
  fire if chain breaks)

**Operational**:

- Owners: Compliance + Data Engineering jointly
- Hot-tier outage runbook: RUNBOOK-014-audit-hot-tier.md
- Hash-chain break runbook: RUNBOOK-015-audit-chain-break.md

## Related

- ADR-014: Idempotency keys (idempotency cache hits MUST also be audited)
- INC-2025-09 (audit log replay incident — see postmortem)
