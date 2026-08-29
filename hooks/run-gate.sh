#!/usr/bin/env bash
# Gate runner (invoked by developers/PO, not registered as a hook):
#   bash hooks/run-gate.sh
#
# Reads the Gate command from PROJECT_CONTEXT.md ("**Gate**: <command>",
# with or without a leading list marker) and runs it. On success, writes
# the gate artifact that hooks/gate-before-merge.sh checks before allowing
# a PR merge:
#
#   .gate/last-pass.json  (at the repo toplevel of the current checkout/worktree)
#   {"sha":"<HEAD sha>","tree":"<index tree, or \"\" if the working tree had
#    unstaged changes>","branch":"<branch>","ts":"<UTC ISO-8601>","status":"pass"}
#
# On failure, any existing artifact is deleted and the script exits nonzero.
# No-op (exit 0) when the Gate field is missing or still a {{...}} placeholder,
# so templates degrade gracefully before a project configures its gate.
#
# v2.1.3 fix round 1 (review): a project whose **Gate** command itself invokes
# this script (e.g. "bash hooks/run-gate.sh" -- a copy/paste mistake, or a
# gate that shells out to a wrapper that shells out here) would otherwise
# recurse until the process/fd limit kills it. RUN_GATE_ACTIVE guards against
# that: it is exported before the gate command runs and checked on entry.

if [ "${RUN_GATE_ACTIVE:-}" = "1" ]; then
  echo "BLOCKED: **Gate** must not invoke run-gate.sh itself" >&2
  exit 2
fi

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  echo "Usage: bash hooks/run-gate.sh"
  echo ""
  echo "Runs the Gate command from PROJECT_CONTEXT.md (**Gate**: <command>)."
  echo "Green: writes .gate/last-pass.json (checked by gate-before-merge.sh) and prints GATE PASS <sha>."
  echo "Red:   deletes the artifact and exits nonzero."
  echo "No Gate configured: prints GATE SKIP and exits 0."
  exit 0
fi

CWD=$(pwd)
REPO_TOP=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_TOP" ]; then
  echo "GATE ERROR: not inside a git repository" >&2
  exit 1
fi

# Read Gate command from PROJECT_CONTEXT.md. Tolerates: leading "- " / "* " list
# markers, the "**Gate Command**:" label style (java/python variants), and
# surrounding backticks — several variants write commands as `cmd`.
GATE_CMD=$(grep -E '^[-*[:space:]]*\*\*Gate( Command)?\*\*:' "$REPO_TOP/PROJECT_CONTEXT.md" 2>/dev/null | sed 's/.*\*\*Gate\( Command\)\?\*\*:[[:space:]]*//;s/[[:space:]]*$//;s/^`//;s/`$//' | head -1)

# No-op: no PROJECT_CONTEXT.md or no Gate command configured
if [ -z "$GATE_CMD" ]; then
  echo "GATE SKIP (no Gate command configured in PROJECT_CONTEXT.md)"
  exit 0
fi

# No-op: placeholder not yet filled in
case "$GATE_CMD" in
  *\{\{*\}\}*)
    echo "GATE SKIP (Gate command is still a template placeholder)"
    exit 0
    ;;
esac

HEAD_SHA=$(git -C "$CWD" rev-parse HEAD 2>/dev/null)
BRANCH=$(git -C "$CWD" branch --show-current 2>/dev/null)
ARTIFACT_DIR="$REPO_TOP/.gate"
ARTIFACT="$ARTIFACT_DIR/last-pass.json"

cd "$REPO_TOP" || exit 1

# Preflight: the Gate command below relies on pytest-cov (declared in the
# "dev" optional-dependencies group). A bare `uv sync` does not install
# extras, so pytest-cov is missing and pytest aborts with an opaque
# "unrecognized arguments: --cov=..." error before collecting any tests.
# Catch that case here with an actionable message instead.
if command -v uv >/dev/null 2>&1; then
  if ! uv run python -c "import pytest_cov" >/dev/null 2>&1; then
    echo "GATE ERROR: pytest-cov is not installed in this environment." >&2
    echo "run: uv sync --extra dev --extra api" >&2
    exit 1
  fi
fi

echo "GATE: running: $GATE_CMD"

# v2.1.3 fix round 1 (Critical 2 / penumbra #2c): key the artifact on the
# INDEX tree, not just HEAD's sha. At PreToolUse commit time (pre-commit-test.sh
# invoking this script before the `git commit` runs) the index tree is the tree
# the commit is about to get -- so gate-before-merge.sh can accept an artifact
# whose tree matches HEAD^{tree} even though its sha is the PARENT commit's,
# not the new one. Accepted miss: `git commit -a` or a commit with extra
# `git add` after this ran stages more than the index snapshot we hashed here
# -- that produces a tree mismatch too, and the merge gate falls back to
# requiring a fresh run, exactly as before this fix.
#
# v2.1.3 fix round 2: only record the tree when the working tree matches the
# index (`git diff --quiet`). write-tree hashes the INDEX; if there are
# unstaged changes beyond it, a `git commit -a` (or a manual `git add` after
# this ran) would fold those in too, producing a DIFFERENT tree than the one
# we are about to hash -- recording it would let a mismatched commit slip
# through gate-before-merge.sh's tree check. sha-only in that case.
TREE_HASH=""
if git -C "$REPO_TOP" diff --quiet 2>/dev/null; then
  TREE_HASH=$(git -C "$REPO_TOP" write-tree 2>/dev/null)
fi

RUN_GATE_ACTIVE=1
export RUN_GATE_ACTIVE
if bash -c "$GATE_CMD"; then
  mkdir -p "$ARTIFACT_DIR"
  TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '{"sha":"%s","tree":"%s","branch":"%s","ts":"%s","status":"pass"}\n' \
    "$HEAD_SHA" "$TREE_HASH" "${BRANCH:-unknown}" "$TS" > "$ARTIFACT"
  echo "GATE PASS $HEAD_SHA"
  exit 0
else
  rm -f "$ARTIFACT"
  echo "GATE FAILED: '$GATE_CMD' exited nonzero. Fix the failures and re-run 'bash hooks/run-gate.sh'." >&2
  exit 1
fi
