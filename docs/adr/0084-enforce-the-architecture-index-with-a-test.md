# ADR 0084: Enforce the Architecture Index With a Test

## Status

Accepted. A test fails when `docs/architecture/README.md` and the
documents beside it disagree: a listed document with no text, a row
for a file that does not exist, or a document with no row. Five
documents that were empty since the commit that added them are removed
with their rows.

Related: ADR 0082.

## Context

`docs/architecture/README.md` is the index of the architecture
documents, and it says that diagrams remain implementation-accurate.
It listed seven documents. Nothing checked that the index and the
directory agree.

A survey at 1ff0987, before this change, found:

1. Five of the seven documents were 0 bytes: 03-backend-components,
   04-frontend-components, 05-request-flow, 06-database and
   07-future-cluster. Each has one commit, c39b7ba, the one that added
   the directory, so none of them ever held text. The index described
   them as the backend modules, the React architecture, the API
   request lifecycle, the PostgreSQL schema and the long-term
   distributed vision.
2. 01-system-overview and 02-clean-architecture had content. ADR 0082
   found 02 empty and filled it. That change made the layer rules a
   test and did not look at the other documents.
3. The index rows are names in a table, not links, so a link checker
   would have had nothing to follow. A search for the names of the
   five found only their rows in the index.

## Decision

1. `tests/architecture/test_architecture_documents.py` reads the rows
   of the index and the files in `docs/architecture/`. It fails when a
   listed document has no text, when a row names a file that does not
   exist, and when a document is in the directory and not in the index.
2. The five empty documents and their five rows are removed. Two
   documents are left, 01-system-overview and 02-clean-architecture.
3. The documents are removed and not written. A row in the index is a
   promise, and these five promised content that nobody had written.
   Each would be a diagram or a schema that has to match the code,
   which is its own reviewed change. A document that is written later
   comes back with its row in the same commit, and the test requires
   both.

## Evidence

- On 1ff0987 the new test failed 5 times and passed 4 times. Each
  failure said that one of the five documents was empty.
- With the five removed, it passes 4 tests. Three mutations each fail
  it: emptying a listed document, adding a row for a file that does
  not exist, and adding a file with no row. Each was restored
  afterwards.
- The architecture tests pass (24), ruff is clean, and strict mypy
  reports no issues in 175 source files.
- The full suite passes (1077).

## Consequences

- An empty document, a row without a file and a file without a row
  each fail the suite, and CI with it.
- Adding an architecture document is one commit that adds the file
  with text and its row.
- Every row in the index now leads to a document with content.

## Not Claimed

- That the two remaining documents are accurate. The test checks that
  a document exists, has text and is listed. It does not compare a
  diagram with the code.
- That a listed document is more than a stub. Any text that is not
  blank passes.
- That the topics of the five removed documents are written up
  anywhere. This change writes none of them.

## Alternatives Considered

- **Write the five documents in this change.** Rejected. Each is a
  diagram or a schema that has to match the code, and five written to
  satisfy a test would be reviewed as filler.
- **Keep the empty files and exempt them in the test.** Rejected. It
  would record the gap and keep the promise in the index, which is the
  state this change removes.
- **A link checker in CI.** Rejected. The rows are not links, and a
  checker follows links and does not ask whether the target has text.
