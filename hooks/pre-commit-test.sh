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

. "$(dirname "$0")/lib/git-cmd.sh"

gc_read_stdin
gc_guard_off && exit 0
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

# No-op: no PROJECT_CONTEXT.md or no Test command configured
if [ -z "$TEST_CMD" ]; then
  exit 0
fi

# No-op: placeholder not yet filled in
case "$TEST_CMD" in
  *\{\{*\}\}*) exit 0 ;;
esac

echo "PRE-COMMIT: Running tests ($TEST_CMD)..." >&2
cd "$REPO_PATH" || exit 1

if eval "$TEST_CMD" > /dev/null 2>&1; then
  echo "PRE-COMMIT: All tests passed." >&2
  exit 0
else
  echo "BLOCKED: Tests failed. Fix test failures before committing." >&2
  exit 2
fi
