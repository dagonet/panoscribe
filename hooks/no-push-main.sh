#!/usr/bin/env bash
# PreToolUse hook: block push to main/master
# Matcher: Bash|PowerShell
#
# Prevents direct pushes to main/master branches. Forces feature branch + PR.
#
# v2.0: the native git CLI is allowed again, so this gate parses
# tool_input.command instead of keying on the retired mcp__git-tools__git_push
# tool name. Escape hatch: <cwd>/.claude/git-guard-off.

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

  # 1. An explicit main/master destination is always a block.
  if gc_targets_main_ref "$args"; then
    echo "BLOCKED: pushing to main/master is not allowed. Use a feature branch and open a PR." >&2
    exit 2
  fi

  # 2. No explicit refspec -> the push follows the current branch.
  if ! gc_has_refspec "$args" && ! gc_push_skips_branch_check "$args"; then
    if gc_on_main "$repo"; then
      echo "BLOCKED: pushing to main/master is not allowed (current branch of $repo is $(gc_current_branch "$repo")). Use a feature branch and open a PR." >&2
      exit 2
    fi
  fi
done <<GC_SEGMENTS
$segments
GC_SEGMENTS

exit 0
