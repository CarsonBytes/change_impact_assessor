# ADR-001: API Gateway — Kong

- **Status**: Accepted
- **Date**: 2023-08-14
- **Deciders**: Platform Engineering, Payments Lead, Security
- **Tags**: gateway, traffic, security

## Context

Fintora's customer-facing surface is split across four backend services
(mobile-banking-bff, billing-api, kyc-service, public-statements-api).
Without a unified gateway, each service independently terminates TLS,
enforces auth, applies rate limits, and exposes ad-hoc metrics. This has
caused three production incidents in 2022–2023 around inconsistent rate
limiting (INC-2022-11) and misaligned auth retry semantics.

We need a single ingress point that:

- Terminates TLS centrally with HKMA-approved cipher suites
- Enforces uniform auth (mTLS for service-to-service; OAuth2/JWT for clients)
- Applies tenant-aware rate limits
- Emits standardised request-level telemetry to our observability stack

## Decision

We will deploy **Kong Gateway** (open-source edition, self-hosted on EKS)
as the single public ingress for all customer-facing APIs.

- All public traffic enters via Kong
- Internal service-to-service traffic remains direct (mTLS via service mesh)
- Kong plugin set: `key-auth`, `jwt`, `rate-limiting`, `prometheus`, `correlation-id`

## Consequences

**Positive**:

- Unified rate-limiting policy across all public APIs
- Single audit point for HKMA traffic compliance reviews
- Centralised TLS termination simplifies cert rotation

**Negative**:

- Kong becomes a critical single point of failure — must be deployed HA
  across at least two AZs
- Plugin compatibility constrains us when upgrading Kong major versions

**Operational**:

- Owners: Platform Engineering team
- On-call: SRE rotation
- Runbook: RUNBOOK-007-kong-failover.md
