# Project rules (yours; sync never overwrites this file)

<!-- template-sync: project-owned, and never overwritten by a sync; introduced in v3.1.0 -->

This file has no `paths:` key, so Claude Code loads it at EVERY session start,
at the same priority as CLAUDE.md. Anything you write here is always on.

A new or edited rules file is picked up at the NEXT session start, not the current
one -- restart the session to test a change.

To scope it to files instead, add a frontmatter block at the very top:

    ---
    paths:
      - "src/**/*.py"
      - "pyproject.toml"
    ---

Always-on project rules belong in `.claude/project-instructions.md` (imported at
the end of CLAUDE.md), not here; a rule in both places exists twice and drifts.

---

**panoscribe carries no rules here deliberately.** The always-on set lives in
`.claude/project-instructions.md` — green-CI merge gate, verify-jobs-not-
conclusion, gate artifact location, the `uv sync --extra dev --extra api`
bootstrap note, and the compact rule. Add `paths:`-scoped conventions below this
line if a rule should load only when a matching file is touched; put anything
always-on in `project-instructions.md` instead.

> Both sentences above said `CLAUDE.md`'s PROJECT-CUSTOM region until the v4.1.0
> sync. That region no longer exists, and `hooks/deny-claude-md-writes.sh` now
> refuses writes to `CLAUDE.md` outright — so an always-on file was telling every
> session to put rules somewhere nonexistent and write-denied. Upstream corrected
> its own seed in v4.1.0; this file is `once`-class, so that correction could
> never arrive on its own and had to be made by hand. `once` cuts both ways.
