# Fix documented bootstrap command

Tier: T1

## Problem

A fresh clone that follows the documented bootstrap cannot run its own gate.

`PROJECT_CONTEXT.md` Quick Start and `CLAUDE.md` Quick Start both document `uv sync`.
This repo declares its test/dev tooling in `[project.optional-dependencies]`
(pyproject.toml:66-72), not `[dependency-groups]`. Bare `uv sync` installs only the
base `dependencies` list and does not pull extras, so `pytest-cov` never lands in the
venv. `hooks/run-gate.sh` does not self-provision — it greps the `**Gate Command**:`
line out of `PROJECT_CONTEXT.md` and runs it verbatim against whatever venv exists.

Observed on a fresh clone at d7cb753:

```
pytest: error: unrecognized arguments: --cov=panoscribe --cov-fail-under=95
```

ruff format and ruff check pass; pytest aborts before collecting anything, so zero
tests run and `.gate/last-pass.json` is never written. `hooks/gate-before-merge.sh`
then blocks every PR merge.

CI does not hit this: `.github/workflows/ci.yml:26` uses
`uv sync --extra dev --extra api`. The `api` extra is also required — fastapi/uvicorn
dependent tests need it.

`pytest-cov` (7.1.0) is correctly declared and correctly locked. There is no
dependency gap. The docs simply teach the wrong command.

## Scope

1. `PROJECT_CONTEXT.md` — Quick Start / build command: `uv sync` -> `uv sync --extra dev --extra api`.
2. `CLAUDE.md` — Quick Start block: same substitution.
3. `hooks/run-gate.sh` — preflight guard: if `pytest_cov` is not importable, fail with
   `run: uv sync --extra dev --extra api` rather than surfacing an opaque pytest
   argument error.

Do not touch `pyproject.toml`, `uv.lock`, or `.github/workflows/`. Nothing is missing
there.

Leave the `**Gate Command**:` line itself unchanged — `hooks/run-gate.sh` parses it.

## Verification

- With extras installed: `bash hooks/run-gate.sh` -> PASS, 604 passed, 98.40%,
  `.gate/last-pass.json` written.
- Guard path: temporarily point at a venv without pytest-cov (or stub the import
  check) and confirm the new message appears instead of the pytest usage error.
  Confirm the guard does not fire on a correctly provisioned venv.
