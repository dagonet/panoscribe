#!/usr/bin/env bash
# PreToolUse hook: block push to main/master
# Matcher: Bash|PowerShell
#
# Prevents direct pushes to main/master branches. Forces feature branch + PR.
#
# v2.0: the native git CLI is allowed again, so this gate parses
# tool_input.command instead of keying on the retired mcp__git-tools__git_push
# tool name. Escape hatch: <cwd>/.claude/git-guard-off.
#
# v2.2.0: the protected set is configurable. An optional PROJECT_CONTEXT.md line
#
#   - **Protected branches**: develop release
#
# replaces the default `main master`; `none` (or an empty value) protects
# nothing. The payload is parsed through hooks/lib/json.sh (node, python3 or
# jq) — with none of the three on PATH this gate fails CLOSED.

# Fail CLOSED when the sourced lib is missing: without it every gc_* helper is
# undefined, GC_CMD stays empty, and this gate would exit 0 on every push.
lib="$(dirname "$0")/lib/git-cmd.sh"
[ -f "$lib" ] || { echo "BLOCKED: $lib missing — run /sync-template step 6b (hooks/lib/git-cmd.sh)" >&2; exit 2; }
. "$lib"

gc_read_stdin
gc_guard_off && exit 0

# Fail CLOSED on a pre-v2 settings.json: it registers this gate on the retired
# git-tools MCP tools, whose payloads carry no tool_input.command — the v2 gate
# would find nothing to parse and allow the push.
case "$GC_TOOL" in
  mcp__git-tools__git_push|mcp__git-tools__git_commit)
    echo "BLOCKED: settings.json predates this hook (MCP matcher) — restart the session after /sync-template" >&2
    exit 2 ;;
esac

# v2.2.6 round 2 — THE 14th FAIL-OPEN, same shape as pre-commit-test.sh: a bare
# `[ -n "$GC_CMD" ] || exit 0` allowed an invocation whose command arrived empty
# on a payload that parsed. See gc_cmd_unreadable in hooks/lib/git-cmd.sh for the
# state split and for why the refusal is conditional, not an outright inversion.
if gc_cmd_unreadable; then
  echo "BLOCKED: no-push-main: the payload carries a command this gate could not read, so it cannot rule out a push to a protected branch — refusing. Re-run the push. (If it repeats: create '.claude/git-guard-off' under this cwd, make the one fix, then delete it.)" >&2
  exit 2
fi

[ -n "$GC_CMD" ] || exit 0

base="$GC_CWD"
segments=$(gc_segments)

while IFS= read -r seg; do
  [ -n "$seg" ] || continue

  # Track `cd <dir>` so a later bare `git push` is resolved in the right repo.
  cdt=$(gc_cd_target "$seg")
  if [ -n "$cdt" ]; then
    base=$(gc_resolve "$base" "$cdt")
    continue
  fi

  gc_matches_subcommand "$seg" "push" || continue

  repo=$(gc_repo_for "$seg" "$base")
  args=$(gc_push_args "$seg")

  # 1. An explicit protected destination is always a block.
  if gc_targets_main_ref "$args" "$repo"; then
    echo "BLOCKED: pushing to a protected branch ($(gc_protected_branches "$repo")) is not allowed. Use a feature branch and open a PR." >&2
    exit 2
  fi

  # 2. No explicit refspec -> the push follows the current branch.
  if ! gc_has_refspec "$args" && ! gc_push_skips_branch_check "$args"; then
    if gc_on_main "$repo"; then
      echo "BLOCKED: pushing to a protected branch is not allowed (current branch of $repo is $(gc_current_branch "$repo")). Use a feature branch and open a PR." >&2
      exit 2
    fi
  fi
done <<GC_SEGMENTS
$segments
GC_SEGMENTS

exit 0
