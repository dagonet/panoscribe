#!/usr/bin/env bash
# PreToolUse hook: require passing tests before git commit
# Matcher: Bash|PowerShell
#
# Runs the project's test command before allowing a commit.
# Blocks the commit if tests fail.
#
# No-op when TEST_COMMAND is still a placeholder (template not configured)
# or when PROJECT_CONTEXT.md doesn't exist.
#
# Buggy code was the #1 friction category (10 occurrences) in Insights report.
# This hook prevents shipping code that breaks existing tests.
#
# v2.0: the native git CLI is allowed again, so this gate parses
# tool_input.command instead of keying on the retired mcp__git-tools__git_commit
# tool name. Escape hatch: <cwd>/.claude/git-guard-off.

# Fail CLOSED when the sourced lib is missing: without it every gc_* helper is
# undefined, GC_CMD stays empty, and this gate would exit 0 on every commit.
lib="$(dirname "$0")/lib/git-cmd.sh"
[ -f "$lib" ] || { echo "BLOCKED: $lib missing — run /sync-template step 6b (hooks/lib/git-cmd.sh)" >&2; exit 2; }
. "$lib"

gc_read_stdin
gc_guard_off && exit 0

# Fail CLOSED on a pre-v2 settings.json: it registers this gate on the retired
# git-tools MCP tools, whose payloads carry no tool_input.command — the v2 gate
# would find nothing to parse and allow the commit.
case "$GC_TOOL" in
  mcp__git-tools__git_push|mcp__git-tools__git_commit)
    echo "BLOCKED: settings.json predates this hook (MCP matcher) — restart the session after /sync-template" >&2
    exit 2 ;;
esac

[ -n "$GC_CMD" ] || exit 0

# Find the repo of the first `git commit` in the command line (if any).
base="$GC_CWD"
REPO_PATH=""
segments=$(gc_segments)

while IFS= read -r seg; do
  [ -n "$seg" ] || continue

  cdt=$(gc_cd_target "$seg")
  if [ -n "$cdt" ]; then
    base=$(gc_resolve "$base" "$cdt")
    continue
  fi

  if gc_matches_subcommand "$seg" "commit"; then
    REPO_PATH=$(gc_repo_for "$seg" "$base")
    break
  fi
done <<GC_SEGMENTS
$segments
GC_SEGMENTS

# Not a commit -- nothing to gate.
[ -n "$REPO_PATH" ] || exit 0

# Read test command from PROJECT_CONTEXT.md. Tolerates: leading "- " / "* " list
# markers, the "**Test Command**:" label style (java/python variants), and
# surrounding backticks — several variants write commands as `cmd`.
TEST_CMD=$(grep -E '^[-*[:space:]]*\*\*Test( Command)?\*\*:' "$REPO_PATH/PROJECT_CONTEXT.md" 2>/dev/null | sed 's/.*\*\*Test\( Command\)\?\*\*:[[:space:]]*//;s/[[:space:]]*$//;s/^`//;s/`$//' | head -1)

# v2.1.1: projects that declare only a **Gate** command (the gate runs the tests
# plus format/lint) used to make this hook a silent no-op. Fall back to Gate.
if [ -z "$TEST_CMD" ]; then
  TEST_CMD=$(grep -E '^[-*[:space:]]*\*\*Gate( Command)?\*\*:' "$REPO_PATH/PROJECT_CONTEXT.md" 2>/dev/null | sed 's/.*\*\*Gate\( Command\)\?\*\*:[[:space:]]*//;s/[[:space:]]*$//;s/^`//;s/`$//' | head -1)
fi

# Nothing to run. Say so — a silent pass reads exactly like a green test run.
if [ -z "$TEST_CMD" ]; then
  echo "WARN: pre-commit-test: no Test/Gate command in PROJECT_CONTEXT.md — nothing verified" >&2
  exit 0
fi

# No-op: placeholder not yet filled in
case "$TEST_CMD" in
  *\{\{*\}\}*) exit 0 ;;
esac

echo "PRE-COMMIT: Running '$TEST_CMD'..." >&2
cd "$REPO_PATH" || exit 1

# Capture rather than discard: with the Gate fallback $TEST_CMD may be a whole
# gate, and "it failed" with no output leaves nothing to act on. Bounded to the
# last 20 lines so a chatty gate cannot flood the transcript.
OUT=$(mktemp 2>/dev/null || echo "$REPO_PATH/.pre-commit-test.out")
if eval "$TEST_CMD" > "$OUT" 2>&1; then
  rm -f "$OUT"
  echo "PRE-COMMIT: '$TEST_CMD' passed." >&2
  exit 0
else
  echo "BLOCKED: '$TEST_CMD' failed — re-run it and fix the failures before committing." >&2
  echo "--- last 20 lines ---" >&2
  tail -20 "$OUT" >&2
  rm -f "$OUT"
  exit 2
fi
