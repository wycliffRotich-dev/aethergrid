# ADR 0100: Install Only from Hashed Locks and Test the Rule

## Status

Accepted.

Related: ADR 0058, ADR 0059, ADR 0060, ADR 0076 and ADR 0082.

## Context

pyproject.toml gives the seven runtime dependencies a lower bound, and
httpx an upper bound. There was no lock file. Every build of the image
and every CI run resolved the whole tree again, so a green run described
the versions that existed on that day and said nothing about what the
image holds.

The same gap was in the tools that do the installing. The image upgraded
pip to whatever was newest. The build backend, setuptools>=69, was
fetched at build time with no hash check. The base image was a moving
tag, and gcc stayed in the final image although every locked package
ships a wheel. Five workflows named their actions by tag. A tag can be
moved by whoever owns the action, and one of those actions receives
GIST_SECRET.

## Decision

1. Three lock files hold exact versions and SHA-256 hashes. Each
   resolves for Python 3.11 and up in one file:

       uv pip compile pyproject.toml --universal \
           --python-version 3.11 --generate-hashes -o requirements.lock
       uv pip compile pyproject.toml --extra dev --universal \
           --python-version 3.11 --generate-hashes -o requirements-dev.lock
       uv pip compile requirements-build.in --universal \
           --python-version 3.11 --generate-hashes -o requirements-build.lock

   requirements.lock is the runtime set. requirements-dev.lock adds the
   dev extra for CI and never enters the image. requirements-build.lock
   holds pip and setuptools, the tools that install and build.
2. Every pip install in a workflow or in the Dockerfile passes
   --require-hashes or --no-deps. The locks are installed first with
   --require-hashes --only-binary=:all:. The project is installed last
   with --no-deps --no-build-isolation, so the build backend is the one
   the build lock verified and nothing is resolved at that step.
3. The base image is named by digest. The image has no compiler.
4. Every action is named by a full commit SHA, with the tag in a comment.
   Only a local action may be named by path.
5. Tests in tests/supply_chain check rules 2, 3 and 4 against every file
   in .github/workflows and against the Dockerfile. Each rule has tests
   that feed the checker a bad input and expect it to be flagged.
6. A dependency change is a pull request that regenerates the locks with
   the commands in decision 1. A bot may propose the pull request. A
   person reviews the lock diff and CI runs on it.

## Consequences

- The version of every package in the image is recorded and its hash is
  checked on install. A file changed after the lock was made fails the
  build instead of entering the image.
- Nothing updates itself. A security fix reaches the image only when
  someone regenerates a lock or changes the base digest. This is the
  price of a build that gives the same result twice. Dependabot (ADR
  0060) proposes digest and action bumps weekly. Whether it updates the
  lock files made by uv pip compile has not been observed.
- The dev tools in CI are pinned too. A new release of ruff or mypy no
  longer turns CI red on its own. It arrives in a lock change that a
  person reviews.
- The hashes protect against a file that changes after it was locked.
  They do not protect against a malicious release that is already
  current on the day the lock is made.
- wheel and packaging come from the base image and are in no lock. They
  were audited once, by hand, and are fixed by the base image digest.

## Not Claimed

- That the image is free of known vulnerabilities. The OS packages of
  the base image are not scanned.
- That the install rule sees every installer. The scanner matches the
  text pip install, so pip3 install or uv sync would not be seen.

## Alternatives Considered

- **pip-compile.** Rejected. It resolves for the interpreter that runs
  it, and CI tests Python 3.11 and 3.12 from one lock.
- **A project manager such as Poetry, or uv sync.** Rejected for now. It
  adds a tool and a lock format to the image build. The three commands
  above need uv only when a lock is made, and the image installs with
  pip.
- **Hash only the runtime lock.** Rejected. A build backend runs code
  during the install, and pip is the tool that checks every other hash.
- **Keep the tags and trust the owners of the actions.** Rejected. A
  tag can be moved after it was reviewed, and one action holds a secret.
- **Leave pip and setuptools out of the final image.** Deferred. A
  running container has no use for an installer, and a multi-stage build
  would remove it. It was not needed to close the gap in this change.

## Progress

2026-11-15. A pip-audit of the development environment listed twelve
rows for pip 24.0, which are six advisories listed twice each. Upgrading
pip to 26.3 cleared them. The same session showed that the repository
had no lock file and no requirements.txt.

2026-11-15. Reading the Dockerfile showed that pip install . resolved
everything again and that setuptools>=69 was fetched at build time with
no hash check. A lock that covered only the runtime packages would have
left that path open. Pip itself was then moved into the build lock,
because the tool that checks every hash was the one package nothing
checked.

2026-11-15. An environment built from the runtime lock alone passed 1546
tests on Python 3.12 against Postgres. The image built from the locks.
Its packages were the locked ones plus pip, setuptools, wheel and
packaging, and the last two come from the base image. A pip-audit of
that list found nothing. The full dev lock then passed ruff, mypy and
1546 tests on Python 3.11.18.

2026-11-15. The first test for pinned actions assumed that ci.yml was the
only workflow. It failed on four of the five files and listed eight
references by tag, among them the actions that publish the site in
deploy-site.yml. All eight were pinned.

2026-11-15. The install test passed readme-clean-clone.yml because that
workflow runs the README's blocks (ADR 0076) and names no pip install
itself. The README held pip install -e ".[dev]", so that run resolved
fresh. A test that reads the blocks the way the workflow does failed on
step 2. The README now uses the hashed installs.

2026-11-15. Each rule was broken by hand and a test failed every time.
Reverting one pin in deploy-site.yml failed the pin test for that file.
Removing the hash check from the dev install in ci.yml, and the
--no-deps flag from the Dockerfile, failed one install test each, and
putting the old install back into the README failed the test for step
2. The files were restored and their hashes compared.

2026-11-16. Status changed to Accepted. The merged change passed CI
run 43711947511 on Python 3.11 and 3.12 with the hashed installs, and
the container hardening and README clean clone workflows passed on the
same commit. The install scanner gap is now listed as not claimed,
because the README check showed it.

## How to Verify

    pytest -q tests/supply_chain
    pip-audit -r requirements.lock
    docker build -t neuromesh:locktest .
    docker run --rm --entrypoint python neuromesh:locktest \
        -m pip freeze --all

Compare the last output with requirements.lock. It must hold every
locked package for Linux, and apart from neuromesh only pip,
setuptools, wheel and packaging beyond them.
