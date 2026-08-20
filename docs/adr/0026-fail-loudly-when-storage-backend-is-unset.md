# ADR 0026: Fail Loudly When the Storage Backend Is Unset

## Context

`scripts/issue_api_key.py` calls `get_create_api_key_service()`, which reads `NEUROMESH_STORAGE_BACKEND` from the environment and defaults to `"memory"` if it is not set. Running the script without that variable set to `postgres` produces no error and no warning. It prints a normal looking success message and a valid looking key, but the key is written into an in-memory repository that is discarded the moment the process exits. The key never reaches the actual database, and any later attempt to authenticate with it fails with a generic invalid credential error, which gives no indication that the real problem was an unset environment variable at issuance time, not anything wrong with the key itself.

This surfaced directly. A key was issued twice against what looked like the production database, both attempts printed successfully, and both were gone by the time either was tested against the live dashboard. The actual cause took a full debugging session to find, because every layer downstream, the frontend header format, the backend auth comparison, the key generation logic, was already correct. The failure was silent and upstream of all of it.

## Decision

`get_create_api_key_service()`, and the other dependency functions that branch on `NEUROMESH_STORAGE_BACKEND`, should raise a clear error if the variable is unset or set to something other than an explicitly recognized value, rather than silently defaulting to `memory`. A bootstrap script that issues real credentials should never be able to succeed against a throwaway store without the caller being told that is what happened.

## Rejected Alternative

Leaving the default as `memory` and documenting the required environment variables more clearly in the script's docstring. The docstring already mentioned `NEUROMESH_STORAGE_BACKEND` before this was found, and it was still missed under time pressure while debugging a live 401. Documentation does not prevent a silent wrong default from being silently wrong. The fix belongs in the code path that has enough information to know the caller almost certainly did not intend to issue a credential into memory.

## Consequence

Any future run of `issue_api_key.py`, or anything else depending on this backend selection, without `NEUROMESH_STORAGE_BACKEND` explicitly set, fails immediately with a clear message instead of appearing to succeed. This trades a small amount of friction for every local run against every silent failure of this kind going forward.
