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
      cd "$REPO_PATH" || exit 1
      OUT=$(mktemp 2>/dev/null || echo "$REPO_PATH/.pre-commit-test.out")
      if bash "$RUN_GATE" > "$OUT" 2>&1; then
        rm -f "$OUT"
        echo "PRE-COMMIT: 'run-gate.sh' passed." >&2
        exit 0
      else
        echo "BLOCKED: 'run-gate.sh' failed — re-run it and fix the failures before committing." >&2
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
cd "$REPO_PATH" || exit 1

# Capture rather than discard: with the Gate fallback $TEST_CMD may be a whole
# gate, and "it failed" with no output leaves nothing to act on. Bounded to the
# last 20 lines so a chatty gate cannot flood the transcript.
OUT=$(mktemp 2>/dev/null || echo "$REPO_PATH/.pre-commit-test.out")
PCT_T0=$(date +%s 2>/dev/null || echo 0)
if eval "$TEST_CMD" > "$OUT" 2>&1; then
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
  echo "BLOCKED: '$TEST_CMD' failed — re-run it and fix the failures before committing." >&2
  echo "--- last 20 lines ---" >&2
  tail -20 "$OUT" >&2
  rm -f "$OUT"
  exit 2
fi
