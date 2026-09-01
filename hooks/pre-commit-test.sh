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
#
# v2.2.0: the payload is parsed through hooks/lib/json.sh (node, python3 or jq).
# With none of the three on PATH this gate fails CLOSED (exit 2) like the other
# two git gates — a commit whose command cannot be read is not a commit that can
# be shown to have passed its tests. `git-guard-off` still opts out.
#
# READING THE OUTPUT (v2.2.1, from a consumer report):
#   - A green run prints `passed. (<n>s)` and NOTHING else. The captured output
#     is deleted on success by design, so "I saw no test output" is not evidence
#     the tests did not run — the ELAPSED SECONDS are. A real suite takes
#     minutes (616 s measured on a three-project repo); a hook that fell through
#     its own guards returns in about a second.
#   - A `**Test**` value chaining projects with `&&` SHORT-CIRCUITS. When the
#     first project fails, the later ones are UNRUN — not passing. The block
#     message names the whole command, so do not read a failure as "everything
#     after the first project was fine"; nothing after it was executed at all.

# Fail CLOSED when the sourced lib is missing: without it every gc_* helper is
# undefined, GC_CMD stays empty, and this gate would exit 0 on every commit.
lib="$(dirname "$0")/lib/git-cmd.sh"
[ -f "$lib" ] || { echo "BLOCKED: $lib missing — run /sync-template step 6b (hooks/lib/git-cmd.sh)" >&2; exit 2; }
. "$lib"

# v2.1.3 fix round 2: absolutize RUN_GATE HERE, before any `cd`. $0 is a
# relative path when the harness invokes `bash hooks/pre-commit-test.sh`, and
# a relative "$(dirname "$0")/run-gate.sh" is not re-resolved until it is
# actually used below -- by then the script has `cd`'d into REPO_PATH (which
# `git -C <other-repo> commit` can point anywhere), so the stale relative path
# would resolve against the WRONG repo: silently missing there (masking an
# intended run-gate.sh as the legacy eval path), or worse, hitting that other
# repo's own hooks/run-gate.sh instead of this toolkit's.
RUN_GATE="$(cd "$(dirname "$0")" && pwd)/run-gate.sh"

gc_read_stdin
gc_guard_off && exit 0

# Fail CLOSED on a pre-v2 settings.json: it registers this gate on the retired
# git-tools MCP tools, whose payloads carry no tool_input.command — the v2 gate
# would find nothing to parse and allow the commit.
case "$GC_TOOL" in
  mcp__git-tools__git_push|mcp__git-tools__git_commit)
    echo "BLOCKED: settings.json predates this hook (MCP matcher) — restart the session after /sync-template" >&2
    exit 2 ;;
esac

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

# Read test command from PROJECT_CONTEXT.md through GC_KEY_PRE (see the header
# note on that constant in hooks/lib/git-cmd.sh: a leading UTF-8 BOM otherwise
# hides a key that sits on line 1, and THIS hook's no-field arm is warn+allow).
# Tolerates: leading "- " / "* " list
# markers, the "**Test Command**:" label style (java/python variants), and
# surrounding backticks — several variants write commands as `cmd`.
# v2.1.3 fix round 1: **Test** always wins when present -- cheap, unchanged
# behaviour for repos that declare a lightweight Test command. run-gate.sh is
# only consulted below when there is NO Test field.
TEST_CMD=$(grep -E "${GC_KEY_PRE}\*\*Test( Command)?\*\*:" "$REPO_PATH/PROJECT_CONTEXT.md" 2>/dev/null | sed 's/.*\*\*Test\( Command\)\?\*\*:[[:space:]]*//;s/[[:space:]]*$//;s/^`//;s/`$//' | head -1)

# v2.1.3 fix round 2: a still-unfilled {{...}} Test placeholder must not win
# precedence over a real Gate command -- dotnet/dotnet-maui ship exactly this
# shape (Test: uv run pytest, a real Gate). Strip it to "" here, right after
# extraction, so it is treated as absent below and precedence correctly falls
# through to the Gate/run-gate.sh path instead of silently exiting 0.
case "$TEST_CMD" in
  *\{\{*\}\}*) TEST_CMD="" ;;
esac

# v2.1.1: projects that declare only a **Gate** command (the gate runs the tests
# plus format/lint) used to make this hook a silent no-op. Fall back to Gate.
#
# v2.1.3 (consumer feedback, Yutraffic; fix round 1): when the fallback fires
# AND hooks/run-gate.sh sits next to this script, run run-gate.sh instead of
# eval'ing the Gate command ourselves. A green run-gate.sh writes
# .gate/last-pass.json as a side effect, so gate-before-merge.sh is satisfied
# without a second gate run at merge time. A still-unfilled {{...}} placeholder
# is treated as absent here (never routed into run-gate.sh, and never eval'd
# directly) -- it falls through to the "nothing to run" WARN below, same as no
# Gate field at all, so a mid-setup repo cannot get a false green.
if [ -z "$TEST_CMD" ]; then
  GATE_CMD_RAW=$(grep -E "${GC_KEY_PRE}\*\*Gate( Command)?\*\*:" "$REPO_PATH/PROJECT_CONTEXT.md" 2>/dev/null | sed 's/.*\*\*Gate\( Command\)\?\*\*:[[:space:]]*//;s/[[:space:]]*$//;s/^`//;s/`$//' | head -1)
  case "$GATE_CMD_RAW" in
    *\{\{*\}\}*) GATE_CMD_RAW="" ;;
  esac

  if [ -n "$GATE_CMD_RAW" ]; then
    if [ -f "$RUN_GATE" ]; then
      echo "PRE-COMMIT: Running 'run-gate.sh'..." >&2
      # v2.2.5 round 4: exit 2, NOT 1. The harness treats every non-zero, non-2
      # PreToolUse exit as a NON-BLOCKING error and lets the tool call proceed
      # (see the exit-code conventions in hooks/lib/git-cmd.sh) -- so the former
      # `exit 1` here was warn-and-ALLOW: a failed cd into the resolved repo let
      # the commit through UNGATED. Cannot-determine must refuse.
      # Deliberately 2 and not GC_TERMINAL_RC: per the same reasoning as
      # run-gate.sh's own `cd "$REPO_TOP" || exit 1`, a cd failing on a path git
      # just resolved is a transient FAULT (race, permissions, unmounted share),
      # not a settled condition, so "re-run it" is honest advice. And 78 is an
      # internal signal that is never a hook's own exit status.
      cd "$REPO_PATH" || { echo "BLOCKED: pre-commit-test: cannot enter the repository at '$REPO_PATH' — re-run the commit once the path is reachable." >&2; exit 2; }
      OUT=$(mktemp 2>/dev/null || echo "$REPO_PATH/.pre-commit-test.out")
      bash "$RUN_GATE" > "$OUT" 2>&1
      PCT_RC=$?
      if [ "$PCT_RC" -eq 0 ]; then
        rm -f "$OUT"
        echo "PRE-COMMIT: 'run-gate.sh' passed." >&2
        exit 0
      else
        # v2.2.5: suppress the retry advice STRUCTURALLY on a terminal rc. This
        # test names no guard and reads no message, so any future terminal guard
        # inherits it by exiting GC_TERMINAL_RC. The captured tail is printed
        # last either way, so the guard's own specific remedy is what the user
        # reads at the bottom of the block.
        if [ "$PCT_RC" -eq "$GC_TERMINAL_RC" ]; then
          echo "BLOCKED: 'run-gate.sh' cannot succeed as configured — this is a configuration failure, not a failing check. Re-running it will NOT help; apply the remedy below." >&2
        else
          echo "BLOCKED: 'run-gate.sh' failed — re-run it and fix the failures before committing." >&2
          # v2.2.5: name the escape hatch WHERE THE FAILURE SURFACES. Since the
          # toolkit gates itself, a bug in this hook can block the very commit
          # that fixes it — and someone hard-blocked mid-commit is not reading
          # CLAUDE.md. Same principle as the terminal-remedy rule above: the
          # remedy has to appear where the person actually is.
          echo "  (If the HOOK itself is broken rather than the suite: create '.claude/git-guard-off' under this cwd, make the one fix, then delete it. Never leave it in place.)" >&2
        fi
        echo "--- last 20 lines ---" >&2
        tail -20 "$OUT" >&2
        rm -f "$OUT"
        exit 2
      fi
    else
      # v2.1.3 fix round 2: a mirror (e.g. ~/.claude/hooks/) whose run-gate.sh
      # copy was never migrated must not 127 -- fall back to eval'ing the Gate
      # command directly, same as the pre-run-gate.sh behaviour, but say so:
      # a silent fallback here reads exactly like the full-gate path ran.
      echo "WARN: pre-commit-test: run-gate.sh not found next to this hook — evaluating the Gate command directly instead" >&2
      TEST_CMD="$GATE_CMD_RAW"
    fi
  fi
fi

# Nothing to run. Say so — a silent pass reads exactly like a green test run.
if [ -z "$TEST_CMD" ]; then
  echo "WARN: pre-commit-test: no Test/Gate command in PROJECT_CONTEXT.md — nothing verified" >&2
  exit 0
fi

# v2.1.4: the placeholder-{{...}} guard formerly here is unreachable -- both
# TEST_CMD's own extraction (line ~87) and GATE_CMD_RAW's (line ~104) already
# strip a {{...}} placeholder to "", and an empty TEST_CMD exits at line 137
# above before this point is ever reached.

echo "PRE-COMMIT: Running '$TEST_CMD'..." >&2
# Same as the run-gate.sh branch above: `exit 1` from a PreToolUse hook is
# warn-and-ALLOW, so this must be 2 or a failed cd waves the commit through.
cd "$REPO_PATH" || { echo "BLOCKED: pre-commit-test: cannot enter the repository at '$REPO_PATH' — re-run the commit once the path is reachable." >&2; exit 2; }

# Capture rather than discard: with the Gate fallback $TEST_CMD may be a whole
# gate, and "it failed" with no output leaves nothing to act on. Bounded to the
# last 20 lines so a chatty gate cannot flood the transcript.
OUT=$(mktemp 2>/dev/null || echo "$REPO_PATH/.pre-commit-test.out")
PCT_T0=$(date +%s 2>/dev/null || echo 0)
# THE SUBSHELL IS LOAD-BEARING (v2.2.5 round 5, independent QA at 9baa446;
# pre-existing since v2.1.x, not a regression of this branch).
#
# `eval` runs its argument in the CURRENT shell. `$TEST_CMD` is a CONSUMER-
# authored value, so a value whose top level reaches `exit` or `exec` terminated
# THIS HOOK and bypassed the if/else below entirely. Measured, bare `eval`:
#
#   **Test**: exit 1                 -> hook exit 1,  ZERO "BLOCKED" lines
#   **Test**: exec bash -c "exit 1"  -> hook exit 1,  ZERO "BLOCKED" lines
#   **Test**: exec bash -c "exit 78" -> hook exit 78, ZERO "BLOCKED" lines
#
# A non-2 PreToolUse exit is warn-and-ALLOW, so each of those let the commit
# through UNGATED and SILENTLY, and leaked $OUT. The 78 case additionally
# violated the invariant this release documents in hooks/lib/git-cmd.sh: 78 is
# never a hook's own exit status, and a hook NEVER forwards a child's code.
#
# `( ... )` contains both: `exit` ends the subshell and `exec` replaces the
# subshell's process, and either way $? is a CHILD's status that reaches the
# test below like any other. This is containment of the two shell builtins that
# end a process -- NOT a claim of immunity to arbitrary consumer values, which
# is not a property an eval boundary can have.
#
# Round 4's clamp reasoning is undisturbed: a child's 78 still lands in $PCT_RC
# with no provenance marker and still reaches the else branch (see the long note
# below). R5g in scripts/test-hooks.sh drives this BEHAVIOURALLY -- the source
# censuses in verify-template-consistency.sh cannot reach a value that arrives
# as config DATA rather than as hook SOURCE.
( eval "$TEST_CMD" ) > "$OUT" 2>&1
PCT_RC=$?

# NO TERMINAL REMEDY AT THIS BOUNDARY (v2.2.5 round 4), and WHY THE TWO
# BOUNDARIES DIFFER.
#
# `$TEST_CMD` here is either a consumer's **Test** value or — when run-gate.sh is
# absent beside this hook — the raw **Gate** value. Both are ARBITRARY consumer
# commands, and 78 is EX_CONFIG, which real programs emit for their own reasons.
# Nothing stands between that command and this variable, so a 78 arriving here
# is always a CHILD's number, never a verdict any guard of ours reached.
# Forwarding it would hand a plain test failure the terminal remedy text — the
# INVERTED advice the conventions block in hooks/lib/git-cmd.sh forbids ("a hook
# NEVER forwards a child's exit code").
#
# The run-gate.sh boundary above needs no clamp for the opposite reason, and the
# asymmetry is not an oversight: run-gate.sh clamps its OWN gate command's 78
# internally, keyed on the provenance marker it created, so a 78 emerging from
# it has already been decided BY run-gate.sh to be its own terminal guard
# talking. There the number carries provenance; here it carries none.
#
# Residual edge, stated rather than engineered around: `**Test**: bash
# hooks/run-gate.sh` whose own **Gate** is self-referencing would produce a
# genuinely terminal 78 that this clamp demotes to a retryable one. That needs
# two pathologies at once, and attribution across an eval boundary this hook did
# not create would mean rebuilding a causal chain out of a file — the same
# disposition round 3 took for `run-gate.sh; some-other-tool`. The guard still
# prints its own specific remedy in the captured tail below; only the
# "cannot succeed as configured" framing is lost. run-gate.sh's other terminal
# guard is NOT reachable here at all: `$REPO_PATH` was resolved by gc_repo_for,
# so "not inside a git repository" cannot fire under this cd.
#
# SO THE FIX IS THE ABSENCE OF THE BRANCH, NOT A CLAMP ASSIGNMENT. Round 4 first
# wrote `PCT_RC=1` here as well. With the terminal arm gone that statement has NO
# observable effect — deleting it leaves every assertion green, which is exactly
# the guard-indistinguishable-from-its-absence shape this release refuses to
# ship. What is enforced instead is enforceable: the else branch below tests
# `$PCT_RC` against 0 and nothing else, and R5f in scripts/test-hooks.sh goes red
# the moment a terminal arm reappears here.
if [ "$PCT_RC" -eq 0 ]; then
  rm -f "$OUT"
  # The elapsed seconds are the ONLY external evidence the suite actually ran.
  # On success the captured output is deleted (right above) — correct, it is
  # noise on a green run — so "I saw no test output" is not evidence of a no-op.
  # A real suite takes minutes (616 s measured on a three-project repo); a hook
  # that fell through its own guards returns in about a second. One number
  # tells the two apart without reintroducing the noise.
  PCT_T1=$(date +%s 2>/dev/null || echo 0)
  echo "PRE-COMMIT: '$TEST_CMD' passed. ($((PCT_T1 - PCT_T0))s)" >&2
  exit 0
else
  # NO TERMINAL ARM HERE, DELIBERATELY (v2.2.5 round 4) — this absence IS the
  # fix, see the note above the success test. A 78 reaching this point is a
  # child's number with no provenance behind it, so branching on it would hand a
  # plain test failure the terminal remedy: inverted advice. Anyone restoring a
  # terminal arm must FIRST give this boundary a provenance channel; the number
  # alone cannot earn it. R5f in scripts/test-hooks.sh goes red if one returns.
  echo "BLOCKED: '$TEST_CMD' failed — re-run it and fix the failures before committing." >&2
  # Same reason as the run-gate.sh branch above: the escape hatch is named
  # where the block is read, not only in CLAUDE.md.
  echo "  (If the HOOK itself is broken rather than the suite: create '.claude/git-guard-off' under this cwd, make the one fix, then delete it. Never leave it in place.)" >&2
  echo "--- last 20 lines ---" >&2
  tail -20 "$OUT" >&2
  rm -f "$OUT"
  exit 2
fi
