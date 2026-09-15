# Project Context

## Project

- **Name**: panoscribe
- **Repository**: https://github.com/dagonet/panoscribe
- **Tech Stack**: Python 3.11, uv

## Build System

- **Build Command**: uv sync --extra dev --extra api
- **Format Command**: uv run ruff format .
- **Lint Command**: uv run ruff check .
- **Gate Command**: bash preflight.sh && uv run ruff format --check . && uv run ruff check . && uv run pytest --cov=panoscribe --cov-fail-under=95
<!-- **Test Command** is deliberately ABSENT, not `none` — `none` is eval'd as a
     command and would block every commit. With no Test field, pre-commit-test.sh
     falls back to the Gate, which MINTS `.gate/last-pass.json`, so a commit and
     the merge artifact are the same run. Measured: Test ~42s, Gate ~55s, and
     break-even is gate/(gate-test) ~= 4-5 commits per PR. panoscribe averages
     about one, so declaring both cost a full extra gate run per PR (two commits
     on 2026-09-15 needed two test runs PLUS two delegated `ops` gate runs).
     Re-add a Test line only if commits-per-PR rises above the break-even. -->
<!-- Post-edit build runs after every Edit/Write via hooks/post-edit-build.sh and
     is NOT scoped to the edited file, so any real command here runs the whole
     project build on every keystroke-level write. `none` is a true no-op for
     this key (unlike Gate). -->
- **Post-edit build**: none
<!-- Declaring BOTH means the Test runs on commit and the Gate does not, so no artifact is minted and every merge needs a separate `bash hooks/run-gate.sh`. Worth it only above roughly gate_seconds / (gate_seconds - test_seconds) commits per PR — measure yours. Below that, declare the Gate alone and leave the Test field empty (a literal `none` is NOT an opt-out here: it is eval'd as a command and blocks every commit — measured 2026-09-03). -->
<!-- Join Gate command steps with `&&`, never `;` — `;` discards an earlier step's failure status, so `<real gate> ; <anything>` exits 0 and the gate mints a pass artifact on a failing suite. -->
- **Python Version**: 3.11

## Paths

- **Source Root**: src/
- **Test Root**: tests/
- **Worktree Base**: g:/git/.worktrees
- **Log Path**: logs/

## Docker

- **Build Image**: `docker build -t panoscribe .`
- **Run CLI**: `docker run --rm panoscribe --help`
- **Transcribe (GPU)**: `docker run --gpus all --rm -v ./input:/input -v ./output:/output panoscribe transcribe /input/video.mp4 -o /output/transcript.json`
- **Transcribe (CPU)**: `docker run --rm -v ./input:/input -v ./output:/output -e PANO_WHISPER_DEVICE=cpu -e PANO_WHISPER_COMPUTE_TYPE=int8 -e PANO_OCR_DEVICE=cpu panoscribe transcribe /input/video.mp4 -o /output/transcript.json`
- **Prerequisites**: NVIDIA Container Toolkit (GPU), Docker 20.10+

## Workflow Configuration

- **Task source**: `plan-files`
- **Branch strategy**: feature branches per task, PR into `main` (see AGENT_TEAM.md Mode Behavior Table for naming convention). Prose for humans — **no hook reads this line**; the enforced set is `**Protected branches**:` directly below.
<!-- THE line the protection hooks read; space- or comma-separated names.
     EDIT THIS if your trunk is not main/master — nothing fills it in for you,
     and a trunk that is not named here is NOT protected.
     Absent, empty, or an unfilled {{...}} all fall back to `main master`;
     `none` protects nothing (branch rules only; a PR merge stays gated). -->
- **Protected branches**: main
<!-- Gate-checked branches: a merge onto a matching branch needs a fresh gate
     artifact like a protected branch, while a PUSH to it stays ungated — it
     exists for a session/worktree branch that lands milestones before one PR.
     `none` is DELIBERATE and measured, not an unconsidered default: panoscribe
     is squash-via-PR only (2 merge commits in 176), and every route onto main —
     `gh pr merge`, a push to main, a merge on main — is already gated by
     **Protected branches** above, so no content reaches main ungated. Declaring
     `*` would instead gate `git merge main` sync-ups on feature branches:
     friction on a safe operation, guarding a workflow this repo does not have.
     Revisit if long-lived branches ever accumulate work outside a PR. -->
- **Gate-checked branches**: none
<!-- Names EXTRA path prefixes the PO may write directly, on top of the built-in
     surface in hooks/enforce-delegation.sh (docs/plans/, PROJECT_STATE.md,
     PROJECT_CONTEXT.md, .claude/, CLAUDE.md, AGENT_TEAM.md). `none` = no extras,
     which is the template default. Verified current: the built-in denied a
     main-thread write to src/ and allowed .claude/ on 2026-09-15. -->
- **PO write surface**: none
- **Max parallel workstreams**: 5
- **Commit convention**: `feat:`, `fix:`, `chore:`, `test:`, `docs:` prefixes
- **Issue labels** (github-issues mode only): `feature`, `bug`, `tech-debt`

## Preprocessing

- **Ollama**: available (MCP: `ollama-tools`) -- see CLAUDE.local.md for usage rules
- **Context7**: available (MCP: `context7`)
