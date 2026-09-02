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
# EXIT-CODE CONVENTIONS for the gates and the gate runner (v2.2.5). All four
# meanings in one place, because the fourth only makes sense against the others:
#
#     0    pass / not applicable — the tool call proceeds. NOTE it is OVERLOADED
#          at the success end and deliberately so: run-gate.sh also exits 0 when
#          the gate DID NOT RUN (no Gate field, no Gate command matched, or the
#          value is still a {{...}} placeholder), and pre-commit-test.sh cannot
#          tell those from "ran and passed". Documented as intentional, but know
#          the shape: v2.2.4's BOM bug is exactly the mechanism that makes it
#          live — a `**Gate**:` key that stops matching falls to the no-command
#          arm, exits 0, and every commit sails through looking clean. Not in
#          scope for v2.2.5; stated here so the next person adding a code sees
#          the whole picture rather than half of it.
#     2    BLOCK. Retrying after fixing the reported failure can succeed.
#    78    BLOCK, TERMINAL — retrying cannot change the outcome. `GC_TERMINAL_RC`
#          below.
#
#          78 MEANS TERMINAL. THE sysexits NAME IS A COINCIDENCE, NOT A REASON.
#          An earlier draft justified the number as EX_CONFIG ("configuration
#          error"). That argument is withdrawn twice over. First, the class is
#          wider than configuration: the self-reference guard IS a config error,
#          but "not inside a git repository" and a consumer's missing-dependency
#          preflight are ENVIRONMENT errors. All three are terminal — retrying
#          changes none of them — and only one is a config error, so anyone
#          checking the number against sysexits.h and concluding two codes are
#          needed would re-fragment the class this exists to unify. Second, a
#          DOCUMENTED code is MORE likely to collide, not less, because other
#          sysexits-aware programs emit 78 for its documented meaning. Which is
#          the point below.
#
#          THE CLAMP IS WHAT MAKES 78 SAFE, AND THE NUMBER NEVER WAS. A hook
#          NEVER forwards a child's exit code. run-gate.sh runs an arbitrary
#          consumer gate command; if that command exits 78 for its own reasons,
#          forwarding it would hand a plain test failure the terminal remedy
#          text ("edit your **Gate** value") — INVERTED advice, strictly worse
#          than the generic retry line it replaced. So run-gate.sh clamps a
#          gate command's 78 to 1. Anything that starts capturing `$?` and
#          exiting it verbatim opens that channel; do not.
#   127    the HOOK script did not run — its file is missing or its interpreter
#          is unreadable, so the harness never got a verdict out of it. This is
#          why every hook registration is 127-wrapped: an un-run gate must not
#          read as a pass.
#
# THAT LAST LINE IS ABOUT HOOKS, AND ONLY ABOUT HOOKS (v2.2.5). Do not carry it
# across to a CHECKER you invoke yourself. `bash -n <file>` returning 127 is
# bash's own verdict *about the file it was handed* — "No such file or
# directory" — so there it is a hard ERROR naming a missing script, never a
# shrug. Reading it as "did not run" would wave through `bash -n
# hooks/deleted-thing.sh`, which is precisely the condition the wrapper above
# exists to catch. The distinction is the direction of the call: 127 arriving
# FROM the harness means our script was not launched; 127 arriving from a child
# we launched ourselves is that child's answer. See the verdict table in
# user-level-reference/skills/sync-template/SKILL.md step 4.
#
# WHY 78 EXISTS (v2.2.5, consumer report). `run-gate.sh`'s RUN_GATE_ACTIVE guard
# fires correctly when a project's **Gate** value is `bash hooks/run-gate.sh`,
# and then the outer layers buried its accurate one-line diagnosis under two
# generic failures that BOTH said "fix the failures and re-run" — advice to
# retry the one thing that cannot succeed. The defect was not the wording: the
# caller had no way to tell a terminal failure from a retryable one. So the
# distinction is carried in the exit code, and every outer handler suppresses
# its retry advice on GC_TERMINAL_RC *structurally* — it never matches on a
# message or names a particular guard, so the next terminal guard inherits the
# behaviour by exiting 78 and nothing else has to change.
#
# A guard that fires correctly and then prints misleading remediation is not
# much better than one that does not fire. Whatever prints a terminal failure
# ends with the SPECIFIC remedy, and prints no generic "re-run" line at all.
#
# THE BRANCH IS THE FIX; THE NUMBER IS ONLY A NAME. run-gate.sh's
# self-reference guard has exited a distinct, non-generic code (2) since v2.1.3
# and NO outer handler ever read it — before v2.2.5 no script in hooks/ captured
# `$?` into a variable or compared an exit code against anything at all. The
# advice was circular not because the code was indistinguishable but because
# nothing looked at it. So the load-bearing half of this change is
# pre-commit-test.sh and gate-before-merge.sh LEARNING TO BRANCH; renaming 2 to
# 78 while the callers still test truthiness would have been the most expensive
# possible no-op. The rename is still right, for the correct reason: 2 is
# already the hooks' own BLOCK code, so the moment anything does branch, an
# ordinary block and a terminal gate would be indistinguishable.
#
# 78 IS AN INTERNAL SIGNAL AND NEVER A HOOK'S OWN EXIT STATUS. The harness
# treats every non-zero, non-2 PreToolUse exit as a NON-BLOCKING error and lets
# the tool call proceed — so a hook that *exits* 78 warns and ALLOWS. run-gate.sh
# may return 78 to its caller because it is a runner, not a hook;
# pre-commit-test.sh and gate-before-merge.sh must still exit 2 when they block
# and use the 78 only to choose which remediation text to print.
#
# Source it from a hook:  . "$(dirname "$0")/lib/git-cmd.sh"

# The standalone hooks/run-gate.sh repeats this literal (it must run with no
# JSON parser on PATH, which sourcing this file forbids);
# scripts/verify-template-consistency.sh asserts the two copies agree.
GC_TERMINAL_RC=78

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

# v2.2.4 -- the tolerant prefix EVERY `**Key**:` anchor over PROJECT_CONTEXT.md
# must start with. Read this before writing a new field extractor:
#
#   the server strips the BOM for hashing and the hooks do not for grepping, so
#   the same file is two different files depending on which subsystem is looking
#
# A UTF-8 BOM (ef bb bf) sits at byte 0, i.e. INSIDE line 1, so `^` no longer
# abuts the key and the grep returns nothing -- and "no field found" is the
# fail-OPEN arm in pre-commit-test.sh (warn and allow), not a parse error. This
# is routine on Windows: PowerShell 5.1's `>` and `Out-File` write UTF-8 WITH a
# BOM, so one redirect gives a config file a permanent, invisible one. The
# exposure is only ever line 1, which is why the bug hides until someone moves
# a key to the top of the file.
#
# GC_KEY_PRE also carries the leading list-marker tolerance ("- " / "* "), so
# an anchor is `grep -E "${GC_KEY_PRE}\*\*Gate\*\*:"`. The paired `sed` needs no
# change: its leading `.*` consumes the BOM along with the marker.
GC_BOM=$(printf '\357\273\277')
GC_KEY_PRE="^(${GC_BOM})?[-*[:space:]]*"

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

# gc_cmd_unreadable -- true when this invocation is one the git gates were
# registered for AND the command string could not be read out of the payload.
#
# THE 14th FAIL-OPEN (v2.2.6 round 2). All three gates carried a bare
# `[ -n "$GC_CMD" ] || exit 0`: a fail-OPEN guard on a fail-CLOSED gate. NO
# DEFECT WAS EVER OBSERVED IN THE FIELD — the "intermittently empty GC_CMD"
# once reported here is RETRACTED, along with the timing that appeared to show
# it (a PreToolUse hook completes BEFORE the Bash tool runs the command, so a
# timer inside the command cannot observe it; see
# .superpowers/sdd/sync-feedback/empty-payload-failopen.md). What stands is the
# STATE, found by reading this code: `command` key present, read yields nothing,
# gate exits 0. In a gate, an unreadable input is a block, never a pass. The fix
# is mechanism-agnostic because every sub-cause below warrants the same refusal.
#
# THE POLARITY IS NOT FLIPPED UNCONDITIONALLY, and that is the whole design. An
# unconditional refusal on an empty GC_CMD would block every legitimate Bash
# payload that carries no command at all — a hard block traded for a silent gap,
# strictly worse. Of the three states, two are ALREADY fail-closed and only the
# third is live:
#
#   stdin empty or unreadable   -> gc_read_stdin exits 2 (json_valid treats
#                                  empty stdin as INVALID, deliberately).
#   no JSON parser on PATH      -> gc_read_stdin exits 2.
#   payload parsed, GC_CMD ""   -> HERE. It splits three ways:
#
#     tool is not Bash/PowerShell   -> GC_CMD is "" BY DESIGN. Allow.
#     no `command` key at all       -> a legitimate Bash payload carrying no
#                                      command (see the note in gc_read_stdin
#                                      and the shipped "Bash payload with no
#                                      command" fixtures). Allow.
#     a `command` key IS present and
#     the read still yielded ""     -> the gate cannot do its job on a real
#                                      invocation. REFUSE.
#
# So this is NARROWER than "missing or empty": an ABSENT key still allows,
# because making that refuse would hard-block a documented, fixture-covered
# legitimate case. Only "present but unreadable" refuses.
#
# THE KEY PROBE IS A GREP OVER THE RAW PAYLOAD, not a json.sh call — the same
# reason json_session greps: the state being detected is one where the parser
# has already returned nothing, so asking it again proves nothing. It is also
# backend-invariant, so it answers identically in all three parser
# configurations. A false positive needs an unreadable command AND the literal
# `"command":` in some other field of the same payload, and it fails CLOSED,
# which is the correct direction for these three gates.
#
# GC_TOOL EMPTY IS DELIBERATELY INCLUDED in the matched set. These gates are
# registered on Bash|PowerShell, so an empty tool_name on a live invocation is
# the identical cannot-determine one field over — the read that came back empty
# just happened to be tool_name instead of tool_input.command. Excluding it
# would leave the same fault silent through a neighbouring door.
gc_cmd_unreadable() {
  [ -z "$GC_CMD" ] || return 1
  case "$GC_TOOL" in
    Bash|PowerShell|'') ;;
    *) return 1 ;;
  esac
  printf '%s' "$GC_JSON" | grep -q '"command"[[:space:]]*:'
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

# gc_resolve_trunk <repo> -- the remote's default branch, or "" when unknowable.
#
# A LOCAL ref read (`refs/remotes/origin/HEAD`): no network, so it cannot hang
# and needs no timeout wrapper -- this runs inside a PreToolUse hook.
# Deliberately NOT gc_current_branch: at push time HEAD is almost always the
# feature branch being pushed, and protecting that would block the developer's
# own push. setup-project.sh keeps a current-branch fallback because at
# BOOTSTRAP time the checkout IS the trunk; a gate firing at push time is a
# different question with a different safe answer.
# Anything unexpected -- no remote, a detached or missing origin/HEAD, a value
# that is not a plain ref name, a value that is itself a placeholder -- returns
# "" so the caller keeps its own default. Never empty output used as a set,
# never the literal.
gc_resolve_trunk() {
  gcrt=$(git -C "$1" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null)
  gcrt=${gcrt#origin/}
  case "$gcrt" in
    ''|-*|*..*|*[!A-Za-z0-9._/-]*) printf '%s' "" ;;
    *)                             printf '%s' "$gcrt" ;;
  esac
}

# gc_fallback_protected <repo-toplevel> -- the set to protect when the repo
# has not given a usable answer: no `**Protected branches**:` line, an
# unreplaced `{{...}}` one, or an empty one.
#
# `main master` (the historical default) UNION the remote's real trunk. The
# union, not a replacement: narrowing to the resolved trunk alone would REMOVE
# protection from `main` in a repo that has both, so a fix for one exposure
# would open another. Bounded, and every member is individually justified --
# this is NOT "protect every local branch", which is the mirror of the bug it
# fixes.
# Why resolve at all: `main master` does not contain `develop`, so a repo whose
# trunk is neither was unprotected -- SILENTLY when the line was simply absent,
# which is the larger population and predates v2.2.0 entirely. v2.2.1's
# placeholder warn did not protect anything; warning is not protecting.
#
# NOTE THE ASYMMETRY, deliberately: this file fails CLOSED when it cannot read
# the COMMAND (an integrity failure -- something is trying to run and we cannot
# see what) and fails OPEN when it cannot read the REPO'S CONFIGURATION (an
# unconfigured environment -- an unknown is not a violation). Blocking pushes
# because a local ref is missing would be a worse bug than the one being fixed.
gc_fallback_protected() {
  gcpf=$(gc_resolve_trunk "$1")
  if [ -z "$gcpf" ]; then
    # The trunk is unknowable -- `origin/HEAD` is unset on any clone that never
    # ran `git remote set-head`, which is common. We do NOT block on that. But
    # a repo with no local `main` AND no local `master` is certainly not a
    # main-trunk repo, so the fallback set provably covers NO branch it has:
    # that is the one case worth saying out loud, and it cannot false-positive
    # on a main-trunk repo or on a feature branch.
    if ! git -C "$1" show-ref --verify --quiet refs/heads/main 2>/dev/null &&
       ! git -C "$1" show-ref --verify --quiet refs/heads/master 2>/dev/null; then
      json_warn_once "protected-trunk-unknown" "$(json_session "$GC_JSON")" \
        "WARN: $1 has no readable origin/HEAD and no local main or master, so the fallback protected set ('main master') covers no branch in this repo — nothing is protected. Fix with 'git remote set-head origin -a', or name your trunk on the '- **Protected branches**:' line in PROJECT_CONTEXT.md."
    fi
    printf '%s' "main master"
    return 0
  fi
  case " main master " in
    *" $gcpf "*) printf '%s' "main master"; return 0 ;;
  esac
  printf '%s' "main master $gcpf"
}

# gc_protected_branches <repo> -- the branch names the git gates protect.
#
# Optional `**Protected branches**:` line in the repo's PROJECT_CONTEXT.md,
# read with the same tolerant grep as `**Gate**:` (leading list marker,
# surrounding backticks). Names are space- or comma-separated.
# Every arm below that is NOT a configured answer resolves the same way
# (v2.2.3): "main master" PLUS the remote's real trunk. The absent arm is the
# one that matters most -- it is the pre-v2.2.0 hardcode's own blind spot, it
# affects every repo that never configured the field rather than only those
# that took the v2.2.0 template, and unlike the placeholder arm it was SILENT.
#   absent              -> the resolved fallback set, no warning: nothing is
#                          misconfigured here, the repo just never said.
#   `{{DEFAULT_BRANCH}}` -> the resolved fallback set, with one WARN: a
#                          placeholder READS as configured, so this is the case
#                          a consumer does not know they are in.
#   empty value         -> the resolved fallback set, with one WARN: an empty
#                          value is a typo or a truncated sync, not a decision.
#                          v2.2.0 treated it as an opt-out — a silent unprotect.
#   `none`              -> "" — the ONE deliberate way to protect nothing.
#                          Branch rules only: `gh pr merge` stays gated, because
#                          a PR merge is a merge whatever branch it runs on.
gc_protected_branches() {
  gcpb_top=$(git -C "$1" rev-parse --show-toplevel 2>/dev/null)
  [ -n "$gcpb_top" ] || { printf '%s' "main master"; return 0; }
  gcpb_line=$(grep -E "${GC_KEY_PRE}\*\*Protected [Bb]ranches\*\*:" "$gcpb_top/PROJECT_CONTEXT.md" 2>/dev/null | head -1)
  [ -n "$gcpb_line" ] || { gc_fallback_protected "$gcpb_top"; return 0; }
  gcpb=$(printf '%s' "$gcpb_line" \
    | sed 's/.*\*\*Protected [Bb]ranches\*\*:[[:space:]]*//;s/[[:space:]]*$//;s/^`//;s/`$//' \
    | tr ',' ' ' | tr -s '[:space:]' ' ' | sed 's/^ //;s/ $//')
  if gc_is_placeholder "$gcpb"; then
    # WARN, for the same reason the empty arm does — more so. An empty value is
    # visibly empty; an unreplaced placeholder READS as configured, so this is
    # precisely the case a consumer does not know they are in. Silence here was
    # backwards.
    # ...and WARN is not enough on its own: the fallback now also covers the
    # trunk git actually reports, so a develop-trunk repo is protected while it
    # is being told to configure itself, not merely told.
    gcpb_fb=$(gc_fallback_protected "$gcpb_top")
    json_warn_once "protected-branches" "$(json_session "$GC_JSON")" \
      "WARN: **Protected branches**: in $gcpb_top/PROJECT_CONTEXT.md is still an unfilled placeholder ($gcpb) — falling back to '$gcpb_fb'. That fallback is a guess; set a real name."
    printf '%s' "$gcpb_fb"
    return 0
  fi
  case "$(printf '%s' "$gcpb" | tr 'A-Z' 'a-z')" in
    none) printf '%s' "" ;;
    "")
      # Warn ONCE: this function is called several times per gate run (the
      # block message, gc_on_main, gc_protected_alt), so a bare echo would
      # print the same line four times for one push.
      gcpb_efb=$(gc_fallback_protected "$gcpb_top")
      json_warn_once "protected-branches" "$(json_session "$GC_JSON")" \
        "WARN: **Protected branches**: is empty in $gcpb_top/PROJECT_CONTEXT.md — falling back to '$gcpb_efb'. Use 'none' to protect nothing deliberately."
      printf '%s' "$gcpb_efb"
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
