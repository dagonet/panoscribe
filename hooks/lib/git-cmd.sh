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
#
# Source it from a hook:  . "$(dirname "$0")/lib/git-cmd.sh"

GC_JSON=""
GC_TOOL=""
GC_CWD=""
GC_CMD=""

# Word-boundary-safe prefix for a git invocation, allowing `-C <path>` and any
# number of `-c <key>=<value>` options between `git` and the subcommand.
GC_GIT_PRE='\bgit\b([[:space:]]+-C[[:space:]]+[^[:space:]]+)?([[:space:]]+-c[[:space:]]+[^[:space:]]+)*'

# Reads the hook payload from stdin and populates GC_TOOL / GC_CWD / GC_CMD.
gc_read_stdin() {
  GC_JSON=$(cat)
  GC_TOOL=$(node -e "const j=JSON.parse(process.argv[1]);console.log(j.tool_name||'')" "$GC_JSON" 2>/dev/null)
  GC_CWD=$(node -e "const j=JSON.parse(process.argv[1]);console.log(j.cwd||'')" "$GC_JSON" 2>/dev/null)
  if [ -z "$GC_CWD" ] || [ ! -d "$GC_CWD" ]; then
    GC_CWD=$(pwd)
  fi
  case "$GC_TOOL" in
    Bash|PowerShell)
      GC_CMD=$(node -e "const j=JSON.parse(process.argv[1]);console.log((j.tool_input&&j.tool_input.command)||'')" "$GC_JSON" 2>/dev/null)
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
gc_protect_c_paths() {
  [ -n "$1" ] || { printf '%s' ""; return 0; }
  node -e 'const s=process.argv[1];process.stdout.write(s.replace(/-C[ \t]+("([^"]*)"|\x27([^\x27]*)\x27)/g,(m,q,dq,sq)=>"-C "+(dq===undefined?sq:dq).replace(/[ \t]/g,"\u0001")))' "$1" 2>/dev/null \
    || printf '%s' "$1"
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

# gc_on_main <repo>
gc_on_main() {
  b=$(gc_current_branch "$1")
  [ "$b" = "main" ] || [ "$b" = "master" ]
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

# gc_targets_main_ref <push-args> -- a destination that includes main/master.
# `--mirror` and `--all` push every local branch, so they carry main even when
# the checkout is on a feature branch and no ref is named.
gc_targets_main_ref() {
  printf '%s\n' "$1" | grep -qE '(^|[[:space:]])--(mirror|all)([[:space:]]|=|$)' && return 0
  printf '%s\n' "$1" | grep -qE '(^|[[:space:]])(refs/heads/)?(main|master)([[:space:]]|$)' && return 0
  printf '%s\n' "$1" | grep -qE ':[[:space:]]*(refs/heads/)?(main|master)([[:space:]]|$)'
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
