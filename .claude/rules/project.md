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

Always-on project rules belong in CLAUDE.md's PROJECT-CUSTOM region, not here;
a rule in both places exists twice and drifts.

---

**panoscribe carries no rules here deliberately.** The always-on set lives in
`CLAUDE.md`'s PROJECT-CUSTOM region — green-CI merge gate, verify-jobs-not-
conclusion, gate artifact location, the `uv sync --extra dev --extra api`
bootstrap note, and the compact rule. Add `paths:`-scoped conventions below this
line if a rule should load only when a matching file is touched; put anything
always-on in the region instead.
