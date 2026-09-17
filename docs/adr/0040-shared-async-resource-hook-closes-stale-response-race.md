# ADR 0040: Shared useAsyncResource Hook Closes a Stale-Response Race Present in Seven Hooks

## Status

Accepted

## Context

Adding CI coverage for the frontend (a repository gap that had existed since the frontend's start) surfaced 9 `react-hooks/set-state-in-effect` violations. Seven of them, in `useJobs`, `useNodes`, `useWorker`, `useWorkers`, `useEvents`, `useJobDetail`, and `useClusterStats`, shared the exact same shape: an async `refresh()` memoized with `useCallback`, fetching data and setting local state, called from a `useEffect` on mount, on a dependency change, or on a fixed poll interval.

The lint failure was not a false positive. Tracing why the rule fires (it only recognizes a `setState` call as safe when it is made from a function defined lexically inside the effect callback itself, not one merely called from it, regardless of memoization) led to a real question: what happens to a hook's state if a response resolves after a newer fetch has already started? None of the seven hooks had an answer, because none of them guarded against it.

Concretely: `useWorker` and `useJobDetail` re-fetch whenever their `id` argument changes, driven by route params. Navigate from worker A's detail page to worker B's quickly enough, and if A's request resolves after B's, A's response overwrites B's on screen. `useJobs` and `useEvents` poll on a fixed interval; a slow tick's response can resolve after a faster subsequent tick's response, and the slower one wins because it landed last, not because it was newest. This is a live race today, not a hypothetical one, and it depends only on network timing to manifest.

Three narrower fixes were considered before this one and rejected:

1. An `eslint-disable-next-line` comment at each of the 7 call sites. This would have silenced the lint failure without addressing the race it was pointing at.
2. Passing the existing memoized `refresh()` into the effect unchanged. Verified directly against the installed `eslint-plugin-react-hooks@7.1.1`: this still fails the same rule, and still has the same race, regardless of the `useCallback` wrapper. The rule's behavior here is a real signal, not a linter quirk to route around.
3. Fixing each of the 7 hooks independently, in place, with its own `ignore`-flag guard. This would have closed the race in all 7 without lint failures, but leaves the same fetch/loading/error boilerplate duplicated 7 times, the same shape ADR 0033's `persist_job_started` extraction and ADR 0011's `reclaim_job` extraction were written to avoid on the backend: a correctness fix, once found, hand-copied into N call sites instead of named once.

## Decision

Extracted the pattern into a single shared hook, `useAsyncResource<T>`, in `frontend/src/hooks/useAsyncResource.ts`. It takes a fetcher function, a caller-supplied dependency array (the same contract `useEffect` and `useMemo` already ask consumers to uphold), and an optional poll interval.

Inside its own effect, it defines the fetch as a function declared literally within that effect body, guarded by an `ignore` flag scoped to that one effect run:

```ts
useEffect(() => {
  const signal = { ignore: false };

  async function load(isRefresh: boolean) {
    // ... fetch, then setState only if !signal.ignore
  }

  void load(refreshToken > 0);

  const interval = pollIntervalMs
    ? setInterval(() => void load(false), pollIntervalMs)
    : undefined;

  return () => {
    signal.ignore = true;
    if (interval) clearInterval(interval);
  };
}, [...deps, refreshToken]);
```

A response that resolves after `signal.ignore` has been set (because `deps` changed, the poll interval fired again, or the component unmounted) is dropped instead of applied. Whichever fetch is newest always wins, regardless of resolution order.

The one design decision worth recording on its own: `refresh()` does not run its own, separate fetch. It increments a `refreshToken` state value, which is included in the effect's dependency array, causing the same effect, and therefore the same guarded `load()`, to run again. Manual refresh and automatic fetch are not two implementations that happen to agree today; they are the same code path, so they cannot independently drift out of sync later. `resetLoadingOnRefresh` is a second, smaller option, added because the 7 original hooks split into two families here: `useJobs` and `useEvents` (both polling) did not reset `loading` to `true` on a background refresh, to avoid flashing a loading state on every 3-second tick, while the other five did, to show a loading state when their `id` argument changes. This distinction was preserved exactly, not homogenized away, since it reflects a real, existing product decision about when a spinner should reappear.

All 7 hooks were migrated onto `useAsyncResource`, each shrinking to a thin wrapper naming its own return fields. No consuming component required changes, since the external shape of each hook (`{ jobs, loading, error, refresh }`, `{ worker, loading, error, refresh }`, and so on) is unchanged.

## Consequences

### Positive

- Closes a real, previously unguarded race condition in all 7 hooks simultaneously, rather than in whichever hook happens to get touched next.
- Removes 234 lines of near-identical fetch/error/loading boilerplate, replaced by a 99-line shared hook and 7 small wrappers.
- `refresh()` and the automatic fetch are structurally incapable of diverging, since they are the same effect run rather than two call paths that happen to do the same thing today.
- Satisfies `react-hooks/set-state-in-effect` as a consequence of fixing the actual bug, not as the goal in itself.

### Negative

- `useAsyncResource`'s effect dependency array is `[...deps, refreshToken]`, a spread of a caller-supplied array rather than a static list `exhaustive-deps` can fully verify. This is inherent to any hook generic over its caller's own dependencies, and matches the same contract `useEffect` itself already places on any caller. Documented with an inline comment and a scoped `eslint-disable-next-line`, verified to introduce no other lint failures.
- A generic hook is one more level of indirection than reading a single hook's fetch logic directly. Weighed against 7 duplicated copies of that logic, later drifting out of sync one at a time, the indirection was judged worth it.

## Alternatives Considered

### Per-hook eslint-disable comments

Rejected. Would have silenced the lint rule without closing the race it was pointing at, since the rule's complaint (an untraceable `setState` reachable from an effect) and the actual bug (no guard against a stale response) are different framings of the same underlying gap.

### Fix each of the 7 hooks independently, in place

Rejected. Closes the race in all 7, same as the shared hook, but leaves the fetch/loading/error pattern duplicated 7 times rather than named once, the exact situation ADR 0011 and ADR 0033 were written to close on the backend. The next hook needing this pattern would have to reimplement it correctly from scratch rather than reuse something already proven correct.
