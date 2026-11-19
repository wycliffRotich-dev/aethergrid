# ADR 0103: Limit Anonymous Requests With a Bounded Limiter of Its Own

## Status

Proposed.

Related: ADR 0021, ADR 0094 and ADR 0102.

## Context

ADR 0094 says every route of the public app is rate limited and that
nothing is deployed until the app has a limiter of its own for anonymous
callers. The limiter of ADR 0021 cannot be reused:

- It is keyed on an ApiKeyId, and its exception carries one. An anonymous
  caller has no key, and a domain type that stands for an address would be
  a lie.
- Its table of buckets never shrinks. That is acceptable for keys an
  operator issued. For anonymous addresses it is a memory exhaustion,
  because a caller can create entries without bound.
- A bucket per client is not enough on its own. A caller who can rotate
  sources, such as the 2^64 addresses of one IPv6 /64, never meets a
  bucket that is empty.
- Behind a proxy the socket address is the proxy's. Trusting the
  X-Forwarded-For header without a rule lets the caller write the key that
  is used to count them.

## Decision

1. One module, app/application/public_rate_limiter.py, standard library
   only, holds AnonymousRateLimiter and its own exception. The domain gains
   nothing, and the limiter of ADR 0021 and its tests are not touched.
2. A request passes only when both a per client bucket and one global
   bucket hold a token. Both are checked and consumed under one lock, and a
   refusal consumes nothing. A client that is refused cannot drain the
   global bucket, and a global refusal does not cost a client a token.
3. The table of clients holds at most max_clients entries. When it is full,
   the least recently used entry is dropped. A client whose entry was
   dropped starts again with a full bucket. That is the reason for the
   global bucket, which bounds the total load however clients rotate.
   A new client that the global bucket refuses is not added to the table,
   so a flood of refused addresses cannot evict clients that were
   admitted. A client that is refused by its own bucket counts as
   recently used, so a caller who keeps hitting an empty bucket cannot
   have it dropped and refilled by rotating other addresses.
4. A client key is the IPv4 address, the first 64 bits of an IPv6 address,
   or one shared key for a missing or unparseable address, so garbage
   cannot create keys. An IPv4 mapped IPv6 address is keyed as its IPv4
   address.
5. The address is chosen by a function in app/presentation/public. With
   AETHERGRID_PUBLIC_TRUSTED_PROXY_HOPS at 0 it uses the socket address and
   ignores X-Forwarded-For. With N above 0 it uses the Nth entry from the
   right of X-Forwarded-For, because the entries on the right were written
   by proxies the operator controls and the caller can write only the left.
   When the header has fewer than N entries, the request did not pass
   through every proxy, and the socket address is used. The setting is
   required, has no default, and must be an integer from 0 to 5.
   Repeated X-Forwarded-For header lines are joined in the order they
   were received before counting, and an empty entry counts as an entry,
   so neither can shift which entry is chosen. A bracket or a port on the
   chosen entry, as in 203.0.113.9:443 or [2001:db8::1]:443, is removed
   only when it has exactly that shape, with a port of 1 to 5 ASCII
   digits that is no larger than 65535. Any other form is left as it is
   and gets the shared key under decision 4. The setting accepts only the
   characters 0 to 5 and no other spelling of a number.
6. A refused request gets 429 with a fixed body and a Retry-After header in
   whole seconds, at least 1. The response names no client and no limit.
7. The limiter is a middleware of the public app, not a dependency of its
   routes, so unknown paths and refused methods are counted and a new route
   cannot leave it out. It is the outermost middleware. The CORS
   middleware answers a preflight itself, so a limiter inside it would
   leave preflights uncounted and be a free path around the limit. Because
   the limiter is outside, a refusal does not pass through CORS, and the
   429 sets Access-Control-Allow-Origin itself, only when the Origin
   header equals the configured origin, so the browser reads a 429 and not
   a CORS error. A refusal never allows credentials. A test compares that
   header with the one the CORS middleware sends on an admitted request. A
   WebSocket handshake is counted like any request, and a refused one is
   closed with code 1013. Lifespan events are not requests and pass
   through. No route is exempt, /healthz included.
8. The limits are named constants of the module: per client 20 tokens with
   2 refilled each second, global 200 tokens with 50 refilled each second,
   and 10000 clients. The only setting is the number of proxy hops, because
   a wrong value is a security fault and the limits are a tuning matter.

## Consequences

- Memory is bounded by max_clients, and a test floods the limiter with more
  addresses than that and checks the size.
- The limiter takes a clock, so tests refill it exactly and nothing sleeps.
  The clock is read inside the lock, and a step backwards adds no tokens.
- Like ADR 0021, the state is local to the process. Two public processes
  have two limiters, so the public app is run as one process.
- A flood from many networks can empty the global bucket and refuse real
  visitors. The limiter bounds the load that reaches the database. It does
  not promise availability under attack.
- The container health probe is counted as a client of its own and polls
  rarely.
- The public settings gain one required value, and their tests change on
  purpose.
- create_public_app takes an optional limiter so a test can give it a clock.
  When none is given it builds one with the limits of decision 8, and a
  test shows that default is active.

## Not Claimed

- That the public demo is safe to expose. Nothing is deployed.
- That a flood from many networks is stopped. The global bucket only bounds
  the load.
- That the limit values are right. They are first values and are not
  measured.
- That the close code of a refused WebSocket handshake is what a browser
  sees. It was tested through Starlette's test client only, and the public
  app serves no WebSocket route.
- That the operator's proxy writes X-Forwarded-For as decision 5 assumes.
  The hops setting is trusted as it is given.

## Alternatives Considered

- **Reuse the limiter of ADR 0021 with a made up ApiKeyId.** Rejected. It
  puts an address in a type that stands for a key, and its table is
  unbounded.
- **Refuse new clients when the table is full.** Rejected. An attacker
  fills the table and every real visitor is then refused.
- **Trust the leftmost X-Forwarded-For entry.** Rejected. The caller writes
  it.
- **Rely on a limiter in the proxy alone.** Rejected as the only layer. The
  app is its own boundary (ADR 0094) and a proxy can be misconfigured. A
  limiter in front is welcome and does not replace this one.
- **A dependency on each route.** Rejected. Unknown paths and refused
  methods would go uncounted, and a new route could omit it.
- **A shared store such as Redis.** Rejected. One process needs none, and a
  new service to run and secure would add an attack surface for no gain.

## How to Verify

    pytest -q tests/architecture tests/presentation/public
