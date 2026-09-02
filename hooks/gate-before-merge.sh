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
# v2.4.0 (A6): a merge initiated while the checkout is on a PROTECTED branch is
# refused outright, before the artifact is even read — on that topology the
# merge lands the other side's content, so no comparison against this
# checkout's HEAD can say anything about it. See the block above that check.
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
# CONSEQUENCE, by construction, on a repo that commits straight to trunk: the
# artifact is STALE most of the time. Any commit moves HEAD and changes the
# tree — a docs-only commit included, because docs are tracked content — so both
# keys miss. That is correct. The artifact blesses one specific tree, that tree
# genuinely changed, and the gate cannot know which changes are harmless. The
# tree key was added in v2.1.5 to fix a different problem (the artifact's `sha`
# being the PARENT commit when an agent chains `git add … && git commit`), not
# to make an artifact outlive later commits. It costs nothing in practice: this
# gate only fires on merge-shaped commands, so staleness is invisible until an
# actual merge — at which point re-running the gate is exactly the requirement.
# Do NOT add a path-filtered or docs-excluding tree key to "fix" it: deciding
# which file changes are safe to skip is the judgement a gate must not make.
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

# v2.2.6 round 2 -- THE 14th FAIL-OPEN, third instance. Checked BEFORE the tool
# case below, because that case's `*)` arm is exactly the door an unreadable
# tool_name walks through. See gc_cmd_unreadable in hooks/lib/git-cmd.sh.
if gc_cmd_unreadable; then
  echo "BLOCKED: gate-before-merge: the payload carries a command this gate could not read, so it cannot rule out a merge -- refusing. Re-run the command. (If it repeats: create '.claude/git-guard-off' under this cwd, make the one fix, then delete it.)" >&2
  exit 2
fi

# Branch on the TOOL, never on the parsed string. This hook is registered on
# Bash|PowerShell, so if node is missing or the JSON does not parse, GC_CMD is
# empty -- and treating that as "not a Bash call" would fall through to the
# artifact check and block every Bash call in the session. A Bash payload with
# NO COMMAND KEY is a Bash payload with no merge in it; only the GitHub merge
# tools are gated unconditionally.
#
# v2.2.6 round 2 narrows what "we cannot read it" means here: a payload that
# HAS a `command` key we could not read no longer reaches this case at all --
# it was refused above. What still falls open below is the genuinely absent
# key and the genuinely unknown tool, which are not cannot-determine states.
case "$GC_TOOL" in
  Bash|PowerShell) ;;   # gate only merge-shaped commands (scanned below)
  mcp__*)          ;;   # the GitHub merge tools: always gated
  *) exit 0 ;;          # unknown tool, or a payload with no command key at all
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

# Read Gate command from PROJECT_CONTEXT.md through GC_KEY_PRE (see the header
# note on that constant in hooks/lib/git-cmd.sh: a leading UTF-8 BOM otherwise
# hides a key that sits on line 1).
# Tolerates: leading "- " / "* " list
# markers, the "**Gate Command**:" label style (java/python variants), and
# surrounding backticks — several variants write commands as `cmd`.
GATE_CMD=$(grep -E "${GC_KEY_PRE}\*\*Gate( Command)?\*\*:" "$REPO_TOP/PROJECT_CONTEXT.md" 2>/dev/null | sed 's/.*\*\*Gate\( Command\)\?\*\*:[[:space:]]*//;s/[[:space:]]*$//;s/^`//;s/`$//' | head -1)

# No-op: no PROJECT_CONTEXT.md or no Gate command configured
if [ -z "$GATE_CMD" ]; then
  exit 0
fi

# No-op: placeholder not yet filled in
case "$GATE_CMD" in
  *\{\{*\}\}*) exit 0 ;;
esac

# v2.4.0 (A6, found live merging PR #75) -- THE ARTIFACT CHECK BELOW COMPARES
# THE ARTIFACT TO **HEAD**, AND HEAD IS THE MERGE CONTENT ONLY ON SOME
# TOPOLOGIES. A controller sitting on `main` merges the PR BRANCH's tip, not
# HEAD; so "re-run the gate on the current head" gates content that is already
# merged, writes a green artifact, and then permits a merge of entirely
# different content -- a correct guard whose own remediation manufactures the
# false receipt. A flow of branch -> commit -> gate -> push -> PR -> merge has
# the controller ON the branch, where `artifact.sha == branch tip == merged
# content` and the same check is sound. Same hook, opposite validity.
#
# The split is purely local -- no API, no network, and both helpers are already
# in this hook: if the merge is initiated while HEAD is on a PROTECTED branch,
# the thing being merged is BY CONSTRUCTION not HEAD, so the comparison below
# verifies nothing. Say so and refuse; on a feature branch, fall through to the
# comparison, which is meaningful there.
#
# DELIBERATELY NOT UNCONDITIONALLY FAIL-CLOSED. Target resolvability varies by
# path: `git merge <ref>` resolves locally, the MCP merge tools carry
# pullNumber/owner/repo (identified, but needing an API call), and a bare
# `gh pr merge` names no target at all. Refusing on every unresolvable path
# hard-blocks every PR merge for anyone offline -- the "unconditional
# fail-closed blocks everything" hazard from the GC_CMD round. The
# protected-branch detector is what makes cannot-determine-must-refuse
# affordable here: it refuses exactly the case where the evidence is known to
# be irrelevant, and stays out of the way otherwise.
if gc_on_main "$CWD"; then
  {
    echo "BLOCKED: this merge was initiated while the checkout is on a protected branch ($(gc_current_branch "$CWD"))."
    echo "A merge run from a protected branch lands the OTHER side's content, not this checkout's HEAD — so comparing the gate artifact to HEAD verifies nothing, and re-running the gate here would only bless content that is already merged."
    echo "Gate the content that is actually being merged: check out the merge target (the PR branch head) and run 'bash hooks/run-gate.sh' there, or gate on the branch before opening the PR, and merge from that checkout."
    echo "(If this is a false positive: create '.claude/git-guard-off' under this cwd, make the one merge, then delete it.)"
  } >&2
  exit 2
fi

ARTIFACT="$REPO_TOP/.gate/last-pass.json"

if [ ! -f "$ARTIFACT" ]; then
  echo "BLOCKED: No gate artifact found. Run 'bash hooks/run-gate.sh' on the PR branch head (green gate writes .gate/last-pass.json), then merge." >&2
  exit 2
fi

# v2.4.0 (A6, consumer report): READ THE ARTIFACT AS JSON, NOT AS ONE SPELLING
# OF IT. Until now both reads were hardcoded to `"sha":"` — exactly the bytes
# our own run-gate.sh printf emits, with no space after the colon. A consumer
# whose project-owned gate writes the same fields pretty-printed
# (`{"sha": "…"}`, entirely valid JSON) got an EMPTY ARTIFACT_SHA and was
# blocked on every merge with `artifact sha: none` — a gate that passed,
# reported as stale, for a reason that has nothing to do with staleness. They
# carried a local widening for releases.
#
# REPLACING run-gate.sh WHOLESALE IS A SUPPORTED CONFIGURATION: the contract
# between the two halves is the `**Gate**` field plus the artifact FORMAT, not
# the script. So the reader must accept any valid JSON spelling of that format,
# not merely the one our writer happens to produce.
#
# THE `sed` IS WIDENED IN LOCKSTEP WITH THE `grep`, deliberately. Accepting
# `"sha": "` in the grep while stripping only `"sha":"` in the sed leaves a
# LEADING SPACE on the value — a sha that matches nothing, i.e. the same silent
# mismatch moved one step later and made harder to see. Both use the same
# tolerant pattern for that reason; do not "simplify" one of them.
ARTIFACT_SHA=$(grep -o '"sha"[[:space:]]*:[[:space:]]*"[^"]*"' "$ARTIFACT" | head -1 | sed 's/.*"sha"[[:space:]]*:[[:space:]]*"//;s/"$//')
ARTIFACT_TREE=$(grep -o '"tree"[[:space:]]*:[[:space:]]*"[^"]*"' "$ARTIFACT" | head -1 | sed 's/.*"tree"[[:space:]]*:[[:space:]]*"//;s/"$//')
HEAD_SHA=$(git -C "$CWD" rev-parse HEAD 2>/dev/null)
HEAD_TREE=$(git -C "$CWD" rev-parse 'HEAD^{tree}' 2>/dev/null)

# v2.1.3 fix round 1 (Critical 2 / penumbra #2c): accept either a sha match
# (the classic case: gate ran on this exact commit) or a tree match (the
# pre-commit-test.sh -> run-gate.sh chain: the gate ran against the INDEX
# just before `git commit`, so its "sha" is the PARENT commit but its "tree"
# is the tree the new commit just got). Both still gated by the freshness
# window below.
if [ -z "$ARTIFACT_SHA" ] || { [ "$ARTIFACT_SHA" != "$HEAD_SHA" ] && { [ -z "$ARTIFACT_TREE" ] || [ "$ARTIFACT_TREE" != "$HEAD_TREE" ]; }; }; then
  # v2.4.0 (A6, defect 1): the MESSAGE had drifted to the weaker half of the
  # check. The artifact matches by sha OR by tree, and the tree half is the one
  # that survives a squash -- a consumer measured a squash changing the sha and
  # leaving the tree byte-identical -- so a message naming only the sha sends
  # them to re-run a gate whose tree already matched. It also said "the current
  # head" without saying WHICH head, which is exactly the ambiguity that makes
  # gating `main` look like a remedy. The message is what a consumer acts on at
  # 2am; report both keys and name the head.
  {
    echo "BLOCKED: Gate artifact is stale — it matches this checkout by neither key."
    echo "  artifact sha:  ${ARTIFACT_SHA:-none}    HEAD:          $HEAD_SHA"
    echo "  artifact tree: ${ARTIFACT_TREE:-none}    HEAD^{tree}:   $HEAD_TREE"
    echo "Run 'bash hooks/run-gate.sh' on the head that is actually being MERGED — the PR branch tip, from a checkout of that branch — then merge from there. Gating some other head produces a fresh artifact that verifies nothing."
  } >&2
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
