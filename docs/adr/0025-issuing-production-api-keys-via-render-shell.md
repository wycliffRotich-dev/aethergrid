# ADR 0025: Issuing Production API Keys via Render Shell

## Context

`scripts/issue_api_key.py` writes directly to whichever Postgres database it is pointed at. Local development runs Postgres in Docker on port 5433, so keys issued locally only exist in that local database. The live dashboard at aethergrid-dashboard.onrender.com authenticates against a separate production database on Render. A key issued locally has no effect there.

The obvious way to fix that is to run the script locally with `DATABASE_URL` overridden to point at the production database. That works, but it means pulling a live production credential onto a developer laptop every time a key needs to be issued, into shell history, terminal scrollback, and potentially into a screenshot or a paste. Render also gives every web service a Shell tab, a terminal that runs inside the deployed container, already configured with the production `DATABASE_URL` and with no credential ever leaving Render's infrastructure.

## Decision

Production API keys are issued by running `scripts/issue_api_key.py` from Render's Shell tab on the web service, not from a local machine. Local runs of the script are for local development only, against the Dockerized Postgres instance on port 5433.

## Rejected Alternative

Overriding `DATABASE_URL` locally to point at the production database and running the script from a laptop. I rejected this because it requires a live production credential to exist outside Render's infrastructure, even briefly, which contradicts the exposure discipline already established in ADR 0015, ADR 0020, and ADR 0024. Convenience is not a strong enough reason to let a production secret leave the environment that is supposed to hold it.

## Consequence

Issuing a production key takes one extra step, opening Render's dashboard instead of running a command locally. In exchange, no production database credential is ever typed, exported, or stored on a developer machine. This keeps the project consistent with how it treats every other credential boundary.
