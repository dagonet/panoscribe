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
# On failure, any existing artifact is deleted and the script exits nonzero:
# 1 for an ordinary red gate (retry after fixing), GC_TERMINAL_RC (78) when the
# failure is terminal — a configuration the gate command cannot succeed under,
# where "re-run it" is the wrong advice. See the exit-code conventions block in
# hooks/lib/git-cmd.sh.
#
# THE TERMINAL CONTRACT IS PUBLIC (v2.3.0). A **Gate** command — typically a
# preflight chained ahead of the real gate, `bash preflight.sh && <gate>` — can
# declare its OWN terminal condition: print the remedy to stderr, touch
# $RUN_GATE_TERMINAL, exit 78. The clamp below then passes the 78 through
# instead of collapsing it to 1, and the terminal branch stays silent so the
# consumer's remedy is the last thing on screen. Worked example and the naming
# commitment this implies: docs/verification.md.
# No-op (exit 0) when the Gate field is missing or still a {{...}} placeholder,
# so templates degrade gracefully before a project configures its gate.
#
# v2.1.3 fix round 1 (review): a project whose **Gate** command itself invokes
# this script (e.g. "bash hooks/run-gate.sh" -- a copy/paste mistake, or a
# gate that shells out to a wrapper that shells out here) would otherwise
# recurse until the process/fd limit kills it. RUN_GATE_ACTIVE guards against
# that: it is exported before the gate command runs and checked on entry.

#
# v2.2.5 (consumer report): the guard was safe but its follow-on advice was
# circular — the outer layers appended "fix the failures and re-run" to a
# condition that no amount of re-running can change. GC_TERMINAL_RC, defined
# locally for the same standalone reason as GC_KEY_PRE below, is how a caller
# tells the two apart. See the exit-code conventions block in
# hooks/lib/git-cmd.sh; scripts/verify-template-consistency.sh asserts the two
# definitions stay in step.
GC_TERMINAL_RC=78

if [ "${RUN_GATE_ACTIVE:-}" = "1" ]; then
  echo "BLOCKED: **Gate** must not invoke run-gate.sh itself" >&2
  echo "Edit '**Gate**:' in PROJECT_CONTEXT.md to your real build/test commands — run-gate.sh RUNS that value, so it cannot BE that value." >&2
  # PROVENANCE MARKER, and it is load-bearing (v2.2.5 round 3). The OUTER
  # run-gate.sh clamps a gate command's 78 to 1, because an arbitrary consumer
  # gate that exits 78 for its own reasons must not inherit the terminal remedy
  # text. But in the self-reference case the gate command IS run-gate.sh, so the
  # clamp would swallow the one signal item K exists to deliver. The exit code
  # carries a VALUE; what the outer layer needs is PROVENANCE. This file, and
  # only this file, touches the marker the outer exported — at any nesting depth,
  # since the variable is inherited through wrappers too. See the clamp below.
  [ -n "${RUN_GATE_TERMINAL:-}" ] && : > "$RUN_GATE_TERMINAL"
  exit "$GC_TERMINAL_RC"
fi

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  echo "Usage: bash hooks/run-gate.sh"
  echo ""
  echo "Runs the Gate command from PROJECT_CONTEXT.md (**Gate**: <command>)."
  echo "Green: writes .gate/last-pass.json (checked by gate-before-merge.sh) and prints GATE PASS <sha>."
  echo "Red:   deletes the artifact and exits 1 (78 when the failure is terminal — see hooks/lib/git-cmd.sh)."
  echo "No Gate configured: prints GATE SKIP and exits 0."
  echo ""
  echo "Your Gate command can declare its own terminal condition: print the remedy"
  echo "to stderr, touch \$RUN_GATE_TERMINAL, and exit with the terminal code."
  echo "Worked example: docs/verification.md."
  exit 0
fi

CWD=$(pwd)
REPO_TOP=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_TOP" ]; then
  # TERMINAL (v2.2.5 round 3): re-running this from the same cwd cannot ever make
  # that directory a git repository. Before this it exited 1, so pre-commit-test
  # appended "re-run it and fix the failures" — item K's circular advice, in a
  # guard that already existed rather than a hypothetical future one. The class
  # is TERMINAL, not "configuration": this one is an ENVIRONMENT error and 78
  # covers both (see the exit-code conventions in hooks/lib/git-cmd.sh).
  echo "GATE ERROR: not inside a git repository" >&2
  echo "Run 'bash hooks/run-gate.sh' from inside the checkout — cd to the repository and re-run it there." >&2
  exit "$GC_TERMINAL_RC"
fi

# GC_KEY_PRE, defined locally: this script is deliberately standalone (it must
# run with no JSON parser on PATH, which sourcing hooks/lib/git-cmd.sh would
# forbid), so it repeats the constant rather than importing it. The definition
# and the reason live in the header note on GC_KEY_PRE in hooks/lib/git-cmd.sh;
# scripts/verify-template-consistency.sh asserts the two stay in step.
GC_BOM=$(printf '\357\273\277')
GC_KEY_PRE="^(${GC_BOM})?[-*[:space:]]*"

# Read Gate command from PROJECT_CONTEXT.md. Tolerates: an optional leading
# UTF-8 BOM, leading "- " / "* " list
# markers, the "**Gate Command**:" label style (java/python variants), and
# surrounding backticks — several variants write commands as `cmd`.
GATE_CMD=$(grep -E "${GC_KEY_PRE}\*\*Gate( Command)?\*\*:" "$REPO_TOP/PROJECT_CONTEXT.md" 2>/dev/null | sed 's/.*\*\*Gate\( Command\)\?\*\*:[[:space:]]*//;s/[[:space:]]*$//;s/^`//;s/`$//' | head -1)

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

echo "GATE: running: $GATE_CMD"
# This `exit 1` DELIBERATELY STAYS 1 and is not a terminal 78 (v2.2.5 round 3):
# a failing cd to a path git JUST resolved is an environment FAULT — a race, a
# permissions change, an unmounted share — not a settled condition. Retrying can
# legitimately succeed, so "re-run it" is the right advice here and this is not
# an inconsistency to tidy up.
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
# The provenance channel for the recursion guard at the top of this file. It
# lives inside TMPD, so the EXIT trap removes it; a nested run-gate.sh at ANY
# depth inherits the variable and touches the file before exiting 78.
#
# THE MARKER IS A FILE, AND ON WINDOWS THAT IS LOAD-BEARING (v2.2.5 round 4).
# Git Bash's MSYS layer REWRITES a POSIX-looking environment value when it
# crosses into a native Windows process: the child receives `C:/Users/.../Temp/...`
# where this script set `/tmp/...`. `mktemp -d` returns a real `/tmp/...` path on
# this platform, so the translation DOES happen in the real script — it is not a
# hypothetical. The mechanism survives it only because both spellings resolve to
# the SAME FILE and the translation is consistent in both directions. If this
# value were ever compared as a STRING — or used as a key rather than a path —
# it would break silently on Windows and nowhere else.
RUN_GATE_TERMINAL="$TMPD/terminal"
export RUN_GATE_TERMINAL
rm -f "$RUN_GATE_TERMINAL"
bash -c "$GATE_CMD"
GATE_RC=$?

# THE CLAMP. NOT DEAD CODE — DELETING IT OPENS A COLLISION CHANNEL (v2.2.5
# round 3). Until this release every nonzero from the gate command collapsed to
# a hardcoded `exit 1`, because `$?` was never captured. That accidental clamp is
# what kept the toolchain safe, and giving the guard a distinguishable code is
# exactly the change that leads someone to refactor it into `exit $GATE_RC` —
# at which point a consumer gate command exiting 78 for its own reason (78 is
# EX_CONFIG; real programs emit it) inherits the terminal remedy text "edit your
# **Gate** value", printed over a plain test failure. That is INVERTED advice,
# strictly worse than the generic retry line it replaces. Measured downstream:
# `uv run` propagates a child's code verbatim, so the channel is open one layer
# up and closed only here.
#
# So a gate command's 78 is clamped to 1 — UNLESS a nested run-gate.sh left the
# provenance marker, which is the one case where the 78 really is this script's
# own terminal guard talking. Keyed on WHO decided, not on the number.
#
# THE HONEST LIMIT OF THE MARKER (v2.2.5 round 4). It proves that *a* nested
# run-gate.sh exited terminally during THIS invocation. It does NOT prove that
# *this* `$GATE_RC` came from that nested run. A gate of the form
# `bash hooks/run-gate.sh; some-other-tool` sets the marker via the recursion
# guard and then takes its final rc from the second command — so an unrelated 78
# there inherits the terminal remedy, which is the very collision this clamp
# closes, reopened one step along. It needs a self-referencing gate AND a second
# command exiting 78, and closing it would mean reconstructing the causal chain
# rather than a single fact, so it is recorded as a known edge rather than
# fixed. Read this test as "a terminal guard fired in here", not as
# "provenance settled".
if [ "$GATE_RC" -eq "$GC_TERMINAL_RC" ] && [ ! -f "$RUN_GATE_TERMINAL" ]; then
  GATE_RC=1
fi

if [ "$GATE_RC" -eq 0 ]; then
  mkdir -p "$ARTIFACT_DIR"
  TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '{"sha":"%s","tree":"%s","branch":"%s","ts":"%s","status":"pass"}\n' \
    "$HEAD_SHA" "$TREE_HASH" "${BRANCH:-unknown}" "$TS" > "$ARTIFACT"
  echo "GATE PASS $HEAD_SHA"
  exit 0
elif [ "$GATE_RC" -eq "$GC_TERMINAL_RC" ]; then
  # TERMINAL: reachable only when the clamp above let the 78 through, i.e.
  # something left the provenance marker. Two producers, one rule:
  #   * a NESTED run-gate.sh hitting its own recursion guard (a self-invoking
  #     **Gate**, directly or through a wrapper);
  #   * since v2.3.0, THE **Gate** COMMAND ITSELF, following the public contract
  #     in docs/verification.md (print remedy, touch $RUN_GATE_TERMINAL, exit
  #     78). The marker never meant "run-gate.sh decided"; it means "whoever
  #     exited took responsibility for the remedy", which is why the clamp is
  #     keyed on it and not on the caller.
  # DELIBERATELY SILENT. The generic "fix the failures and re-run" of the else
  # arm is wrong here, and so is any replacement of it: only the guard knows the
  # specific remedy, it has already printed it on this same stderr, and it must
  # stay the LAST thing on screen. Printing a trailing summary would bury it
  # again — which is the exact defect this branch exists to fix. The code is
  # propagated so the caller (pre-commit-test.sh) can suppress ITS retry advice
  # by the same structural test, without knowing which guard fired.
  rm -f "$ARTIFACT"
  exit "$GC_TERMINAL_RC"
else
  rm -f "$ARTIFACT"
  echo "GATE FAILED: '$GATE_CMD' exited nonzero. Fix the failures and re-run 'bash hooks/run-gate.sh'." >&2
  exit 1
fi
