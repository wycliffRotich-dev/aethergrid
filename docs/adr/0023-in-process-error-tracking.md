# ADR 0023: In-Process Error Tracking

## Status

Proposed

## Context

The README's "What's Next" lists error tracking as the last remaining item from the original hardening list, after rate limiting (ADR 0021) and structured logging (ADR 0022). ADR 0022 explicitly deferred it, noting that alerting has different failure modes than request logging and deserves its own reasoning rather than being folded in.

Before writing any decision here, `RequestLoggingMiddleware.dispatch` was tested directly, the same empirical discipline used before ADR 0022's own correction. The result surfaced a real, already-shipped gap, not just a design question: `dispatch` has no `try/except` around `call_next`. If a route handler raises an unhandled exception, `call_next` raises, `dispatch` exits immediately, and `RequestLoggingService.log_completed_request` is never called. The client still receives Starlette's default `500`, but the request is invisible to this codebase's own logging entirely, not merely untracked as an error, absent from the log stream altogether. This is the single case error tracking exists to cover, and it is currently the one case request logging misses. That finding is folded into this decision, not treated as a separate, unaddressed problem, the same way ADR 0022 folded the cluster loop's unformatted logs into its own scope rather than leaving them for later.

The background cluster loop (`_run_cluster_loop`) already catches broadly: both `cluster_tick_service.execute()` and `reconciliation_loop.execute()` are wrapped in `try/except Exception`, logging via `logger.exception(...)`, structured as JSON since ADR 0022. What is missing there is not visibility, the exception is already logged with a full traceback, but a distinct, queryable record that says "this needs a human", separate from a log stream a human is not necessarily watching in real time.

Two axes were considered, mirroring how ADR 0021 and ADR 0022 were scoped: whether to depend on an external service, and where capture actually happens.

**External dependency.** A third-party error tracking service, Sentry or similar, was considered and rejected for the same reason ADR 0021 rejected Redis and ADR 0022 rejected a dedicated JSON logging library: it solves a problem, persistent, cross-instance error aggregation and real-time alerting, this system does not have yet at single-process, portfolio-stage scale, at the cost of a new dependency, credential, and configuration surface it does not otherwise carry. This system runs as a single process today; multi-instance deployment remains future work per ADR 0021's own noted limitation. Introducing an external service now would be solving a scaling and operations problem that does not exist yet, at the cost of complexity that is real today.

**Where capture happens.** Two places already exist that are the natural hosts, since both already catch broadly: `RequestLoggingMiddleware.dispatch` on the request path, and the cluster loop's two existing `except Exception` blocks on the background path. Neither currently does more than log. The gap is a structured, in-process record of recent failures, not a new place to observe exceptions.

## Decision

- A new `ErrorTrackingService` in `app/application/services/`, framework-agnostic like every other application service in this codebase, no FastAPI import. It exposes a single method, `capture_error(*, source: str, exc: Exception, context: dict[str, object] | None = None)`. `source` distinguishes where the error came from (`"request"`, `"cluster_tick"`, `"reconciliation"`), and `context` carries whatever fields are relevant to that source, method, path, and caller_id for a request; nothing required for the background loop today, though the shape allows it later.
- `capture_error` does two things: it logs the error at `ERROR` via the standard `logging` module with `exc_info` set, so it flows through the same JSON formatter and root logger configured in ADR 0022 with no new logging configuration needed, and it appends a structured record, timestamp, source, exception type, exception message, formatted traceback, and context, to a bounded in-memory store, a fixed-size deque holding the most recent 200 errors. This is the part a log stream alone does not give: a live, queryable-in-process view of recent failures, not just a scrolling stream a human has to be watching.
- Because `capture_error` now does the logging itself, it replaces the cluster loop's existing raw `logger.exception(...)` calls in both `except Exception` blocks, rather than running alongside them. Calling both would double-log the same exception under two different code paths for no reason.
- `RequestLoggingMiddleware.dispatch` wraps `call_next` in `try/except Exception`. On exception, it calls `ErrorTrackingService.capture_error(source="request", exc=exc, context={"method": ..., "path": ..., "caller_id": ...})`, still calls `RequestLoggingService.log_completed_request` with `status_code=500` (an unhandled exception always surfaces to the client as Starlette's default `500`) and the elapsed duration, so the request is no longer invisible to request logging, and then re-raises, so the actual response Starlette sends to the client is untouched by any of this.
- `capture_error`'s own internal work, logging and appending to the bounded store, is wrapped in its own `try/except` that swallows any internal failure. A failure inside error tracking itself must never mask, replace, or block the original exception or the response already being built, the same principle ADR 0022 already applied to `RequestLoggingService`'s own logging calls.
- No new endpoint exposing the in-memory error store is added by this decision. The store exists as an internal building block; whether and how to expose it, an authenticated endpoint, for example, is left to a future decision rather than assumed here.
- No real-time alerting, paging, or notification is added. Capturing and structuring an error is not the same as a human being told about it. That gap is named explicitly rather than implied as solved, and is deferred the same way ADR 0022 deferred log shipping and aggregation.

## Consequences

The specific gap found before this decision was written is closed: an unhandled exception on the request path now produces both a correctly logged request outcome (`status_code=500`) and a captured, structured error record, instead of being absent from this codebase's own logging entirely.

The bounded in-memory error store is lost on process restart and gives no unified view across multiple instances, the same accepted tradeoff ADR 0021's rate limiter already made, and the same deployment-shape limitation ADR 0021 and ADR 0022 both already flagged. If this system moves to multiple concurrent instances, this decision needs revisiting the same way those did.

No alerting exists after this change. An operator still has to look, either at the log stream or, once built, at whatever surfaces the in-memory store, nothing pages anyone. This is a real limitation, not an oversight, and is named here so it is not mistaken for solved.

Consolidating the cluster loop's exception logging into `capture_error` means a failure in `ErrorTrackingService` itself, however unlikely given its own internal `try/except`, is now the single point that logs cluster loop errors. This is judged an acceptable concentration of responsibility, consistent with this codebase's existing pattern of a single, tested service owning a cross-cutting concern (`RateLimiterService` for limits, `RequestLoggingService` for request logs), not a new category of risk.
