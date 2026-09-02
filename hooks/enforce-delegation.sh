#!/usr/bin/env bash
# enforce-delegation.sh — PreToolUse hook: the PO (main thread) never does
# hands-on work; sub-agents do all coding/building/testing.
#
# Matchers (two groups in settings.json):
#   Edit|Write|NotebookEdit  — deny main-thread edits outside the PO write surface
#   Bash                     — deny main-thread build/test-runner commands
#
# Discriminator: the hook stdin JSON contains `agent_id` ONLY when the call
# originates inside a subagent. agent_id present -> allow (subagents do the
# work). Absent -> main thread -> enforce.
#
# PO write surface (main-thread Edit/Write allowed): docs/plans/,
# PROJECT_STATE.md, PROJECT_CONTEXT.md, .claude/, CLAUDE.md, CLAUDE.local.md,
# AGENT_TEAM.md, and any path OUTSIDE the repo root (scratchpad, ~/.claude
# memory). Everything else (source code, tests, docs content) is agent work.
#
# Main-thread Bash: build/test runners (npm test, dotnet build, pytest,
# cargo test, playwright, mvn, gradle, go test) and hooks/run-gate.sh are
# denied — the coder runs the gate, the tester verifies, ops handles env
# work. The PO verifies via the .gate/last-pass.json artifact, never by
# running the suite. Evaluated per SEGMENT (split on && || ; & | newline);
# a segment whose first token is `git` or `gh` is EXEMPT — git/GitHub I/O is
# the PO's documented role (AGENT_TEAM.md), so `git add hooks/run-gate.sh`
# and `git commit -m "run pytest first"` pass, while `git add x && bash
# hooks/run-gate.sh` still denies on its second segment.
#
# Known limitations (both deliberate — this hook is fail-OPEN by contract):
#   * the split is quote-blind, so a separator INSIDE a quoted message
#     (`git commit -m "a; pytest -q"`) still splits and the tail is judged on
#     its own. Errs CLOSED, at parity with the pre-v2.1.5 whole-string match.
#     Pinned by a fixture.
#   * only `cd X` and `VAR=value` prefixes are stripped. Command wrappers —
#     `env VAR=x pytest`, `time pytest`, `nice pytest`, `xargs …` — are not,
#     so they pass. Errs OPEN, matching this hook's failure polarity: a
#     determined bypass is not the threat model, an accidental main-thread
#     `pytest` is.
#   * HEREDOC BODIES ARE STRIPPED before the split (v2.3.0), because a body is
#     data with an explicit terminator — `cat > plan.md <<EOF … npm test … EOF`
#     is authoring, not running. Quoted literals are NOT stripped: `bash -c
#     "npm test"` and `echo "npm test"` are the same syntactic shape, and
#     separating them needs a maintained wrapper allowlist whose every gap is a
#     new evasion channel. So `echo "npm test"` stays judged as written.
#
# THIS HOOK DOES NOT SOURCE hooks/lib/git-cmd.sh, AND THAT IS THE DESIGN. The
# three git gates there are fail-CLOSED and scan the whole command string on
# purpose, so `bash -c "git push origin main"` cannot evade them and a false
# positive on `echo "git push origin main"` costs one retry. Opposite polarity,
# opposite trade — do not "unify" the two by giving git-cmd.sh this stripping.
#
# Escape hatch: create `.claude/delegation-off` at the repo root to disable
# (also the fix if a pre-agent_id CLI ever denies subagent calls).
#
# FAILURE POLARITY — deliberately fail-OPEN:
#   * Do NOT wrap this hook with the exit-2-on-127 pattern. A missing script
#     would then block ALL Edit/Write INCLUDING subagents' — total paralysis
#     (same class as the SubagentStop stop-gate rule).
#   * Registration uses a WARN-wrapper instead: on 127 it prints a stderr
#     diagnostic ("delegation enforcement offline — run /sync-template") and
#     exits 0, so absence is visible but never blocking.
#   * Internal parse failures exit 0 (pass-through) — never block a subagent
#     on malformed stdin.

if [ "${1:-}" = "--help" ]; then
  cat <<'EOF'
Usage: registered as a Claude Code PreToolUse hook (settings.json).
  Matcher "Edit|Write|NotebookEdit": denies main-thread edits outside the PO
  write surface (docs/plans/, PROJECT_STATE.md, PROJECT_CONTEXT.md, .claude/,
  CLAUDE.md, CLAUDE.local.md, AGENT_TEAM.md, paths outside the repo).
  Matcher "Bash": denies main-thread build/test-runner commands and
  hooks/run-gate.sh.
Subagent calls (stdin contains agent_id) always pass. Disable by creating
.claude/delegation-off at the repo root.
EOF
  exit 0
fi

INPUT=$(cat)

# v2.2.0: the classifier below is an embedded node program, so this hook needs
# node specifically. Without it it stays fail-open, but says so once.
jlib="$(dirname "$0")/lib/json.sh"
if [ -f "$jlib" ]; then
  . "$jlib"
  json_require_node enforce-delegation "$(json_session "$INPUT")" || exit 0
fi
command -v node >/dev/null 2>&1 || exit 0

DECISION=$(node -e '
let raw = "";
process.stdin.on("data", d => raw += d);
process.stdin.on("end", () => {
  let j;
  try { j = JSON.parse(raw); } catch (e) { console.log("PASS"); return; }

  // Subagent calls always pass — agent_id is present only inside subagents.
  if (j.agent_id) { console.log("PASS"); return; }

  const tool = j.tool_name || "";
  const input = j.tool_input || {};
  const cwd = (j.cwd || process.cwd()).replace(/\\/g, "/");

  if (tool === "Bash" || tool === "PowerShell") {
    // v2.3.0: strip HEREDOC BODIES before anything else looks at the string.
    // A heredoc body is DATA being written to a file, not a command list, and
    // it is the only quoting form with an EXPLICIT TERMINATOR -- so it can be
    // removed without guessing where it ends. Measured: the whole of this
    // false-deny traffic here in the sampled window was authoring a document
    // that happens to CONTAIN "pytest -q" or "npm test" on a line of its own.
    // The opening line is KEPT (the redirection and anything after it on that
    // line are real command text); only the body and its terminator go.
    // Deliberately NOT extended to quoted literals -- see the header: telling
    // bash -c "..." from echo "..." needs a maintained wrapper allowlist, and
    // every wrapper missing from it becomes an evasion channel that is closed
    // today. An UNTERMINATED heredoc matches nothing and is judged as before.
    // (No apostrophes in this block: the program is a single-quoted shell
    // argument. \x27 is the quote character where a regex needs one.)
    // The leading (^|[^<]) is NOT decoration: without it `cat f <<<EOF` matches
    // starting at the SECOND `<`, so a here-STRING reads as a heredoc opener and
    // the real commands after it are swallowed. Caught by the fixture arm that
    // puts a runner after a here-string, not by reading the regex.
    const stripHeredocs = (c) => c.replace(
      /(^|[^<])(<<-?[ \t]*(["\x27]?)([A-Za-z_][A-Za-z0-9_]*)\3[^\n]*\n)[\s\S]*?\n[ \t]*\4[ \t]*(?=\n|$)/g,
      "$1$2");
    const cmd = stripHeredocs(input.command || "");

    // v2.1.5: evaluate per SEGMENT, not against the whole command string.
    // A segment whose first token is git or gh is exempt (see header).
    // NOTE: this block is a single-quoted shell string -- no apostrophes.
    const denySegment = (seg) => {
      // strip leading VAR=value assignments, so CI=1 pytest is a pytest segment

      const s = seg.replace(/^\s+/, "").replace(/^(\w+=\S*\s+)+/, "").trim();
      if (!s) return false;
      if (/^(git|gh)\b/.test(s)) return false;
      return (
        /^npm\s+test\b/.test(s) ||
        /^npm\s+run\s+(test|build|e2e|coverage)\b/.test(s) ||
        /^npx\s+(vitest|jest|playwright)\b/.test(s) ||
        /^pytest\b/.test(s) ||
        /^cargo\s+(test|build|run)\b/.test(s) ||
        /^dotnet\s+(build|test|run)\b/.test(s) ||
        /^mvn\s/.test(s) ||
        /^(\.\/)?gradlew?\b/.test(s) ||
        /^go\s+test\b/.test(s) ||
        // v2.2.1: anchored like every sibling above. Unanchored, this matched
        // the STRING "hooks/run-gate.sh" anywhere in the command -- including
        // inside the applied_files JSON that /sync-template step 7 assembles,
        // which necessarily names that very file. The more faithfully the skill
        // was followed, the more certainly the sync command itself was denied.
        // (No apostrophes in this block: the whole program is a single-quoted
        // shell argument, so one would end the string and disable the hook.)
        // This hook is fail-OPEN workflow policy: a false DENY costs real work,
        // so patterns match command position only. The three git gates are
        // fail-CLOSED and deliberately do the opposite -- see hooks/lib/git-cmd.sh.
        // The leading class is PATH characters only, not \S*: with \S* a
        // pretty-printed JSON line whose first token merely ENDS in the path
        // (a quote, a brace, a colon before it) still matched, which is the
        // hole this anchor was closing.
        /^(bash\s+|sh\s+)?[\w./\\-]*hooks\/run-gate\.sh\b/.test(s)
      );
    };

    const deny = cmd
      .split(/&&|\|\||[;&|\n]/)
      .map(seg => seg.replace(/^\s*cd\s+\S+\s*/, ""))
      .some(denySegment);
    console.log(deny ? "DENY_BASH\t" + cwd : "PASS");
    return;
  }

  // Edit | Write | NotebookEdit
  let p = input.file_path || input.notebook_path || "";
  if (!p) { console.log("PASS"); return; }
  p = p.replace(/\\/g, "/");

  const allowPatterns = [
    /(^|\/)docs\/plans\//,
    /(^|\/)PROJECT_STATE\.md$/,
    /(^|\/)PROJECT_CONTEXT\.md$/,
    /(^|\/)\.claude\//,
    /(^|\/)CLAUDE\.md$/,
    /(^|\/)CLAUDE\.local\.md$/,
    /(^|\/)AGENT_TEAM\.md$/,
  ];
  if (allowPatterns.some(re => re.test(p))) { console.log("PASS"); return; }

  // Paths outside the repo root (scratchpad, ~/.claude memory) are PO-legal.
  // Repo root detection happens in the shell wrapper (git); here we only
  // handle the relative-path case: a relative path is inside the repo.
  console.log("CHECK_ROOT\t" + p + "\t" + cwd);
});
' <<<"$INPUT" 2>/dev/null) || exit 0

case "$DECISION" in
  PASS|"")
    exit 0
    ;;
  DENY_BASH*)
    HOOK_CWD=$(printf '%s' "$DECISION" | cut -f2)
    FILE_PATH=""
    ;;
  CHECK_ROOT*)
    FILE_PATH=$(printf '%s' "$DECISION" | cut -f2)
    HOOK_CWD=$(printf '%s' "$DECISION" | cut -f3)
    ;;
  *)
    exit 0
    ;;
esac

# Kill-switch at the repo root of the session cwd (gates BOTH deny paths).
REPO_ROOT=$(git -C "$HOOK_CWD" rev-parse --show-toplevel 2>/dev/null | tr '\\' '/')
if [ -n "$REPO_ROOT" ] && [ -f "$REPO_ROOT/.claude/delegation-off" ]; then
  exit 0
fi

if [ -z "$FILE_PATH" ]; then
  # Bash deny path
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"DELEGATE: builds/tests run inside agents — coder runs the gate, tester verifies, ops handles env/tool work. The PO verifies via the .gate/last-pass.json artifact. Escape hatch: create .claude/delegation-off."}}\n'
  exit 0
fi

# Absolute path outside the repo root -> PO-legal (scratchpad, memory).
case "$FILE_PATH" in
  /*|[A-Za-z]:/*)
    if [ -n "$REPO_ROOT" ]; then
      case "$FILE_PATH" in
        "$REPO_ROOT"/*) ;;                       # inside repo -> fall through to deny
        *) exit 0 ;;                             # outside repo -> allow
      esac
    fi
    ;;
esac

printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"DELEGATE: PO never edits code. Spawn coder (code and docs), ops (env/files), tester (verification). PO write surface: docs/plans/, PROJECT_STATE.md, PROJECT_CONTEXT.md, .claude/, CLAUDE.md, AGENT_TEAM.md. Escape hatch: create .claude/delegation-off."}}\n'
exit 0
