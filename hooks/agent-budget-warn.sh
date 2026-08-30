#!/usr/bin/env bash
# PreToolUse tool-call budget for agents. Counters the runaway single spawn.
#
# Measured motivation: median 15 tool calls per agent, but 35 of 150 agents in one
# real session exceeded 60 and 19 exceeded 120, with a worst spawn of 417 calls.
# Nothing in the toolkit bounded a single spawn.
#
# Why blocking escalates (v1.2): v1.1 blocked exactly once at 120 and then only
# warned. The 417-call agent proves a single block does not stop a runaway, so the
# block now repeats every BLOCK_EVERY calls past BLOCK_AT.
#
# Contract (measured from live hook stdin):
#   Named teammates DO fire the project's PreToolUse and DO carry agent_id
#   (e.g. "aprobe-teammate-2-e14467006a486b91") plus agent_type. Main-thread
#   calls carry neither. So agent_id is a sound discriminator here, and the
#   agents that actually run away are reachable.
#
# Cost discipline: this fires on EVERY agent tool call, so the hot path is pure
# shell — one grep, no node, and an immediate exit on the main thread.
#
# PARSER-FREE BY CONSTRUCTION, and therefore silent about parsers (v2.2.1).
# The one field it needs is agent_id, and it reads it with a grep over the raw
# payload — it never sources hooks/lib/json.sh, so it does not need node,
# python3 or jq and never prints the `WARN: <hook>: no JSON parser on PATH`
# line the six fail-open hooks print. The v2.2.0 notes read as though every
# fail-open hook warns; this one has nothing to warn about. Do NOT add a warn
# call here: it would fire on every agent tool call for no enforcement gap.
#
# Posture: WARN once, then block on each threshold crossing. A hard wall would
# break legitimate large tasks; the goal is to force a deliberate reconsideration
# at each escalation. Wrap with the WARN-on-127 form in settings.json (exit 0) —
# a missing budget hook must never brick every tool call.
#
# CRITICAL: every threshold test uses -eq, never -ge. PreToolUse fires on every
# call, so a >= test would block calls 121, 122, 123 ... and the agent could never
# report its partial progress — the same unbounded-refire hazard the TeammateIdle
# ledger exists to prevent. The counter increments by exactly 1 per call, so each
# threshold is hit exactly once and calls between thresholds pass untouched.

set -u

WARN_AT=60
BLOCK_AT=120
BLOCK_EVERY=60

INPUT=$(cat 2>/dev/null || true)
[ -z "$INPUT" ] && exit 0

# Fast path: main thread has no agent_id -> not our business.
AGENT_ID=$(printf '%s' "$INPUT" | grep -o '"agent_id":"[^"]*"' | head -1 | cut -d'"' -f4)
[ -z "$AGENT_ID" ] && exit 0

SESSION=$(printf '%s' "$INPUT" | grep -o '"session_id":"[^"]*"' | head -1 | cut -d'"' -f4)
[ -z "$SESSION" ] && exit 0

# Kill switch, mirroring the other guards. ROOT is reused for the audit log.
ROOT=""
HOOK_CWD=$(printf '%s' "$INPUT" | grep -o '"cwd":"[^"]*"' | head -1 | cut -d'"' -f4)
if [ -n "${HOOK_CWD:-}" ]; then
  ROOT=$(printf '%s' "$HOOK_CWD" | tr '\\' '/')
  [ -f "$ROOT/.claude/liveness-off" ] && exit 0
fi

# Audit trail. Threshold events ONLY -- this hook runs on every tool call, so
# logging each pass would add a second write to the hot path and ~10,000 lines of
# no signal per session. The counter file already proves the hook ran.
# Best-effort: never allowed to change the exit code.
log_event() {
  [ -n "$ROOT" ] || return 0
  [ -d "$ROOT/.claude" ] || return 0
  printf '%s agent-budget-warn agent=%s calls=%s action=%s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo unknown-time)" \
    "$AGENT_ID" "$N" "$1" >> "$ROOT/.claude/liveness.log" 2>/dev/null || true
  return 0
}

# Sanitize: agent_id is used as a filename.
SAFE=$(printf '%s' "$AGENT_ID" | tr -c 'A-Za-z0-9._-' '_')
DIR="${TMPDIR:-/tmp}/claude-agent-budget/$SESSION"
mkdir -p "$DIR" 2>/dev/null || exit 0
COUNTER="$DIR/$SAFE"

N=0
[ -f "$COUNTER" ] && N=$(cat "$COUNTER" 2>/dev/null || echo 0)
case "$N" in ''|*[!0-9]*) N=0 ;; esac
N=$((N + 1))
printf '%s' "$N" > "$COUNTER" 2>/dev/null || exit 0

# Block on each threshold crossing: BLOCK_AT, then every BLOCK_EVERY past it
# (120, 180, 240, ...). Strictly -eq / modulo-zero, so calls in between pass.
if [ "$N" -eq "$BLOCK_AT" ] || { [ "$N" -gt "$BLOCK_AT" ] && [ $(( (N - BLOCK_AT) % BLOCK_EVERY )) -eq 0 ]; }; then
  log_event block
  cat >&2 <<EOF
BUDGET: this spawn has made $N tool calls (median is 15; 120 is the first ceiling).

Stop expanding and land what you have. Report your partial result plus the
blocker and let the PO re-tier the remainder — do not keep growing scope inside
one spawn. A long run is not evidence of progress.

You may continue past this, but it will stop you again every $BLOCK_EVERY calls.
Escape hatch: create .claude/liveness-off.
EOF
  exit 2
fi

# Single advisory warning at WARN_AT.
if [ "$N" -eq "$WARN_AT" ]; then
  log_event warn
  printf 'BUDGET: %s tool calls so far. Check that you are still inside your stated scope.\n' "$N" >&2
fi

exit 0
