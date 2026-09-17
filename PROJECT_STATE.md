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

**claude-code-toolkit v4.0.1** (`a97235bd`), synced 2026-09-17 (PR #143). Manifest is **v3** (three-class ownership). `template_verify` post_commit: **18 PASS, 0 FAIL**.

Sync history since v3.0.0:

| Version | Commit | PR | Note |
|---|---|---|---|
| v3.0.2 | `60e4b0d` | #137 | |
| v3.0.3 | `86561fe` | #138 | |
| v3.0.4 | `1450034` | #139 | |
| — | — | #140 | Fixed `placeholders.BUILD_COMMAND`, which held the *test* command; repaired the rendered damage at `CLAUDE.md:88` |
| v4.0.0 | `89dcaee` | #141 | Manifest v2 → v3; sync server now ships from the toolkit checkout |
| — | — | #142 | Declared `**Gate-checked branches**`/`**PO write surface**`/`**Post-edit build**` (all `none`, measured); removed `**Test Command**` |
| v4.0.1 | `a97235bd` | #143 | `lastSynced*` pair dropped; gate artifacts moved into `.git/gate/`; `**Gate Command**` → `**Gate**` |

### v4.0.1 — what changed here

- **Legacy version labels gone.** `lastSyncedVersion`/`lastSyncedVersionOf` were client-stamped by the old skill step 7b and duplicated the server-written `template_version`/`template_commit`. Step 7b is deleted upstream, so `superseded_keys_dropped` removed them for good rather than re-adding them next sync. `unknown_keys` is now empty.
- **Gate artifacts moved** to `<common git dir>/gate/last-pass.<sha>.json` — shared across worktrees, and inside `.git`, so no longer a working-tree object `git add -A` could sweep up. The three legacy `.gate/` files were removed **by name** after checking `**Log Path**`; another consumer had 585 KB of unrecoverable logs behind the same instruction when it said to delete the directory.
- **`**Gate Command**` renamed to `**Gate**`.** v4.0.1 normalised `Gate` and `Test` to the short spelling while keeping `Build`/`Format`/`Lint Command` long. The hooks accept both; the rename cleared the one `template_verify` FAIL (`declared_keys: deprecated_spelling`). **Do not** shorten Build/Format/Lint — the template declares those long, and renaming creates the same mismatch in the other direction.

**CORRECTION carried in #143:** the long-standing note that `**Test**: none` is eval'd as a command and blocks every commit is **wrong, and has been since toolkit v3.0.3**. `hooks/pre-commit-test.sh` treats a trimmed, case-insensitive `none` as *not declared* and falls through to the Gate — identical to absent. It came from the template's own stale comment, which is `once`-class here and so would never have self-corrected. `**Test**` stays absent because absent is unambiguous, not because `none` is unsafe.

**Rules-file delivery, measured 2026-09-17.** An *unscoped* `.claude/rules/*.md` (no `paths:` key) IS delivered to every subagent at spawn, with full content, at `CLAUDE.md` priority — `.claude/rules/project.md` arrives; `python.md` (scoped `**/*.py`) does not. But a rules file **created or edited mid-session does not reach a subagent spawned later in that session** — measured twice, untracked and staged, so index-tracked-ness is not the gate. Whether the gate is "committed to HEAD" or "present at session start" is unresolved. Practical rule: after touching a rules file, assume nothing reads it until the next session.

### v4.0.0 — manifest v2 → v3 ownership classes

Three `keep-mine` resolutions were dropped by the migration. A dropped resolution is a loss **only when the incoming class is weaker**:

| Path | Incoming class | Effect |
|---|---|---|
| `PROJECT_CONTEXT.md` | `once` | **Stronger** than `keep-mine` — never overwritten again |
| `PROJECT_STATE.md` | `once` | **Stronger** |
| `CLAUDE.md` | `template` | The only real one; resolved by **accepting the template** |

`CLAUDE.md`'s two out-of-region deviations were both superseded by v4.0.0 (it ships the single-entry-point Quick Start and an equivalent Required-Skills sentence). The PROJECT-CUSTOM region is preserved by the region mechanism, independently of ownership class.

`CLAUDE.local.md` is now **project-owned** — dropped from manifest tracking as project-class, untouched on disk.

**`once` cuts both ways.** A `once` file is never clobbered and, by the same mechanism, never re-diffed — so template-side *additions* never arrive. `PROJECT_CONTEXT.md` therefore keeps the `**Gate Command**` / `**Test Command**` spellings (the hooks still accept both) and will **not** receive the newly declared `**Gate-checked branches**`, `**PO write surface**` or `**Post-edit build**` keys without a hand edit. `**Gate-checked branches**` is the one with teeth: its absence is why `gate-before-merge.sh`'s gate-checked arm has never once fired here.

**`.claude/rules/project.md` loads at launch.** A rules file with no `paths:` key is delivered at every session start at `CLAUDE.md` priority — only `paths:`-scoped ones are lazy. The migration wrote a diff of `CLAUDE.md`'s out-of-region hunks there on the opposite assumption; the body was replaced with an inert note in #141, and the always-on rules stay in `CLAUDE.md`'s PROJECT-CUSTOM region as the single source. Fixed upstream in toolkit v4.0.1.

The v3.0.0 consolidation retired three agents — **spawn the successor, not the retired name**:

| Retired | Spawn instead | Why it is safe |
|---|---|---|
| `requirements-engineer` | `architect` | absorbed it; carries `brainstorming` (`AGENT_TEAM.md:405`, PO routing at `:65`) |
| `test-writer` | `tester` | absorbed it; carries `test-driven-development` (`:404`) |
| `doc-generator` | `coder` | absorbed it |

Absorb, not rename — the survivors gained the skills, so no capability was lost. Seven agent files remain.

**Deviation tracking is now the ownership class, not a hand-kept list.** Under manifest v3 the old "permanent deviations" list (`PROJECT_CONTEXT.md`, `CLAUDE.md`, `PROJECT_STATE.md`) is obsolete: `PROJECT_CONTEXT.md`, `PROJECT_STATE.md` and `VERIFICATION_PLAYBOOK.md` are `once` (kept by the class, no annotation needed), and `CLAUDE.md` is `template` with its project content held in the PROJECT-CUSTOM region. `hooks/run-gate.sh` left the old list back in PR #131 — the #98 pytest-cov preflight moved out to repo-root `preflight.sh`, wired through the **Gate Command** under the toolkit's terminal contract, so the hook is byte-identical to the template and auto-updates.

`preflight.sh` itself stays project-owned at the repo root and is **not** manifest-tracked: it runs as the first command of the Gate Command precisely so it does not have to live inside `hooks/run-gate.sh`, which syncs verbatim and would force a hand-merge on every release.

## Backlog

_See GitHub Issues._
