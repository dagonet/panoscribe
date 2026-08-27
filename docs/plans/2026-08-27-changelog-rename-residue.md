# Clean rename residue in CHANGELOG.md

Tier: T1

## Problem

A full case-insensitive audit of the `omniscribe` -> `panoscribe` rename (all tracked
files, plus untracked sweeps of `.claude/` and `hooks/`) found 434 hit lines. All but
two are intentional history. The two stale spots are both in `CHANGELOG.md`:

1. `CHANGELOG.md:3` — the document's own header sentence:
   `All notable changes to OmniScribe will be documented in this file.`
   This describes the project in the present tense, not a dated record. Should say
   panoscribe.

2. `CHANGELOG.md:270-285` — 16 link-reference definitions of the form
   `[0.x.y]: https://github.com/dagonet/OmniScribe/releases/tag/vX.Y.Z` (0.1.0 through
   0.2.5). The repo is now `dagonet/panoscribe`. GitHub redirects renamed repos so
   these resolve today, but they break permanently if the old name is ever reclaimed
   by someone else — which is exactly the risk that motivated the rename.

## Explicitly NOT in scope

Do not rewrite historical content. These are correct as-is and must stay:

- `README.md:308-319` — the "Renamed from OmniScribe" migration section, including the
  `OMNI_*` -> `PANO_*` env var mapping. It must name the old thing to be useful.
- `CHANGELOG.md` dated release entries (~43 hits) describing what actually shipped at
  the time: `src/omniscribe/...`, `OMNI_OCR_DET_LANG`, `OmniScribeError`,
  `--cov=omniscribe`. Rewriting these falsifies history.
- `docs/plans/*.md` — 22 files, ~323 hits. Historical sprint/phase records, the rename
  decision record itself, and the three 2026-08-26 plans authored pre-rename.

## Verified consistent — do not touch

All six naming surfaces already agree on `panoscribe`: pyproject dist name (:2) and
wheel packages (:116), the module dir `src/panoscribe/`, the entry point (:75), the
`--cov=panoscribe` target in both PROJECT_CONTEXT.md:15 and ci.yml:35, project URLs
(:78-81) matching `git remote`, and README badges. No mismatches.

## Scope

1. `CHANGELOG.md:3` — OmniScribe -> panoscribe.
2. `CHANGELOG.md:270-285` — the 16 link-reference URLs, `dagonet/OmniScribe` ->
   `dagonet/panoscribe`. Mechanical; change only the org/repo path, leave tags and
   version labels alone.

## Branch cleanup (same task, separate from the PR)

Delete remote branch `origin/docs/project-state-phase-6`. It does not appear in
`git branch -r --merged main` because it was squash-merged (as main's 4cf156a, PR #94),
so no merge commit links it. Verified by content instead: its sole content commit
0095bcc changes one line of PROJECT_STATE.md, and the only remaining diff against main
is `# panoscribe — Project State` vs `# OmniScribe — Project State`. The rest of the
97-file diff is just the branch predating the rename. Zero unique work is lost.

## Verification

- `bash hooks/run-gate.sh` -> PASS, expect 604 passed / 98.40%.
- `grep -rin omniscribe CHANGELOG.md` -> only dated historical entries remain; the
  header line and all 16 link refs are clean.
- No other tracked file changes.
