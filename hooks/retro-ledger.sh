#!/usr/bin/env bash
# SubagentStop hook: records subagent FAILURES in a per-project retro ledger.
# No matcher — it runs for every subagent stop.
#
# Stdin fields used (SubagentStop payload):
#   cwd                    project root the subagent ran in
#   agent_type             e.g. coder, code-reviewer, tester
#   agent_id               e.g. agent-a003c937d78f9f557
#   agent_transcript_path  JSONL transcript of the SUBAGENT (not the session)
#   session_id, last_assistant_message  (documented; unused here)
#
# What counts as a failure: a `tool_result` block whose text matches
#   No such tool available | BLOCKED: | DELEGATE: | CONTRACT VIOLATION | hook error
# Hook blocks reach the agent as tool_result text too, so text matching covers
# both the `is_error: true` case and the hook-block case in one pass. Prose in
# an assistant message never counts — only tool_result blocks are inspected.
#
# Output (only when at least one failure was found), appended as ONE line to
#   $HOME/.claude/projects/<project-slug>/memory/retro.md
#   YYYY-MM-DD HH:MM | <agent_type> | <agent_id> | dead=[a,b] | blocks=[x.sh] | errors=<n>
#
# <project-slug> replicates Claude Code's auto-memory directory rule, measured
# against the real dirs under ~/.claude/projects: EVERY one of  :  \  /  .  _
# becomes a dash. Verified against existing directories on this host:
#   G:\git\claude-code-toolkit  ->  G--git-claude-code-toolkit
#   C:\Users\DarkNite\.claude   ->  C--Users-DarkNite--claude
# The colon contributes its own dash — it is replaced, not stripped.
#
# FAIL-OPEN BY CONSTRUCTION: this hook must NEVER exit non-zero and never
# blocks a stop. Missing node, missing/unreadable transcript, unparseable
# payload, unwritable memory dir — all exit 0 silently. Because it cannot
# block, its settings.json registration is deliberately NOT wrapped in the
# exit-127 fail-closed wrapper used for the PreToolUse gates.

set -u

INPUT=$(cat 2>/dev/null || true)

printf '%s' "$INPUT" | node -e '
const fs = require("fs");
const os = require("os");
const path = require("path");

let raw = "";
process.stdin.on("data", c => raw += c);
process.stdin.on("end", () => {
  let p;
  try { p = JSON.parse(raw); } catch (e) { return; }
  if (!p || typeof p !== "object") return;

  const tp = p.agent_transcript_path || "";
  if (!tp) return;
  let txt;
  try { txt = fs.readFileSync(tp, "utf8"); } catch (e) { return; }

  const FAIL = /No such tool available|BLOCKED:|DELEGATE:|CONTRACT VIOLATION|hook error/;
  // A hook block reaches the agent as ordinary tool_result text, so it is counted
  // even without is_error — but ONLY in its real shape: the literal "hook error",
  // or a line that STARTS with "BLOCKED:". Anything else must carry is_error.
  // Without that second condition, reading hooks/*.sh or grepping for "BLOCKED:"
  // would log a failure for a tool call that succeeded.
  const HOOKBLOCK = /hook error|^BLOCKED:/m;
  const DEAD = /No such tool available:\s*([A-Za-z0-9_\-]+)/g;
  // Hook script names are read from the bracketed hook command only
  // (`PreToolUse:Bash hook error: [bash 'hooks/x.sh'; …]: BLOCKED: …`), never from
  // arbitrary .sh tokens in the surrounding prose or in a tool output.
  const HOOKCMD = /\[[^\]]*\]/g;
  const SCRIPT = /([A-Za-z0-9_\-]+\.sh)/g;

  const dead = new Set();
  const blocks = new Set();
  let errors = 0;

  for (const line of txt.split(/\r?\n/)) {
    if (!line.trim()) continue;
    let o;
    try { o = JSON.parse(line); } catch (e) { continue; }
    const content = o && o.message && o.message.content;
    if (!Array.isArray(content)) continue;
    for (const b of content) {
      if (!b || b.type !== "tool_result") continue;
      const text = typeof b.content === "string" ? b.content : JSON.stringify(b.content || "");
      const isBlock = HOOKBLOCK.test(text);
      if (!isBlock && !(b.is_error === true && FAIL.test(text))) continue;
      errors++;
      let m;
      DEAD.lastIndex = 0;
      while ((m = DEAD.exec(text)) !== null) dead.add(m[1]);
      if (isBlock) {
        HOOKCMD.lastIndex = 0;
        let cmd;
        while ((cmd = HOOKCMD.exec(text)) !== null) {
          SCRIPT.lastIndex = 0;
          while ((m = SCRIPT.exec(cmd[0])) !== null) blocks.add(path.basename(m[1]));
        }
      }
    }
  }
  if (errors === 0) return;

  // Bounded rendering: one pathological run must not produce a line that dwarfs
  // the rest of the ledger (and, through retro-brief, the session context).
  const CAP = 5;
  const render = set => {
    const all = [...set].sort();
    const shown = all.slice(0, CAP);
    if (all.length > CAP) shown.push("+" + (all.length - CAP) + " more");
    return "[" + shown.join(",") + "]";
  };

  const cwd = p.cwd || process.cwd();
  const slug = cwd.replace(/[:\\\/._]/g, "-");
  // Base-dir helper — MUST stay identical in hooks/retro-brief.sh.
  // Under Git Bash, HOME can arrive as /c/Users/x; Windows node resolves a
  // leading "/" against the CURRENT DRIVE, which would silently write the ledger
  // to G:\Users\x instead of C:\Users\x. Normalise /<letter>/ -> <letter>:/ on
  // win32 only (on POSIX, /c/... is a legitimate absolute path).
  const winify = s => (process.platform === "win32" ? s.replace(/^\/([A-Za-z])\//, "$1:/") : s);
  const home = process.env.CLAUDE_MEMORY_HOME
    || (process.env.HOME && winify(process.env.HOME))
    || os.homedir();
  const dir = path.join(home, ".claude", "projects", slug, "memory");

  const d = new Date();
  const pad = n => String(n).padStart(2, "0");
  const stamp = d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
                " " + pad(d.getHours()) + ":" + pad(d.getMinutes());

  const entry = [
    stamp,
    p.agent_type || "unknown",
    p.agent_id || "unknown",
    "dead=" + render(dead),
    "blocks=" + render(blocks),
    "errors=" + errors
  ].join(" | ") + "\n";

  try {
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(path.join(dir, "retro.md"), entry);
  } catch (e) { /* an unwritable memory dir must never break a stop */ }
});
' 2>/dev/null

exit 0
