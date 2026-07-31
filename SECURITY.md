# Security Policy

## Supported Versions

AetherGrid is an active portfolio project, not a versioned production release. Security fixes are applied to the `main` branch only.

## Reporting a Vulnerability

If you find a security issue in AetherGrid, please report it privately rather than opening a public issue.

Use GitHub's [private vulnerability reporting](https://github.com/wycliffRotich-dev/aethergrid/security/advisories/new) for this repository. This lets you describe the issue directly to the maintainer without exposing it publicly before a fix is available.

Please include:

- A clear description of the vulnerability
- Steps to reproduce it
- The potential impact, if you can assess it

## What to Expect

This is a solo-maintained project. There's no formal SLA, but reports will be acknowledged and looked at as soon as possible. Given the project's current scope (see the README's "A Deliberate Security Decision Worth Naming" section), some risk areas, like arbitrary command execution, are already known and deliberately unexposed rather than hidden. If your report overlaps with something already documented there, it's still worth reporting, context helps.

## Scope

This policy covers the AetherGrid codebase itself: the API, scheduling logic, and dashboard. It does not cover third-party dependencies; report those to their own maintainers, or via GitHub's Dependabot alerts for this repository.
