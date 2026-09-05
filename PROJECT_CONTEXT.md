# Project Context

## Project

- **Name**: panoscribe
- **Repository**: https://github.com/dagonet/panoscribe
- **Tech Stack**: Python 3.11, uv

## Build System

- **Build Command**: uv sync --extra dev --extra api
- **Test Command**: uv run pytest
- **Format Command**: uv run ruff format .
- **Lint Command**: uv run ruff check .
- **Gate Command**: bash preflight.sh && uv run ruff format --check . && uv run ruff check . && uv run pytest --cov=panoscribe --cov-fail-under=95
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
- **Max parallel workstreams**: 5
- **Commit convention**: `feat:`, `fix:`, `chore:`, `test:`, `docs:` prefixes
- **Issue labels** (github-issues mode only): `feature`, `bug`, `tech-debt`

## Preprocessing

- **Ollama**: available (MCP: `ollama-tools`) -- see CLAUDE.local.md for usage rules
- **Context7**: available (MCP: `context7`)
