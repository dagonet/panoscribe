#!/usr/bin/env bash
# hooks/lib/git-cmd.sh
#
# Shared command parsing for the v2.0 git-native PreToolUse gates
# (pre-commit-test.sh, no-push-main.sh, gate-before-merge.sh).
#
# v1.x keyed those gates on MCP tool names because a blanket hook banned Bash git
# outright. v2.0 allows the native git/gh CLI, so the gates parse
# tool_input.command instead.
#
# Design notes:
#   - Matching is UNANCHORED inside each segment and quotes are stripped, so
#     wrapper payloads (bash -c "...", pwsh -Command "...") are covered. A false
#     positive (echo "git push origin main") is accepted: these gates fail closed.
#   - `<cwd>/.claude/git-guard-off` is the escape hatch for all three gates.
#   - v2.2.0: the payload is read through hooks/lib/json.sh (node, python3 or
#     jq). With NO parser on PATH the gates fail CLOSED — see gc_read_stdin.
#   - v2.2.1: three more ways a gate could not determine the answer, all of
#     which used to resolve to "allow" and now resolve to "refuse":
#     an unparseable payload (gc_read_stdin), a parser that is present but
#     broken (json.sh's json_probe_ok), and an unreplaced `{{...}}`
#     config value (gc_is_placeholder).
#
# WHY THESE GATES SCAN THE WHOLE STRING, and why enforce-delegation.sh does the
# opposite: these three are fail-CLOSED security gates, so an unanchored match
# is correct — `bash -c "git push origin main"` must not evade them, and a false
# positive on `echo "git push origin main"` costs one retry. enforce-delegation
# is fail-OPEN workflow policy, where a false DENY costs real work and no safety
# argument justifies it, so ITS patterns are anchored to command position. Do
# not "fix" these three the same way; the polarity is the whole difference.
#
# Source it from a hook:  . "$(dirname "$0")/lib/git-cmd.sh"

# Fail CLOSED when the JSON reader is missing: without it GC_CMD would be empty
# and every gate would allow every command.
gc_json_lib="$(dirname "${BASH_SOURCE[0]:-$0}")/json.sh"
if [ ! -f "$gc_json_lib" ]; then
  echo "BLOCKED: $gc_json_lib missing — run /sync-template step 6b (hooks/lib/json.sh)" >&2
  exit 2
fi
. "$gc_json_lib"

GC_JSON=""
GC_TOOL=""
GC_CWD=""
GC_CMD=""

# Word-boundary-safe prefix for a git invocation, allowing `-C <path>` and any
# number of `-c <key>=<value>` options between `git` and the subcommand.
GC_GIT_PRE='\bgit\b([[:space:]]+-C[[:space:]]+[^[:space:]]+)?([[:space:]]+-c[[:space:]]+[^[:space:]]+)*'

# Reads the hook payload from stdin and populates GC_TOOL / GC_CWD / GC_CMD.
#
# With no JSON parser on PATH the gates cannot see the command at all, so they
# fail CLOSED (exit 2) rather than wave every push and merge through. The
# documented escape hatch still wins — but the payload cwd is unreadable then,
# so it is looked for under the process cwd, which is the project directory
# Claude Code runs hooks in.
gc_read_stdin() {
  GC_JSON=$(cat)
  if ! json_have; then
    GC_CWD=$(pwd)
    GC_TOOL=""
    GC_CMD=""
    gc_guard_off && return 0
    echo "BLOCKED: no JSON parser (node, python3 or jq) on PATH — the git gates cannot inspect the command. Install one, or create <cwd>/.claude/git-guard-off to opt out." >&2
    exit 2
  fi
  # v2.2.1: a payload that does not PARSE is not a payload with no command in
  # it. json_get returns "" for both, and the gates read "" as "nothing to
  # inspect, allow" — so malformed JSON, a truncated payload and empty stdin all
  # exited 0 in silence. The parser is present and working here; the INPUT is
  # the problem, so the message is deliberately distinct from the no-parser one:
  # from outside, the two used to be indistinguishable, which is what made the
  # first report of this read as a false alarm.
  if ! json_valid "$GC_JSON"; then
    GC_CWD=$(pwd)
    GC_TOOL=""
    GC_CMD=""
    gc_guard_off && return 0
    echo "BLOCKED: hook payload did not parse — the git gates cannot inspect the command. Create <cwd>/.claude/git-guard-off to opt out." >&2
    exit 2
  fi
  GC_TOOL=$(json_get "$GC_JSON" tool_name)
  GC_CWD=$(json_get "$GC_JSON" cwd)
  if [ -z "$GC_CWD" ] || [ ! -d "$GC_CWD" ]; then
    GC_CWD=$(pwd)
  fi
  case "$GC_TOOL" in
    Bash|PowerShell)
      # ACCEPTED AND DOCUMENTED, not fixed: json_get prints "" for a
      # `tool_input.command` that is an object or an array, which is
      # indistinguishable here from the key being absent — and an absent key IS
      # a legitimate allow (a Bash payload carrying no command must not block
      # every Bash call; fixture: "Bash payload with no command"). Telling the
      # two apart needs a "key present but non-scalar" probe that json.sh does
      # not have, and the case is not reachable from Claude Code, which always
      # sends a string. Revisit if a real payload ever shows otherwise.
      GC_CMD=$(json_get "$GC_JSON" tool_input.command)
      ;;
    *)
      GC_CMD=""
      ;;
  esac
  GC_CMD=$(gc_protect_c_paths "$GC_CMD")
}

# gc_protect_c_paths <command> -- make quoted `-C` paths survive quote stripping.
#
# gc_segments deletes quote characters, so `git -C "C:/a b" push` would become
# `git -C C:/a b push`: the strict `git -C <token>` shape stops matching AND
# gc_git_c would yield the truncated "C:/a", which gc_resolve rejects, silently
# falling back to the payload cwd -- so the implicit branch check would then
# evaluate the WRONG repo. Spaces inside a quoted -C argument are replaced with
# \001 here (before any stripping) and decoded again in gc_git_c.
#
# v2.2.0: pure sed, so it no longer needs node. Each pass replaces one blank
# inside a quoted `-C` argument; the loop runs until the string stops changing.
# The quotes themselves are left in place — gc_segments strips them anyway.
GC_SOH=$(printf '\001')
gc_protect_c_paths() {
  [ -n "$1" ] || { printf '%s' ""; return 0; }
  gcs=$1
  while :; do
    gcn=$(printf '%s' "$gcs" | sed \
      -e "s/\(-C[[:space:]]\{1,\}\"[^\"]*\)[[:space:]]\([^\"]*\"\)/\1${GC_SOH}\2/" \
      -e "s/\(-C[[:space:]]\{1,\}'[^']*\)[[:space:]]\([^']*'\)/\1${GC_SOH}\2/")
    [ "$gcn" = "$gcs" ] && break
    gcs=$gcn
  done
  printf '%s' "$gcs"
}

# True when the repo has opted out of the git gates.
gc_guard_off() {
  [ -f "$GC_CWD/.claude/git-guard-off" ]
}

# Splits GC_CMD into segments on && || ; | and newlines, with quote characters
# removed so quoted wrapper payloads become plain text in the same segment.
gc_segments() {
  printf '%s\n' "$GC_CMD" | tr -d "\"'" | tr '|;' '\n\n' | sed 's/&&/\n/g'
}

# Prints the `cd <target>` argument of a segment, if the segment is a bare cd.
gc_cd_target() {
  printf '%s\n' "$1" | sed -n 's/^[[:space:]]*cd[[:space:]]\+\([^[:space:]]\+\)[[:space:]]*$/\1/p' | head -1
}

# Prints the `git -C <path>` argument of a segment, if present.
# Decodes the \001 placeholders written by gc_protect_c_paths back to spaces.
gc_git_c() {
  printf '%s\n' "$1" | sed -n 's/.*\bgit[[:space:]]\+-C[[:space:]]\+\([^[:space:]]\+\).*/\1/p' | head -1 | tr '\001' ' '
}

# gc_resolve <base> <path> -- absolute path, or the base when <path> is not a dir.
gc_resolve() {
  case "$2" in
    /*|[A-Za-z]:[/\\]*) [ -d "$2" ] && printf '%s\n' "$2" || printf '%s\n' "$1" ;;
    *)                  [ -d "$1/$2" ] && printf '%s\n' "$1/$2" || printf '%s\n' "$1" ;;
  esac
}

# gc_repo_for <segment> <base> -- the repo a segment operates on.
gc_repo_for() {
  gcp=$(gc_git_c "$1")
  if [ -n "$gcp" ]; then
    gc_resolve "$2" "$gcp"
  else
    printf '%s\n' "$2"
  fi
}

# gc_current_branch <repo>
gc_current_branch() {
  git -C "$1" branch --show-current 2>/dev/null
}

# gc_is_placeholder <value> -- true for an unreplaced `{{...}}`.
#
# GENERAL PRINCIPLE, and the reason this is a shared helper rather than one
# `case` arm: AN UNREPLACED PLACEHOLDER MUST NEVER WIDEN ACCESS. A hook reading
# a PROJECT_CONTEXT.md value that is still `{{...}}` has not been configured —
# it must behave exactly as if the line were absent, never treat the literal as
# data. v2.2.0 shipped the opposite for the protected set and silently
# unprotected trunk in every consumer that accepted the template.
# SUBSTRING, not whole-string: `{{DEFAULT_BRANCH}} develop` is a half-filled
# value, and a whole-string match read it as TWO literal branch names — the
# unsafe direction, since neither matches a real branch. Falling back to the
# default costs a `develop` repo one edit; treating the placeholder as data
# costs it its protection. pre-commit-test.sh has used the substring form for
# the same job since v2.1.3.
gc_is_placeholder() {
  case "$1" in
    *'{{'*'}}'*) return 0 ;;
    *)           return 1 ;;
  esac
}

# gc_protected_branches <repo> -- the branch names the git gates protect.
#
# Optional `**Protected branches**:` line in the repo's PROJECT_CONTEXT.md,
# read with the same tolerant grep as `**Gate**:` (leading list marker,
# surrounding backticks). Names are space- or comma-separated.
#   absent              -> "main master" (the pre-v2.2.0 hardcoded default)
#   `{{DEFAULT_BRANCH}}` -> "main master" — as if absent (v2.2.1, see above)
#   empty value         -> "main master", with one WARN: an empty value is a
#                          typo or a truncated sync, not a decision. v2.2.0
#                          treated it as an opt-out, which is a silent unprotect.
#   `none`              -> "" — the ONE deliberate way to protect nothing.
#                          Branch rules only: `gh pr merge` stays gated, because
#                          a PR merge is a merge whatever branch it runs on.
gc_protected_branches() {
  gcpb_top=$(git -C "$1" rev-parse --show-toplevel 2>/dev/null)
  [ -n "$gcpb_top" ] || { printf '%s' "main master"; return 0; }
  gcpb_line=$(grep -E '^[-*[:space:]]*\*\*Protected [Bb]ranches\*\*:' "$gcpb_top/PROJECT_CONTEXT.md" 2>/dev/null | head -1)
  [ -n "$gcpb_line" ] || { printf '%s' "main master"; return 0; }
  gcpb=$(printf '%s' "$gcpb_line" \
    | sed 's/.*\*\*Protected [Bb]ranches\*\*:[[:space:]]*//;s/[[:space:]]*$//;s/^`//;s/`$//' \
    | tr ',' ' ' | tr -s '[:space:]' ' ' | sed 's/^ //;s/ $//')
  if gc_is_placeholder "$gcpb"; then
    # WARN, for the same reason the empty arm does — more so. An empty value is
    # visibly empty; an unreplaced placeholder READS as configured, so this is
    # precisely the case a consumer does not know they are in. Silence here was
    # backwards.
    json_warn_once "protected-branches" "$(json_session "$GC_JSON")" \
      "WARN: **Protected branches**: in $gcpb_top/PROJECT_CONTEXT.md is still an unfilled placeholder ($gcpb) — falling back to 'main master'. If your trunk is not main/master, it is NOT protected until you set a real name."
    printf '%s' "main master"
    return 0
  fi
  case "$(printf '%s' "$gcpb" | tr 'A-Z' 'a-z')" in
    none) printf '%s' "" ;;
    "")
      # Warn ONCE: this function is called several times per gate run (the
      # block message, gc_on_main, gc_protected_alt), so a bare echo would
      # print the same line four times for one push.
      json_warn_once "protected-branches" "$(json_session "$GC_JSON")" \
        "WARN: **Protected branches**: is empty in $gcpb_top/PROJECT_CONTEXT.md — falling back to 'main master'. Use 'none' to protect nothing deliberately."
      printf '%s' "main master"
      ;;
    *) printf '%s' "$gcpb" ;;
  esac
}

# gc_protected_alt <repo> -- the protected branches as a grep -E alternation,
# or "" when nothing is protected.
gc_protected_alt() {
  printf '%s' "$(gc_protected_branches "$1")" | tr ' ' '|'
}

# gc_on_main <repo> -- the checkout sits on a protected branch.
gc_on_main() {
  b=$(gc_current_branch "$1")
  [ -n "$b" ] || return 1
  for gcpbb in $(gc_protected_branches "$1"); do
    [ "$b" = "$gcpbb" ] && return 0
  done
  return 1
}

# gc_matches_subcommand <segment> <subcommand>
#
# The strict form requires `-C <path>` to be a single space-free token. A quoted
# path with a space (`git -C "C:/a b" push …`) loses its quotes in gc_segments
# and no longer matches, which would silently bypass every gate — so a segment
# that carries a `git -C` is re-tested against a looser shape and fails closed.
gc_matches_subcommand() {
  printf '%s\n' "$1" | grep -qE "${GC_GIT_PRE}[[:space:]]+$2([[:space:]]|\$)" && return 0
  printf '%s\n' "$1" | grep -qE '\bgit\b[[:space:]]+-C\b' || return 1
  printf '%s\n' "$1" | grep -qE "\bgit\b.*\b$2\b"
}

# gc_push_args <segment> -- everything after the `push` subcommand ("" if none).
gc_push_args() {
  gcpa=$(printf '%s\n' "$1" | sed -n 's/.*\bgit\([[:space:]]\+-C[[:space:]]\+[^[:space:]]\+\)\?\([[:space:]]\+-c[[:space:]]\+[^[:space:]]\+\)*[[:space:]]\+push\([[:space:]]\|$\)/\3/p' | head -1)
  # Same quoted-`-C`-with-a-space case as gc_matches_subcommand: fall back to
  # "everything after push" so the destination ref is still inspected.
  if [ -z "$gcpa" ] && printf '%s\n' "$1" | grep -qE '\bgit\b.*\bpush\b'; then
    gcpa=$(printf '%s\n' "$1" | sed -n 's/.*\bpush\b//p' | head -1)
  fi
  printf '%s\n' "$gcpa"
}

# gc_targets_main_ref <push-args> <repo> -- a destination that includes a
# protected branch. `--mirror` and `--all` push every local branch, so they
# carry the protected ones even when the checkout is on a feature branch and no
# ref is named. With nothing protected (`**Protected branches**: none`) every
# destination is fine.
gc_targets_main_ref() {
  gcta=$(gc_protected_alt "$2")
  [ -n "$gcta" ] || return 1
  printf '%s\n' "$1" | grep -qE '(^|[[:space:]])--(mirror|all)([[:space:]]|=|$)' && return 0
  printf '%s\n' "$1" | grep -qE "(^|[[:space:]])(refs/heads/)?($gcta)([[:space:]]|\$)" && return 0
  printf '%s\n' "$1" | grep -qE ":[[:space:]]*(refs/heads/)?($gcta)([[:space:]]|\$)"
}

# gc_has_refspec <push-args> -- true when a destination ref is named explicitly
# (i.e. more than just the remote survives after dropping flags).
#
# A bare `HEAD` (`git push origin HEAD`) names no branch: it resolves to the
# current checkout, so it must fall through to the current-branch check rather
# than count as an explicit refspec. `HEAD:main` is a real refspec and still
# counts (and is caught by gc_targets_main_ref anyway).
gc_has_refspec() {
  n=$(printf '%s\n' "$1" | tr ' \t' '\n\n' | grep -E '^[^-][^[:space:]]*$' | grep -cvx 'HEAD')
  [ "${n:-0}" -ge 2 ]
}

# gc_push_skips_branch_check <push-args> -- pushes that are not branch pushes,
# so the implicit "current branch is main" rule must not fire.
gc_push_skips_branch_check() {
  printf '%s\n' "$1" | grep -qE '(^|[[:space:]])--(tags|delete)([[:space:]]|=|$)'
}
