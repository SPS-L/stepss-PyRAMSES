# Rename to stepss-python-ui / stepss Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename this repository to `stepss-python-ui` and its Python package from `pyramses` to `stepss`, publish it to PyPI as `stepss` over OIDC trusted publishing, and keep every existing `import pyramses` working through a one-time forwarding distribution.

**Architecture:** The package directory moves with `git mv` so history follows it. Everything that names the package is then updated in place. A second, tiny distribution keeps the old import name alive by aliasing the real modules into `sys.modules`. Publishing switches from a long-lived API token to three GitHub OIDC trusted publishers.

**Tech Stack:** Python 3, setuptools, pytest, GitHub Actions, PyPI trusted publishing, Astro/Starlight (docs site).

**Spec:** `docs/superpowers/specs/2026-08-11-rename-to-stepss-design.md`

## Global Constraints

- **First release version is `3.58.1`.** RAMSES v3.58 was published on 2026-08-11 while this plan was being written, and the sync automation released `pyramses 3.58` (bundling RAMSES v3.58 and Helios v1.4.1) before the rename began. Tag `v3.58` therefore already exists, so the bare version on the 3.58 base is taken and the next counter is `.1`. Verified by running `bash tools/bump_version.sh manual`, which prints `3.58.1`. **If another upstream release lands before the first `stepss` release, re-derive this number the same way rather than trusting this line.**
- **The last real `pyramses` release is `3.58`**, not 0.3.5. The shim's own version must exceed it or unpinned users never upgrade into the bridge.
- **The shim pins `stepss>=3.58.1`** and is itself versioned `3.58.1`.
- **Never rename `pyramses-libs-*.zip`.** These are release-asset names produced by `stepss-ramses/.github/workflows/release.yml` (lines 67, 159, 231). Renaming them breaks the binary fetch. They appear in **two** files, and both must be protected: `tools/update_ramses_libs.sh` (lines 28, 34, 35) and `tools/test_update_ramses_libs.sh`, whose fixtures fabricate zips under those exact names to feed a fake `gh`. Renaming only the first leaves the test asserting against names the script no longer requests, which fails loudly; renaming only the second would let the test pass while the real fetch was broken, which does not.
- **Never rename the `PYRAMSES_DISPATCH_TOKEN` secret.** It lives in `stepss-ramses` and `stepss-helios`. It is an identifier, not user-facing; renaming it means coordinated secret rotation across two private repos for zero benefit.
- **Never rewrite historical documents.** `docs/superpowers/plans/2026-08-06-*`, `docs/superpowers/specs/2026-08-06-*` and `stepss-docs/public/changelog.txt` describe what was true at the time. They keep the old name.
- **Do not touch `tests/baselines/nordic_baseline.npz`.** It is shared byte-for-byte with `stepss-ramses`.
- **`__version__` must stay a plain `__version__ = 'x.y.z'` at the start of a line** in the package `__init__.py`. `setup.py` parses it by regex rather than importing it.
- **No em-dashes (U+2014)** in any prose. House style across every `stepss-*` repo. En-dashes are fine in numeric ranges. Verify with `grep -rnP '\x{2014}'`.
- **Never chain git commands** with `&&`, `||` or `;`. Run each separately.
- **Never use `gh api -F`**, always `-f`.
- **GitHub Actions versions** are fixed org-wide: `actions/checkout@v7`, `actions/setup-python@v7`, `pypa/gh-action-pypi-publish@release/v1` (rolling tag, the one documented exception to major-only pinning).
- **Branch:** all code tasks land on `rename-to-stepss`. Default branch stays `master`.

## File Structure

**Moved:**
- `src/pyramses/` becomes `src/stepss/` (whole tree, via `git mv`)

**Created:**
- `src/stepss/scripts/__init__.py`: makes the `scripts` subpackage discoverable by `find_packages()` (Task 2)
- `compat/pyramses/setup.py`: packaging metadata for the forwarding distribution (Task 5)
- `compat/pyramses/README.rst`: PyPI long description explaining the rename (Task 5)
- `compat/pyramses/pyramses/__init__.py`: the forwarding module itself (Task 5)
- `tools/test_compat_shim.sh`: verifies the shim in a clean venv, matching the repo's `tools/test_*.sh` convention (Task 5)
- `.github/workflows/publish-compat-shim.yml`: one-shot publisher for the shim (Task 5)

**Modified:** `src/setup.py`, all `.py` under `src/stepss/`, `tests/conftest.py`, `tests/test_*.py`, `examples/helios/*.py`, `tools/*.sh`, `.github/workflows/{sync-upstream-release,python-publish,bundled-drift-check}.yml`, `README.rst`, `src/README.rst`, `NOTICE`, `CLAUDE.md`, `.github/copilot-instructions.md`, and in other repos: `stepss-ramses/.github/workflows/release.yml`, `stepss-helios/.github/workflows/ci.yml`, `stepss/.gitmodules`, `stepss/CLAUDE.md`, `stepss/README.md`, plus the docs site.

---

## Phase 0: Manual prerequisites

These are GitHub and PyPI console actions. They are not code and cannot be scripted from here. **Publishers are already registered** (confirmed with the user).

- [x] **P0.1** Rename the repository: GitHub, Settings, `stepss-pyramses` to `stepss-python-ui`. Must happen before any publish, because the OIDC token carries the repository's current name and GitHub's rename redirect does not apply to it.

- [x] **P0.2** Update your local remote after the rename:

```bash
git remote set-url origin git@github.com:SPS-L/stepss-python-ui.git
```

- [x] **P0.3** Create the `pypi` environment: Settings, Environments, New environment, name `pypi`. Set **Deployment branches** to "Selected branches", add `master`. Add **no required reviewers** (the release path is unattended `repository_dispatch`; a reviewer would hang it).

- [x] **P0.4** Confirm the three trusted publishers exist and read exactly:

| PyPI project | Owner | Repository | Workflow | Environment |
|---|---|---|---|---|
| `stepss` | `SPS-L` | `stepss-python-ui` | `sync-upstream-release.yml` | `pypi` |
| `stepss` | `SPS-L` | `stepss-python-ui` | `python-publish.yml` | `pypi` |
| `pyramses` | `SPS-L` | `stepss-python-ui` | `publish-compat-shim.yml` | `pypi` |

---

## Task 1: Move the package and turn the test suite green

**Files:**
- Move: `src/pyramses/` to `src/stepss/`
- Modify: `src/setup.py`, `src/stepss/__init__.py`, `src/stepss/simulator.py`, `src/stepss/extractor.py`, `src/stepss/cases.py`, `src/stepss/globals.py`, `src/stepss/helios.py`, `src/stepss/_bundled.py`, `src/stepss/scripts/exec.py`
- Test: `tests/conftest.py`, `tests/test_nordic.py`, `tests/test_helios_basic.py`, `tests/test_helios_data.py`, `tests/test_helios_modify.py`, `tests/test_helios_outputs.py`, `tests/test_examples.py`, `examples/helios/0{1,2,3,4,5}_*.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the importable package `stepss`, exporting exactly what `pyramses` exported: `cfg`, `sim`, `extractor`, `cur`, `curplot`, `helios`, `HeliosSession`, `HeliosError`, plus `stepss.globals.RAMSESError`, `stepss.__version__`, `stepss.__ramses_version__`, `stepss.__helios_version__`, and the submodules `stepss.globals`, `stepss.cases`, `stepss.simulator`, `stepss.extractor`, `stepss.helios`. Task 5's shim depends on every one of these names.

- [ ] **Step 1: Confirm the starting state is green**

```bash
cd /home/apetros/Code/stepss/stepss-python-ui
pip install ./src pytest
pytest tests/ -v
```

Expected: PASS. If it is already red, stop and report; do not rename on top of a broken suite.

- [ ] **Step 2: Move the package directory**

```bash
git mv src/pyramses src/stepss
```

- [ ] **Step 3: Rewrite the package `__init__.py` header**

Replace the module docstring and `__package_name__` in `src/stepss/__init__.py`. Leave `__version__` untouched (the automation owns it, and `setup.py` regex-parses it):

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""stepss - Python interface to the STEPSS power-system simulation platform.

Drives RAMSES, the time-domain dynamic simulator, and Helios, the AC
power-flow engine, both of which ship as bundled shared libraries.

Public API exported by this package:

- :class:`~stepss.cases.cfg` - build and manage a simulation case (input/output files).
- :class:`~stepss.simulator.sim` - load the RAMSES shared library and run simulations.
- :class:`~stepss.extractor.extractor` - parse Fortran binary trajectory files post-simulation.
- :class:`~stepss.extractor.cur` - lightweight NamedTuple holding a (time, value, msg) timeseries.
- :func:`~stepss.extractor.curplot` - plot one or more :class:`cur` objects on a single axes.
- :class:`~stepss.helios.HeliosSession` - run AC power flows with the Helios engine.
- :class:`~stepss.globals.HeliosError` - exception raised by Helios calls.

Module-level flags set at import time:

- ``__runTimeObs__`` - ``True`` when gnuplot is available on the system PATH and runtime
  observable plots are therefore enabled; ``False`` otherwise.

This package was previously distributed as ``pyramses``. The ``pyramses``
distribution on PyPI is now a forwarding shim onto this one.
"""

__package_name__ = "stepss"
```

- [ ] **Step 4: Replace the remaining module references in the package sources**

These files carry the name only in docstrings, `:class:` targets and error message text. `pyramses` never appears as a substring of another identifier in `src/`, so a plain substitution is safe here (unlike `tools/`, see Task 3).

**`--include=*.py` is mandatory, not tidiness.** `src/stepss/libs/` holds the compiled shared libraries, and a bare `grep -rl` reports binary matches: `ramses.so` and `ramses.dll` can contain the string `pyramses` in their symbol or path tables. Feeding those to `sed -i` would rewrite the binaries in place and corrupt the bundled engine, and the Nordic gate would then fail in a way that looks like a solver regression.

```bash
cd /home/apetros/Code/stepss/stepss-python-ui
grep -rl --include='*.py' 'pyramses\|PyRAMSES' src/stepss/ | xargs sed -i 's/pyramses/stepss/g; s/PyRAMSES/STEPSS/g'
```

- [ ] **Step 5: Review that substitution by eye**

```bash
git diff src/stepss/
```

Read every hunk. You are looking for prose that now reads wrong rather than merely renamed, for example a sentence that said "PyRAMSES turns that into a RAMSESError" and now says "STEPSS turns that into a RAMSESError" (correct), versus one that said "PyRAMSES wraps RAMSES" and now says "STEPSS wraps RAMSES" (still correct but check the article). Fix any that read badly. Confirm no line in `src/stepss/libs/` was touched.

- [ ] **Step 6: Update `src/setup.py`**

Three places name the package as a string. All three must change, and none of them is caught by the substitution in Step 4 because `setup.py` lives at `src/`, not `src/stepss/`.

In `read_metadata()`:

```python
    init_path = os.path.join(os.path.dirname(__file__), 'stepss', '__init__.py')
```

In the `setup()` call, the description, keywords, `package_data` key and entry point:

```python
    description='Python interface to the STEPSS power-system simulation platform.',
```
```python
    keywords=['STEPSS', 'RAMSES', 'Helios', 'Power Systems', 'Simulator'],
```
```python
    package_data={
        # Headers are platform-independent and live at the libs/ root; the
        # shared libraries are split per platform because the Linux and macOS
        # RAMSES builds share the filename ramses.so.
        'stepss': ['libs/*.h',
                   'libs/win/*.dll',
                   'libs/lin/*.so',
                   'libs/mac/*.so', 'libs/mac/*.dylib'],
    },
```
```python
    entry_points={
        'console_scripts' : [
            'ramses = stepss.scripts.exec:run',
        ]
    }
```

Also update the module docstring at the top of `setup.py`, which names `pyramses` twice.

- [ ] **Step 7: Update the test suite imports**

```bash
cd /home/apetros/Code/stepss/stepss-python-ui
sed -i 's/pyramses/stepss/g; s/PyRAMSES/STEPSS/g; s/PYRAMSES_HELIOS_LIB_DIR/STEPSS_HELIOS_LIB_DIR/g' \
  tests/conftest.py tests/test_nordic.py tests/test_helios_basic.py \
  tests/test_helios_data.py tests/test_helios_modify.py \
  tests/test_helios_outputs.py tests/test_examples.py
```

`PYRAMSES_HELIOS_LIB_DIR` is a developer-only override read in `tests/conftest.py:17`. It is referenced nowhere else in any repo (checked: `stepss-helios/.github/workflows/ci.yml` only dispatches, it does not run this suite), so renaming it is safe.

- [ ] **Step 8: Update the examples**

```bash
sed -i 's/pyramses/stepss/g; s/PyRAMSES/STEPSS/g' examples/helios/*.py
```

- [ ] **Step 9: Reinstall and run the full suite**

```bash
pip uninstall -y pyramses stepss
pip install ./src
pytest tests/ -v
```

Expected: PASS, same count as Step 1. `tests/test_nordic.py` must still fail-by-design internally: `execSim()` raises `RAMSESError` with flag `-1` naming `sim_minmaxvolt`, and the test asserts that. A Nordic test that suddenly reports a clean run is the regression.

- [ ] **Step 10: Verify no stale references remain in the moved tree**

```bash
grep -rn 'pyramses\|PyRAMSES' src/ tests/ examples/ --exclude-dir=libs --exclude-dir=build --exclude-dir='*.egg-info'
```

Expected: no output.

- [ ] **Step 11: Commit**

```bash
git add -A src tests examples
git commit -m "Rename the pyramses package to stepss"
```

---

## Task 2: Ship the `scripts` subpackage

This fixes a pre-existing bug, confirmed empirically and unrelated to the rename: `src/pyramses/scripts/` has never contained an `__init__.py`, so `find_packages()` never discovered it. `src/pyramses.egg-info/top_level.txt` lists only `pyramses` and `SOURCES.txt` contains no `scripts` entry, yet `entry_points.txt` declares `ramses = pyramses.scripts.exec:run`. The console script installs and then fails to import its target.

Skip this task if you would rather fix it separately; nothing downstream depends on it.

**Files:**
- Create: `src/stepss/scripts/__init__.py`

**Interfaces:**
- Consumes: `stepss` package from Task 1.
- Produces: an importable `stepss.scripts.exec` with a `run` callable.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_examples.py`:

```python
def test_console_script_target_is_importable():
    """The `ramses` console script entry point must be shipped in the wheel.

    Regression guard: `stepss/scripts/` had no __init__.py, so find_packages()
    skipped it and the installed entry point pointed at a missing module.
    """
    from stepss.scripts.exec import run

    assert callable(run)
```

- [ ] **Step 2: Run it and verify it fails**

```bash
pytest tests/test_examples.py::test_console_script_target_is_importable -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'stepss.scripts'`.

- [ ] **Step 3: Create the missing `__init__.py`**

```python
# -*- coding: utf-8 -*-
"""Console-script entry points for the stepss package."""
```

- [ ] **Step 4: Reinstall and verify it passes**

```bash
pip install ./src
pytest tests/test_examples.py::test_console_script_target_is_importable -v
```

Expected: PASS.

- [ ] **Step 5: Confirm the subpackage now ships**

```bash
python -c "import stepss.scripts.exec, os; print(os.path.dirname(stepss.scripts.exec.__file__))"
```

Expected: a path inside `site-packages`, not inside this repository.

- [ ] **Step 6: Commit**

```bash
git add src/stepss/scripts/__init__.py tests/test_examples.py
git commit -m "Ship the scripts subpackage so the ramses console script resolves"
```

---

## Task 3: Update the `tools/` scripts

**Files:**
- Modify: `tools/bump_version.sh`, `tools/update_ramses_libs.sh`, `tools/update_helios_libs.sh`, `tools/test_bump_version.sh`, `tools/test_update_ramses_libs.sh`

**Interfaces:**
- Consumes: the `src/stepss/` layout from Task 1.
- Produces: `bump_version.sh` writing `src/stepss/_bundled.py` and reading `src/stepss/__init__.py`; the env-var overrides `STEPSS_ROOT`, `STEPSS_TAGS`, `STEPSS_LIBS_DIR`. Task 4's workflows call these.

**A blanket sed here is wrong.** `tools/update_ramses_libs.sh` contains `pyramses-libs-*` at lines 28, 34, 35, 41 and 49, and those are release-asset filenames produced by `stepss-ramses`. They must survive unchanged.

- [ ] **Step 1: Rename the path and env-var references, protecting the asset names**

```bash
cd /home/apetros/Code/stepss/stepss-python-ui
# Protect the upstream asset name first, substitute, then restore it.
sed -i 's/pyramses-libs/@@ASSET@@/g' tools/update_ramses_libs.sh
sed -i 's|src/pyramses|src/stepss|g; s/PYRAMSES_ROOT/STEPSS_ROOT/g; s/PYRAMSES_TAGS/STEPSS_TAGS/g; s/PYRAMSES_LIBS_DIR/STEPSS_LIBS_DIR/g; s/pyramses/stepss/g; s/PyRAMSES/STEPSS/g' \
  tools/bump_version.sh tools/update_ramses_libs.sh tools/update_helios_libs.sh \
  tools/test_bump_version.sh tools/test_update_ramses_libs.sh
sed -i 's/@@ASSET@@/pyramses-libs/g' tools/update_ramses_libs.sh
```

- [ ] **Step 2: Verify the asset names survived and nothing else did**

```bash
grep -n 'pyramses' tools/*.sh
```

Expected: only the `pyramses-libs` asset names, in **both** files: lines 28, 34, 35 of `tools/update_ramses_libs.sh` and lines 20, 22, 24, 71 of `tools/test_update_ramses_libs.sh`. Nothing else. Lines 41 and 49 of `update_ramses_libs.sh` carry the bare word `pyramses` in a comment and an echo, and those are supposed to have become `stepss`. If any line outside that set still says `pyramses`, fix it by hand.

- [ ] **Step 3: Confirm no placeholder leaked**

```bash
grep -rn '@@ASSET@@' tools/
```

Expected: no output.

- [ ] **Step 4: Run the tool test suites**

```bash
bash tools/test_bump_version.sh
bash tools/test_update_ramses_libs.sh
```

Expected: both PASS.

- [ ] **Step 5: Sanity-check the version computation, without side effects**

`bump_version.sh` **rewrites `src/stepss/_bundled.py` and `src/stepss/__init__.py`** as part of running. Use the `STEPSS_ROOT` override so it writes into a throwaway copy, never the working tree:

```bash
TMPD="$(mktemp -d)"
mkdir -p "$TMPD/src/stepss"
cp src/stepss/__init__.py src/stepss/_bundled.py "$TMPD/src/stepss/"
STEPSS_ROOT="$TMPD" STEPSS_TAGS="v3.58
v0.3.5" bash tools/bump_version.sh ramses v3.58
rm -rf "$TMPD"
```

Expected: `3.58.1` on stdout, matching the Global Constraints. If it prints anything else, stop and report: the version scheme is the one thing this rename must not disturb.

- [ ] **Step 5b: Confirm the working tree is unchanged by that probe**

```bash
git status --short src/stepss
```

Expected: no output. If `__init__.py` or `_bundled.py` shows as modified, the probe escaped its sandbox: `git checkout -- src/stepss` and fix the `STEPSS_ROOT` usage before continuing. A stray version bump committed here would collide with the release automation.

- [ ] **Step 6: Commit**

```bash
git add tools
git commit -m "Point the release tooling at src/stepss"
```

---

## Task 4: Repoint the workflows and switch publishing to OIDC

**Files:**
- Modify: `.github/workflows/sync-upstream-release.yml`, `.github/workflows/python-publish.yml`, `.github/workflows/bundled-drift-check.yml`

**Interfaces:**
- Consumes: `src/stepss/` paths (Task 1), `STEPSS_*` env vars and `tools/` scripts (Task 3).
- Produces: a release pipeline that authenticates to PyPI by OIDC and uploads the `stepss` distribution.

- [ ] **Step 1: Rename paths and identifiers in `sync-upstream-release.yml`**

```bash
cd /home/apetros/Code/stepss/stepss-python-ui
sed -i 's|src/pyramses|src/stepss|g; s|pyramses/libs/|stepss/libs/|g; s/pyramses_tag/stepss_tag/g; s/pyramses-sync/stepss-sync/g; s|pypi.org/project/pyramses|pypi.org/project/stepss|g; s|stepss-pyramses|stepss-python-ui|g; s/PyRAMSES/STEPSS/g; s/pyramses/stepss/g' \
  .github/workflows/sync-upstream-release.yml
```

This covers: the wheel-content assertion at lines 396-401 (which checks for `pyramses/libs/lin/ramses.so` and five siblings **inside the built wheel**, so it must become `stepss/libs/...` or the build gate fails), the import smoke test at line 469, the `_bundled.py` reads at 538-539, the release title at 566, the concurrency group at 36, and the PyPI history URLs in the failure-report text at 165, 646 and 671.

- [ ] **Step 2: Verify the wheel-content assertion changed**

```bash
sed -n '394,403p' .github/workflows/sync-upstream-release.yml
```

Expected: six `stepss/libs/...` paths. This one matters more than the others: it is the gate that proves the binaries actually made it into the wheel.

- [ ] **Step 3: Switch the `release` job to OIDC**

In `.github/workflows/sync-upstream-release.yml`, the `release` job starts at line 475. Add `environment:` and `id-token: write`:

```yaml
  release:
    needs: [fetch, build-wheel, nordic]
    runs-on: ubuntu-24.04
    environment: pypi
    permissions:
      contents: write
      id-token: write
```

Then delete the `password:` line from the publish step, leaving:

```yaml
      # Last, deliberately. A PyPI version can never be reclaimed, so it runs
      # only once master has moved and the release exists. If this step alone
      # fails, the tested wheel is attached to the release above and
      # python-publish.yml can upload it by hand.
      #
      # Authenticated by OIDC trusted publishing: no secret is read here, and
      # the token GitHub mints names this repository and this workflow file,
      # both of which the publisher on PyPI is registered against.
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          packages-dir: dist/
```

Keep the `Mark PyPI published` step and its `pypi_done` output exactly as they are: `report-failure` keys "retryable" against "version gone" off it.

- [ ] **Step 4: Switch `python-publish.yml` to OIDC**

This workflow also **matches the release's attached distributions by filename**, `pyramses-"$VERSION"-*`. That must become `stepss-"$VERSION"-*`, or every break-glass republish downloads a release and then matches nothing. Nothing tests this path until the day it is needed, which is the worst day to discover it.

Update the `tag` input description (it says "pyramses release tag"), the wheel-filename match, then the `deploy` job:

```yaml
jobs:
  deploy:
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    environment: pypi
    permissions:
      contents: read
      id-token: write
```

Delete the `password:` line from its publish step too. The "No checkout" design is unaffected: OIDC needs no working tree.

- [ ] **Step 5: Repoint `bundled-drift-check.yml`**

```bash
sed -i 's|src/pyramses|src/stepss|g; s|pypi.org/pypi/pyramses/json|pypi.org/pypi/stepss/json|g; s|pypi.org/project/pyramses|pypi.org/project/stepss|g; s|SPS-L/stepss-pyramses|SPS-L/stepss-python-ui|g; s/pyramses-sync/stepss-sync/g; s/pyramses/stepss/g' \
  .github/workflows/bundled-drift-check.yml
```

The PyPI query at lines 116-117 is the critical one. Left pointing at `pyramses`, this workflow compares `master`'s version against the frozen shim forever and files a bogus divergence issue on every run.

- [ ] **Step 6: Verify no publish step still reads the secret**

```bash
grep -rn 'PYPI_API_TOKEN\|password:' .github/workflows/
```

Expected: no output.

- [ ] **Step 7: Verify every publish job declares the environment and permission**

```bash
grep -n -A6 'environment: pypi' .github/workflows/
```

Expected: two matches (`sync-upstream-release.yml`, `python-publish.yml`), each followed within a few lines by `id-token: write`. A publisher registered with an environment rejects any token that lacks the claim, and the failure appears as a 403 at the final step.

- [ ] **Step 8: Confirm the workflows still parse**

```bash
python -c "import yaml,glob,sys; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]; print('all workflows parse')"
```

Expected: `all workflows parse`.

- [ ] **Step 9: Check for stragglers**

```bash
grep -rn 'pyramses\|PyRAMSES' .github/workflows/
```

Expected: no output.

- [ ] **Step 10: Commit**

```bash
git add .github/workflows
git commit -m "Repoint the workflows at stepss and publish over OIDC"
```

---

## Task 5: The `pyramses` compatibility shim

**Files:**
- Create: `compat/pyramses/setup.py`, `compat/pyramses/README.rst`, `compat/pyramses/pyramses/__init__.py`, `tools/test_compat_shim.sh`, `.github/workflows/publish-compat-shim.yml`

**Interfaces:**
- Consumes: everything Task 1 produced, by name: `stepss.globals`, `stepss.cases`, `stepss.simulator`, `stepss.extractor`, `stepss.helios`, `stepss.__all__`, `stepss.__version__`.
- Produces: a `pyramses` distribution that satisfies `import pyramses`, `pyramses.cfg`, `pyramses.sim`, and `from pyramses.globals import RAMSESError`.

- [ ] **Step 1: Write the failing test**

Create `tools/test_compat_shim.sh`, following the repo's convention that each helper script has a `tools/test_*.sh` alongside it:

```bash
#!/usr/bin/env bash
# Verify the pyramses compatibility shim forwards to stepss.
#
# Builds a throwaway venv, installs the real package and then the shim, and
# asserts that the three import shapes real user code uses still work:
#   import pyramses
#   pyramses.cfg / pyramses.sim
#   from pyramses.globals import RAMSESError   <- needs sys.modules aliasing
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT

python -m venv "$TMPD/venv"
VPY="$TMPD/venv/bin/python"
[ -x "$VPY" ] || VPY="$TMPD/venv/Scripts/python.exe"

"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet "$ROOT/src"
# --no-deps: the shim's stepss>=3.58.1 pin cannot resolve until stepss is on
# PyPI, and the local build installed above is the thing under test anyway.
"$VPY" -m pip install --quiet --no-deps "$ROOT/compat/pyramses"

"$VPY" - <<'PY'
import warnings

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    import pyramses

assert any(issubclass(w.category, DeprecationWarning) for w in caught), \
    "FAIL: importing pyramses raised no DeprecationWarning"

assert callable(pyramses.cfg), "FAIL: pyramses.cfg missing"
assert callable(pyramses.sim), "FAIL: pyramses.sim missing"

from pyramses.globals import RAMSESError
from pyramses.helios import HeliosSession
assert issubclass(RAMSESError, Exception)
assert HeliosSession is not None

import stepss
assert pyramses.cfg is stepss.cfg, "FAIL: shim is not forwarding to stepss"
print("PASS: shim forwards to stepss")
PY

echo "PASS: all compat shim checks"
```

- [ ] **Step 2: Run it and verify it fails**

```bash
chmod +x tools/test_compat_shim.sh
bash tools/test_compat_shim.sh
```

Expected: FAIL, because `compat/pyramses` does not exist yet. The `pip install` step errors out.

- [ ] **Step 3: Write the forwarding module**

Create `compat/pyramses/pyramses/__init__.py`:

```python
# -*- coding: utf-8 -*-
"""Compatibility shim: ``pyramses`` is now ``stepss``.

This distribution exists so that code and notebooks written against
``pyramses`` keep running unchanged. It contains no logic of its own: every
name is the one ``stepss`` defines. It depends on ``stepss>=3.58.1`` and is
published once, so it keeps delivering the current engine without ever
being updated itself.
"""

import importlib
import sys
import warnings

# Warn BEFORE importing stepss, and do not move this below the import.
# `stepss.cases` and `stepss.extractor` assign `warnings.showwarning =
# CustomWarning` at module scope, which replaces the process-wide warning
# display hook. That is exactly the hook `warnings.catch_warnings(record=True)`
# installs to capture warnings, so any warning issued after `import stepss`
# goes to RAMSES's printer instead of the caller's recorder: it reaches stderr
# but is invisible to `catch_warnings`, `pytest.warns`, and any other tooling
# that intercepts warnings. Issuing it first means this deprecation is
# delivered through whatever handler the *user* configured, which is also the
# more correct behaviour on its own merits.
warnings.warn(
    "pyramses is now stepss: pip install stepss. This compatibility package "
    "forwards to it and will not be updated.",
    DeprecationWarning,
    stacklevel=2,
)

import stepss                 # noqa: E402
from stepss import *          # noqa: F401,F403,E402
from stepss import __all__, __version__   # noqa: E402

# `from stepss import *` binds the public API but does not recreate submodule
# paths, and `from pyramses.globals import RAMSESError` is a documented usage
# (it is how the Nordic regression test imports it). Alias the real modules
# into this package's namespace so those imports resolve to the same objects.
for _sub in ('globals', 'cases', 'simulator', 'extractor', 'helios'):
    sys.modules[__name__ + '.' + _sub] = importlib.import_module('stepss.' + _sub)
del _sub
```

- [ ] **Step 4: Write the shim's packaging metadata**

Create `compat/pyramses/setup.py`:

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build script for the pyramses compatibility shim.

Deliberately standalone: it shares no code with src/setup.py, because this
distribution is published exactly once and must not drift with the real one.
"""

import os

from setuptools import setup


def read(name):
    with open(os.path.join(os.path.dirname(__file__), name), encoding='utf-8') as f:
        return f.read()


setup(
    name='pyramses',
    version='3.58.1',
    description='Compatibility shim: pyramses is now stepss.',
    long_description=read('README.rst'),
    long_description_content_type='text/x-rst',
    author='Petros Aristidou',
    author_email='apetros@pm.me',
    url='https://stepss.sps-lab.org',
    license='Apache-2.0',
    packages=['pyramses'],
    install_requires=['stepss>=3.58.1'],
    classifiers=[
        "Development Status :: 7 - Inactive",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
    ],
)
```

- [ ] **Step 5: Write the shim's PyPI page**

Create `compat/pyramses/README.rst`:

```rst
pyramses is now stepss
======================

This package is a compatibility shim. The project it used to hold was renamed
to `stepss <https://pypi.org/project/stepss/>`_.

Install the real package::

   pip install stepss

Then change ``import pyramses`` to ``import stepss``. The API is otherwise
identical: ``cfg``, ``sim``, ``extractor``, ``curplot``, ``HeliosSession`` and
the rest keep their names.

Installing ``pyramses`` still works and still gives you the current engine: it
pulls in ``stepss`` and forwards every name to it, including submodule imports
such as ``from pyramses.globals import RAMSESError``. It emits a
``DeprecationWarning`` on import, and it will not be updated again.

Documentation: https://stepss.sps-lab.org/python/
```

- [ ] **Step 6: Run the test and verify it passes**

```bash
bash tools/test_compat_shim.sh
```

Expected: `PASS: shim forwards to stepss` then `PASS: all compat shim checks`.

- [ ] **Step 7: Write the one-shot publishing workflow**

Create `.github/workflows/publish-compat-shim.yml`:

```yaml
name: Publish compatibility shim

# One-shot, by hand. The `pyramses` distribution is a forwarding shim onto
# `stepss`: it is published once and never updated, so it deliberately has no
# trigger tied to a release.
#
# It is a separate workflow from the release pipeline because the PyPI trusted
# publisher on the `pyramses` project binds to this filename alone. Renaming
# this file breaks that binding.
on:
  workflow_dispatch:
    inputs:
      publish:
        description: 'Actually upload to PyPI (leave off to rehearse)'
        required: false
        default: false
        type: boolean

permissions:
  contents: read

jobs:
  publish:
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    environment: pypi
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@v7

      - uses: actions/setup-python@v7
        with:
          python-version: '3.12'

      # The forwarding test installs the real package and imports it. Import
      # alone does not load ramses.so, but helios is touched, and a job that
      # ends up loading either library without these fails at load time rather
      # than at import. Cheap insurance; every CI job here installs them.
      - name: Install the bundled libraries' system dependencies
        run: sudo apt-get update && sudo apt-get install -y libopenblas0 libgfortran5 libgomp1

      - name: Build the shim
        run: |
          set -euo pipefail
          python -m pip install --upgrade pip build
          python -m build --sdist --wheel --outdir dist/ compat/pyramses
          ls -l dist/

      - name: Verify the shim forwards to stepss
        run: bash tools/test_compat_shim.sh

      # Read from github.event.inputs, which is a string, and compare against
      # the quoted literal. The `inputs` context would give a boolean here, and
      # an unquoted comparison coerces an unset value and fails *open*. Same
      # reasoning as the rehearsal guard in sync-upstream-release.yml.
      - name: Publish to PyPI
        if: github.event.inputs.publish == 'true'
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          packages-dir: dist/
```

- [ ] **Step 8: Confirm the new workflow parses**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/publish-compat-shim.yml')); print('parses')"
```

Expected: `parses`.

- [ ] **Step 9: Confirm the shim did not pollute the main package's install**

```bash
pip uninstall -y pyramses
python -c "import stepss; print(stepss.__version__)"
```

Expected: prints a version, with no `DeprecationWarning`. The two distributions own different top-level names and must not collide.

- [ ] **Step 10: Commit**

```bash
git add compat tools/test_compat_shim.sh .github/workflows/publish-compat-shim.yml
git commit -m "Add the pyramses compatibility shim forwarding to stepss"
```

---

## Task 6: Repository prose

**Files:**
- Modify: `README.rst`, `src/README.rst`, `NOTICE`, `CLAUDE.md`, `.github/copilot-instructions.md`

**Interfaces:**
- Consumes: nothing at runtime. `README.rst` becomes the PyPI long description via `setup.py`'s `read_first_existing('../README.rst', 'README.rst')`, so errors here are user-visible on PyPI.

- [ ] **Step 1: Rewrite the `README.rst` header block**

The badges point at the old project and the title names the old package. Replace the top of the file through the title:

```rst
|PyPI version| |PyPI status| |Docs status|

.. |PyPI version| image:: https://img.shields.io/pypi/v/stepss
   :target: https://pypi.org/project/stepss/
   :alt: PyPI version

.. |PyPI status| image:: https://img.shields.io/pypi/status/stepss
   :target: https://pypi.org/project/stepss/
   :alt: PyPI status

.. |Docs status| image:: https://img.shields.io/github/actions/workflow/status/SPS-L/stepss-docs/deploy.yml?branch=main&label=docs
   :target: https://github.com/SPS-L/stepss-docs/
   :alt: Docs deploy status

STEPSS: Python Interface to RAMSES and Helios
=============================================
```

Adjust the `=` underline to match the title length exactly, or RST emits a warning that surfaces on the PyPI page.

- [ ] **Step 2: Fix the install instructions**

Two blocks name the package:

```rst
   pip install jupyter ipython stepss
```
```rst
   pip install stepss
```

- [ ] **Step 3: Add a rename note after the install section**

```rst
Renamed from PyRAMSES
~~~~~~~~~~~~~~~~~~~~~

This package was published as ``pyramses`` up to version 3.58. Existing code
keeps working: ``pip install pyramses`` now installs a shim that forwards to
this package. New code should use ``import stepss``.
```

- [ ] **Step 4: Replace the remaining prose references**

`tests/baselines/README.md` and `tests/data/nordic/README.md` are included here because Task 1 correctly left them alone: they are prose, not code, and no earlier task claimed them. Do not touch `tests/baselines/nordic_baseline.npz` itself, only the README beside it.

```bash
cd /home/apetros/Code/stepss/stepss-python-ui
sed -i 's/pyramses/stepss/g; s/PyRAMSES/STEPSS/g' \
  src/README.rst NOTICE .github/copilot-instructions.md \
  tests/baselines/README.md tests/data/nordic/README.md
```

Then read `README.rst` in full and fix any sentence the earlier edits left reading awkwardly, in particular the `pyramses.helios` module reference under Key Features, which must now read `stepss.helios`.

`tests/baselines/README.md` needs a second look after the substitution: it describes the baseline being shared byte-for-byte with `stepss-ramses`, and any sentence that now claims `stepss` produces the baseline rather than the RAMSES engine has changed meaning and must be reworded.

- [ ] **Step 5: Update `CLAUDE.md`**

Rewrite the eight references. The essential edits: the "What this is" paragraph now describes `stepss` and `stepss.helios`; the CI-managed paths become `src/stepss/libs/{lin,win,mac}/`, `src/stepss/_bundled.py` and `src/stepss/__init__.py`; the Testing section's note that "`RAMSESError` is not exported at package level, import it from `pyramses.globals`" becomes `stepss.globals`. Add a Conventions bullet:

```markdown
- The `pyramses` distribution is a frozen forwarding shim in `compat/pyramses/`,
  published once by `publish-compat-shim.yml`. Do not release it again, and do
  not rename that workflow file: the PyPI trusted publisher binds to it.
```

- [ ] **Step 6: Verify house style**

```bash
grep -rnP '\x{2014}' README.rst src/README.rst NOTICE CLAUDE.md .github/copilot-instructions.md compat/
```

Expected: no output.

- [ ] **Step 7: Verify the README renders as valid RST**

```bash
pip install --quiet readme_renderer
python -m readme_renderer README.rst -o /dev/null
```

Expected: no errors. This is what PyPI runs; a failure here means a broken project page.

- [ ] **Step 8: Confirm only historical documents still say pyramses**

```bash
grep -rln 'pyramses\|PyRAMSES' --exclude-dir=.git --exclude-dir=build --exclude-dir=__pycache__ --exclude-dir=.pytest_cache .
```

Expected: exactly `./docs/superpowers/plans/2026-08-06-pyramses-release-automation.md`, `./docs/superpowers/specs/2026-08-06-pyramses-release-automation-design.md`, the new `./docs/superpowers/*/2026-08-11-*` files, `./compat/pyramses/...`, and `./tools/update_ramses_libs.sh` (the protected asset names). Anything else is a miss.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Update the repository prose for the stepss rename"
```

---

## Task 7: Upstream dispatch targets

**Files:**
- Modify: `/home/apetros/Code/stepss/stepss-ramses/.github/workflows/release.yml:267,355,364`
- Modify: `/home/apetros/Code/stepss/stepss-helios/.github/workflows/ci.yml:183,188,194,200`

**Interfaces:**
- Consumes: the renamed repository from P0.1.
- Produces: dispatches that address `stepss-python-ui` directly rather than relying on GitHub's rename redirect.

These are separate repositories. Commit in each one independently; do not touch the umbrella pointer here (Task 8 does that).

- [ ] **Step 1: Update `stepss-ramses`**

```bash
cd /home/apetros/Code/stepss/stepss-ramses
git checkout -b rename-to-stepss
sed -i 's|SPS-L/stepss-pyramses|SPS-L/stepss-python-ui|g; s/stepss-pyramses/stepss-python-ui/g' .github/workflows/release.yml
```

Leave the `pyramses-libs-*.zip` **filenames** at lines 67, 159, 231 and 270-272 alone: those are this repo's own asset names and `tools/update_ramses_libs.sh` fetches them by that exact pattern.

But lines 270-272 are half asset name and half destination path, and **the destination half must change**. They read `place ramses.so in src/pyramses/libs/lin/` and similar; `src/pyramses/libs/` no longer exists, so those instructions send a human refreshing the bundle by hand to a directory that is not there. Change only the right-hand side to `src/stepss/libs/{lin,win,mac}/`.

Also rename the job id `notify-pyramses` (line 349) to `notify-python-ui` and reword the comment above it, matching what the equivalent job in `stepss-helios` gets. Grep the whole file for the old job id first: a job id can also appear in a `needs:` list, an `if:` condition, or a `${{ needs.<id>.outputs.* }}` expression, and a half-renamed id breaks the workflow at parse time or silently skips the job.

- [ ] **Step 2: Verify**

```bash
grep -n 'pyramses' .github/workflows/release.yml
```

Expected: only the `pyramses-libs-*` asset lines.

- [ ] **Step 3: Commit `stepss-ramses`**

```bash
git add .github/workflows/release.yml
git commit -m "Dispatch to stepss-python-ui after the rename"
```

- [ ] **Step 4: Update `stepss-helios`**

```bash
cd /home/apetros/Code/stepss/stepss-helios
git checkout -b rename-to-stepss
sed -i 's|SPS-L/stepss-pyramses|SPS-L/stepss-python-ui|g; s/notify-pyramses/notify-python-ui/g; s/stepss-pyramses/stepss-python-ui/g; s/pyramses/stepss/g' .github/workflows/ci.yml
```

Do **not** rename `PYRAMSES_DISPATCH_TOKEN` (line 196). It is a repository secret; renaming it means rotating secrets in two private repos for no benefit. Verify the sed left it intact in the next step.

- [ ] **Step 5: Verify the secret name survived**

```bash
grep -n 'PYRAMSES_DISPATCH_TOKEN\|stepss-python-ui\|notify-' .github/workflows/ci.yml
```

Expected: `PYRAMSES_DISPATCH_TOKEN` still present at line 196, the dispatch URL naming `stepss-python-ui`, and the job named `notify-python-ui`. If the secret name was changed, restore it.

- [ ] **Step 6: Commit `stepss-helios`**

```bash
git add .github/workflows/ci.yml
git commit -m "Dispatch to stepss-python-ui after the rename"
```

---

## Task 8: Umbrella repository

**Files:**
- Modify: `/home/apetros/Code/stepss/.gitmodules`, `/home/apetros/Code/stepss/CLAUDE.md`, `/home/apetros/Code/stepss/README.md`

**Interfaces:**
- Consumes: the renamed remote from P0.1.
- Produces: `git submodule update --init --recursive` resolving `stepss-python-ui`.

Do this only after P0.1 has actually landed, or the new URL will not resolve.

- [ ] **Step 1: Move the submodule**

```bash
cd /home/apetros/Code/stepss
git mv stepss-pyramses stepss-python-ui
```

`git mv` on a submodule updates `.gitmodules`, the index and `.git/modules` bookkeeping in one step. Doing it by hand leaves the gitdir pointer stale.

- [ ] **Step 2: Fix the URL, which `git mv` does not change**

Edit `.gitmodules` so the section reads:

```ini
[submodule "stepss-python-ui"]
	path = stepss-python-ui
	url = ../stepss-python-ui.git
	branch = master
```

The URL stays **relative** so the repo works over both SSH and HTTPS. The tracked branch stays `master`.

- [ ] **Step 3: Sync and verify**

```bash
git submodule sync stepss-python-ui
git submodule update --init stepss-python-ui
git config --file .gitmodules --get submodule.stepss-python-ui.url
```

Expected: `../stepss-python-ui.git`.

- [ ] **Step 4: Update the umbrella prose**

In `CLAUDE.md` and `README.md`, replace `stepss-pyramses` with `stepss-python-ui`, and update the component description so it names the `stepss` PyPI package. In `CLAUDE.md`, the sentence "PyRAMSES bundles ramses plus helios" becomes "the `stepss` package bundles ramses plus helios".

- [ ] **Step 5: Verify house style**

```bash
grep -rnP '\x{2014}' CLAUDE.md README.md
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add .gitmodules CLAUDE.md README.md stepss-python-ui
git commit -m "Rename the pyramses submodule to stepss-python-ui"
```

---

## Task 9: Documentation site

**Files:**
- Move: `stepss-docs/src/content/docs/pyramses/` to `stepss-docs/src/content/docs/python/`
- Modify: `stepss-docs/astro.config.mjs`, `stepss-docs/CLAUDE.md`, `stepss-docs/README.md`, and roughly 20 content pages

**Interfaces:**
- Consumes: the `stepss` package name and the `/python/` URL prefix.
- Produces: the URLs `stepss-helios` and `stepss-cg-studio` READMEs link to, preserved by redirect.

- [ ] **Step 1: Branch and move the pages**

```bash
cd /home/apetros/Code/stepss/stepss-docs
git checkout -b rename-to-stepss
git mv src/content/docs/pyramses src/content/docs/python
```

- [ ] **Step 2: Update the sidebar in `astro.config.mjs`**

Replace the group at lines 86-95:

```javascript
				{
					label: 'Python API',
					items: [
						{ label: 'Overview',      slug: 'python/overview' },
						{ label: 'Installation',  slug: 'python/installation' },
						{ label: 'Examples',      slug: 'python/examples' },
						{ label: 'API Reference', slug: 'python/api-reference' },
						// Not "Power Flow (Helios)": that label belongs to the engine
						// reference under Simulation Guide. This page is the Python API.
						{ label: 'Helios Power-Flow API', slug: 'python/helios' },
					],
				},
```

- [ ] **Step 3: Add the redirects**

Extend the `redirects` block at line 16:

```javascript
	redirects: {
		'/user-guide/pfc': '/user-guide/power-flow/',
		'/developer/codegen-library': '/developer/codegen-blocks/',
		// The Python API pages moved when the package was renamed from
		// pyramses to stepss. The stepss-helios and stepss-cg-studio READMEs
		// and the PyPI project page link to the old paths.
		'/pyramses/overview': '/python/overview/',
		'/pyramses/installation': '/python/installation/',
		'/pyramses/examples': '/python/examples/',
		'/pyramses/api-reference': '/python/api-reference/',
		'/pyramses/helios': '/python/helios/',
	},
```

- [ ] **Step 4: Sweep the content**

```bash
cd /home/apetros/Code/stepss/stepss-docs
grep -rl 'pyramses\|PyRAMSES' src/content/docs/ | xargs sed -i 's|/pyramses/|/python/|g; s/pyramses/stepss/g; s/PyRAMSES/STEPSS/g'
```

Then update `src/content/docs/resources/repositories.md` so the repository URL reads `https://github.com/SPS-L/stepss-python-ui`, and check `src/content/docs/python/installation.mdx` and `getting-started/installation.mdx` for `pip install` lines that must now say `stepss`.

- [ ] **Step 4b: Close the inbound links from the package repo**

Task 6 deliberately left `stepss.sps-lab.org/pyramses/*` links intact in `stepss-python-ui`'s `README.rst` and `src/README.rst`, because at that point the pages had not moved and rewriting them would have pointed at a URL that did not exist. This step is where they move, and it is the reason this dependency is closed here rather than tracked as a follow-up nobody owns. `README.rst` is the PyPI project page, so these are the links a new user actually clicks.

In `/home/apetros/Code/stepss/stepss-python-ui` (a **different repository**, commit there separately):

```bash
cd /home/apetros/Code/stepss/stepss-python-ui
sed -i 's|stepss.sps-lab.org/pyramses/|stepss.sps-lab.org/python/|g' README.rst src/README.rst
grep -n 'sps-lab.org' README.rst src/README.rst
```

Read the grep output and confirm every URL resolves against the new structure. Note that `stepss.sps-lab.org/user-guide/pfc/` may also appear: leave it, it is a different redirect that already exists and still works.

Then re-run the PyPI render gate, since `README.rst` is the project page:

```bash
python -m readme_renderer README.rst -o /dev/null
```

- [ ] **Step 5: Add a rename note to the Python overview page**

At the end of `src/content/docs/python/overview.md`:

```markdown
:::note[Renamed from PyRAMSES]
This package was published as `pyramses` up to version 3.58. Existing code
keeps working: `pip install pyramses` installs a shim that forwards to
`stepss`. New code should use `import stepss`.
:::
```

- [ ] **Step 6: Update `stepss-docs/CLAUDE.md`**

In the "One owner per topic" table, the last row's owner changes from "the matching `pyramses/` page" to "the matching `python/` page". Add to the redirects note that the `/pyramses/*` URLs are kept alive for the same reason `/user-guide/pfc` is.

- [ ] **Step 7: Verify house style**

```bash
grep -rnP '\x{2014}' src CLAUDE.md README.md astro.config.mjs
```

Expected: no output. This is the documented check for this repo.

- [ ] **Step 8: Build, which is the only validation step**

```bash
npm install
npm run build
```

Expected: a clean build. It catches broken internal links from the page move, bad frontmatter, and MDX syntax errors. Any link still pointing at `/pyramses/...` inside the site should be fixed at source rather than left to the redirect.

- [ ] **Step 9: Confirm only the changelog still names the old package**

```bash
grep -rln 'pyramses\|PyRAMSES' src public astro.config.mjs
```

Expected: `public/changelog.txt` (historical, left alone) and `astro.config.mjs` (the redirect keys, which must say `pyramses`).

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Move the Python API docs to /python/ for the stepss rename"
```

---

## Phase 3: Release sequence

Run these in order, after Tasks 1-9 are merged to their default branches.

- [ ] **R1** Rehearse: Actions, `sync-upstream-release.yml`, Run workflow from `master`, source `manual`, **`publish` unticked**. This runs fetch, build and the three-platform gate, then stops, reaching neither `master` nor PyPI. Expected: green, with no release created and no PyPI upload.

- [ ] **R2** Confirm the rehearsal's build gate asserted the renamed wheel paths. In the run log, the wheel-content step must list six `stepss/libs/...` entries.

- [ ] **R3** Real release: same workflow, source `manual`, **`publish` ticked**. Expected: version `3.58.1`, `master` fast-forwarded, tag `v3.58.1` and a GitHub release created, and the `stepss` project created on PyPI. The pending publisher converts to a normal one at this moment. Re-derive the expected number first if any upstream release landed since this plan was written.

- [ ] **R4** Verify: `pip install stepss` in a clean venv, then `python -c "import stepss; print(stepss.__version__, stepss.__ramses_version__, stepss.__helios_version__)"`.

- [ ] **R5** Publish the shim: Actions, `publish-compat-shim.yml`, **`publish` unticked** first to rehearse the build and the forwarding test. Then run again with **`publish` ticked**.

- [ ] **R6** Verify the bridge in a clean venv: `pip install pyramses`, then `python -c "import pyramses; print(pyramses.__version__)"`. Expected: a `DeprecationWarning` and the `stepss` version.

- [ ] **R7** Delete the `PYPI_API_TOKEN` repository secret (Settings, Secrets and variables, Actions) and revoke the token on PyPI (Account settings, API tokens). Leaving it forfeits the point of the OIDC migration.

- [ ] **R8** Confirm the drift check is clean: Actions, `bundled-drift-check.yml`, Run workflow. Expected: green with no issue filed. A failure here means it is still querying `pyramses` on PyPI.

**Expect `bundled-drift-check.yml` to be red between now and R3.** It queries `https://pypi.org/pypi/stepss/json`, which 404s until the project exists, and `curl -f` then exits 1. This is not a regression introduced by the rename: the job is already failing beforehand, because its version parser demands three numeric parts and both `master` (`3.58`) and the published `pyramses` (`3.58`) have two. Both conditions clear the moment R3 publishes `3.58.1`. Do not "fix" it in the interim; just do not trust its silence, since a failed PyPI step also suppresses the upstream drift comparison that did succeed.

**If R3 fails at the PyPI step only:** nothing was uploaded, so version `3.58.1` is not spent. Fix the publisher registration (most likely a workflow-filename or environment-claim mismatch), then run `python-publish.yml` with tag `v3.58.1`. It uploads the gated wheel already attached to the release. Do not rebuild.

Two constraints on that break-glass path that did not exist before this change:

- **Dispatch it from `master`.** The `pypi` environment restricts deployments to `master` (P0.3), so running it from any other branch now fails at the environment gate before it reaches PyPI.
- **It can no longer republish a pre-rename release.** It matches assets as `stepss-"$VERSION"-*`, so any tag at or before `v3.58` (whose assets are `pyramses-*.whl`) will match nothing. That is correct, since those artifacts belong to a different PyPI project, but it means the old releases have no rescue path through this workflow. They do not need one.

---

## Out of scope

The twelve content repositories naming `pyramses` in notebooks, examples and READMEs keep working through the shim and are tracked separately: `stepss-test-systems`, `stepss-ramses` (`examples/Nordic/`, `docs/`), `stepss-helios` (`README.md`, `docs/`, `tests/smoke/api_smoke.py`), `stepss-eigenanalysis`, `stepss-uramses`, `stepss-RamsesNN`, `stepss-java-ui`, `stepss-userguide` (`install.tex`), `stepss-cg-studio`.
