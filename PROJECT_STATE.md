# panoscribe — Project State

## Current Sprint

_No active sprint._

## Phase Status

- **Phase 1 (MVP):** Complete — transcription pipeline
- **Phase 2 (OCR):** Complete — frame sampling, scene-change detection
- **Phase 3 (Platform):** Complete — platform profiles, UI filter, OCR wire-in
- **Phase 4 (Merge):** Complete — ASR↔OCR merge with dedup
- **Phase 5 (Polish):** Complete — LLM cleanup, batch processing, Docker containerization
- **Phase 6 (Advanced):** Partially complete — FastAPI mode and translation shipped; Web UI, speaker diarization, and browser extension not started

## Toolkit

**claude-code-toolkit v3.0.0** (`34fde8d`), synced 2026-09-02 (PR #134).

The v3.0.0 consolidation retired three agents — **spawn the successor, not the retired name**:

| Retired | Spawn instead | Why it is safe |
|---|---|---|
| `requirements-engineer` | `architect` | absorbed it; carries `brainstorming` (`AGENT_TEAM.md:405`, PO routing at `:65`) |
| `test-writer` | `tester` | absorbed it; carries `test-driven-development` (`:404`) |
| `doc-generator` | `coder` | absorbed it |

Absorb, not rename — the survivors gained the skills, so no capability was lost. Seven agent files remain.

Permanent deviations, deliberate and not drift to clean up: `PROJECT_CONTEXT.md`, `CLAUDE.md`, `PROJECT_STATE.md`. `hooks/run-gate.sh` left this list in PR #131 — the #98 pytest-cov preflight moved out to repo-root `preflight.sh`, wired through the **Gate Command** under the toolkit's terminal contract, so the hook is now byte-identical to the template and auto-updates.

## Backlog

_See GitHub Issues._
