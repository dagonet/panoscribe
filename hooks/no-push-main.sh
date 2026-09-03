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

# np_strip_redir <args> -- <args> with shell REDIRECTION tokens removed.
#
# v3.0.2: `git push origin 2>&1` on a protected branch was ALLOWED. `2>&1`
# starts with a digit, so gc_has_refspec counted two non-flag tokens, read
# "destination named", and skipped the current-branch check — a fail-open, not
# a false positive. The counting bug is inside gc_has_refspec in
# hooks/lib/git-cmd.sh; it is compensated here, at the call site, because that
# lib is covered by the ~90-minute three-parser matrix and this shape carries no
# JSON. Same reason gate-before-merge.sh carries its own copy as
# a6_strip_redir: the duplication is deliberate and small.
#
# NOT GREEDY, and that is the point: dropping everything after a `>` would turn
# `git push origin main 2>&1` into a refspec-free push and lose the explicit
# protected destination. Only a token that is ITSELF a redirection operator is
# dropped — with its target attached (`2>&1`, `>file`), or bare (`>`, `2>`)
# plus exactly the one token that follows it. The empty-token arm is first
# because `tr` emits an empty field for a double space, which would otherwise
# consume the skip and leak the redirect target back in as an operand.
np_strip_redir() {
  printf '%s\n' "$1" | tr ' \t' '\n\n' | awk '
    $0 == "" { next }
    skip == 1 { skip = 0; next }
    /^([0-9]*|&)(>>|>|<).+$/ { next }
    /^([0-9]*|&)(>>|>|<)$/ { skip = 1; next }
    { print }
  ' | tr '\n' ' '
}

# v3.0.1 (consumer report): the no-refspec path below reads the CURRENT BRANCH,
# which is ambient state this hook resolves BEFORE the command runs — so
# `git checkout main && git push` was evaluated on the feature branch and let
# through. The refspec paths are immune by construction: they key on the
# argument, never on ambient state.
# ORDER, not co-presence: only a branch change that PRECEDES the push matters,
# because only that changes where the push lands. `git push origin feature/x &&
# git checkout main` is unaffected, and must stay so.
moved=0

while IFS= read -r seg; do
  [ -n "$seg" ] || continue

  # Track `cd <dir>` so a later bare `git push` is resolved in the right repo.
  cdt=$(gc_cd_target "$seg")
  if [ -n "$cdt" ]; then
    base=$(gc_resolve "$base" "$cdt")
    continue
  fi

  # A clause that can move HEAD to another branch. `--` means "everything after
  # is a path", so `git checkout -- file` restores files without moving HEAD and
  # must not arm the refusal.
  #
  # KEYED ON THE TARGET, not on the presence of a checkout: `git checkout
  # feature/z && git push` lands nothing on a protected branch, and refusing it
  # would be a false positive on ordinary work. The target is an ARGUMENT — in
  # the payload, not ambient state — which is the whole point. Last one wins.
  # 0 = harmless, 1 = moves onto a protected branch, 2 = target unresolvable.
  if { gc_matches_subcommand "$seg" "checkout" || gc_matches_subcommand "$seg" "switch"; } &&
     ! printf '%s\n' "$seg" | grep -qE '(^|[[:space:]])--([[:space:]]|$)'; then
    mvargs=$(printf '%s\n' "$seg" | sed -n 's/.*[[:space:]]\(checkout\|switch\)\([[:space:]]\|$\)/\2/p' | head -1)
    mvtarget=$(printf '%s\n' "$mvargs" | tr ' \t' '\n\n' | grep -E '^[^-][^[:space:]]*$' | head -1)
    case "$mvtarget" in
      ''|*[!A-Za-z0-9._/-]*) moved=2 ;;
      *)
        moved=0
        for mvp in $(gc_protected_branches "$(gc_repo_for "$seg" "$base")"); do
          [ "$mvtarget" = "$mvp" ] && moved=1
        done ;;
    esac
    continue
  fi

  gc_matches_subcommand "$seg" "push" || continue

  repo=$(gc_repo_for "$seg" "$base")
  args=$(np_strip_redir "$(gc_push_args "$seg")")

  # 1. An explicit protected destination is always a block.
  if gc_targets_main_ref "$args" "$repo"; then
    echo "BLOCKED: pushing to a protected branch ($(gc_protected_branches "$repo")) is not allowed. Use a feature branch and open a PR." >&2
    exit 2
  fi

  # 2. No explicit refspec -> the push follows the current branch.
  if ! gc_has_refspec "$args" && ! gc_push_skips_branch_check "$args"; then
    if [ "$moved" != 0 ]; then
      {
        if [ "$moved" = 1 ]; then
          echo "BLOCKED: this push names no refspec, so it follows the current branch — and an earlier clause in the same command checks out '$mvtarget', which is protected. This hook runs BEFORE the command, so the branch it can read is not the branch this would push."
        else
          echo "BLOCKED: this push names no refspec, so it follows the current branch — and an earlier clause in the same command changes that branch to a target this hook cannot resolve ('${mvtarget:-<none named>}'), so which branch it pushes to cannot be determined."
        fi
        echo "Do the checkout and the push as SEPARATE calls, or name the destination: 'git push origin <branch>' keys on its argument and never consults the current branch."
        echo "(If this is a false positive: create '.claude/git-guard-off' under this cwd, make the one push, then delete it.)"
      } >&2
      exit 2
    fi
    if gc_on_main "$repo"; then
      echo "BLOCKED: pushing to a protected branch is not allowed (current branch of $repo is $(gc_current_branch "$repo")). Use a feature branch and open a PR." >&2
      exit 2
    fi
  fi
done <<GC_SEGMENTS
$segments
GC_SEGMENTS

exit 0
