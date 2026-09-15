# Project rules (yours; sync never overwrites this file)

<!-- template-sync: project-owned, and never overwritten by a sync; introduced in v3.1.0 -->

Add `paths:`-scoped conventions here — style, language and file-type rules that
should load only when a matching file is touched.

**This file is deliberately inert.** A rules file with no `paths:` key loads at
launch at `CLAUDE.md` priority, so anything written here is always in context.
panoscribe's always-on project rules live in the PROJECT-CUSTOM region of
`CLAUDE.md`; duplicating them here would create a second always-loaded copy to
drift out of sync with the first.

> The v2→v3 migration originally wrote a diff of `CLAUDE.md`'s out-of-region
> hunks into this file, on the assumption that an unscoped rules file is never
> delivered. That assumption was wrong — the file loads for every session — so
> the record was removed: both hunks were superseded by toolkit v4.0.0, and the
> original is preserved in git history and in the pre-migration backup.
> Fixed upstream in toolkit v4.0.1.
