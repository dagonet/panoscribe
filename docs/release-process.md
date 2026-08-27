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

## TestPyPI first

The `panoscribe` name is not yet registered on real PyPI. Until the pending
publisher above is confirmed to exist and a TestPyPI publish has been
verified, do not run the `pypi` target.
