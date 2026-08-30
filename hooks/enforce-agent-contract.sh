#!/usr/bin/env bash
# SubagentStop hook: contract stop-gate for coder/reviewer agents.
# Matcher: coder|dotnet-coder|rust-coder|java-coder|python-coder|code-reviewer
#
# Blocks (exit 2) an agent from ending WITHOUT its required deliverable:
#   - coder types:    final message must contain "## Gate Results" AND "## Spec Compliance"
#   - code-reviewer:  final message must BE the single word "clean" (strict equality)
#                     or contain a severity-tagged findings list ("**Severity**")
# The stderr is fed back to the agent, which continues and produces the report.
#
# Loop guard: a marker file bounds enforcement to EXACTLY ONE forced continuation
# per session+agent (SubagentStop carries no stop_hook_active field — see below —
# so we keep our own state). The marker is STICKY: once written it is never
# removed by this hook, on any path. Every later stop for that same session+agent
# passes through with a non-blocking CONTRACT-ENFORCER stderr line telling the PO
# to treat the report as incomplete.
#
# v2.2.2: it used to be deleted on BOTH the compliant path and the let-through
# path, which made it bound nothing — the next stop started fresh and prodded
# again, so a coder that kept yielding was prodded on every odd-numbered stop
# forever. Markers are left to TMPDIR lifetime rather than given a
# json_warn_once-style TTL on purpose: an expiring marker re-arms mid-run, which
# is the same unbounded loop with a slower clock.
#
# SubagentStop terminal detection: investigated in v2.2.2, not available. The
# measured payload (user-level-reference/settings-reference.md, "Measured stdin
# fields") carries agent_id, agent_type, agent_transcript_path and
# last_assistant_message — no stop_hook_active and no "this agent will resume"
# flag. A trailing tool_use block is NOT a substitute discriminator: that is the
# same fact this hook already encodes as "empty text => no report". So the hook
# cannot tell a terminal stop from an intermediate yield, and the sticky marker
# is what bounds the cost of not knowing. Do not add a heuristic here.
#
# Deliberately FAIL-OPEN when broken (transcript missing, node absent, fields
# absent, marker dir unwritable): a broken enforcer must never trap an agent.
# Do NOT wrap this hook's registration in the exit-127 fail-closed wrapper used
# for PreToolUse guards — a missing enforcer would otherwise block stops forever.

INPUT=$(cat)

# v2.2.0: fields go through hooks/lib/json.sh, but the transcript scan below is
# an embedded node program — so this hook still needs node specifically, and
# says so once (fail-open) when it is missing.
jlib="$(dirname "$0")/lib/json.sh"
[ -f "$jlib" ] || {
  echo "WARN: enforce-agent-contract: hooks/lib/json.sh missing — enforcement inactive" >&2
  exit 0
}
. "$jlib"
json_require_node enforce-agent-contract "$(json_session "$INPUT")" || exit 0

AGENT_TYPE=$(json_get "$INPUT" agent_type)
# v2.2.2: the measured SubagentStop payload lists agent_transcript_path -- this
# subagent's own JSONL, not the session's -- and retro-ledger.sh, the other
# consumer of this event, reads it. This hook read transcript_path. Prefer the
# documented field; keep transcript_path as a fallback for a payload lacking it.
TRANSCRIPT=$(json_get "$INPUT" agent_transcript_path)
[ -n "$TRANSCRIPT" ] || TRANSCRIPT=$(json_get "$INPUT" transcript_path)
AGENT_ID=$(json_get "$INPUT" agent_id)
SESSION_ID=$(json_get "$INPUT" session_id)

# Fail-open: not enough information to enforce.
if [ -z "$AGENT_TYPE" ] || [ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ]; then
  exit 0
fi

# Last assistant entry's text blocks (empty when the final entry is tool_use-only —
# that counts as non-compliant: the agent ended without a report).
LAST_TEXT=$(tail -c 300000 "$TRANSCRIPT" | node -e '
let d="";
process.stdin.on("data",c=>d+=c);
process.stdin.on("end",()=>{
  const lines=d.split("\n").filter(Boolean);
  let txt="";
  for (const l of lines){
    let j; try { j=JSON.parse(l); } catch(e) { continue; } // first line may be cut by tail
    if (j.type!=="assistant" || !j.message) continue;
    // v2.2.2: message.content is an ARRAY only for turns that mix text with
    // tool calls. A plain text-only assistant turn -- which is exactly what a
    // compliant final report is -- serializes content as a STRING. Reading
    // only the array shape skipped every compliant report and left txt holding
    // an earlier, non-compliant, mid-run turn, so the agent could never satisfy
    // the contract. Both shapes now, string first.
    const c=j.message.content;
    if (typeof c==="string") txt=c;
    else if (Array.isArray(c)) txt=c.filter(b=>b&&b.type==="text").map(b=>b.text||"").join("\n");
  }
  process.stdout.write(txt);
});' 2>/dev/null)

# Verdict per agent type.
ok=0
missing=""
case "$AGENT_TYPE" in
  code-reviewer)
    trimmed=$(printf '%s' "$LAST_TEXT" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    if [ "$trimmed" = "clean" ] || printf '%s' "$LAST_TEXT" | grep -q '\*\*Severity\*\*'; then
      ok=1
    else
      missing="a severity-tagged findings list (each finding with **Severity** and file:line) or the single word 'clean'"
    fi
    ;;
  *)
    gaps=""
    printf '%s' "$LAST_TEXT" | grep -q '## Gate Results'     || gaps="'## Gate Results'"
    printf '%s' "$LAST_TEXT" | grep -q '## Spec Compliance'  || gaps="${gaps:+$gaps and }'## Spec Compliance'"
    if [ -z "$gaps" ]; then
      ok=1
    else
      missing="the required section(s) $gaps"
    fi
    ;;
esac

TMPBASE="${TMPDIR:-${TMP:-${TEMP:-/tmp}}}"
MARKER="$TMPBASE/.contract-prod-${SESSION_ID}-${AGENT_ID}"

if [ "$ok" = "1" ]; then
  exit 0
fi

# Already prodded once this session for this agent: let every later stop through,
# but signal the PO. The marker is NOT removed here -- see the loop-guard note.
if [ -f "$MARKER" ]; then
  echo "CONTRACT-ENFORCER: $AGENT_TYPE/$AGENT_ID ended without $missing after one prod — treat the report as incomplete and re-dispatch per the stall runbook." >&2
  exit 0
fi

# First non-compliant stop: record the prod, block the stop, tell the agent exactly what to do.
if ! touch "$MARKER" 2>/dev/null; then
  # Cannot persist the loop guard — fail open rather than risk an unbounded block loop.
  echo "CONTRACT-ENFORCER: marker dir unwritable ($TMPBASE); letting $AGENT_TYPE/$AGENT_ID stop unenforced." >&2
  exit 0
fi

if [ "$AGENT_TYPE" = "code-reviewer" ]; then
  echo "CONTRACT VIOLATION: your final message must be either a severity-tagged findings list (each finding: **Severity**: critical|warning|suggestion + file:line locator) or the single word: clean. Post your review result now — do not end without it." >&2
else
  echo "CONTRACT VIOLATION: your final report is missing $missing. Produce it now: run 'bash hooks/run-gate.sh' and paste the verbatim tail under '## Gate Results' (or the Build/Test/Format/Lint outputs if no Gate is configured), then echo every numbered spec item under '## Spec Compliance' as DONE or DEVIATED: <reason>." >&2
fi
exit 2
