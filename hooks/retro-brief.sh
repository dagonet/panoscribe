#!/usr/bin/env bash
# SessionStart hook: replays the last 10 subagent-failure entries at session start.
# No matcher. Counterpart of hooks/retro-ledger.sh, which writes the ledger.
#
# Stdin fields used: cwd (source/session_id are ignored).
# SessionStart stdout is added to the session context, so the brief is what the
# PO sees before picking up work.
#
# The <project-slug> rule MUST stay identical to hooks/retro-ledger.sh: every
# one of  :  \  /  .  _  becomes a dash (Claude Code's auto-memory rule, e.g.
# G:\git\claude-code-toolkit -> G--git-claude-code-toolkit). A divergence would
# make the ledger silently unreadable; scripts/test-hooks.sh has a round-trip
# fixture that writes with one hook and reads with the other.
#
# FAIL-OPEN BY CONSTRUCTION: no ledger, no node, unparseable payload -> silent
# exit 0. Never wrapped in the exit-127 fail-closed wrapper.

set -u

INPUT=$(cat 2>/dev/null || true)

# v2.2.0: the ledger lookup below is an embedded node program, so this hook
# needs node specifically. Without it it stays fail-open, but says so once.
jlib="$(dirname "$0")/lib/json.sh"
if [ -f "$jlib" ]; then
  . "$jlib"
  json_require_node retro-brief "$(json_session "$INPUT")" || exit 0
fi
command -v node >/dev/null 2>&1 || exit 0

LEDGER=$(printf '%s' "$INPUT" | node -e '
const os = require("os");
const path = require("path");
let raw = "";
process.stdin.on("data", c => raw += c);
process.stdin.on("end", () => {
  let p;
  try { p = JSON.parse(raw); } catch (e) { return; }
  const cwd = (p && p.cwd) || process.cwd();
  const slug = cwd.replace(/[:\\\/._]/g, "-");
  // Base-dir helper — MUST stay identical in hooks/retro-ledger.sh. See the
  // comment there: a Git Bash HOME of /c/Users/x resolves against the current
  // drive under Windows node, which would point the brief at the wrong tree.
  const winify = s => (process.platform === "win32" ? s.replace(/^\/([A-Za-z])\//, "$1:/") : s);
  const home = process.env.CLAUDE_MEMORY_HOME
    || (process.env.HOME && winify(process.env.HOME))
    || os.homedir();
  console.log(path.join(home, ".claude", "projects", slug, "memory", "retro.md"));
});
' 2>/dev/null)

[ -n "$LEDGER" ] || exit 0
[ -s "$LEDGER" ] || exit 0

# v3.0.1: THIS IS THE VIEW. hooks/retro-ledger.sh keeps every row it observed,
# including budget-only spawns; the filtering belongs here, where dropping a row
# hides nothing (retro.md still holds it) instead of in the record, where a row
# that disappears reads as "clean" rather than "changed".
#
# Two transforms, both of which the previous `tail -n 10` alone got wrong:
#
#   1. Drop budget-only rows. A budget ceiling is a liveness control tripping as
#      designed. Measured on a consumer: 30 rows, all 30 budget warnings, zero
#      real failures — a brief nobody could read.
#      NEVER key this filter on errors= or budget= ALONE. A measured row
#      `dead=[Bash,Edit] | budget=0 | errors=2` had a fabricated errors count and
#      an exactly-true dead list, and it produced two real defect reports. A grant
#      gap is not a failure — the agent completes and silently delivers something
#      weaker — so `dead=` is surfaced on its own merits and a row carrying one is
#      never dropped.
#
#   2. Dedupe by agent id, LAST ROW WINS, *before* tailing. Measured: one
#      long-running agent held 11 of 30 cumulative rows and hid three of the four
#      agents behind the tail, under a heading promising the last 10 SUBAGENT
#      entries. The heading below says "one row per agent" for the same reason.
#
# Fields are parsed from the END (`$(NF)` … `$(NF-3)`): only agent_type and
# agent_id sit ahead of them, so tail-indexing cannot be thrown off by an extra
# separator. A line that is not a ledger row (fewer than 7 fields) passes
# through untouched. Truncated at 200 columns: this output is injected into the
# session context, so one pathological ledger line must not be able to flood it.
echo "RETRO (last 10 subagent failures, one row per agent — fix the cause or delegate it):"
awk -F' \\| ' '
  NF >= 7 {
    d = $(NF-3); bl = $(NF-2); bu = $(NF-1); er = $(NF)
    sub(/^dead=/, "", d); sub(/^blocks=/, "", bl)
    sub(/^budget=/, "", bu); sub(/^errors=/, "", er)
    if (d == "[]" && bl == "[]" && bu + 0 > 0 && er + 0 == 0) next
    k = $3
  }
  NF < 7 { k = "\x01line" NR }
  { row[k] = $0; pos[k] = ++n; ord[n] = k }
  END { for (i = 1; i <= n; i++) if (pos[ord[i]] == i) print row[ord[i]] }
' "$LEDGER" | tail -n 10 | cut -c1-200

exit 0
