#!/usr/bin/env bash
# TeammateIdle gate: a named teammate must not go idle without ever reporting.
#
# Why this event and not Stop/SubagentStop:
#   - Agent-tool sub-agents do not need this. Measured 35/35 delivered a report
#     inline in their completion notification (median 8,371 chars, none stall-like).
#   - Named teammates run as separate sessions. They emit no task-notification and
#     no SubagentStop, and their only report channel is a voluntary SendMessage.
#     Measured 64 of 90 never sent a substantive message.
#   - Stop is useless here: its background_tasks entries report status "running"
#     for a teammate that has already idled, and carry no teammate_name.
#
# Contract (measured from live hook stdin, not docs):
#   stdin: teammate_name, team_name, session_id, transcript_path, cwd, prompt_id
#   exit 2 blocks the idle AND the stderr text is delivered to the teammate.
#   There is NO loop-guard field (no stop_hook_active equivalent) and TeammateIdle
#   fires again seconds later -> the ledger below is mandatory, not an optimization.
#
# Safety posture:
#   - Append-only ledger. NEVER delete a marker: deleting it on a second idle
#     (the pattern enforce-agent-contract.sh uses, which is safe for a
#     once-per-agent SubagentStop) would loop block -> pass -> block forever here.
#   - At most one block per teammate. There is deliberately NO session-wide cap:
#     v1.1 shipped MAX_BLOCKS=3 and a replay over a real 208 MB / 10-day transcript
#     showed it exhausted itself in 21 hours, after which the gate was inert for
#     ~500 further idles. Removing it takes coverage from 3 blocks to 41 (of 44
#     achievable); the per-teammate marker already bounds the total at the number
#     of distinct teammates that ever qualify. Worst measured day: 10.
#   - Fail-open on every unexpected condition.
#   - Must NOT be 127-wrapped in settings.json: a missing stop-style gate must
#     never trap teammates in an unstoppable loop.

set -u

# Idles ARE recorded in the lead transcript before this hook runs (verified), so a
# recorded streak of 2 means this is the teammate's second unreported idle -- the
# point at which the Escalation Protocol runbook says to act. Measured on a real
# 167-hour transcript: streak>=2 selects 14 of 90 teammates (including runs of ten
# consecutive idles), streak>=1 would have selected 84 of 90 and fired on healthy
# report-then-idle cycles. Conservative on purpose: this interrupts an agent.
IDLE_STREAK_BEFORE_BLOCK=2

INPUT=$(cat 2>/dev/null || true)
[ -z "$INPUT" ] && exit 0

field() { printf '%s' "$INPUT" | grep -o "\"$1\":\"[^\"]*\"" | head -1 | cut -d'"' -f4; }

NAME=$(field teammate_name)
SESSION=$(field session_id)
TRANSCRIPT=$(field transcript_path)
HOOK_CWD=$(field cwd)

# No identity -> nothing actionable.
[ -z "$NAME" ] && exit 0
[ -z "$SESSION" ] && exit 0

# Kill switch at the repo root, mirroring hooks/enforce-delegation.sh.
# REPO_ROOT is reused further down for the audit log, so resolve it once here.
REPO_ROOT=""
if [ -n "${HOOK_CWD:-}" ]; then
  REPO_ROOT=$(git -C "$HOOK_CWD" rev-parse --show-toplevel 2>/dev/null | tr '\\' '/')
  if [ -n "$REPO_ROOT" ] && [ -f "$REPO_ROOT/.claude/liveness-off" ]; then
    exit 0
  fi
fi

LEDGER="${TMPDIR:-/tmp}/claude-teammate-liveness/$SESSION"
mkdir -p "$LEDGER" 2>/dev/null || exit 0

# Already nagged this teammate once -> never again. This is the ONLY throttle.
[ -f "$LEDGER/$NAME.blocked" ] && exit 0

# Decide from the teammate's message history in the LEAD's transcript (where
# teammate messages land). The signal is NOT "never reported" -- measured, only 4
# of 90 teammates never reported at all, so that trigger would be useless. The
# real pathology is idling repeatedly BETWEEN reports: 279 bare idle
# notifications against 305 substantive messages, with runs like
# R R I I I I I I I I I I R (ten consecutive idles, no output).
#
# So: fire when this teammate already has >=1 unreported idle on record, making
# the current one at least its second in a row. That matches the documented
# runbook (1st idle -> prod once, 2nd idle -> TaskStop) and, on the measured
# transcript, fires for 45 of 90 teammates while leaving a healthy
# report-then-idle alone. (>=1 total idle would have fired for 84 of 90.)
[ -z "$TRANSCRIPT" ] && exit 0
[ -f "$TRANSCRIPT" ] || exit 0

REPORTED=$(node -e '
try {
  const fs = require("fs");
  const [file, name] = [process.argv[1], process.argv[2]];
  // Scan the WHOLE transcript. An earlier version scanned only the last 40 MB and
  // produced false positives: a teammate whose only report landed earlier than the
  // window read as silent. Measured cost is ~0.5 s per 40 MB, and this fires only
  // on a teammate idle, so whole-file is affordable. Absurdly large files fail open.
  const HARD_LIMIT = 250 * 1024 * 1024;
  const size = fs.statSync(file).size;
  if (size > HARD_LIMIT) { console.log("UNKNOWN"); process.exit(0); }
  const text = fs.readFileSync(file, "utf8");
  const esc = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // Tags live inside JSON string values, so every quote may appear escaped as \".
  // Match both forms: a raw scan is far cheaper than JSON.parse per line, but it
  // MUST tolerate the backslashes or a teammate that reported reads as silent.
  const Q = "\\\\?\"";
  const re = new RegExp(
    "<(?:teammate|agent)-message (?:teammate_id|from)=" + Q + esc + Q + "[^>]*>([\\s\\S]*?)</(?:teammate|agent)-message>",
    "g"
  );
  const IDLE = new RegExp(Q + "type" + Q + "\\s*:\\s*" + Q + "idle_notification" + Q);
  // Walk the blocks for this teammate in order and count how many bare idles
  // trail the most recent substantive message.
  // NOTE: no apostrophes anywhere inside this node script -- it is passed to
  // node -e inside a single-quoted shell string, so one apostrophe ends the
  // string and bash then tries to parse the JavaScript.
  let m, blocks = 0, trailingIdles = 0;
  while ((m = re.exec(text)) !== null) {
    const body = m[1].trim();
    if (!body) continue;
    blocks++;
    if (IDLE.test(body)) trailingIdles++;
    else trailingIdles = 0;          // a real report resets the streak
  }
  // Zero blocks means this teammate is not represented in the transcript at all —
  // absence of evidence, not evidence of silence. Fail open.
  if (blocks === 0) { console.log("UNKNOWN"); process.exit(0); }
  console.log("STREAK " + trailingIdles);
} catch (e) {
  console.log("UNKNOWN");
}
' "$TRANSCRIPT" "$NAME" 2>/dev/null) || exit 0

# Fail open on anything but a confident streak reading.
case "$REPORTED" in
  "STREAK "*) STREAK=${REPORTED#STREAK } ;;
  *) exit 0 ;;
esac
case "$STREAK" in ''|*[!0-9]*) exit 0 ;; esac

# The current idle may not be written to the transcript yet, so a recorded streak
# of >=1 means this is at least the teammate's second idle without reporting.
[ "$STREAK" -ge "$IDLE_STREAK_BEFORE_BLOCK" ] || exit 0

: > "$LEDGER/$NAME.blocked" 2>/dev/null || exit 0

# Audit trail. Block events only -- a passing idle carries no signal, and the
# ledger already proves the hook ran. Best-effort: a failed write must never
# change the exit code, so every failure mode is swallowed.
if [ -n "$REPO_ROOT" ] && [ -d "$REPO_ROOT/.claude" ]; then
  printf '%s require-teammate-report teammate=%s streak=%s action=block\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo unknown-time)" \
    "$NAME" "$STREAK" >> "$REPO_ROOT/.claude/liveness.log" 2>/dev/null || true
fi

cat >&2 <<EOF
LIVENESS: this is at least your second idle in a row with no report in between.

A bare idle notification is a NON-report — the orchestrator cannot tell your work
from a stall, and unreported work gets redone or dropped.

Send your report to main now via SendMessage: what you did, what you found, what
is left, and any blocker. If you genuinely have nothing to report, say that
explicitly in one line rather than going silent.

This fires at most once per teammate, ever. Escape hatch: create .claude/liveness-off.
EOF
exit 2
