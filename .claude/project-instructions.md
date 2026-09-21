This file is imported at the end of `CLAUDE.md`; where the two conflict, this file wins. It is loaded at session start, always on — a new or edited version here is picked up at the NEXT session start, not the current one.

What belongs here: project rules, plugin routing blocks (context-mode and similar), and the MCP servers this project relies on (name, purpose, main-thread only) — `CLAUDE.local.md` is no longer shipped, so list them here; the user-level `mcp-usage` skill covers the occasional procedures. Nothing here should duplicate a `paths:`-scoped rules file. Shared, committed project rules belong in `project-instructions.md`; machine-local ones belong in `CLAUDE.local.md` — the migration folds nothing from one into the other, and no precedence between them is claimed, because none exists to claim.


# Project Notes (panoscribe)

**Green-CI merge gate (definition of done):** a PR may be merged ONLY after its head SHA shows a successful GitHub Actions run — check via `gh_workflow_list` / `github_workflow_run_wait` and require `conclusion=success` before merging. Local green is insufficient: platform-specific failures (e.g. Linux-only import errors) never surface on Windows. After merging, confirm main's push run is also green. If CI is red for an unrelated reason, fix CI first — never merge on top of red. The PO includes this gate in every dev spawn prompt's merge instructions and re-checks Actions status at every release.

**Verify a run's jobs, not its conclusion:** a workflow run in which every job is skipped still reports `success`. After any publish/release dispatch, confirm at job level (`github_check_runs_for_sha`) that the specific job you needed actually ran.

**Gate artifact location:** `hooks/gate-before-merge.sh` reads `.gate/last-pass.json` from the checkout it resolves as the repo root. Run `bash hooks/run-gate.sh` in the checkout you merge from — an artifact written inside an agent worktree is never seen by the hook and presents as an "artifact expired" error that re-running cannot clear.

**Bootstrap is `uv sync --extra dev --extra api`** — test/dev tooling lives in `[project.optional-dependencies]`; bare `uv sync` skips `pytest-cov` and the gate fails with an opaque pytest argument error. Release sequence: `docs/release-process.md`. Right after a release, `uv` may serve a stale index for the new version — see `docs/troubleshooting.md`.

**Compact — also preserve:** team configuration (team name, active teammates and their roles).
