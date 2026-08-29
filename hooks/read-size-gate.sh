#!/usr/bin/env bash
# PreToolUse hook: cap unbounded Read calls instead of blocking them.
#
# Matcher: Read
# Intent: Read results averaged 6 K chars with no `limit` on 5,032 of 10,336
# measured calls (docs/plans/2026-04-14-context-baseline.md). Blocking the call
# cost a round trip and taught the caller nothing; rewriting it is invisible and
# always makes progress.
#
# Decision rule (offset defaults to 0):
#   tool_input.limit present         -> silent pass (the caller bounded it)
#   size > BIG_FILE_BYTES            -> cap without counting lines (no offset
#                                       can bring the remainder under the cap,
#                                       and scanning every byte on a hook that
#                                       fires on every Read is not free)
#   file_lines - offset <= THRESHOLD -> silent pass
#   otherwise -> stdout a hookSpecificOutput with permissionDecision "allow",
#     updatedInput = the ORIGINAL tool_input plus limit=THRESHOLD, and an
#     additionalContext naming the offset to pass next. Exit 0.
#
# updatedInput REPLACES the whole input object, so tool_input is copied
# wholesale (Object.assign) — `pages` and any field a future Claude Code
# version adds survive untouched.
#
# Binary-ish extensions (images, PDFs, notebooks) are skipped: their Read
# result is not line-addressable and a limit would corrupt it.
#
# The hook never exits non-zero. Missing files, unreadable paths and malformed
# payloads are silent passes; Read will produce its own error. Log append to
# ~/.claude/state/read-size-gate.log is best-effort and never masks the
# decision.

THRESHOLD=500
# Above this size the cap is decided from the byte size alone — see below.
BIG_FILE_BYTES=10485760
LOG_FILE="$HOME/.claude/state/read-size-gate.log"

TOOL_INPUT=$(cat)

# v2.2.0: the decision engine below is an embedded node program (statSync, line
# count, updatedInput rewrite), so this hook needs node specifically. Without it
# it stays fail-open, but says so once instead of disappearing silently.
jlib="$(dirname "$0")/lib/json.sh"
if [ -f "$jlib" ]; then
  . "$jlib"
  json_require_node read-size-gate "$(json_session "$TOOL_INPUT")" || exit 0
fi
command -v node >/dev/null 2>&1 || exit 0

# ONE node process per Read call. The first version spawned five (four JSON
# parses plus the emitter) on a hook that fires on every Read; process startup
# dominated the hook's cost. The payload arrives on STDIN, never in argv, so a
# large tool_input cannot hit the platform argument-length caps.
printf '%s' "$TOOL_INPUT" | node -e '
try {
  var fs = require("fs");
  var payload = JSON.parse(fs.readFileSync(0, "utf8"));
  if (payload.tool_name !== "Read") process.exit(0);

  var input = payload.tool_input || {};
  var filePath = input.file_path;
  if (typeof filePath !== "string" || !filePath) process.exit(0);

  // The caller already bounded the read — nothing to do.
  if (input.limit != null) process.exit(0);

  // Not line-addressable: Read renders these as images, pages or notebook cells.
  if (/\.(png|jpe?g|gif|pdf|ipynb)$/i.test(filePath)) process.exit(0);

  var st;
  try { st = fs.statSync(filePath); } catch (e) { process.exit(0); }
  if (!st.isFile()) process.exit(0);

  var cap = Number(process.argv[1]);
  var logFile = process.argv[2];
  var bigBytes = Number(process.argv[3]);

  // offset defaults to 0. A non-numeric offset is treated as absent rather
  // than guessed at. The pre-PR3 script ignored offset entirely, so a Read
  // already near EOF was judged by the whole file length.
  var offset = Number(input.offset);
  if (!isFinite(offset) || offset < 0) offset = 0;

  var lines = null;
  var context;
  if (st.size > bigBytes) {
    // Do not read a huge file just to decide: at this size no offset can bring
    // the remainder under the cap, and counting lines would mean scanning
    // every byte inside a hook that runs on every Read.
    var mb = Math.round(st.size / (1024 * 1024));
    context = "File is " + mb + " MB; capped at " + cap +
      " lines starting at offset " + offset + "; pass offset=" +
      (offset + cap) + " to continue.";
  } else {
    var buf = fs.readFileSync(filePath);
    lines = 0;
    for (var i = 0; i < buf.length; i++) if (buf[i] === 10) lines++;
    if (lines - offset <= cap) process.exit(0);
    context = "Read capped at " + cap + " of " + lines +
      " lines starting at offset " + offset + "; pass offset=" +
      (offset + cap) + " to continue.";
  }

  // Best-effort log append. Failures never mask the decision.
  try {
    fs.mkdirSync(require("path").dirname(logFile), { recursive: true });
    fs.appendFileSync(logFile, [
      new Date().toISOString().replace(/\.\d+Z$/, "Z"),
      "CAP", cap, lines === null ? st.size + "B" : lines, filePath
    ].join("\t") + "\n");
  } catch (e) {}

  console.log(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "allow",
      updatedInput: Object.assign({}, input, { limit: cap }),
      additionalContext: context
    }
  }));
} catch (e) {}
' "$THRESHOLD" "$LOG_FILE" "$BIG_FILE_BYTES" 2>/dev/null

exit 0
