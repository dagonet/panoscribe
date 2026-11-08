# Release process

panoscribe publishes to PyPI via [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC) — there is no API token or long-lived secret in GitHub. The release
workflow is `.github/workflows/publish.yml`.

## One-time setup (already required before the first release)

On both pypi.org and test.pypi.org, create a **pending publisher** for the
`panoscribe` project with these exact values:

| Field | Value |
| --- | --- |
| Owner | `dagonet` |
| Repository | `panoscribe` |
| Workflow filename | `publish.yml` |
| Environment name | `testpypi` (TestPyPI) / `pypi` (PyPI) |

The workflow filename is load-bearing — PyPI ties the pending publisher to that
exact name. If the workflow is ever renamed, the pending/trusted publisher
config on both indexes must be updated first, or every publish job will fail
OIDC verification.

Also create matching GitHub Environments named `testpypi` and `pypi` under
repo Settings -> Environments (needed for the `environment:` gate on each
publish job; add required reviewers there if you want a manual approval step
before a real PyPI publish).

## Cutting a release

1. **Bump the version** in `pyproject.toml` (`version = "X.Y.Z"`). This project
   does not use VCS-derived versioning — the literal must be updated by hand
   and must exactly match the tag pushed in step 3, or the `guard` job in
   `publish.yml` fails the run.
2. **Update `CHANGELOG.md`** with the new version's entries.
3. **Tag and push**:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
4. Pushing the tag triggers `.github/workflows/publish.yml`, which:
   - re-runs the full CI suite (`ci.yml`, invoked as a reusable workflow),
     including the `ocr-engine` job (see below),
   - runs `guard` to confirm the tag matches the `pyproject.toml` version,
   - builds sdist + wheel with `uv build` and validates them with
     `twine check --strict`,
   - publishes to **TestPyPI** automatically on tag push.
5. Once the name is registered and TestPyPI has verified good, trigger a real
   PyPI publish via `workflow_dispatch` with `target: pypi` (this job is
   gated behind an explicit dispatch input so it cannot fire accidentally on
   an ordinary tag push).
6. On a successful `publish-pypi`, the `create-release` job automatically
   creates the GitHub Release for `vX.Y.Z`, using the matching `## [X.Y.Z]`
   section of `CHANGELOG.md` as the release notes. **Do not create the
   GitHub Release by hand** — the job is idempotent (it edits the Release if
   one already exists for that tag instead of failing), so a manual Release
   created before the workflow runs is fine, but creating one afterwards
   would be a duplicate. No Release is created for a bare tag push or a
   `target: testpypi` dispatch, since those only publish to the TestPyPI
   rehearsal index, not the real one. If `create-release` fails after
   `publish-pypi` already succeeded (e.g. a missing `CHANGELOG.md` section),
   the package is already live on PyPI -- re-dispatching would hit the
   intentional "file already exists" failure from step 5, so recover by
   creating the Release by hand instead of re-running the workflow.

## The `ocr-engine` job gates releases

`ci.yml` has a job named `ocr-engine` that runs on every pull request (and
on pushes to `main`), and so also inside the release workflow, because `publish.yml` calls
`ci.yml`. It builds the real RapidOCR engine on CPU for every mapped
language plus de/fr/es/pt on the v6 path, under both model sets
(`uv run pytest -m engine`);
the normal `test` job mocks RapidOCR and cannot see a rapidocr update that
drops a model. A red `ocr-engine` job stops the release before anything is
built or published.

On a cold cache the job downloads about 205 MB of models and fonts from `modelscope.cn`
(the job timeout is 20 minutes). The models are cached under
`rapidocr/models` in the package folder, with a cache key that holds the
rapidocr version (`rapidocr-models-3.10.0-...` in `ci.yml`); change the key
when rapidocr is bumped. On a rapidocr bump also check that `_LAZY_LOADERS`
(`src/panoscribe/ocr/rapid_ocr.py`) and the private `_load_*` calls in the
Dockerfile still exist in the new version. If the run fails while downloading, re-run it first:
a `modelscope.cn` outage looks the same as a missing model.

## Known post-publish artifact: stale uv cache

Right after a successful `publish-pypi` run, an install with `uv pip install
panoscribe==<version>` can fail with a misleading "no version" error even
though the package is live — this is a stale `uv` package-index cache, not a
failed release. See
[docs/troubleshooting.md#stale-uv-cache-right-after-a-release](troubleshooting.md#stale-uv-cache-right-after-a-release)
before assuming the publish itself needs to be re-run.

## TestPyPI first

The `panoscribe` name is not yet registered on real PyPI. Until the pending
publisher above is confirmed to exist and a TestPyPI publish has been
verified, do not run the `pypi` target.
