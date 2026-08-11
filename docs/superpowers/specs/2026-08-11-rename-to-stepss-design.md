# Rename PyRAMSES to STEPSS for Python

**Date:** 2026-08-11
**Status:** Approved, ready for implementation planning

## Summary

Rename the repository `SPS-L/stepss-pyramses` to `SPS-L/stepss-python-ui`, rename
the Python package from `pyramses` to `stepss`, and publish it to PyPI as
`stepss` so that users install it with `pip install stepss`. Existing
`import pyramses` code keeps working through a one-time compatibility
distribution that forwards to the new package.

In the same pass, migrate PyPI publishing from a long-lived API token to
GitHub OIDC trusted publishing. This is bundled deliberately rather than
deferred: trusted publishing binds to `owner/repo`, which is the thing this
project changes, so doing it separately would mean configuring the binding
twice.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Distribution and import name | `stepss` | The wheel bundles the RAMSES and Helios binaries rather than merely binding to them, so for a pip user it genuinely is the platform. Matches the brand and the docs domain. Avoids a `py` prefix that modern practice treats as redundant. |
| Repository name | `stepss-python-ui` | Parallels `stepss-java-ui`, so the org listing reads as one platform with a Java front end and a Python front end. |
| Backward compatibility | PyPI transition shim | Old code, notebooks and student scripts keep running untouched, and keep receiving engine updates. Published once, never maintained. |
| Docs URLs | `/python/*` with redirects | Leaves room for a future `/java/` section. Avoids `stepss.sps-lab.org/stepss/overview/`. |
| PyPI auth | OIDC trusted publishing | Removes a long-lived credential and adds PEP 740 attestations. |
| Rename mechanism | GitHub rename in place | Preserves history, tags, issues and stars, and keeps the version scheme continuous (see below). |

### Alternatives considered and rejected

- **`pystepss`.** Follows the `pypowsybl` precedent for a Python API onto a
  multi-language platform, and puts clear water between this package and the
  existing PyPI project `steps` (STochastic Engine for Pathway Simulation,
  v5.1.0), which is one letter away and is also a simulator. Rejected because
  the wheel is not a thin binding: it ships the engines. The `steps` collision
  is a search and typo nuisance, not a correctness problem.
- **Hard break** (final `pyramses` release raises `ImportError`). Rejected:
  breaks every existing notebook on upgrade for no benefit the shim does not
  already deliver.
- **Freeze `pyramses` silently.** Rejected: existing installs would stop
  receiving engine updates with no in-code signal that a successor exists.
- **A new repository instead of a rename.** Rejected: it would orphan the tags
  that `tools/bump_version.sh` derives the version counter from, breaking the
  documented version scheme at exactly the moment it is hardest to verify.

## What is deliberately held constant

- **The version scheme.** Versions stay `<bundled RAMSES version>[.<counter>]`.
  Renaming in place preserves the tags, and `bump_version.sh` derives the
  counter from the tags that already exist rather than from a stored number,
  so it keeps counting correctly straight through the rename. The rename does
  not perturb it at all, which the events of 2026-08-11 demonstrated: RAMSES
  v3.58 was published while this spec was being written, and the automation
  released `pyramses 3.58` (bundling RAMSES v3.58, Helios v1.4.1) on the old
  name, unaffected. Tag `v3.58` therefore exists, the bare version on that base
  is taken, and **the first `stepss` release is `3.58.1`** (confirmed by
  running `bash tools/bump_version.sh manual`). No reset to 1.0, and no
  discontinuity in the rule that the leading components name the RAMSES shared
  library inside the wheel.

  Re-derive that number the same way if a further upstream release lands before
  the first `stepss` release; do not trust it as a constant.
- **Public API names**: `cfg`, `sim`, `extractor`, `cur`, `curplot`,
  `HeliosSession`, `HeliosError`. Only the package containing them moves. This
  is what makes the shim a pure forward with no translation layer.
- **The `ramses` console script name.** It launches RAMSES, which is still
  true. Only its target changes, to `stepss.scripts.exec:run`.
- **Conventions**: camelCase for the RAMSES API, snake_case for
  `stepss.helios`. Default branch stays `master`.
- **The Nordic regression baseline.** `tests/baselines/nordic_baseline.npz` is
  shared byte-for-byte with `stepss-ramses` and must not be touched by this
  work.

## Scope

**In scope:** the package repository, the two upstream dispatch workflows in
`stepss-ramses` and `stepss-helios`, the umbrella submodule pointer, and the
documentation site.

**Out of scope, tracked as a follow-up sweep:** the twelve content repositories
that mention `pyramses` in notebooks, example scripts and READMEs. The shim
keeps all of them working, so their timing is free. They are enumerated in the
appendix.

## Component 1: repository rename

Rename `SPS-L/stepss-pyramses` to `SPS-L/stepss-python-ui` through GitHub's
repository settings. GitHub serves redirects for git remotes and for API
requests to the old name.

**The redirect does not extend to OIDC.** The token GitHub Actions mints
carries the repository's current name, so the rename must land before the first
publish, and the trusted publishers must be registered against the new name.

## Component 2: package rename

`git mv src/pyramses src/stepss`, then update references. Tracked files
carrying `pyramses` or `PyRAMSES`, by reference count:

| File | Refs | Nature of the change |
|---|---|---|
| `src/pyramses/simulator.py` | 82 | Docstrings, `RAMSESError` messages, module paths |
| `src/pyramses/extractor.py` | 47 | Docstrings and cross-references |
| `README.rst` | 41 | Title, badges (PyPI URLs), install instructions, prose |
| `src/pyramses/cases.py` | 21 | Docstrings |
| `src/pyramses/__init__.py` | 9 | `__package_name__`, module docstring, `:class:` targets |
| `.github/copilot-instructions.md` | 9 | Prose |
| `CLAUDE.md` | 8 | Paths and prose |
| `src/setup.py` | 5 | `read_metadata` path, `package_data` key, `entry_points`, description, keywords |
| `src/pyramses/scripts/exec.py` | 5 | Module path |
| `src/pyramses/globals.py` | 5 | Docstrings |
| `src/README.rst` | 3 | Prose |
| `src/pyramses/helios.py` | 3 | Docstrings |
| `src/pyramses/_bundled.py` | 1 | Header comment (file is CI-managed) |
| `NOTICE` | 1 | Prose |

`setup.py` needs care in three places: `read_metadata` opens
`os.path.join(dirname, 'pyramses', '__init__.py')`; `package_data` is keyed on
the string `'pyramses'`; and `entry_points` names `pyramses.scripts.exec:run`.
The regex parse of `__version__` is unaffected, but the constraint documented
in CLAUDE.md still holds: the assignment must stay a plain
`__version__ = 'x.y.z'` at the start of a line.

`src/MANIFEST.in` and `.github/workflows/tests.yml` are name-agnostic and need
no change.

Tests and examples are mechanical `import pyramses` to `import stepss` edits:
`tests/conftest.py`, the five `tests/test_*.py` files, and the five
`examples/helios/*.py` files. `tests/test_nordic.py` additionally imports
`RAMSESError` from `pyramses.globals`.

**Historical documents are not rewritten.** The two files under
`docs/superpowers/` (127 and 43 references) describe the release automation
project as it was, and `stepss-docs/public/changelog.txt` is a changelog.
Rewriting either would misrepresent what happened. They keep the old name.

## Component 3: the transition shim

A second distribution named `pyramses`, sourced at `compat/pyramses/` inside
the renamed repository, depending on `stepss>=3.58.1`.

```python
import importlib, sys, warnings
import stepss
from stepss import *                    # noqa: F403
from stepss import __all__, __version__

# `from stepss import *` does not recreate submodule paths, and
# `from pyramses.globals import RAMSESError` is a documented usage, so alias
# the real modules into this package's namespace explicitly.
for _sub in ('globals', 'cases', 'simulator', 'extractor', 'helios'):
    sys.modules[__name__ + '.' + _sub] = importlib.import_module('stepss.' + _sub)

warnings.warn("pyramses is now stepss: pip install stepss. This compatibility "
              "package forwards to it and will not be updated.",
              DeprecationWarning, stacklevel=2)
```

The `sys.modules` aliasing is the load-bearing part. A star-import alone would
leave `from pyramses.globals import RAMSESError` raising `ModuleNotFoundError`,
which is precisely the import path the Nordic regression test and the CLAUDE.md
guidance use.

The shim's own distribution version is `3.58.1`, matching the first `stepss`
release. Under PEP 440 that is greater than the last real `pyramses` (3.58),
so unpinned users upgrade into the bridge. The `>=` dependency means it keeps
delivering the current engine indefinitely without further releases. Note that
`pyramses.__version__` will therefore report the version of the `stepss`
actually installed, not the shim's, which is the more useful answer.

Published by a dedicated `publish-compat-shim.yml`, `workflow_dispatch` only,
run once. A dedicated workflow keeps the blast radius small and gives the
trusted publisher on the `pyramses` project a filename to bind to that is not
entangled with the `stepss` release path.

## Component 4: OIDC trusted publishing

Three publishers, already registered:

| PyPI project | Repository | Workflow file | Environment |
|---|---|---|---|
| `stepss` | `SPS-L/stepss-python-ui` | `sync-upstream-release.yml` | `pypi` |
| `stepss` | `SPS-L/stepss-python-ui` | `python-publish.yml` | `pypi` |
| `pyramses` | `SPS-L/stepss-python-ui` | `publish-compat-shim.yml` | `pypi` |

**Repository changes.** Create a `pypi` environment under Settings,
Environments, with its deployment branch restricted to `master` and **no
required reviewers**. The release path is unattended: `repository_dispatch`
fires it from `stepss-ramses` and `stepss-helios`, so a required reviewer would
hang the release job waiting for a human who does not know they are needed.
Accepted consequence: a `workflow_dispatch` from a feature branch with
`publish` ticked is blocked, which is the correct outcome anyway.

**Workflow changes**, in both `sync-upstream-release.yml` (the `release` job)
and `python-publish.yml` (the `deploy` job):

```yaml
    environment: pypi          # add
    permissions:
      contents: write          # unchanged (read, in python-publish.yml)
      id-token: write          # add
```
```yaml
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          packages-dir: dist/   # `password:` deleted
```

The upload stays inside the existing `release` job rather than moving to an
id-token-only job. Splitting would be marginally tighter, but that job already
holds `contents: write`, and the split would break the `pypi_done` output that
`report-failure` keys "retryable" against "version gone" off.

`pypa/gh-action-pypi-publish` stays pinned at `@release/v1` per the umbrella
CLAUDE.md: that is a rolling branch upstream publishes through, and is the one
documented exception to major-only pinning.

Under trusted publishing the action emits PEP 740 attestations by default, so
releases gain signed provenance at no cost.

**Final step: delete the `PYPI_API_TOKEN` repository secret and revoke the
token on PyPI.** Leaving it in place forfeits the point of the migration.

## Component 5: upstream dispatch targets

- `stepss-ramses/.github/workflows/release.yml:364`
- `stepss-helios/.github/workflows/ci.yml:200`

Both call `gh api /repos/SPS-L/stepss-pyramses/dispatches`. GitHub's rename
redirect keeps these firing, so nothing breaks at the moment of rename, but
leaving them is a latent trap: if a repository is ever created at the old name,
the dispatch silently retargets to it. Update both to `stepss-python-ui`.

Per the repo conventions, these use `gh api -f` and never `-F`.

## Component 6: umbrella repository

In `stepss/`:

- `.gitmodules`: rename the section, path and URL to `stepss-python-ui`. The
  URL stays relative (`../stepss-python-ui.git`). The tracked branch stays
  `master`.
- Move the submodule working directory and update `.git/modules` accordingly.
- Update the component table in `stepss/CLAUDE.md` and `README.md`.

## Component 7: documentation site

- `git mv src/content/docs/pyramses src/content/docs/python`.
- `astro.config.mjs`: sidebar group label `PyRAMSES` becomes `Python API`; the
  five slugs `pyramses/*` become `python/*`. The deliberately divergent label
  on the Helios page ("Helios Power-Flow API", distinct from the engine
  reference under Simulation Guide) is preserved.
- Add five `redirects` entries beside the existing `/user-guide/pfc` one:
  `/pyramses/overview`, `/pyramses/installation`, `/pyramses/examples`,
  `/pyramses/api-reference`, `/pyramses/helios`. The stepss-helios and
  stepss-cg-studio READMEs and PyPI both link into these paths.
- Content sweep across the roughly 25 files naming pyramses, including
  `getting-started/installation.mdx`, `getting-started/quickstart.mdx`,
  `getting-started/overview.md`, `getting-started/license.md`, `index.mdx`,
  `developer/uramses.mdx`, `resources/repositories.md` (repository URL),
  `resources/references.md`, the `test-systems/` pages, three `models/` pages,
  and four `user-guide/` pages.
- Update the "One owner per topic" table in `stepss-docs/CLAUDE.md`: the owner
  row for the Python API changes from `pyramses/` to `python/`.
- `public/changelog.txt` is left alone as a historical record.

House style applies: no em-dashes, verified with
`grep -rnP '\x{2014}' src CLAUDE.md README.md astro.config.mjs`.

## Order of operations

The sequence is forced by the OIDC and PyPI couplings.

1. Rename the GitHub repository. Must precede any publish, because OIDC reads
   the current name.
2. Create the `pypi` environment (branch-restricted to `master`, no reviewers).
3. Update the umbrella `.gitmodules` and submodule path.
4. In-repo rename: `git mv`, all references, shim added, workflows switched to
   OIDC. Full test suite green locally.
5. Update the two upstream dispatch targets in `stepss-ramses` and
   `stepss-helios`.
6. **Documentation site, merged and deployed.** This ordering is load-bearing
   and an earlier draft of this spec had it wrong, placing the docs last.
   `README.rst` becomes the PyPI **long description**, and PyPI freezes that
   text into the release: it cannot be edited afterwards, and correcting it
   costs another version number that can never be reclaimed. The README links
   to `/python/*` pages that do not exist until this deploy lands. Releasing
   first would permanently attach a project page of dead links to `3.58.1`.
   Verify the five URLs serve `200` before continuing.
7. **Rehearse**: `workflow_dispatch` with `publish` unticked. Per the existing
   design this runs fetch, build and the three-platform gate, then stops,
   reaching neither `master` nor PyPI. This proves the renamed pipeline without
   spending a version.
8. Real release: `workflow_dispatch` with `publish` ticked. Creates the
   `stepss` project on PyPI and converts the pending publisher.
9. Publish the shim once via `publish-compat-shim.yml`, pinned to `>=` the
   version from step 8.
10. Delete and revoke `PYPI_API_TOKEN`.
11. Follow-up sweep (out of scope here).

Step 6 is not optional. It is the only thing that exercises the renamed paths
across Linux, Windows and macOS before a version is spent.

## Testing

Existing gates carry over unchanged:

- `pip install ./src` then `pytest tests/ -v`.
- The Nordic regression gate against the byte-shared baseline. The documented
  behaviour still applies: `execSim()` raises `RAMSESError` with flag `-1`
  naming `sim_minmaxvolt`, a clean completion is the regression, and `endSim()`
  must not be called after the trip.
- `bash tools/test_bump_version.sh` and `bash tools/test_update_ramses_libs.sh`,
  both of which contain path fixtures needing updates (19 and 5 references).

New gate, to be added: in a clean virtualenv, `pip install pyramses` must yield

- a working `import pyramses`,
- a working `from pyramses.globals import RAMSESError`,
- a `DeprecationWarning` raised on import.

Documentation site: `npm run build`, which is the only validation step and
catches every internal link the page move breaks.

## Risks

| Risk | Mitigation |
|---|---|
| Trusted publisher misconfigured (wrong workflow filename, missing `environment:` declaration) | Returns 403 and uploads nothing, so no version is spent. Fix the binding and re-run `python-publish.yml` with the same tag; the gated wheel is already attached to the GitHub release. |
| The `stepss` name is taken before the first release. A pending publisher does not reserve it. | Keep the gap between configuration and step 7 short. |
| Break-glass unusable if only its publisher is wrong | Both `stepss` publishers are registered up front, so the two paths fail independently. |
| Inbound links to `/pyramses/*` break | Five redirect entries, matching the precedent set for `/user-guide/pfc`. |
| A downstream repo pins `pyramses==3.58` (or any earlier version) | Unaffected. Unpinned consumers upgrade into the shim. |

## Appendix: follow-up sweep (out of scope)

Repositories mentioning `pyramses` that the shim keeps working, to be updated
separately: `stepss-test-systems` (notebooks, scripts and READMEs across ten
test systems), `stepss-ramses` (`examples/Nordic/`, `docs/`), `stepss-helios`
(`README.md`, `docs/`, `tests/smoke/api_smoke.py`), `stepss-eigenanalysis`
(example notebooks), `stepss-uramses`, `stepss-RamsesNN`, `stepss-java-ui`,
`stepss-userguide` (`install.tex`), and `stepss-cg-studio`.
