# Project instructions
<!-- template-sync: project-owned; migrated from CLAUDE.md at v3.1.0; migration-base: 1450034; rendered: yes -->

## Migrated from CLAUDE.md — review, then keep or delete
```diff
--- CLAUDE.md@1450034
+++ CLAUDE.md@project
@@ -70,7 +70,7 @@
 
 **Strong triggers, plugin defaults, and meta skills:** see the same section in `~/.claude/CLAUDE.md`.
 
-**When spawning agents:** `AGENT_TEAM.md` -> *Spawn-Prompt Binding Table* lists the skills each subagent type must invoke. `hooks/require-skills-block.sh` enforces it mechanically — a spawn of a bound `subagent_type` without a `## Required Skills` block is blocked with exit 2.
+**When spawning agents:** every spawn of a bound `subagent_type` MUST carry a `## Required Skills` block in the prompt body, listing the skills that `AGENT_TEAM.md` -> *Spawn-Prompt Binding Table* binds to that type. Also enforced by `hooks/require-skills-block.sh`.
 
 ## Working Preferences
 
@@ -148,15 +148,17 @@
 ## Quick Start
 
 ```bash
-uv sync --extra dev --extra api               # Build the project
-uv run pytest                # Run tests
-uv run ruff format .              # Format code
-uv run ruff check .                # Lint code
+uv sync --extra dev --extra api  # Build: install/sync the environment (test/dev tooling lives in optional-dependencies)
+uv run pytest               # Run tests
+uv run ruff format .        # Format code
+uv run ruff check .         # Lint code
+bash hooks/run-gate.sh      # Green-CI gate (format-check + lint + coverage) -> .gate/last-pass.json
 ```
 
-> Replace placeholders above with your project's actual commands from `PROJECT_CONTEXT.md`.
+> Full command reference: `PROJECT_CONTEXT.md`.
 
 ---
 
 <!-- Project-specific rules and plugin routing blocks (context-mode, …) belong inside the PROJECT-CUSTOM region below -->
 
+
```
