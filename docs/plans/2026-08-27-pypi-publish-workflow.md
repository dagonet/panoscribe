# PyPI publish workflow (Trusted Publishing, TestPyPI first)

Tier: T3

## Problem

Nothing publishes. `.github/workflows/` contains exactly one file, `ci.yml`, with jobs
`test` (matrix 3.11/3.13) and `resolve`. There is no publish, release, or build
workflow — not partial, not disabled. The rename to `panoscribe` was motivated by
freeing the install name, but `pip install panoscribe` still gets nothing.

The PyPI name is NOT yet registered, so the pipeline is proven against TestPyPI first.

## Decisions (made by the user)

- **Trusted Publishing / OIDC.** No API token, no long-lived secret in GitHub.
- **TestPyPI first**, then real PyPI once the pipeline is proven.

## Pre-existing defects that block or degrade the first upload

These are packaging bugs found during recon. Fix them in this workstream — an upload
attempt fails or ships wrong metadata otherwise.

1. **License metadata conflict (hard blocker).** `pyproject.toml` sets
   `license = "MIT"` (PEP 639 SPDX expression) AND still lists the deprecated
   `"License :: OSI Approved :: MIT License"` classifier. Warehouse rejects a
   distribution carrying both. Remove the classifier, keep the SPDX expression.
   Requires hatchling >= 1.27 to emit Metadata 2.4 — verify the pinned build backend
   version supports it. Add a `license-files` key so `LICENSE` lands in wheel metadata
   (currently absent).
2. **Missing `py.typed` (false metadata claim).** `find src -name py.typed` is empty,
   yet `"Typing :: Typed"` is a declared classifier and mypy runs `strict = true`. The
   package is typed but ships no type information. Add `src/panoscribe/py.typed` and
   ensure hatchling includes it in the wheel.
3. **Version can drift from the tag.** `version = "0.3.0"` is a hand-edited literal in
   pyproject; there is no hatch-vcs/setuptools-scm. `src/panoscribe/__init__.py:6`
   reads it back via `importlib.metadata.version("panoscribe")`. A tag-triggered
   workflow will happily publish a distribution whose version disagrees with the tag.
   Do NOT convert to VCS versioning in this workstream — instead add an explicit
   guard job that fails the run when the tag does not match the pyproject version.

## Scope

### 1. `pyproject.toml` fixes
Items 1-2 above. Do not change the version literal.

### 2. `src/panoscribe/py.typed`
Empty marker file, included in the wheel.

### 3. `.github/workflows/publish.yml`

Trigger: `on: push: tags: ['v*.*.*']` plus `workflow_dispatch` (with a boolean input
selecting TestPyPI vs PyPI, defaulting to TestPyPI).

Jobs, in order:

- `guard` — check out at the tag, parse the version from `pyproject.toml`, assert it
  equals the tag with the leading `v` stripped. Fail loudly with both values on
  mismatch. Every later job needs this.
- `build` — `uv build` producing sdist + wheel; run `twine check --strict dist/*`;
  upload `dist/` as a workflow artifact so a failed publish is still inspectable.
- `publish-testpypi` — `pypa/gh-action-pypi-publish` with
  `repository-url: https://test.pypi.org/legacy/`, `environment: testpypi`,
  `permissions: id-token: write`.
- `publish-pypi` — same action, real index, `environment: pypi`, gated so it does not
  run until TestPyPI has succeeded and the name is registered. Until the user
  confirms the real-PyPI pending publisher exists, this job stays behind a condition
  that cannot fire accidentally.

Conventions to match (from existing `ci.yml`): floating action version tags, NOT
SHA-pins (`actions/checkout@v4`, `astral-sh/setup-uv@v8.1.0`). `ci.yml` has no
`permissions:` block at all, so add `id-token: write` fresh, scoped per-job — never
repo-wide.

### 4. Verification job wiring
The publish workflow must not be able to publish a distribution that failed tests.
Either require the existing `test`/`resolve` jobs, or re-run the gate inside `build`.
Prefer reusing `ci.yml` rather than duplicating its logic.

### 5. `docs/` — release process
Document the release sequence: bump version -> update CHANGELOG -> tag `vX.Y.Z` ->
push tag -> workflow publishes. Include what the user must do once on pypi.org.

## What the user must do (cannot be automated from here)

Create a **pending publisher** on PyPI and TestPyPI for `panoscribe`:
- Owner: `dagonet`
- Repository: `panoscribe`
- Workflow filename: `publish.yml` (pin this exactly; do not rename it later)
- Environment: `testpypi` for TestPyPI, `pypi` for PyPI

Surface these four values in the PR body verbatim so they can be pasted.

## Verification

- `bash hooks/run-gate.sh` -> PASS, expect 604 passed / 98.40%.
- `uv build` locally -> sdist + wheel produced; `twine check --strict dist/*` clean.
- Inspect the built wheel: confirm `py.typed` is present, confirm `LICENSE` is in
  metadata, confirm no duplicate/conflicting license fields.
- Confirm the guard job fails on a deliberately mismatched tag/version pair (test the
  logic locally; do not push a junk tag).
- Do NOT push a real tag or attempt an actual upload in this PR. Landing the workflow
  and proving the build is the deliverable; the first real publish is a separate,
  user-initiated step after the pending publisher exists.

## Out of scope

VCS-derived versioning, changing the release cadence, signing/attestations, and the
actual v0.4.0 release itself.
