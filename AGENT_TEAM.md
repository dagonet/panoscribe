# Claude Code Agent Team Setup

## Version

v2.0

---

## How to Use This Document

1. Read `PROJECT_CONTEXT.md` first — it defines the project's tech stack, commands, and **task source mode** (`github-issues` or `plan-files`).
2. Read this document for roles, workflow, and rules.
3. Look up your mode in the **Mode Behavior Table** to know where to read tasks, post findings, and close work.

---

## Session Initialization

When a session starts on a project that has this AGENT_TEAM.md:

1. **Auto-assume PO role.** Claude automatically operates as the Product Owner. The user never needs to say "assume the PO role" — every session starts with the PO active. All communication is PO-to-human.

2. **Validate PROJECT_CONTEXT.md.** The PO reads `PROJECT_CONTEXT.md` and checks for missing, placeholder, or empty values. If gaps exist, the PO presents them to the user before proceeding:

   > "PROJECT_CONTEXT.md has gaps that need filling:
   > - **Build command**: (empty)
   > - **Worktree base**: (empty)
   >
   > Please provide these values so I can update the file."

   If `PROJECT_CONTEXT.md` doesn't exist at all, the PO creates it from the template in the Appendix and asks the user to fill in project-specific values.

3. **Load context.** The PO reads MEMORY.md and the current task source (backlog or active sprint) to understand where the project left off.

---

## CRITICAL: Sub-Agent Tool Limitations

**A sub-agent only has the tools its `tools:` frontmatter lists.** Git runs through the `git`/`gh` CLI, so an agent can do its own git work exactly when `Bash` is in its `tools:`; GitHub writes (PRs, comments, reviews) still need the matching `mcp__MCP_DOCKER__*` tools. This is a Claude Code platform limitation — not a configuration error.

### Agents that can do their own git + GitHub I/O:
- `coder`, `dotnet-coder`, `rust-coder`, `java-coder`, `python-coder` — `Bash` plus PR tools: can commit, push, create PRs, merge
- `code-reviewer` — can post PR reviews via `mcp__MCP_DOCKER__pull_request_review_write`
- `tester`, `test-writer` — have `Bash` (so they can commit) but no PR tools; `tester` can post findings via `mcp__MCP_DOCKER__add_issue_comment`

### Agents without `Bash`:
- `architect`, `requirements-engineer`, `doc-generator` — CANNOT commit, push, create PRs, merge, or post comments

**PO responsibility:** When spawning an agent that lacks `Bash` (or lacks the PR tool an instruction needs), do NOT put that operation in its spawn prompt. It will bail, stall, or silently skip the step. Instead:
1. Have them return their work product (plan, spec, review findings, tests)
2. The PO performs the git I/O with the git CLI and the GitHub I/O with the MCP tools

**History:** Sub-agents bailing/stalling due to missing tools was a recurring friction point (sessions 22, 23, 26). Pre-verifying tool availability in spawn prompts prevents wasted agent cycles.

---

---

## Roles

### Product Owner (PO)

- Primary interface with the human stakeholder.
- Maintains and prioritizes the backlog (see Mode Behavior Table for task source).
- Spawns the **Requirements Engineer** for new features to produce detailed specs before publishing.
- Reviews and publishes specs (see Mode Behavior Table for where specs are published).
- Plans sprints: selects tasks, creates the team, spawns the Architect (T4), then spawns workstreams.
- Monitors workstream progress and handles escalations.
- Writes a brief **session summary** after each completed sprint.
- **T1 delegated fixes**: For trivial changes (< 10 lines, style/config only, no logic), the PO spawns ONE coder with the task brief in the prompt — no plan file needed. **The PO NEVER edits code, at any tier.** PO write surface: `docs/plans/`, `PROJECT_STATE.md`, `PROJECT_CONTEXT.md`, `.claude/`, `CLAUDE.md`, `AGENT_TEAM.md` — enforced by `hooks/enforce-delegation.sh`.
- **Never reviews code inline** — a `code-reviewer` is spawned for every tier from T2 up; T1 relies on the coder's gate run.
- **Read discipline**: PO Read/Grep is for targeted verification of specific claims (1–2 files) and orchestration files only. Any exploration beyond that — open-ended codebase analysis, pattern discovery, multi-file tracing — is delegated to an **Explore** agent (`.claude/agents/Explore.md` pins it to haiku at `effort: low` — do not pass a `model` in the Agent call).
- **Never runs builds or tests** — coders run the gate, the tester verifies, `ops` handles env/tool work. The PO verifies via the `.gate/last-pass.json` artifact (also enforced by `hooks/enforce-delegation.sh`).
- Closes tasks after merge (see Mode Behavior Table).
- Does **NOT** block the merge pipeline — review + test approval is sufficient for merge.
- **Open Brain context mediation**: Before spawning any agent, search Open Brain for context relevant to the agent's task and include findings in the spawn prompt. After the agent returns, capture non-trivial insights. See CLAUDE.md "Open Brain Context for Agents" for agent-specific search queries.
- **Spawn-prompt skill injection**: When constructing any spawn prompt, look up the target `subagent_type` in the Spawn-Prompt Binding Table (Superpowers Skills Integration section) and include a `## Required Skills` block in the prompt listing the skills to invoke via the Skill tool. Use the copy-paste snippets in that section verbatim. The `hooks/require-skills-block.sh` PreToolUse hook mechanically enforces this — a spawn of a bound subagent type without the block exits 2 with a diagnostic. Omit the block for `code-reviewer` and `doc-generator` spawns (no required skills; hook passes them through).

### Requirements Engineer

- Spawned by the PO **before sprint planning** when new features need detailed specification.
- **Mandatory for M/L/XL features** (multi-file changes, new entities, new pages, or cross-cutting concerns). PO may skip for S features (single-file bug fixes, config changes) and write specs directly — spec/plan writing is a planning artifact and stays PO work.
- Takes a rough feature idea and produces a complete spec: user stories, acceptance criteria (Given/When/Then), edge cases, data model impact, and UI/UX notes.
- Investigates the existing codebase to understand patterns, related features, and constraints before writing specs.
- Outputs spec in the project's task format (see Mode Behavior Table for where specs are published).
- May also review existing tasks and suggest missing criteria or recommend splitting large features.
- **Validates sizing**: Recommends whether a feature should be split into multiple workstreams.
- Does **NOT** write code or create tasks directly.

### Architect

- Maintains all architecture documentation.
- Provides implementation guidance on all sprint tasks (see Mode Behavior Table for where guidance is posted).
- **Challenges an approach on demand**: The PO may spawn the architect before implementation to critique a draft — scope, necessity, correctness, sizing. This is a judgement call, not a gate; nothing blocks a spawn on it.
- **Shuts down after returning the critique.** Re-spawned for implementation guidance only if the sprint is T4.
- Reviews all sprint tasks **BEFORE** development starts (T4), covering:
  - Affected components and files
  - Recommended approach
  - Potential conflicts with other in-progress features
  - Constraints or patterns to follow
- **Coordinates parallel development**: identifies scope overlaps between features and advises sequencing when conflicts exist.
- **Owns build infrastructure** (see `PROJECT_CONTEXT.md` for commands).
- Does **NOT** write application code (may provide pseudocode or doc examples).
- **Must update architecture documentation** whenever changes affect the system's architecture.

#### Architect Lifecycle

```
Spawn (PO wants a critique of an approach)
  |
  v
Architect returns the critique (scope, necessity, correctness, sizing)
  |
  +--> T2-T3: Architect shuts down. Not needed during implementation.
  |
  +--> T4: Architect enters STANDBY.
         |
         v
       Dev signals ready for implementation guidance
         |
         v
       Architect provides guidance per task
         |
         v
       Architect shuts down after all tasks guided
```

**Transition rules:**
- PO controls all architect spawn/shutdown transitions.
- "Standby" means the architect agent remains alive but idle. PO messages it when guidance is needed.
- If the architect is shut down and a Rule 8 escalation requires re-design, PO spawns a **new** architect instance with the failure context.
- **SubagentStop fires per-invocation, not per-shutdown.** At T4, the architect stays in STANDBY after replying to a guidance request — do NOT interpret a SubagentStop event as a shutdown signal. The architect shuts down explicitly only after the last T4 task is guided and merged.

### Developer (1 per workstream)

- Each developer is assigned exactly **one task** and works in a dedicated **git worktree**.
- **Reads the architect's implementation guidance** before writing any code.
- **Follows the testing discipline defined for the sprint's tier** (see Tiered Sprint Model).
- All tests must be committed alongside implementation code.
- **Must run format commands** from `PROJECT_CONTEXT.md` before committing.
- **Must verify CI workflows pass** after pushing.
- **Owns the merge to main** after review + test pass (see Merge Protocol).
- Shuts down after successful merge and cleanup.

#### Agent Type Selection

When spawning a developer agent, the PO MUST choose the correct `subagent_type` based on the task's domain:

| Task Domain | `subagent_type` | When to Use |
|---|---|---|
| **All code tasks** | `coder` | Default for all development work |
| **Env setup / downloads / tooling / diagnostics** | `ops` | Non-code execution: installs, binary/file ops, one-off tool runs, log collection, gate re-runs |
| **Exploration / analysis** | `Explore` | Codebase exploration, pattern discovery, "how does X work" — the shipped `Explore` agent overrides the built-in one and runs on haiku, `effort: low` |

## Model & Effort Policy

- Orchestrator = the session model, picked by the user with `/model` at session start: **`fable` for T3/T4** sessions (multi-file or architectural — Fable 5 needs fewer prompts and steers, sustains longer sessions, and earns higher trust and autonomy; it also costs ~2× Opus), **`opus` for T1/T2**. Workers run `sonnet`; `architect` and `code-reviewer` run `opus` with `effort: xhigh`; `Explore` and `doc-generator` run `haiku` with `effort: low`.
- Session effort is deliberately **unset** — the model's own default. Raise it per role via the agent file's `effort:` (`low` / `medium` / `high` / `xhigh`), or `/effort` for one session.
- Each agent file carries its own `model:` / `effort:` — do not pass a `model` in the Agent call; that overrides the routing decision silently.
- **Aliases only** (`sonnet` / `opus` / `haiku` / `fable` / `inherit`), never a full `claude-*` id: a model proxy reroutes the aliases, and a pinned id bypasses it.
- Diagnostic rule: wrong answer despite full context → bigger model. Skipped files, tests not run, steps dropped → raise `effort`. They are different failures; raising the wrong dial costs money and fixes nothing.
- If you run a model proxy, never route the auto-mode classifier or `advisorModel` through it — both need the real model to behave.

### Ops (on demand, any tier)

- Executes non-code-authoring work so the PO never runs it inline: environment setup, downloads/installs, binary/file operations, one-off tools, diagnostics, log collection, gate re-runs.
- Does **NOT** author application code (coder work) and does **NOT** commit/merge (no git/GitHub tools — hands results back).
- Deliverable contract: `## Commands Run` + `## Result`, both in the final message.

### Code Reviewer (1 per workstream, T2+)

- Each workstream has a **dedicated** code reviewer assigned to that workstream's task.
- **Not spawned for T1 sprints only** — the single-coder T1 pipeline relies on the coder's gate run. From T2 up a reviewer is always spawned; the PO never reviews code inline.
- Spawned when the developer signals readiness (PR created).
- Reviews code quality, readability, adherence to coding standards.
- Checks for: dead code, magic numbers, missing error handling, code duplication, overly complex methods.
- Validates testing discipline: tests are meaningful, cover edge cases, and match acceptance criteria.
- **Posts review findings on the pull request** via `mcp__MCP_DOCKER__pull_request_review_write` (event `COMMENT`).
- Review categories: `CRITICAL`, `WARNING`, `SUGGESTION`.
  - `CRITICAL`: Must fix before merge.
  - `WARNING`: Should fix, but non-blocking if justified.
  - `SUGGESTION`: Nice to have, can defer.
- **No bikeshedding**: Do not block on purely stylistic changes unless they materially impact clarity.
- Shuts down after review is complete (single pass — findings go back to dev if needed, then re-review).
- Does **NOT** write application code.

### Tester (1 per workstream, T3+ only)

- Each workstream has a **dedicated** tester assigned to that workstream's task.
- **Not spawned for T1 or T2 sprints** — the coder's gate run covers build+test there; the tester verifies acceptance criteria from T3.
- Spawned after code review passes (no open `CRITICAL` findings).
- **Posts findings on the pull request** via `mcp__MCP_DOCKER__add_issue_comment` (PR number).
- Reports: test results, data verification, log analysis.
- Does **NOT** modify application source code.
- Shuts down after verification is complete.

#### Verification Tiers

| Sprint Tier | Tester Role | Verification Scope |
|---|---|---|
| **T1 Trivial** | Not spawned | Coder runs gate; PO judges the gate artifact + coder screenshots |
| **T2 Simple** | Not spawned | Coder runs gate; reviewer approves; PO judges the evidence |
| **T3 Standard** | Structural only | Run tests + data/log checks |
| **T4 Complex** | Full verification | Write targeted verification tests + full suite |

#### Verification Types

- **Structural (agent-verifiable)**: Element exists, page loads, data correct in DB, logs clean, tests pass. Tester handles autonomously.
- **Visual (PO-verifiable)**: Layout alignment, font sizes, colors, spacing, overflow. Tester captures screenshots, PO reviews.

#### Tester Verification Checklist

For each task, the tester verifies:

1. **Build project**: Run build command from `PROJECT_CONTEXT.md`
2. **Run test suite**: Run test commands from `PROJECT_CONTEXT.md` — all pass, no regressions (or run `bash hooks/run-gate.sh` when the **Gate** field is configured — one command covers format/lint/build/test)
3. **Data verification** (if applicable): Schema changes applied, data integrity verified
4. **Log verification**: No errors or unexpected warnings in application logs
5. **Acceptance criteria validation**: Each criterion from the task is met

### Supporting Agents (Optional)

These agents are spawned at PO discretion. They are not part of the standard workstream pipeline.

#### Test Writer

- Spawned by PO after a T4 developer completes a complex feature where test coverage is insufficient (< 80% on changed files).
- Writes comprehensive tests (unit + integration) for the completed feature code.
- Does NOT modify application source code.
- Shuts down after tests are written and passing.
- **When NOT to spawn**: T1-T3 tasks (developer writes tests per tier discipline), or when developer already met coverage targets.

#### Doc Generator

- Spawned by PO after T3+ features that add or change public APIs, new entities, or architectural patterns.
- Generates/updates API documentation, usage examples, and architecture notes.
- Outputs to the project's documentation directory (see `PROJECT_CONTEXT.md`).
- Shuts down after documentation is complete.
- **When NOT to spawn**: Internal refactors with no API changes, T1-T2 tasks, or when the developer already documented changes.

---

## Workstream Model

### What is a workstream?

A workstream is an **independent pipeline** for a single task, containing:

```
Developer --> Code Reviewer --> Tester --> Developer merges PR
```

Each workstream operates autonomously. No shared reviewer or tester bottleneck.

### Workstream Lifecycle

Parallelism comes from the **Agent tool**: one Agent call per workstream, several
in flight at once. Workstream N is a position in the plan, not an agent name —
the PO tracks which spawn belongs to which workstream and puts the task
identification in the spawn prompt.

```
1. PO assigns task to workstream N
2. PO spawns a coder -> implements the feature (per tier testing discipline)
3. Coder creates the PR and reports it in its final message
4. PO spawns a code-reviewer -> reviews the PR -> returns findings
   |-- CRITICAL findings -> PO spawns a coder to fix -> new reviewer -> re-review
   \-- NO CRITICAL FINDINGS -> proceed to step 5
   (Max 3 fix cycles — then PO pauses workstream per Rule 8)
5. PO spawns a tester -> verifies on branch or post-merge
   |-- FAIL -> PO spawns a coder to fix, back to step 4
   \-- PASS -> tester returns its verdict
6. The merging coder executes the Merge Protocol (see below)
7. The merging coder cleans up the worktree + branch and reports
```

---

## Mode Behavior Table

The `task-source` field in `PROJECT_CONTEXT.md` determines which column applies.

| Action | `github-issues` | `plan-files` |
|--------|-----------------|--------------|
| **Task definition** | GitHub Issue with acceptance criteria | `docs/plans/sprint-N-*.md` with task sections |
| **RE output** | Issue markdown for PO to post | Plan file markdown for PO to save |
| **Architect guidance** | Comment on the GitHub Issue | Inline `## Architect Guidance` section in plan file |
| **Dev discovers task** | Dev reads issue via `mcp__MCP_DOCKER__issue_read` | PO inlines task AC + files in dev prompt; plan file path for full context |
| **Review findings** | PR review via `mcp__MCP_DOCKER__pull_request_review_write` | PR review via `mcp__MCP_DOCKER__pull_request_review_write` |
| **Test findings** | PR comment via `mcp__MCP_DOCKER__add_issue_comment` (PR number) | PR comment via `mcp__MCP_DOCKER__add_issue_comment` (PR number) |
| **Close task** | PO closes GitHub Issue via `mcp__MCP_DOCKER__issue_write` | Task list (TaskUpdate) during sprint; MEMORY.md after sprint |
| **Branch naming** | `feature/issue-{number}` or `bugfix/issue-{number}` | PO specifies per task in plan (e.g., `feature/calendar-tz-fix`) |
| **Worktree naming** | `{base}/{project}-issue-{number}/` | `{base}/{project}-{branch-name}/` |
| **Commit convention** | `issue-{number}: {description}` | `feat:` / `fix:` / `chore:` / `test:` / `docs:` prefixes |
| **Tech debt tracking** | PO creates GitHub Issue with `tech-debt` label | PO notes in MEMORY.md or next sprint's plan file |
| **Sprint state** | `PROJECT_STATE.md` with issue/PR numbers | MEMORY.md sprint summary |

---

## Tiered Sprint Model

Not all changes need the full sprint ceremony. The PO selects the tier based on complexity:

| Tier | Criteria | Agents | Testing Discipline |
|------|----------|--------|--------------------|
| **T1 Trivial** | < 10 lines, style/config, no logic | 1 coder (solo — no reviewer/tester) | No new tests. Coder runs the gate (build + existing suite) before merging. |
| **T2 Simple** | 1-2 files, < 50 lines, clear root cause | coder + code-reviewer | Tests recommended if logic changes. Coder runs the gate; reviewer approves. |
| **T3 Standard** | Multi-file, < 200 lines, needs tests | Dev + reviewer + tester | **TDD required.** Failing tests first, then implement. Coverage >= 80% for changed files. |
| **T4 Complex** | Architectural, > 200 lines, new entities | Architect + dev + reviewer + tester — or say **"use a workflow"** (below) when it is too big for one pass | **Full BDD/TDD.** BDD scenarios from acceptance criteria. Failing tests first. Coverage >= 80%. Architect reviews test strategy. |

### Tier Selection Guidelines

- **Lowest defensible tier wins**: pick the smallest tier the work actually needs, and justify escalation rather than justifying restraint. Measured cost of getting this wrong: in one 167-hour session, 22 of 107 user turns spawned more than 2 agents, including 6 agents for `"analyze the last race results"` (a read-only question) and 5 for `"continue"`.
- **The tier table above is a cap on team size, not a menu.** T2 means *at most* coder + reviewer. Never spawn a role the tier does not list.
- **Single file or single symbol ⇒ T1**: one coder, no reviewer, no tester.
- **Question-shaped turns spawn at most one agent.** "How does X work", "what does the data say", "is Y correct" are read-only — answer from one `Explore` (or one `ops` for a command), never a sprint team.
- **Never spawn `Explore` when the target file is already named.** If you or the user already said which file, hand the path to the assigned dev and let it grep directly — a discovery agent for an already-discovered file is pure latency.
- **Same-file rule**: When 2+ fixes touch the same file, assign them to a **single dev agent** regardless of tier. This avoids merge conflicts and saves an agent spawn.
- **Style/config-only changes** (layout, styling, alignment): Always T1 unless they affect data binding or behavior.
- **Bug fixes with known root cause**: T2 if single-file, T3 if multi-file or needs new tests.
- **New features or refactors**: T3 minimum, T4 if architectural decisions are needed.
- **Tester at T3**: Runs existing tests + data/log checks. Does NOT write new test cases.
- **Tester at T4**: Full verification including writing targeted verification test cases.
- **Skip tester** for T1-T2 — the coder's gate run covers build+test there.
- **Visual verification: capture by agent, judgment by PO**: the coder (T1/T2) or tester (T3+) captures screenshots; the PO reviews layout, alignment, colors, spacing. The PO never launches the app or runs capture tooling — that is agent work.

### When to say "use a workflow"

When a T4 task is too big for one pass — a multi-module migration, a sweep across many
files, competing hypotheses to test in parallel — the PO says the trigger phrase **"use a
workflow"**. Claude then builds a *dynamic workflow*: a script that orchestrates waves of
subagents (implementers → two verifiers → a fixer per task, then summarizers), runs it in
the background, and verifies the result before reporting. Run it in **auto mode**, so it
does not stop for permissions mid-wave. The merge gate still applies to whatever branch
comes out: `bash hooks/run-gate.sh`, then the usual `gate-before-merge` path. The
orchestration script lives under `.claude/` or outside the repo, and the gate runs inside
the worker waves — never from the PO thread (`enforce-delegation.sh` denies main-thread
test/gate commands).

Do **not** use a workflow for sequential work (each task needs the previous one's output)
or for several tasks touching the same file — waves assume independence, and the same-file
rule still sends those to one dev. The Workflow tool's "is this big enough" guideline is
configurable, so size it to the repo rather than to the default.

### T1 Examples

| Change | T1? | Why |
|--------|-----|-----|
| Fix a typo in a log message | Yes | Single string, no logic |
| Update a version number in config | Yes | Config-only, no logic |
| Add a CSS class for spacing | Yes | Style-only, no behavior |
| Rename a variable for clarity (1 file) | Yes | Style, < 10 lines |
| Add a missing `using`/`import` directive | Yes | Build fix, no logic |
| Update `.gitignore` | Yes | Config, no logic |
| Fix a null check in a service method | **No → T2** | Logic change, even if 1 line |
| Add a new config key + reading code | **No → T2** | Config + logic, 2 concerns |
| Reorder methods for readability | **No** | Merge conflict risk, low value |
| "Analyze the last race results" | **Not a tier at all** | Read-only question — 0-1 agents, never a sprint team |
| "Continue" / "carry on" | **Not a tier at all** | Resume the existing workstream; spawn nothing new |
| Fix a build break in a named file | Yes | File is already known — no `Explore` spawn, hand the path to one coder |

Within the agreed tier: do the complete thing, not the demo path — a working end-to-end implementation, not a happy-path skeleton.

### Tiered Definition of Done

| Checkpoint | T1 | T2 | T3 | T4 |
|-----------|----|----|----|----|
| Acceptance criteria met | PO verifies | PO verifies | Tester verifies | Tester verifies |
| BDD scenarios exist | — | — | — | Required |
| New tests for changed logic | — | If logic changed | Required | Required |
| All existing tests pass | Required | Required | Required | Required |
| Code reviewer approved | — | PO reviews | Required | Required |
| Coverage >= 80% changed files | — | — | Required | Required |
| Architect guidance followed | — | — | — | Required |
| Post-rebase verification | — | Required | Required | Required |
| Build clean + formatted | Required | Required | Required | Required |
| PR squash-merged | — | Required | Required | Required |
| Worktree cleaned up | — | Required | Required | Required |
| No `TODO`/`FIXME`/`HACK` in changed files | Required | Required | Required | Required |
| Task closed (see Mode Table) | PO | PO | PO | PO |

### Lean Dev Prompt Templates

Both templates carry the five *Task Brief Upfront* headings — an issue link or a plan path
is a reference, never a substitute for the brief.

**github-issues mode (T2-T3):**

```
Task #{n}: issue #{issue}. Worktree: {path}, branch: feature/issue-{issue}.

## Goal
{1-2 sentences}

## Constraints
{what must not change; platform/style rules}

## Acceptance Criteria
- [ ] {criterion 1}

## Files in scope
- {file} — {what to change}   (out of scope: {paths})

## Definition of done
{tests to pass} + `bash hooks/run-gate.sh` green, then PR.

## Required Skills
- {skill} — {why}

Context: the GitHub issue (reference only — the brief above is authoritative).
Workflow: implement -> gate -> commit -> push -> create PR (MCP github) -> report the PR URL in your final message.
```

**plan-files mode (T2-T3):**

```
Task #{n}: {title}. Worktree: {path}, branch: {branch}.

## Goal
{1-2 sentences}

## Constraints
{what must not change; platform/style rules}

## Acceptance Criteria
- [ ] {criterion 1}

## Files in scope
- {file} — {what to change}   (out of scope: {paths})

## Definition of done
{tests to pass} + `bash hooks/run-gate.sh` green, then PR.

## Required Skills
- {skill} — {why}

Context: {plan_file_path} if one exists (reference only — the brief above is authoritative).
Architect guidance: {summary or "none — T2/T3 task"}.
Workflow: implement -> gate -> commit -> push -> create PR (MCP github) -> report the PR URL in your final message.
```

**PO responsibility (plan-files mode):** The PO MUST inline the acceptance criteria and file list directly in the dev spawn prompt. The dev agent should NOT need to read the plan file to understand its task. The plan file path is provided only for additional context.

---

## Parallel Development via Git Worktrees

### Why worktrees?

Each developer agent gets its own working directory with its own branch, all backed by a single shared `.git` database. No checkout conflicts, no stashing, no interference.

### Setup

Prefer `isolation: worktree` — set it in the agent's frontmatter, or pass it on
the Agent call — and let Claude Code create and attach the worktree. The PO does
not run `git worktree add` by hand; that is hands-on work, and a worktree the PO
made is one the harness does not know it owns.

```
# on the Agent call (per spawn)
isolation: worktree

# fallback only — a developer agent creating its own worktree
git worktree add {worktree_base}/{project}-issue-{number} -b feature/issue-{number} main   # github-issues mode
git worktree add {worktree_base}/{project}-{branch-name} -b {branch-name} main             # plan-files mode
```

See `PROJECT_CONTEXT.md` for worktree base path. See Mode Behavior Table for naming convention.

### Rules

- Each worktree is created from `main` at the time of assignment.
- Each developer works **only** in its assigned worktree.
- Max parallel workstreams as specified in `PROJECT_CONTEXT.md`.
- Architect **must** flag scope conflicts before parallel work begins.
- On completion (PR merged), the developer removes the worktree and deletes the branch.

---

## Merge Protocol

After code review and testing pass, the developer executes the merge. MCP tools (git and GitHub) are listed explicitly in each developer agent's `tools:` frontmatter, giving them direct access to commit, push, create PRs, and merge.

| Developer sub-agent type | Merge owner |
|---|---|
| `coder`, `python-coder`, `dotnet-coder`, `rust-coder`, `java-coder` | Developer (MCP tools listed explicitly) |
| `general-purpose` (declared with `tools: *`) | Developer (full MCP catalog via ToolSearch) |

**Agents without `Bash`** (`architect`, `requirements-engineer`, `doc-generator`): return work to the PO; the PO does the git I/O with the git CLI and the GitHub I/O with the MCP tools.

### Steps (Developer-executed)

```
1. Pull latest main into the worktree (`git pull --rebase origin main`).

2. If conflicts exist:
   a. Resolve conflicts (prefer preserving both changes when possible).
   b. Run format commands from PROJECT_CONTEXT.md.
   c. Rebuild and verify (must be 0 errors).
   d. Rerun tests (must be 0 new failures).
   e. Commit the rebase resolution.
   f. Force-push the branch.

   2b. If conflicts are complex (>10 conflicting files OR >100 conflict lines):
       - Developer messages PO. PO decides: (a) resolve with guidance from developer, (b) defer merge until other workstreams complete, or (c) re-spawn architect for conflict resolution strategy.

3. Verify CI passes:
   a. Check CI workflow status via gh_workflow_list after push.
   b. CI fires on `pull_request` and on push-to-main; a bare branch push produces NO run.
      Open the PR first, then look up the run id — an empty workflow list right after
      `git push` is not a CI failure.
   c. If CI fails, fix before merging.

4. Run the gate on the rebased head:
   a. Execute `bash hooks/run-gate.sh` in the worktree. A green gate writes `.gate/last-pass.json`
      for the current HEAD — this artifact is the ONLY accepted green.
   a2. The commit gate keys on the WORKING TREE at gate time — commit exactly what was gated.
      A chained `git add … && git commit` is fine; a partial add after the gate mismatches.
   b. The merge tools are hard-blocked by `hooks/gate-before-merge.sh` without a fresh,
      SHA-matching artifact (< 60 min old). Do not attempt to merge around it.
   c. If the gate fails, fix the failures and re-run. Skip this step only when the
      **Gate** field in PROJECT_CONTEXT.md is unset (the merge hook then passes through).

5. Squash-merge:
   a. Squash-merge the PR via GitHub MCP (merge_pull_request, method: squash).
   b. Verify merge succeeded.

6. Cleanup:
   a. Remove the worktree.
   b. Delete the local and remote feature branch.
   c. Notify the PO that merge is complete.
```

### Merge Ordering

When multiple workstreams finish around the same time, merges happen on a **first-ready, first-merge** basis. Each subsequent merge must rebase onto the updated main before merging.

The PO coordinates merge ordering by sending merge-go-ahead messages. Developers wait for the go-ahead before merging.

---

## Workflow

### Sprint Planning Flow

```
1. PO analyses the task and sizes it against the tier table
       |
2. PO spawns Requirements Engineer for M/L/XL features (if needed)
   - RE produces specs; PO publishes per Mode Behavior Table
   - PO writes specs directly for S features / bugs
       |
3. PO writes the task brief: goal, constraints, acceptance criteria,
   files in scope, definition of done (see Task Brief Upfront)
   - optionally records it as a plan file in docs/plans/
       |
4. PO may spawn the Architect for a critique (optional, architectural work)
       |
5. PO confirms the approach with the user for anything non-obvious
       |
6. PO creates team, spawns workstreams per tier, brief in each prompt:
   - T1: 1 coder, uniform PR pipeline (no reviewer/tester)
   - T2: coder + code-reviewer
   - T3: coder + reviewer + tester
   - T4: coder(s) + reviewer + tester (architect consulted in step 4)
```

### Per-Workstream Flow

```
1. Developer creates worktree and branch
   - reads architect's guidance (T4)
   - follows tier's testing discipline
   - commits per convention (see Mode Behavior Table)
       |
2. Developer creates PR, signals ready for review
       |
3. Code Reviewer reviews (dedicated to this workstream) -> shuts down
   |-- CRITICAL findings -> Developer fixes (same branch) -> PO spawns new reviewer -> re-review
   \-- NO CRITICAL FINDINGS -> proceed to step 4
       |
4. Tester verifies (dedicated to this workstream)
   |-- FAIL -> Developer fixes -> back to step 3
   \-- PASS -> Tester shuts down
       |
5. PO sends merge-go-ahead. Developer executes the merge.
   Note: For T4 sprints where a tester wrote verification tests, PO includes in the go-ahead:
   "Tester wrote verification tests — check `git status` and commit them before merging."
       |
6. Merge Protocol runs (per merge-owner table in Merge Protocol section).
   - rebase onto latest main
   - resolve conflicts if any
   - rebuild + retest after rebase
   - squash-merge PR
       |
7. Developer cleans up worktree + branch, shuts down
       |
8. PO closes the task (see Mode Behavior Table)
```

### Sprint Parallel Flow

```
Architect reviews all tasks -> scope-conflict check -> shuts down
       |
|-- WS1: coder --> code-reviewer --> tester --> coder merges PR --> cleanup
|-- WS2: coder --> code-reviewer --> tester --> coder merges PR --> cleanup
|-- WS3: coder --> code-reviewer --> tester --> coder merges PR --> cleanup
|-- WS4: coder --> code-reviewer --> tester --> coder merges PR --> cleanup
\-- WS5: coder --> code-reviewer --> tester --> coder merges PR --> cleanup

(one Agent call per box; workstreams run in parallel, the PO tracks which spawn
 belongs to which workstream — the agents are not named)

Merges are sequenced by PO (first-ready, first-merge)
```

### Task Brief Upfront

Current models do not need a staged planning ritual — they need the whole task in the
prompt. Every spawn prompt therefore states, in the prompt itself:

- **Goal** — what the change must achieve, in one or two sentences.
- **Constraints** — what must not change, what to leave alone, platform/style rules.
- **Acceptance criteria** — the observable conditions that make the work correct.
- **Files in scope** — the paths to touch, and the paths explicitly out of scope.
- **Definition of done** — the tests to pass and the gate to run (`bash hooks/run-gate.sh`).

An agent that has to go looking for any of the five is being under-briefed; that is a
prompt defect, not an agent failure. The `## Required Skills` block stays part of every
bound spawn and is enforced by `hooks/require-skills-block.sh`.

**Plan files are optional.** Write one in `docs/plans/` when the work spans sessions, when
several workstreams need a shared reference, or when a decision deserves a record. Nothing
blocks a spawn on a plan file, and no literal in one is parsed by any hook.

**Challenging a plan is optional and on demand.** For architectural work, invoke the
`challenge` skill or spawn the architect with the draft — it is a judgement call the PO
makes, not a gate the workflow enforces.

---

## Communication Protocol

### Handoff mechanism

A subagent has one channel: **its final message**. Everything the PO acts on —
status, files changed, commands run plus an output summary, open concerns — is in
there. There is no progress channel and no partial delivery.

- Coder final message: "PR created, ready for review" + the PR URL (PO spawns a reviewer)
- Reviewer final message: "Review complete, findings: ..." (PO decides the next step)
- Tester final message: "Verification complete, verdict: PASS/FAIL" (PO issues the merge-go-ahead or a fix brief)
- Merging coder final message: "Merge complete, cleanup done" (PO closes the task)

**Long tasks:** pass `background: true` on the Agent call. The spawn returns
immediately, the subagent keeps running, and the PO acts on the task-completion
notification — it does not poll.

**Follow-ups:** a *completed* subagent can be resumed by name with SendMessage to
ask one follow-up question against the context it already has. That is the only
remaining use of SendMessage: it is a cheaper re-read, never a coordination
channel and never a way to hand over new work. This is the one exception to the
"no side channel" rule in the agent mandate, and it is not a contradiction of it:
a follow-up question may arrive after you finish — answer it in a new final
message. Nothing arrives *during* a run.

### PO orchestration

Orchestration happens in the *next* spawn prompt, not in a message stream:

- Merge-go-ahead: spawn (or resume) the merging coder with "you are clear to merge; main is at commit {sha}".
- Hold: simply do not spawn the merge yet — workstream N merges first.
- Review findings: spawn a coder with the CRITICAL items inlined, then spawn a fresh reviewer for the re-review.

### State tracking

- **github-issues mode**: PO updates `PROJECT_STATE.md` with issue/PR numbers at sprint boundaries.
- **plan-files mode**: PO updates MEMORY.md with sprint summary at sprint boundaries.

---

## Permission Batching

At the start of every sprint, the PO requests ALL necessary permissions from the user in a single prompt:

**Standard sprint permissions (always requested):**
- Run build, test, and format commands in worktrees
- Create/remove git worktrees and branches
- Push branches to remote
- Create and merge pull requests via GitHub MCP
- Read/write files in worktrees

The PO presents these as a single confirmation at sprint start. All agents are spawned with `mode: bypassPermissions` so no further prompts occur during the sprint.

**CRITICAL**: Every `Task` tool call for spawning agents MUST include `mode: "bypassPermissions"` parameter.

---

## Rules

1. **No direct pushes to main** — everything goes through PRs, including T1 trivial fixes (one coder: branch → fix → gate → PR → self-merge). No exceptions.
2. **One task per developer** — no multitasking within an agent.
3. **Max parallel workstreams** as specified in `PROJECT_CONTEXT.md`.
4. **Architect reviews BEFORE development** — guidance before dev starts (T4).
5. **Developers own the merge** — all developer agents have `Bash` plus the PR tools and execute their own merges after PO sends merge-go-ahead. Agents without `Bash` (`architect`, `requirements-engineer`, `doc-generator`) return work to the PO.
6. **PO sequences merges** — developers wait for merge-go-ahead from the PO before merging.
7. **Post-rebase verification required** — rebuild + retest before merge.
8. **Max 3 fix cycles per task** — then PO pauses the workstream and selects one of: (a) scope reduction, (b) architect re-design, or (c) human escalation. See Escalation Protocol.
9. **Workstream agents are ephemeral** — shut down after their phase.
10. **Agents must not modify files outside their assigned worktree.**
11. **Permission propagation** — all permissions requested once at sprint start. Agents spawned with `mode: bypassPermissions`.
12. **Mode consistency** — the sprint's primary task source determines the mode. T1/T2 hotfixes may bypass mode formalities if urgent — but a hotfix is still a coder spawn and still runs the gate; only the reviewer may be skipped.
13. **Brief discipline** — every spawn prompt carries the full task brief (goal, constraints, acceptance criteria, files in scope, definition of done). See Task Brief Upfront. Team composition still follows the tier caps; a plan file is optional at every tier.

---

## Escalation Protocol

- **Developer stuck** (>3 fix cycles): PO pauses the workstream and selects one of:
  - **(a) Scope reduction**: Simplify the task (remove edge cases, split into smaller pieces) and restart with reduced scope.
  - **(b) Architect re-design**: Re-spawn architect with the failure context. Architect produces a new approach. Dev restarts from the new plan.
  - **(c) Human escalation**: Notify the user with: task description, what was tried (3 cycles), failure details, and recommended next steps.
- **Merge conflicts too complex**: the developer reports the details in its final message. PO decides per the Merge Protocol fallback (defer, re-spawn architect, etc.).
- **Tester can't verify**: it reports why; the PO routes the work to a developer.
- **Scope conflict discovered mid-sprint**: PO pauses affected workstreams, re-spawns architect for conflict resolution.
- **Any agent stuck after escalation**: PO notifies the human (via issue comment in github-issues mode, or direct message in plan-files mode).
- **Missing or empty report** (runbook — judgment removed on purpose):
  1. A **foreground** Agent call cannot stall: it either returns a final message or it errors. An error is a failed dispatch — read it and re-dispatch; do not "wait".
  2. A **background** agent reports through the task-completion notification. Check it (or `ListAgents`) ONCE. Past the agent's tool-call budget with no completion, treat the run as failed — do not poll in a loop.
  3. Verify the actual work state via `git log` / `git status` / `list_pull_requests` — **never trust the agent's last claim**; committed work frequently exists despite a truncated report (and vice versa).
  4. Count the failure as one strike toward the 3-cycle escalation above, then re-dispatch with a TIGHTER brief: the verified state, the remaining work, and nothing else. **Never self-perform the failed agent's work as fallback** — the PO does not code, review, or test inline.
  5. **Dead-coder merge handoff**: if the failed coder left a pushed branch with an open PR, spawn a FRESH coder with the PR URL, branch name, and worktree path in the spawn prompt to rebase, re-run the gate, and complete the merge. The PO never finishes merges by hand.
  6. **Report agents (reviewer/architect/tester/ops/etc.)**: their report IS the deliverable. A final message without one is a failed run — re-dispatch, citing the reporting mandate. `hooks/enforce-agent-contract.sh` (SubagentStop) catches the coder/reviewer cases mechanically; for the rest the mandate lives in the agent definitions and spawn prompts.
  7. Repeated failures of the same shape are recorded by `hooks/retro-ledger.sh` and replayed at the next session start — fix the cause (the agent's `tools:` allowlist, the prompt, the hook) instead of re-dispatching into the same wall.

---

## Preprocessing

Token efficiency preprocessing (Ollama, Context7) is configured per-project in `CLAUDE.local.md`. See that file for mandatory preprocessing rules.

---

## Superpowers Skills Integration

When the [superpowers plugin](https://github.com/anthropics/claude-plugins-official/tree/main/superpowers) is installed, its skills handle implementation mechanics (how to code efficiently) while AGENT_TEAM.md owns quality gates (tier, workstream, review, test, merge). Skills are tools used within the lifecycle defined here, not replacements for it.

### Spawn-Prompt Binding Table

When spawning an agent, include in the spawn prompt a `## Required Skills` block listing the skills below for the target subagent type. The spawned agent must invoke each skill via the Skill tool before beginning task work. This is **mechanically enforced** by `hooks/require-skills-block.sh` (PreToolUse on `Task`) — a spawn of a bound subagent type without a `## Required Skills` block exits 2.

| subagent_type | Required Skills |
|---|---|
| `coder` and any `<lang>-coder` — the template's own (`dotnet-coder`, `rust-coder`, `java-coder`, `python-coder`) **and any your project adds** (`cpp-coder`, `go-coder`, …); the hook matches the shape, not a list | `karpathy-guidelines`, `test-driven-development`, `verification-before-completion`, `receiving-code-review` |
| `code-reviewer` | *(none — review is the agent's core job)* |
| `tester` | `systematic-debugging`, `verification-before-completion` |
| `test-writer` | `test-driven-development` |
| `architect` | `writing-plans` |
| `requirements-engineer` | `brainstorming` |
| `doc-generator` | *(none)* |
| `ops` | *(none — pass-through)* |
| `Explore` | *(none — pass-through; custom Explore agent, haiku, effort low)* |

**Reference-only skills** (handled by existing AGENT_TEAM.md constructs, not injected via spawn prompt): `using-git-worktrees` (Worktree Naming), `finishing-a-development-branch` (Merge Protocol), `dispatching-parallel-agents` (Tier Model workstreams), `subagent-driven-development` (plan-files mode execution).

**Chain note:** `writing-plans` produces a plan, which is an optional artifact (see *Task Brief Upfront*). Nothing validates it before execution; the spawn prompt's brief and the review/tester pipeline carry that weight.

### Copy-paste snippets

Use these snippets verbatim when constructing spawn prompts. Append to the body of the prompt, then add the task-specific instructions below.

**Report agents (code-reviewer, architect, tester, test-writer, requirements-engineer, doc-generator, ops) — ALWAYS add these lines to their spawn prompts** (their definitions carry the same mandate; repeating it in the prompt is what reliably prevents an empty return):

```markdown
CRITICAL: your final message IS the deliverable. It must contain: status, files changed, commands run + output summary, open concerns.
If the task grows past its stated scope (extra files, a second root cause, a redesign), stop and report what is done plus the blocker instead of expanding scope.
```

**Coder (and variant coders `dotnet-coder`, `rust-coder`, `java-coder`, `python-coder`):**

```markdown
## Required Skills
Invoke these via the Skill tool before beginning task work:
- karpathy-guidelines
- superpowers:test-driven-development
- superpowers:verification-before-completion
- superpowers:receiving-code-review

CRITICAL: your final message IS the deliverable. It must contain: status, files changed, commands run + output summary, open concerns.
If the task grows past its stated scope (extra files, a second root cause, a redesign), stop and report what is done plus the blocker instead of expanding scope. A long run is not evidence of progress.
```

**Tester:**

```markdown
## Required Skills
Invoke these via the Skill tool before beginning task work:
- superpowers:systematic-debugging
- superpowers:verification-before-completion
```

**Test-writer:**

```markdown
## Required Skills
Invoke these via the Skill tool before beginning task work:
- superpowers:test-driven-development
```

**Architect:**

```markdown
## Required Skills
Invoke these via the Skill tool before beginning task work:
- superpowers:writing-plans
```

**Requirements-engineer:**

```markdown
## Required Skills
Invoke these via the Skill tool before beginning task work:
- superpowers:brainstorming
```

**Code-reviewer / doc-generator:** omit the block entirely (hook passes them through).

---

## Tech Debt Tracking

- Code reviewers flag tech debt in their PR review findings.
- **github-issues mode**: PO creates tech debt issues with the `tech-debt` label.
- **plan-files mode**: PO notes tech debt in MEMORY.md and includes in next sprint's plan file.
- Tech debt follows the same workstream workflow as features.

---

## Session Summary Template

After each completed sprint, the PO updates memory:

```markdown
### Sprint {N} — {Theme}
- **Delivered**: {task titles}
- **PRs merged**: #{A}, #{B}, #{C}
- **Test suite**: {total} tests, {failures} failures
- **New backlog items**: {tech debt from review, gaps from testing}
- **Key decisions**: {architectural or scope decisions}
```

---

## Sprint Retrospective

**Mandatory** after every sprint. The PO conducts the retrospective immediately after the session summary and records findings in MEMORY.md under `Sprint {N} Lessons`.

### Retrospective Template

```markdown
### Sprint {N} Retrospective

#### Tier Assessment
- Was the tier (T1-T4) appropriate for each task?
- Could any task have been handled at a lower tier?
- Were any agents unnecessary? (quantify: agents spawned vs lines changed)

#### Token Efficiency
- Total agents spawned: {N}
- Lines changed: {N}
- Ratio: lines/agent — target > 50 for T3, > 200 for T4
- Could same-file fixes have been combined into one agent?

#### Mode Effectiveness
- Was the task source (github-issues/plan-files) appropriate for this sprint?
- Would the other mode have been better? Why?

#### What went well
- {Workflow patterns that worked}
- {Quality outcomes — clean reviews, no regressions}

#### What didn't go well
- {Agent stalls, communication failures, unexpected blockers}
- {Review churn, merge conflicts, build/test issues}

#### Agent performance
- {Did the reviewer post reviews directly to the PR? If not, why?}
- {Were dev prompts concise (lean template) or verbose?}
- {Did any agent need re-spawning?}

#### Common review findings
- {Recurring issues — add to Developer Checklist if pattern emerges}

#### Action items for next sprint
- [ ] {Specific improvement}
- [ ] {Process change}
- [ ] {Agent/tool/skill update}

#### Team Evolution Ideas
- {New skills, MCP servers, or tools that would help}
- {Agent definition changes needed}
- {CLAUDE.md or AGENT_TEAM.md updates}
```

### Retrospective Guidelines

1. **Be specific**: Reference task identifiers, agent names, and timestamps where possible.
2. **Focus on process, not blame**: Agents are tools — if one stalled, the question is "why?" and "how to prevent it?", not "which agent failed?".
3. **Update this document**: If a retrospective identifies a recurring pattern, add it to the relevant section (Rules, Escalation Protocol, etc.).
4. **Track improvement over sprints**: Compare current retrospective to previous ones. Are action items being addressed?
5. **Feed back into planning**: Use retrospective findings to inform sprint sizing, workstream count, and agent configuration.

---

## Appendix: Implementation Plan Template (plan-files mode)

When using `plan-files` mode, implementation plans follow this structure:

```
# Sprint {N}: {Topic} — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** {1-2 sentences}
**Architecture:** {Key decisions}
**Tech Stack:** {Relevant technologies}
**Tier:** T{N}  (optional — no hook reads this)
**Team:** {subagent types per tier — e.g., "coder, code-reviewer, tester"}  (optional — no hook reads this)

---

## Task 1: {Title}

**Branch:** `feature/{descriptive-name}`
**Files:** {list of files to modify/create}
**Acceptance Criteria:**
- {criterion 1}
- {criterion 2}

**Steps:**
1. {step}
2. {step}

---
```

## Appendix: PROJECT_CONTEXT.md Template

When `PROJECT_CONTEXT.md` doesn't exist, the PO creates it from this template:

```
# Project Context

## Project

- **Name**: {project name}
- **Tech stack**: {languages, frameworks, databases}
- **Repository**: {repo URL}
- **Branch strategy**: feature branches per task, PR into `main` (see AGENT_TEAM.md Mode Behavior Table for naming convention). Prose for humans — no hook reads this line.
<!-- THE line the protection hooks read; space- or comma-separated names. Absent or empty -> `main master`. `none` protects nothing (branch rules only; a PR merge stays gated). Write a REAL branch name here, never a placeholder. -->
- **Protected branches**: main

## Commands

- **Build**: {build command}
- **Test**: {test command}
- **Format**: {format command}
- **Lint**: {lint command}

## Paths

- **Worktree base**: {path}
- **Architecture docs**: {docs path}
- **Log location**: {log path or stdout}

## Workflow Configuration

- **Task source**: {github-issues | plan-files}
- **Max parallel workstreams**: {number}
- **Commit convention**: {convention description}
- **Issue labels** (github-issues mode only): {comma-separated labels}

## Preprocessing

- **Ollama**: {available | not available}
- **Context7**: {available | not available}
```

---

## Open Brain Context for Agents

Spawned agents cannot access Open Brain directly. The PO must search for relevant context and include it in agent spawn prompts. After agents return, capture durable insights.

### Before Spawning

| Agent Type | Search Query | Include in Prompt |
|---|---|---|
| Architect | `"architecture {component}"`, `"tech debt {area}"` | Past decisions, rejected alternatives, known coupling issues |
| Code Reviewer | `"bug pattern {component}"`, `"review {area}"` | Recurring issues, known weak spots, past review findings |
| Coder | `"implementation {component}"`, `"pitfall {area}"` | Failed approaches, trade-off decisions, integration gotchas |
| Tester | `"failure mode {feature}"`, `"regression {area}"` | Known failure patterns, data state gotchas, flaky test history |
| Test Writer | `"edge case {component}"`, `"test pattern {area}"` | Historically problematic cases, boundary conditions |
| Requirements Engineer | `"feature {domain}"`, `"scope {area}"` | Past scope surprises, edge cases that tripped users |

### After Agent Returns

Capture durable insights — not routine results:

| Agent Type | What to Capture |
|---|---|
| Architect | Decisions with rationale, rejected alternatives, new tech debt identified |
| Code Reviewer | Non-trivial bug patterns, recurring issues by component |
| Coder | Non-obvious implementation decisions, approaches that failed and why |
| Tester | Bugs found with root cause, regression patterns, data state issues |
| Test Writer | Critical edge cases discovered, boundary conditions that matter |
| Requirements Engineer | Key scope decisions, excluded features and why, edge cases found |

Skip capture for routine outcomes ("no issues found", "all tests pass").

---

<!-- PROJECT-CUSTOM:BEGIN — sync-template preserves everything between these markers -->
<!-- Project-specific rules, routing blocks, and extensions go here. -->
<!-- PROJECT-CUSTOM:END -->
