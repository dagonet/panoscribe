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
- **Gate Command**: uv run ruff format --check . && uv run ruff check . && uv run pytest --cov=panoscribe --cov-fail-under=95

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
- **Max parallel workstreams**: 5
- **Commit convention**: `feat:`, `fix:`, `chore:`, `test:`, `docs:` prefixes
- **Issue labels** (github-issues mode only): `feature`, `bug`, `tech-debt`

## Preprocessing

- **Ollama**: available (MCP: `ollama-tools`) -- see CLAUDE.local.md for usage rules
- **Context7**: available (MCP: `context7`)