#!/usr/bin/env bash
# Gate preflight (panoscribe, issue #98).
#
# Runs as the FIRST command of the **Gate Command** in PROJECT_CONTEXT.md, so
# it lives here rather than inside hooks/run-gate.sh — that file is synced
# verbatim from claude-code-toolkit and every local edit forces a hand-merge.
#
# WHY: the gate's pytest invocation relies on pytest-cov, which is declared in
# the "dev" group of [project.optional-dependencies]. A bare `uv sync` does not
# install extras, so pytest-cov is missing and pytest aborts with an opaque
# "unrecognized arguments: --cov=..." before collecting a single test. Catch
# that here with an actionable remedy instead.
#
# HOW (run-gate.sh v2.3.0 public terminal contract): print the remedy, touch
# "$RUN_GATE_TERMINAL", exit 78. run-gate.sh clamps a gate command's 78 to 1
# UNLESS that marker exists; with it, run-gate.sh takes its terminal branch and
# stays deliberately silent, so the remedy printed here is the last thing the
# user reads. The marker is provenance only — the exit code is the contract.

# Must match GC_TERMINAL_RC in hooks/lib/git-cmd.sh (and hooks/run-gate.sh).
GC_TERMINAL_RC=78

# Permissive when uv is absent: no uv, no opinion.
if ! command -v uv >/dev/null 2>&1; then
  exit 0
fi

if ! uv run python -c "import pytest_cov" >/dev/null 2>&1; then
  # Marker written BEFORE the remedy so the remedy stays the last line on
  # stderr. Only on the failure path: writing it unconditionally would hand the
  # terminal remedy to a later genuine 78 from the gate's own commands (78 is
  # EX_CONFIG; real programs emit it), which is the inversion run-gate.sh's
  # clamp exists to prevent. Idiom copied verbatim from run-gate.sh:57 — the
  # `${VAR:-}` expansion keeps a standalone `bash preflight.sh` safe (the
  # variable is unset then, and a bare expansion would abort under `set -u`).
  # The guard gates only the marker; the 78 below is unconditional.
  [ -n "${RUN_GATE_TERMINAL:-}" ] && : > "$RUN_GATE_TERMINAL"
  echo "GATE ERROR: pytest-cov is not installed in this environment." >&2
  echo "run: uv sync --extra dev --extra api" >&2
  exit "$GC_TERMINAL_RC"
fi

exit 0
