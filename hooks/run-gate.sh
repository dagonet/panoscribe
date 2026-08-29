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
#   {"sha":"<HEAD sha>","tree":"<working-tree hash>","branch":"<branch>",
#    "ts":"<UTC ISO-8601>","status":"pass"}
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
# v2.1.5 (consumer feedback: Yutraffic PR #223 e59e6fd vs 567f0d1, panoscribe
# PR #123): key the artifact on the WORKING TREE, not the index. The PreToolUse
# hook fires before a chained `git add ... && git commit` stages anything, so
# the v2.1.3 index tree was the PARENT tree and the v2.1.3-round-2 `git diff
# --quiet` guard recorded no tree at all -- the artifact matched nothing and the
# single-run merge path never fired for agents, who chain add+commit habitually.
#
# A temp index (a copy of the real one, so unchanged paths need no re-stat) is
# `add -A`'d and hashed. The REAL index is never touched, and .gitignore is
# respected, so .gate/ and build output stay out of the hash.
#
# Consequently `git add -A && git commit`, `git commit -a`, and separate
# add/commit calls all yield `HEAD^{tree} == tree`. A PARTIAL-add commit
# mismatches by design: the committed tree is not what was gated, so
# gate-before-merge.sh correctly demands a fresh run.
#
# CAVEAT -- the hash is taken BEFORE the gate command runs (deliberately: a
# gate that fails must not have its own mutations blessed). So a gate that
# MUTATES the tree makes the following commit mismatch anyway:
#   * a formatter in the gate rewriting tracked files;
#   * gate-generated output that is untracked and NOT gitignored (coverage
#     reports, `pytest-of-*`, build logs) -- `add -A` on the temp index writes
#     blobs for every unignored untracked file on every run, so such output
#     lands in the NEXT run's hash and never in this one's.
# The fix is on the project side: gitignore everything the gate produces (and
# run the formatter before the gate, not inside it).
#
# `rev-parse --git-path index` (not a hardcoded .git/index) is what makes this
# work in a LINKED WORKTREE, where the index lives at
# .git/worktrees/<name>/index -- coder/tester run under `isolation: worktree`.
TMPD=$(mktemp -d)
trap 'rm -rf "$TMPD"' EXIT
TMPIDX="$TMPD/index"   # must not pre-exist: git rejects a 0-byte index
cp "$(git -C "$REPO_TOP" rev-parse --git-path index)" "$TMPIDX" 2>/dev/null || true
GIT_INDEX_FILE="$TMPIDX" git -C "$REPO_TOP" add -A >/dev/null 2>&1
TREE_HASH=$(GIT_INDEX_FILE="$TMPIDX" git -C "$REPO_TOP" write-tree 2>/dev/null)

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
