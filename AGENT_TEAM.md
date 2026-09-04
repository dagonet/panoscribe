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
- `code-reviewer` — has `Bash` for local `git diff <base>..<head>` (read-only in effect: it holds no write tool) and can post PR reviews via `mcp__MCP_DOCKER__pull_request_review_write`
- `tester` — has `Bash` (so it can commit) but no PR tools; it can post findings via `mcp__MCP_DOCKER__add_issue_comment`

### Agents without `Bash`:
- `architect` — CANNOT commit, push, create PRs, merge, or post comments

### The rule that covers every tool, not just `Bash`

**`.claude/agents/<name>.md` is the source of truth. Before you put an operation in a spawn prompt, read that agent's own `tools:` line** — the limitation is not specific to git, and `Bash` is simply the one that bit often enough to get written down. The cases that actually bite:

- **`Bash`** — `architect` has none. It cannot commit, push, open or merge PRs, run a build, or run the gate.
- **`Edit` / `Write`** — `Explore` and `code-reviewer` have **neither**. `Explore` is a read-only search agent and `code-reviewer` reports findings; asking either to apply a fix, fix a typo, or update a doc is asking for a tool it does not hold. Every other agent (`architect`, `coder`, `<lang>-coder`, `ops`, `tester`) has both.
- **GitHub MCP (`mcp__MCP_DOCKER__*`)** — `Explore`, `architect` and `ops` have none, so none of them can open a PR, merge one, or post a comment. `code-reviewer` holds the review-write tool only; `tester` holds the issue-comment tool only; the coders hold the PR create/merge/update set.
- **`isolation: worktree`** — set in frontmatter on `coder`, `tester` and every `<lang>-coder`. Those agents run in their own worktree and cannot reach the main checkout, which is why the sync/merge steps say *never spawn a worktree-isolated agent to commit a sync*.

*(Deliberately a rule plus its exceptions, not a per-agent capability matrix. A matrix restating twenty-odd frontmatter cells in prose is the stale-doc defect this release exists to remove, and it would need a consistency assertion diffing it against `.claude/agents/*.md` to stay honest. The rule above names only the facts that change a spawn decision, and it ends by pointing at the file that cannot go stale.)*

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
- Spawns the **Architect** for new features to produce detailed specs before publishing (it absorbed the retired `requirements-engineer` in v3.0.0 and carries `brainstorming` for exactly this).
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
- **Open Brain context mediation**: Before spawning any agent, search Open Brain for context relevant to the agent's task and include findings in the spawn prompt. After the agent returns, capture non-trivial insights. See `AGENT_TEAM.md` → *Open Brain Context for Agents* (below, in this file) for agent-specific search queries.
- **Spawn-prompt skill injection**: When constructing any spawn prompt, look up the target `subagent_type` in the Spawn-Prompt Binding Table (Superpowers Skills Integration section) and include a `## Required Skills` block in the prompt listing the skills to invoke via the Skill tool. Use the copy-paste snippets in that section verbatim. The `hooks/require-skills-block.sh` PreToolUse hook mechanically enforces this — a spawn of a bound subagent type without the block exits 2 with a diagnostic. Omit the block for `code-reviewer` spawns (no required skills; the hook passes it through).

## Model & Effort Policy

- Orchestrator = the session model, picked by the user with `/model` at session start: **`fable` for T3/T4** sessions (multi-file or architectural — Fable 5 needs fewer prompts and steers, sustains longer sessions, and earns higher trust and autonomy; it also costs ~2× Opus), **`opus` for T1/T2**. Workers run `sonnet`; `architect` and `code-reviewer` run `opus` with `effort: xhigh`; `Explore` runs `haiku` with `effort: low`.
- Session effort is deliberately **unset** — the model's own default. Raise it per role via the agent file's `effort:` (`low` / `medium` / `high` / `xhigh`), or `/effort` for one session.
- Each agent file carries its own `model:` / `effort:` — do not pass a `model` in the Agent call; that overrides the routing decision silently.
- **Aliases only** (`sonnet` / `opus` / `haiku` / `fable` / `inherit`), never a full `claude-*` id: a model proxy reroutes the aliases, and a pinned id bypasses it.
- Diagnostic rule: wrong answer despite full context → bigger model. Skipped files, tests not run, steps dropped → raise `effort`. They are different failures; raising the wrong dial costs money and fixes nothing.
- If you run a model proxy, never route the auto-mode classifier or `advisorModel` through it — both need the real model to behave.

## Workstream Model

### What is a workstream?

A workstream is an **independent pipeline** for a single task, containing:

```
Developer --> Code Reviewer --> Tester --> Developer merges PR
```

Each workstream operates autonomously. No shared reviewer or tester bottleneck.

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

`isolation: worktree` cuts the agent's worktree from **`origin/main`** — not from the branch you have checked out and not from local `main`. If work lands on a session branch and `main` moves only when the session PR lands, every worktree coder starts from a tree missing the whole session's work, plan files included, until that PR lands: the lag equals the unlanded work. Land PRs mid-session to reset it. "Rebase first" in the brief cannot prevent it — the base is chosen after the brief is written. The PO's control is a post-spawn base check: `git rev-list --count <base>..<session-branch>` must be 0, and `git cat-file -e <base>:<path>` must succeed for every file the brief names. Untracked files (a plan doc not yet committed) are never in the worktree; hand the coder an absolute path.

---

## Merge Protocol

After code review and testing pass, the developer executes the merge. MCP tools (git and GitHub) are listed explicitly in each developer agent's `tools:` frontmatter, giving them direct access to commit, push, create PRs, and merge.

| Developer sub-agent type | Merge owner |
|---|---|
| `coder`, `python-coder`, `dotnet-coder`, `rust-coder`, `java-coder` | Developer (MCP tools listed explicitly) |
| `general-purpose` (declared with `tools: *`) | Developer (full MCP catalog via ToolSearch) |

**Agents without `Bash`** (`architect`): return work to the PO; the PO does the git I/O with the git CLI and the GitHub I/O with the MCP tools.

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

## Rules

1. **No direct pushes to main** — everything goes through PRs, including T1 trivial fixes (one coder: branch → fix → gate → PR → self-merge). No exceptions.
2. **One task per developer** — no multitasking within an agent.
3. **Max parallel workstreams** as specified in `PROJECT_CONTEXT.md`.
4. **Architect reviews BEFORE development** — guidance before dev starts (T4).
5. **Developers own the merge** — all developer agents have `Bash` plus the PR tools and execute their own merges after PO sends merge-go-ahead. Agents without `Bash` (`architect`) return work to the PO.
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

## Superpowers Skills Integration

When the [superpowers plugin](https://github.com/anthropics/claude-plugins-official/tree/main/superpowers) is installed, its skills handle implementation mechanics (how to code efficiently) while AGENT_TEAM.md owns quality gates (tier, workstream, review, test, merge). Skills are tools used within the lifecycle defined here, not replacements for it.

### Spawn-Prompt Binding Table

When spawning an agent, include in the spawn prompt a `## Required Skills` block listing the skills below for the target subagent type. The spawned agent must invoke each skill via the Skill tool before beginning task work. This is **mechanically enforced** by `hooks/require-skills-block.sh` (PreToolUse on `Task`) — a spawn of a bound subagent type without a `## Required Skills` block exits 2.

| subagent_type | Required Skills |
|---|---|
| `coder` and any `<lang>-coder` — the template's own (`dotnet-coder`, `rust-coder`, `java-coder`, `python-coder`) **and any your project adds** (`cpp-coder`, `go-coder`, …); the hook matches the shape, not a list | `karpathy-guidelines`, `test-driven-development`, `verification-before-completion`, `receiving-code-review` |
| `code-reviewer` | *(none — review is the agent's core job)* |
| `tester` — **absorbed `test-writer` in v3.0.0** | `systematic-debugging`, `verification-before-completion`, `test-driven-development` |
| `architect` — **absorbed `requirements-engineer` in v3.0.0** | `writing-plans`, `brainstorming` |
| `ops` | *(none — pass-through)* |
| `Explore` | *(none — pass-through; custom Explore agent, haiku, effort low)* |

**Reference-only skills** (handled by existing AGENT_TEAM.md constructs, not injected via spawn prompt): `using-git-worktrees` (Worktree Naming), `finishing-a-development-branch` (Merge Protocol), `dispatching-parallel-agents` (Tier Model workstreams), `subagent-driven-development` (plan-files mode execution).

**Chain note:** `writing-plans` produces a plan, which is an optional artifact (see *Task Brief Upfront*). Nothing validates it before execution; the spawn prompt's brief and the review/tester pipeline carry that weight.

**v3.0.0 consolidation — three names retired, ABSORBED rather than renamed.** `test-writer` → `tester`, `requirements-engineer` → `architect`, `doc-generator` → `coder`. The survivor keeps the existing name in every case, and that is a hard constraint rather than a style preference: a stale reference to a surviving name fails **loudly, at spawn time**, which is recoverable; a *new* name would make every consumer's keep-mine prose stale at once, silently. The absorbing agents gained the absorbed skill (`tester` gained `test-driven-development`, `architect` gained `brainstorming`) — a superset, not a rename.

### Copy-paste snippets

Use these snippets verbatim when constructing spawn prompts. Append to the body of the prompt, then add the task-specific instructions below.

**Report agents (code-reviewer, architect, tester, ops) — ALWAYS add these lines to their spawn prompts** (their definitions carry the same mandate; repeating it in the prompt is what reliably prevents an empty return):

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

**Tester (absorbed `test-writer` — it writes tests as well as verifying them):**

```markdown
## Required Skills
Invoke these via the Skill tool before beginning task work:
- superpowers:systematic-debugging
- superpowers:verification-before-completion
- superpowers:test-driven-development
```

**Architect (absorbed `requirements-engineer` — it explores requirements as well as planning):**

```markdown
## Required Skills
Invoke these via the Skill tool before beginning task work:
- superpowers:writing-plans
- superpowers:brainstorming
```

**Code-reviewer:** omit the block entirely (hook passes it through).

**Docs** are a `coder` spawn (`doc-generator` was absorbed into `coder` in v3.0.0), so they take the coder block above — including the skills. Docs that ship with the code they describe were always a coder's job; the separate agent duplicated it.

---

## Appendix: PROJECT_CONTEXT.md Template

When `PROJECT_CONTEXT.md` doesn't exist, the PO creates it from this template:

```
# Project Context

## Project

- **Name**: {project name}
- **Tech stack**: {languages, frameworks, databases}
- **Repository**: {repo URL}
- **Branch strategy**: feature branches per task, PR into `main` (see `AGENT_TEAM.md` → *Mode Behavior Table* for naming convention). Prose for humans — no hook reads this line.
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
| Architect | `"architecture {component}"`, `"tech debt {area}"`, `"feature {domain}"`, `"scope {area}"` | Past decisions, rejected alternatives, known coupling issues, past scope surprises |
| Code Reviewer | `"bug pattern {component}"`, `"review {area}"` | Recurring issues, known weak spots, past review findings |
| Coder | `"implementation {component}"`, `"pitfall {area}"` | Failed approaches, trade-off decisions, integration gotchas |
| Tester | `"failure mode {feature}"`, `"regression {area}"`, `"edge case {component}"`, `"test pattern {area}"` | Known failure patterns, data state gotchas, flaky test history, historically problematic cases |

### After Agent Returns

Capture durable insights — not routine results:

| Agent Type | What to Capture |
|---|---|
| Architect | Decisions with rationale, rejected alternatives, new tech debt identified, key scope decisions and excluded features |
| Code Reviewer | Non-trivial bug patterns, recurring issues by component |
| Coder | Non-obvious implementation decisions, approaches that failed and why |
| Tester | Bugs found with root cause, regression patterns, data state issues, critical edge cases discovered |

Skip capture for routine outcomes ("no issues found", "all tests pass").

---

<!-- PROJECT-CUSTOM:BEGIN — sync-template preserves everything between these markers -->
<!-- Project-specific rules, routing blocks, and extensions go here. -->
<!-- PROJECT-CUSTOM:END -->
