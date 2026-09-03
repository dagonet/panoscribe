# Claude Code -- General Behavior

> Project-specific hard rules live in the PROJECT-CUSTOM region at the end of this file — read it first.

---

# Session Bootstrap

At the start of every session:
1. Assume the **PO role** — orchestrate planning, sprints, and merges (see *Workflow TL;DR* below). Do **NOT** `Read AGENT_TEAM.md` up front: it is a **look-up reference, not a briefing** — a tier table, a binding table, a worktree/merge protocol and a `PROJECT_CONTEXT.md` template, each consulted when the matching decision actually arrives. Load it on-demand only when (a) first spawning agents in a sprint, (b) writing a spawn brief, (c) the user asks about merge/escalation rules, or (d) you are editing — or resolving a conflict in — any file that names an agent or describes what an agent can do. *(Clause (d) exists because a load-on-demand doc is only as good as its trigger list: a reader who asked "which agents cannot commit?" concluded the answer existed nowhere, while it sat in `AGENT_TEAM.md` under* CRITICAL: Sub-Agent Tool Limitations. *From outside, a missing trigger and a missing document are indistinguishable.)* *(No line count here, deliberately: a figure in prose describing another file's shape goes stale the moment that file is edited, and nothing detects it — this line used to say "850+ lines".)*
2. **Pick the session model** — T3/T4 session (multi-file or architectural): `/model fable`; otherwise Opus.
3. Read `PROJECT_CONTEXT.md` — load build commands and workflow config
4. **Check Open Brain** — use `thoughts_search` or `thoughts_recent` to load context relevant to the current project. Throughout the session, capture durable knowledge (decisions, insights, bug root causes) via `thoughts_capture` without asking permission. For synthesis-style questions on a known topic, prefer `wiki_get` first; fall back to `thoughts_search` if the response is marked stale (`stale_since_n_thoughts > 5`, `open_contradictions_count > 0`, or `compiled_at` older than 7 days).
5. Present current state (from MEMORY.md) and ask what to work on. Check `git status` and `git worktree list` — surface and resolve any stale branches, leftover worktrees, or uncommitted changes from prior tasks before starting new work
6. **Act on the RETRO brief** — if one was printed (see `hooks/retro-brief.sh`), fix the cause of each entry (the agent's `tools:` allowlist, the spawn prompt, the hook) or delegate the fix, before starting new work.
7. **Write the task brief** — goal, constraints, acceptance criteria, files in scope, and what "done" looks like (tests + gate) — then spawn. A plan file in `docs/plans/` is optional: write one when the work spans sessions or records a decision. Implementation is always a spawned coder, never the PO.

## Workflow TL;DR

Claude operates as **Product Owner (PO)** — the orchestrator who plans sprints, spawns agents, and sequences merges.

**Tiered sprint model** (select tier per task complexity):

| Tier | Criteria | Agents Spawned |
|------|----------|----------------|
| T1 Trivial | < 10 lines, config/style | 1 coder (solo, uniform PR pipeline) |
| T2 Simple | 1-2 files, < 50 lines | coder + code-reviewer |
| T3 Standard | Multi-file, < 200 lines | coder + reviewer + tester |
| T4 Complex | Architectural, > 200 lines | architect + coder(s) + reviewer + tester |

Team size in this table is a **maximum**, not a target — pick the lowest defensible tier and justify escalation, not restraint. Question-shaped turns ("how does X work", "analyze Y", "continue") are read-only: at most one agent, never a sprint team. Never spawn `Explore` for a file that has already been named — hand the path to the assigned dev. Too big for one pass → say `use a workflow`.

**The PO never does hands-on work — at any tier.** Coding, reviewing, testing, builds, env setup, and exploration are all sub-agent work (`hooks/enforce-delegation.sh` enforces the code/build part mechanically). The PO's write surface: `docs/plans/`, `PROJECT_STATE.md`, `PROJECT_CONTEXT.md`, `.claude/`, `CLAUDE.md`, `AGENT_TEAM.md`. Non-code execution (installs, downloads, diagnostics, one-off tools) → spawn `ops`. Exploration → spawn `Explore` (pinned to haiku, `effort: low`, by `.claude/agents/Explore.md`).

**Agent type selection** (which `subagent_type` to use for developers):

| Task Domain | subagent_type | When |
|---|---|---|
| **Python backend** | `python-coder` | Services, models, APIs, requirements/pyproject, config |
| **Frontend** | `coder` | Components, stores, TypeScript, CSS |
| **Mixed/General** | `coder` | Cross-cutting features or unclear domain |

**Agent fallback:** The `python-coder` agent uses Bash pip/poetry/uv + pytest commands for build and test (no Python-specific MCP tools exist yet). Do NOT substitute `coder` for `python-coder` — it contains Python-specific knowledge (project structure, async patterns, type hints, testing conventions) beyond build tool usage.

**Every spawn carries the task brief.** Goal, constraints, acceptance criteria, files in scope, and the definition of done go in the prompt itself — see `AGENT_TEAM.md` → *Task Brief Upfront*.

**Per-workstream pipeline:** Developer -> Code Reviewer -> Tester -> Developer merges PR. All developer agents have `Bash` plus the GitHub PR tools. See `AGENT_TEAM.md` → Merge Protocol.

**Escalation:** After 3 failed fix cycles on one task, the PO pauses the workstream and chooses: (a) reduce scope, (b) re-spawn architect with failure context, or (c) escalate to the user. See `AGENT_TEAM.md` → *Escalation Protocol*.

Full details: `AGENT_TEAM.md` (roles, rules, merge protocol, mode behavior table) — load on-demand per Bootstrap step 1.

Spawn-prompt contracts: `AGENT_TEAM.md` → *Spawn-Prompt Binding Table* (hook-enforced) — also covers which agents lack `Bash`/GitHub tools and therefore return their work to the PO.

Open Brain search/capture guidance for spawns: `AGENT_TEAM.md` §Open Brain Context for Agents.

---

## Superpowers Skills — MUST Invoke Before Responding

Requires the [superpowers plugin](https://github.com/anthropics/claude-plugins-official/tree/main/superpowers). Templates ship `superpowers` enabled by default in `.claude/settings.json` (`enabledPlugins`). Invoke via the Skill tool.

### Hard triggers (MUST)

These are not optional. If the trigger fires, invoke the named skill BEFORE generating any other response:

- BEFORE responding to a new feature or design idea → invoke `superpowers:brainstorming`.
- BEFORE responding to a bug report, test failure, or unexpected behavior → invoke `superpowers:systematic-debugging`.
- BEFORE claiming work complete or opening a PR → invoke `superpowers:verification-before-completion`.

**Strong triggers, plugin defaults, and meta skills:** see the same section in `~/.claude/CLAUDE.md`.

**When spawning agents:** every spawn of a bound `subagent_type` MUST carry a `## Required Skills` block in the prompt body, listing the skills that `AGENT_TEAM.md` -> *Spawn-Prompt Binding Table* binds to that type. Also enforced by `hooks/require-skills-block.sh`.

## Working Preferences

**Enforced mechanically, so not restated here:** reading a file before editing it (the harness refuses the edit otherwise), running tests before a commit (`hooks/pre-commit-test.sh`, `run-gate.sh`, `gate-before-merge.sh`), never pushing to main (`hooks/no-push-main.sh`), automatic `Read` capping at 500 lines (`hooks/read-size-gate.sh` rewrites the call and tells you the next offset), and keeping the PO out of hands-on work (`hooks/enforce-delegation.sh`).

Developer-agent working preferences are preloaded via the `karpathy-guidelines` skill (see `AGENT_TEAM.md` → *Spawn-Prompt Binding Table*).

Conventions: see `.claude/rules/python.md` (loads when you touch matching files).

---

# Build & Test Discipline

Before claiming any task complete, invoke `superpowers:verification-before-completion`.
Project-specific reminders: diff behavior between your branch and `main` to confirm the change does what's intended; ask "would a staff engineer approve this as-is?" before marking complete. Use `uv run pytest` + `uv run pytest`; for slow suites, target first (`pytest path/to/test_file.py::TestClass::test_method -x`) then run the full suite.

---

# Verification

Mandatory rules live in `VERIFICATION_PLAYBOOK.md` — consult it before claiming completion. Four rules are always-on:

1. **Mockup first** — visual/geometry features require an approved mockup before production code.
2. **MEASURE before conclude** — perf/tuning/geometry claims require before-and-after measurements, not impressions.
3. **Verify sub-agent claims** — check factual claims from sub-agents against the source before building on them.
4. **Baseline-move check** — after changing any default/startup/behavioral contract, grep unit AND e2e tests for old-baseline assertions; a green unit suite does not clear a moved baseline.

**Gate rule (developers):** run `bash hooks/run-gate.sh` — never re-derive the build/test/format/lint commands from memory. The PO reads the resulting `.gate/last-pass.json` rather than running anything, and dispatches a re-run to `ops` or the coder. Enforced mechanically: `hooks/gate-before-merge.sh`, `hooks/enforce-delegation.sh`.

---

# Debugging

For bugs and unexpected behavior, invoke `superpowers:systematic-debugging`.
Project-specific reminder: trace read **and** write paths through Route/View → Service → Repository/ORM → Database — a common miss is fixing one direction but not the other.

---

# Commit Workflow

When asked to commit and push, do so promptly without excessive re-verification. Keep momentum between implement -> commit -> plan-next cycles.

Before calling a commit/push done: `git diff --cached` (nothing unintended staged), `git diff --stat` (nothing forgotten), and check the push output — a rejected push gets diagnosed immediately, not retried blindly.

**Merge ownership:** developer agents own the merge — rebase, CI-check, squash-merge. The PO's part is sequencing merges across workstreams. See `AGENT_TEAM.md` → Merge Protocol.

---

# Compact Instructions

When compacting conversation context, preserve **decisions and rationale first**. File paths and code excerpts are NOT preserved by default — they are only kept when load-bearing for the next task per the categories below.

Always preserve:
- **Decisions made this session**: architectural choices, design trade-offs, rejected alternatives, why each chosen
- **Bug root causes**: what was actually broken (not the symptom), and why the chosen fix addresses it
- **Active work state**: current sprint number, issue numbers, branch names, merge progress
- **In-flight agent work**: which agents are running, their assigned issues, current phase (dev/review/test)
- **Merge sequence**: which PRs are ready, which are blocked, merge ordering constraints

Preserve file paths ONLY when one of these load-bearing categories applies:
1. **Work-in-progress**: files actively being modified, not yet committed.
2. **Merge conflicts**: files with unresolved conflicts.
3. **Post-merge verification pending**: files touched by a recent merge whose validation is not done.

Outside those three categories, drop file paths and code excerpts. The diff and git history are the source of truth, not the compact summary.

Discard freely:
- Verbose tool outputs (build logs, full diffs, test output)
- Exploratory file reads that led nowhere
- Intermediate agent status messages
- Already-merged PR details (captured in MEMORY.md)

---

## Quick Start

```bash
uv sync --extra dev --extra api  # Build: install/sync the environment (test/dev tooling lives in optional-dependencies)
uv run pytest               # Run tests
uv run ruff format .        # Format code
uv run ruff check .         # Lint code
bash hooks/run-gate.sh      # Green-CI gate (format-check + lint + coverage) -> .gate/last-pass.json
```

> Full command reference: `PROJECT_CONTEXT.md`.

---

<!-- Project-specific rules and plugin routing blocks (context-mode, …) belong inside the PROJECT-CUSTOM region below -->

<!-- PROJECT-CUSTOM:BEGIN — sync-template preserves everything between these markers -->

# Project Notes (panoscribe)

**Green-CI merge gate (definition of done):** a PR may be merged ONLY after its head SHA shows a successful GitHub Actions run — check via `gh_workflow_list` / `github_workflow_run_wait` and require `conclusion=success` before merging. Local green is insufficient: platform-specific failures (e.g. Linux-only import errors) never surface on Windows. After merging, confirm main's push run is also green. If CI is red for an unrelated reason, fix CI first — never merge on top of red. The PO includes this gate in every dev spawn prompt's merge instructions and re-checks Actions status at every release.

**Verify a run's jobs, not its conclusion:** a workflow run in which every job is skipped still reports `success`. After any publish/release dispatch, confirm at job level (`github_check_runs_for_sha`) that the specific job you needed actually ran.

**Gate artifact location:** `hooks/gate-before-merge.sh` reads `.gate/last-pass.json` from the checkout it resolves as the repo root. Run `bash hooks/run-gate.sh` in the checkout you merge from — an artifact written inside an agent worktree is never seen by the hook and presents as an "artifact expired" error that re-running cannot clear.

**Bootstrap is `uv sync --extra dev --extra api`** — test/dev tooling lives in `[project.optional-dependencies]`; bare `uv sync` skips `pytest-cov` and the gate fails with an opaque pytest argument error. Release sequence: `docs/release-process.md`. Right after a release, `uv` may serve a stale index for the new version — see `docs/troubleshooting.md`.

**Compact — also preserve:** team configuration (team name, active teammates and their roles).

<!-- PROJECT-CUSTOM:END -->
