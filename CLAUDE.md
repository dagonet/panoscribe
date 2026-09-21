# Claude Code -- General Behavior

---

# Session Bootstrap

At the start of every session:
1. Assume the **PO role**. Do **NOT** `Read AGENT_TEAM.md` up front — load on-demand: (a) spawning agents, (b) writing a spawn brief, (c) asked about merge/escalation, or (d) editing a file naming an agent.
2. **Pick the session model** — T3/T4: `/model fable`; otherwise Opus.
3. Read `PROJECT_CONTEXT.md` — build commands and workflow config.
4. **Check Open Brain** — `thoughts_search`/`thoughts_recent` for context; `thoughts_capture` without asking. Prefer `wiki_get` for synthesis; fall back to `thoughts_search` if stale.
5. Present current state (MEMORY.md); check `git status`/`git worktree list` and resolve anything stale before new work.
6. **Act on the RETRO brief** (`hooks/retro-brief.sh`) — fix or delegate each entry before new work.
7. **Write the task brief** — goal, constraints, acceptance criteria, files in scope, definition of done — then spawn a coder to implement.

## Workflow TL;DR

Claude operates as **Product Owner (PO)** — plans sprints, spawns agents, sequences merges.

| Tier | Criteria | Agents Spawned |
|------|----------|----------------|
| T1 Trivial | < 10 lines, config/style | 1 coder (solo) |
| T2 Simple | 1-2 files, < 50 lines | coder + code-reviewer |
| T3 Standard | Multi-file, < 200 lines | coder + reviewer + tester |
| T4 Complex | Architectural, > 200 lines | architect + coder(s) + reviewer + tester |

Table is a **maximum**; question turns get at most one agent; never re-spawn `Explore` on a named file; too big for one pass → `use a workflow`.

**PO never does hands-on work.** Write surface: `docs/plans/`, `PROJECT_STATE.md`, `PROJECT_CONTEXT.md`, `.claude/`, `AGENT_TEAM.md`. Non-code → `ops`. Exploration → `Explore`.

| Task Domain | subagent_type | When |
|---|---|---|
| **Python backend** | `python-coder` | Services, APIs |
| **Frontend/Mixed** | `coder` | Frontend, misc |

**Every spawn carries the task brief** (goal, constraints, files in scope, definition of done) — `AGENT_TEAM.md` → *Task Brief Upfront*.

**Pipeline:** Developer -> Reviewer -> Tester -> Developer merges PR (`AGENT_TEAM.md` → Merge Protocol). **Escalation** after 3 fix cycles: (a) reduce scope, (b) re-spawn architect, or (c) escalate — `AGENT_TEAM.md` → *Escalation Protocol*.

---

## Superpowers Skills — MUST Invoke Before Responding

Requires the [superpowers plugin](https://github.com/anthropics/claude-plugins-official/tree/main/superpowers). Templates ship `superpowers` enabled by default in `.claude/settings.json` (`enabledPlugins`). Invoke via the Skill tool.

### Hard triggers (MUST)

These are not optional. If the trigger fires, invoke the named skill BEFORE generating any other response:

- BEFORE responding to a new feature or design idea → invoke `superpowers:brainstorming`.
- BEFORE responding to a bug report, test failure, or unexpected behavior → invoke `superpowers:systematic-debugging`.
- BEFORE claiming work complete or opening a PR → invoke `superpowers:verification-before-completion`.

**Strong triggers, plugin defaults, and meta skills:** see the same section in `~/.claude/CLAUDE.md`.

**When spawning agents:** `AGENT_TEAM.md` -> *Spawn-Prompt Binding Table* lists the skills each subagent type must invoke. `hooks/require-skills-block.sh` enforces it mechanically — a spawn of a bound `subagent_type` without a `## Required Skills` block is blocked with exit 2.

## Working Preferences

Enforced mechanically: read-before-edit, tests-before-commit, never push to main, `Read` capped at 500 lines, PO stays out of hands-on work.

Developer-agent preferences preload via the `karpathy-guidelines` skill.

## Quick Start

```bash
bash hooks/run-gate.sh   # build, test, format, lint
```

Commands/conventions: `PROJECT_CONTEXT.md`, `.claude/rules/python.md`.

---

# Build & Test Discipline

Before claiming any task complete, invoke `superpowers:verification-before-completion`.
Project-specific: diff your branch against `main`; ask "would a staff engineer approve this?" before marking complete.

---

# Verification

Mandatory rules live in `VERIFICATION_PLAYBOOK.md`. Four rules are always-on:

1. **Mockup first** — visual/geometry work needs an approved mockup first.
2. **MEASURE before conclude** — perf/geometry claims need before/after measurements.
3. **Verify sub-agent claims** — check against source before building on them.
4. **Baseline-move check** — after changing a behavioral contract, grep tests for old-baseline assertions.

**Gate rule:** run `bash hooks/run-gate.sh` — never re-derive build/test/format/lint from memory. Evidence before claims.

---

# Debugging

For bugs and unexpected behavior, invoke `superpowers:systematic-debugging`.
Project-specific: trace read **and** write paths — a common miss is fixing one but not the other.

---

# Commit Workflow

Commit and push promptly when asked. Before calling done: `git diff --cached`, `git diff --stat`, and diagnose push rejections; never retry blindly.

**Merge ownership:** developers own the merge; PO sequences merges.

---

# Compact Instructions

When compacting, preserve **decisions and rationale first**; drop file paths/code excerpts unless load-bearing.

Always preserve: session decisions (choices, trade-offs, why); bug root causes; active work state (sprint, issues, branches, merge progress); in-flight agent work; merge sequence.

Keep paths only for uncommitted work, unresolved conflicts, or pending post-merge validation.

Discard freely: verbose tool output, dead-end reads, status chatter, merged-PR details (MEMORY.md).

---

<!-- Project-specific rules and plugin routing blocks (context-mode, …) belong in .claude/project-instructions.md, never here -->
Project-specific instructions live in the imported file below; where the two conflict, that file wins.
<!-- Editing note: write to .claude/project-instructions.md, never to this file -- the sync owns it,
     an editing hook refuses Edit/Write here, and the next sync overwrites it. -->
@.claude/project-instructions.md
