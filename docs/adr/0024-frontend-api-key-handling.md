# ADR 0024: Frontend API Key Handling

## Context

The dashboard needs an API key to authenticate against every backend route, per ADR 0015. Vite bundles every `import.meta.env.*` value into static JavaScript at build time. That means any key set through `VITE_API_KEY` would ship in plaintext inside the public bundle, readable by anyone who opens devtools or inspects a network request. Deploying the dashboard publicly with a build-time key would hand out a working credential to every visitor by default.

## Decision

The frontend does not accept a build-time API key. The user provides their key through a login screen at runtime. The key is held only in memory for the session and attached to outgoing requests as needed. It never appears in build output, never gets committed to source control, and never gets logged.

## Rejected Alternative

Baking a scoped "demo" key into the build through `VITE_API_KEY`. I considered this since it ships faster and the blast radius could be limited by scoping the key narrowly. I rejected it because it contradicts the exposure discipline I already committed to in ADR 0015 and ADR 0020. A key with real permissions should not be shipped to every visitor's browser by default just because it is convenient, regardless of how narrow its scope is.

## Consequence

Visitors to the live dashboard see an empty, unauthenticated state until they supply their own key. That is a deliberate floor, not a bug. Public reachability and default-open access are two different things, and this project treats them as such everywhere else, so the frontend should not be the one place that quietly breaks that rule.
