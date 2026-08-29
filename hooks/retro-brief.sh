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

# Truncated at 200 columns: this output is injected into the session context, so
# one pathological ledger line must not be able to flood it.
echo "RETRO (last 10 subagent-failure entries — fix the cause or delegate it):"
tail -n 10 "$LEDGER" | cut -c1-200

exit 0
