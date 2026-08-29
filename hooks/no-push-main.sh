#!/usr/bin/env bash
# PreToolUse hook: block push to main/master
# Matcher: Bash|PowerShell
#
# Prevents direct pushes to main/master branches. Forces feature branch + PR.
#
# v2.0: the native git CLI is allowed again, so this gate parses
# tool_input.command instead of keying on the retired mcp__git-tools__git_push
# tool name. Escape hatch: <cwd>/.claude/git-guard-off.

. "$(dirname "$0")/lib/git-cmd.sh"

gc_read_stdin
gc_guard_off && exit 0
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
