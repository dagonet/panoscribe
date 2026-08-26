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
# running the suite.
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
    const cmd = (input.command || "");
    const deny =
      /(^|[;&|]\s*)npm\s+test\b/.test(cmd) ||
      /(^|[;&|]\s*)npm\s+run\s+(test|build|e2e|coverage)\b/.test(cmd) ||
      /(^|[;&|]\s*)npx\s+(vitest|jest|playwright)\b/.test(cmd) ||
      /(^|[;&|]\s*)pytest\b/.test(cmd) ||
      /(^|[;&|]\s*)cargo\s+(test|build|run)\b/.test(cmd) ||
      /(^|[;&|]\s*)dotnet\s+(build|test|run)\b/.test(cmd) ||
      /(^|[;&|]\s*)mvn\s/.test(cmd) ||
      /(^|[;&|]\s*)(\.\/)?gradlew?\b/.test(cmd) ||
      /(^|[;&|]\s*)go\s+test\b/.test(cmd) ||
      /hooks\/run-gate\.sh/.test(cmd);
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

printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"DELEGATE: PO never edits code. Spawn coder (code), doc-generator (docs), ops (env/files), tester (verification). PO write surface: docs/plans/, PROJECT_STATE.md, PROJECT_CONTEXT.md, .claude/, CLAUDE.md, AGENT_TEAM.md. Escape hatch: create .claude/delegation-off."}}\n'
exit 0
