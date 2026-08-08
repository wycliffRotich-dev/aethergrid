# ADR-0006: Defer Frontend Bundle Optimization

## Status

Accepted

## Date

2026-07-11

## Context

After introducing Recharts into the AetherGrid dashboard, the production
frontend bundle increased to approximately 613 kB.

The application builds successfully and functions correctly, but Vite emits
the following warning:

> Some chunks are larger than 500 kB after minification.

This warning is not a functional issue, but indicates an opportunity to
improve loading performance as the frontend grows.

## Decision

Frontend bundle optimization is intentionally deferred until additional
dashboard features have stabilized.

Future optimization work will include:

- Route-based code splitting
- Lazy loading of heavy visualization components
- Vendor chunk separation
- Performance profiling with Lighthouse

## Consequences

Pros:

- No premature optimization.
- Faster feature delivery.
- Simpler development during Phase 8.

Cons:

- Larger initial JavaScript download.
- Bundle warning remains until optimization work is scheduled.

This decision will be revisited before the first production release.
