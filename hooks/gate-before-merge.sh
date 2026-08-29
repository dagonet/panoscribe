#!/usr/bin/env bash
# PreToolUse hook: block PR merge/auto-merge without a fresh gate artifact
# Matcher: Bash|PowerShell|mcp__MCP_DOCKER__merge_pull_request|mcp__github-tools__github_pr_auto_merge
#
# v2.0: `gh pr merge`, a `git merge` while on main/master, and a push that
# targets main/master (fast-forward merge by push) are gated too, because the
# native git/gh CLI is allowed again. The MCP branch is unchanged -- those are
# GitHub tools, not the retired git-tools server. Escape hatch:
# <cwd>/.claude/git-guard-off.
#
# Requires .gate/last-pass.json (written by hooks/run-gate.sh) at the repo
# toplevel of the merging session's cwd — worktree-aware, since developer
# agents self-merge from their worktrees. Blocks (exit 2) unless:
#   - the artifact exists,
#   - its "sha" equals the current HEAD of that checkout OR its "tree" equals
#     that checkout's HEAD^{tree} — as of v2.1.5 "tree" is the WORKING tree at
#     gate time, so a commit of exactly what was gated (chained
#     `git add … && git commit`, or `git commit -a`) matches by tree even
#     though the artifact's sha is the parent commit's, and
#   - the artifact file is younger than 60 minutes (mtime).
#
# No-op (exit 0) when PROJECT_CONTEXT.md has no Gate command or the field is
# still a {{...}} placeholder — same graceful degradation as pre-commit-test.sh.
#
# v2.2.0: "main/master" above means the protected set, which an optional
# PROJECT_CONTEXT.md line configures:
#
#   - **Protected branches**: develop release
#
# Default (field absent) is `main master`; `none` protects nothing — a
# `gh pr merge` is still gated, since that is a merge whatever the branch is.
# The payload is parsed through hooks/lib/json.sh (node, python3 or jq); with
# none of the three on PATH this gate fails CLOSED.

# Fail CLOSED when the sourced lib is missing: without it every gc_* helper is
# undefined, GC_TOOL stays empty, and this gate would exit 0 on every merge.
lib="$(dirname "$0")/lib/git-cmd.sh"
[ -f "$lib" ] || { echo "BLOCKED: $lib missing — run /sync-template step 6b (hooks/lib/git-cmd.sh)" >&2; exit 2; }
. "$lib"

gc_read_stdin
gc_guard_off && exit 0

CWD="$GC_CWD"

# Branch on the TOOL, never on the parsed string. This hook is registered on
# Bash|PowerShell, so if node is missing, the JSON does not parse, or the payload
# carries no tool_input.command, GC_CMD is empty -- and treating that as "not a
# Bash call" would fall through to the artifact check and block every Bash call
# in the session. A Bash payload we cannot read is a Bash payload with no merge
# in it; only the GitHub merge tools are gated unconditionally.
case "$GC_TOOL" in
  Bash|PowerShell) ;;   # gate only merge-shaped commands (scanned below)
  mcp__*)          ;;   # the GitHub merge tools: always gated
  *) exit 0 ;;          # unknown or unparseable tool: fail open
esac

if [ "$GC_TOOL" = "Bash" ] || [ "$GC_TOOL" = "PowerShell" ]; then
  is_merge=0
  base="$CWD"
  segments=$(gc_segments)

  while IFS= read -r seg; do
    [ -n "$seg" ] || continue

    cdt=$(gc_cd_target "$seg")
    if [ -n "$cdt" ]; then
      base=$(gc_resolve "$base" "$cdt")
      continue
    fi

    # 1. gh pr merge (any flags)
    if printf '%s\n' "$seg" | grep -qE '\bgh[[:space:]]+pr[[:space:]]+merge\b'; then
      is_merge=1
      CWD=$(gc_repo_for "$seg" "$base")
      break
    fi

    # 2. git merge while the checkout is on a protected branch
    if gc_matches_subcommand "$seg" "merge"; then
      repo=$(gc_repo_for "$seg" "$base")
      if gc_on_main "$repo"; then
        is_merge=1
        CWD="$repo"
        break
      fi
    fi

    # 3. a push that targets a protected branch -- fast-forward merge by push
    if gc_matches_subcommand "$seg" "push"; then
      repo=$(gc_repo_for "$seg" "$base")
      args=$(gc_push_args "$seg")
      if gc_targets_main_ref "$args" "$repo"; then
        is_merge=1
        CWD="$repo"
        break
      fi
      if ! gc_has_refspec "$args" && ! gc_push_skips_branch_check "$args" && gc_on_main "$repo"; then
        is_merge=1
        CWD="$repo"
        break
      fi
    fi
  done <<GC_SEGMENTS
$segments
GC_SEGMENTS

  [ "$is_merge" = "1" ] || exit 0
fi

REPO_TOP=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_TOP" ]; then
  # Not a git checkout (nothing to gate against) — allow.
  exit 0
fi

# Read Gate command from PROJECT_CONTEXT.md. Tolerates: leading "- " / "* " list
# markers, the "**Gate Command**:" label style (java/python variants), and
# surrounding backticks — several variants write commands as `cmd`.
GATE_CMD=$(grep -E '^[-*[:space:]]*\*\*Gate( Command)?\*\*:' "$REPO_TOP/PROJECT_CONTEXT.md" 2>/dev/null | sed 's/.*\*\*Gate\( Command\)\?\*\*:[[:space:]]*//;s/[[:space:]]*$//;s/^`//;s/`$//' | head -1)

# No-op: no PROJECT_CONTEXT.md or no Gate command configured
if [ -z "$GATE_CMD" ]; then
  exit 0
fi

# No-op: placeholder not yet filled in
case "$GATE_CMD" in
  *\{\{*\}\}*) exit 0 ;;
esac

ARTIFACT="$REPO_TOP/.gate/last-pass.json"

if [ ! -f "$ARTIFACT" ]; then
  echo "BLOCKED: No gate artifact found. Run 'bash hooks/run-gate.sh' on the PR branch head (green gate writes .gate/last-pass.json), then merge." >&2
  exit 2
fi

ARTIFACT_SHA=$(grep -o '"sha":"[^"]*"' "$ARTIFACT" | head -1 | sed 's/"sha":"//;s/"$//')
ARTIFACT_TREE=$(grep -o '"tree":"[^"]*"' "$ARTIFACT" | head -1 | sed 's/"tree":"//;s/"$//')
HEAD_SHA=$(git -C "$CWD" rev-parse HEAD 2>/dev/null)
HEAD_TREE=$(git -C "$CWD" rev-parse 'HEAD^{tree}' 2>/dev/null)

# v2.1.3 fix round 1 (Critical 2 / penumbra #2c): accept either a sha match
# (the classic case: gate ran on this exact commit) or a tree match (the
# pre-commit-test.sh -> run-gate.sh chain: the gate ran against the INDEX
# just before `git commit`, so its "sha" is the PARENT commit but its "tree"
# is the tree the new commit just got). Both still gated by the freshness
# window below.
if [ -z "$ARTIFACT_SHA" ] || { [ "$ARTIFACT_SHA" != "$HEAD_SHA" ] && { [ -z "$ARTIFACT_TREE" ] || [ "$ARTIFACT_TREE" != "$HEAD_TREE" ]; }; }; then
  echo "BLOCKED: Gate artifact is stale (artifact sha: ${ARTIFACT_SHA:-none}, HEAD: $HEAD_SHA). Re-run 'bash hooks/run-gate.sh' on the current head, then merge." >&2
  exit 2
fi

# Freshness: artifact file mtime < 60 minutes (mtime avoids date-parsing portability issues)
ARTIFACT_EPOCH=$(stat -c %Y "$ARTIFACT" 2>/dev/null || stat -f %m "$ARTIFACT" 2>/dev/null || echo 0)
NOW_EPOCH=$(date +%s)
AGE=$((NOW_EPOCH - ARTIFACT_EPOCH))
if [ "$ARTIFACT_EPOCH" -eq 0 ] || [ "$AGE" -gt 3600 ]; then
  echo "BLOCKED: Gate artifact expired (${AGE}s old, max 3600s). Re-run 'bash hooks/run-gate.sh', then merge." >&2
  exit 2
fi

exit 0
