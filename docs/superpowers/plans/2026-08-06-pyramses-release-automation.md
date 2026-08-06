# PyRAMSES Upstream Release Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `stepss-ramses` or `stepss-helios` publishes a release, refresh the binaries pyramses bundles, prove the built wheel works on Linux, Windows and macOS, then cut a pyramses release and publish it to PyPI — with no human in the loop and no path by which an unverified binary reaches PyPI.

**Architecture:** Both upstreams push a `repository_dispatch` at pyramses. A single workflow refreshes the affected libraries, bumps the patch version, builds the fat wheel **once**, gates *that exact wheel* with the full pytest suite on three platforms, then fast-forwards `master`, cuts a GitHub release and uploads the tested bytes to PyPI. CI invokes the same `tools/` scripts a human would, so the refresh logic has one implementation.

**Tech Stack:** GitHub Actions, `gh` CLI, bash, Python 3 (pytest, numpy), setuptools.

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-08-06-pyramses-release-automation-design.md`. Read it before starting.
- Binaries are committed **as-is**. Never strip, never recompress.
- The gated artifact is the **built wheel**, never the source tree. Nothing is rebuilt from `master` at publish time.
- PyPI upload runs **last**, after the fast-forward and the GitHub release. That version number can never be reclaimed.
- A `workflow_dispatch` run is **always a rehearsal**. It must be structurally impossible for it to move `master`, cut a release or publish. No toggle.
- Dispatch payloads are untrusted. Validate the tag as a whole string; take the source from the **event type**, never from the payload.
- Never use `gh api -F`; always `-f`. `-F` reads a value from a local file when it starts with `@`, and git permits a tag named `@evil`.
- Upstream asset naming differs: RAMSES assets are tag-suffixed (`pyramses-libs-linux-v3.55.zip`), Helios assets are not (`helios-api-linux-x86_64.tar.gz`).
- macOS RAMSES keeps the filename `ramses.so`, **not** `.dylib`. pyramses separates platforms by directory, not extension.
- Runner pins: `ubuntu-24.04`, `windows-latest`, `macos-15`. `macos-15` is arm64, which the arm64-only RAMSES macOS build requires.
- Secrets: `PYRAMSES_DISPATCH_TOKEN` in both upstreams (present); `RAMSES_READ_TOKEN` in pyramses, scoped to read both upstreams (**not yet added — Task 5 onward cannot run in CI until it is**).

## Facts established by probing (do not re-derive)

These were measured on 2026-08-06 against the bundled library. Rely on them.

- The Nordic collapse raises `pyramses.globals.RAMSESError` from `execSim()` with flag `-1`. The message contains `sim_minmaxvolt` and `Voltage out of bounds at bus g6`.
- `RAMSESError` is **not** exported at package level. Import it as `from pyramses.globals import RAMSESError`.
- After the trip, `ram.getSimTime()` returns `163.14000000000965`.
- `obs.trj` **is** written despite the exception. It is ~92 MB.
- **Do not call `endSim()` after the trip.** It raises a second, misleading `RAMSESError` ("Load records"). Calling it will make the test fail for the wrong reason.
- The library path reproduces the standalone executable's trajectory **bit-exactly** (`max |diff| 0.0` across 751 samples × 1417 columns). `stepss-ramses/tests/baselines/nordic_baseline.npz` is reused unchanged.
- The currently bundled RAMSES library reports version **3.51**; the bundled Helios C API is **v1.2.0**.

---

### Task 1: Vendor the Nordic case, baseline and comparator

**Files:**
- Create: `tools/compare_trj.py` (copied from `stepss-ramses`)
- Create: `tests/data/nordic/{dyn_A.dat,volt_rat_A.dat,settings1.dat,obs.dat,short_trip_branch.dst}`
- Create: `tests/data/nordic/LICENSE`, `tests/data/nordic/README.md`
- Create: `tests/baselines/nordic_baseline.npz`, `tests/baselines/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `tools/compare_trj.py` with subcommands `compare <trj> <baseline.npz>` and `make-baseline <trj> -o <out.npz> [--ncols N] [--tmax S] [--dt S] [--meta TEXT]`. Exit 0 pass, 1 fail. Task 2 shells out to it.

- [ ] **Step 1: Copy the case, baseline and comparator in**

Run from the `stepss-pyramses` repository root. `$R` points at a
`stepss-ramses` checkout; as a sibling directory under the `stepss` umbrella
that is `../stepss-ramses`.

```bash
R=../stepss-ramses
[ -d "$R/examples/Nordic" ] || { echo "set R to a stepss-ramses checkout"; exit 1; }
mkdir -p tests/data/nordic tests/baselines
cp $R/tools/compare_trj.py tools/compare_trj.py
chmod +x tools/compare_trj.py
cp $R/examples/Nordic/{dyn_A.dat,volt_rat_A.dat,settings1.dat,obs.dat,short_trip_branch.dst} tests/data/nordic/
cp $R/examples/Nordic/LICENSE tests/data/nordic/LICENSE
cp $R/tests/baselines/nordic_baseline.npz tests/baselines/
```

`compare_trj.py` is copied verbatim — it needs no pyramses-specific change.

- [ ] **Step 2: Write the case attribution**

Create `tests/data/nordic/README.md`:

```markdown
# Nordic voltage-collapse regression case

Vendored from `SPS-L/stepss-ramses`, `examples/Nordic/`. Apache-2.0; the
licence travels with the files as `LICENSE`.

This is the **CI variant**: `dyn_A.dat` + `volt_rat_A.dat` +
`short_trip_branch.dst`. It is deliberately the same variant, with the same
`settings1.dat` and `obs.dat`, that the stepss-ramses release gate runs, so a
single baseline serves both repositories.

Do not edit these files. Changing them changes the observable count and
invalidates `tests/baselines/nordic_baseline.npz`; refresh both together and
say why in the commit message.

The case is also published as PyRAMSES teaching material for the EEN452
course at Cyprus University of Technology.
```

- [ ] **Step 3: Write the baseline refresh policy**

Create `tests/baselines/README.md`:

```markdown
# CI baselines

`nordic_baseline.npz` — the Nordic voltage-collapse trajectory, all 1417
columns interpolated onto a 0 : 0.2 : 150 s grid, plus the final simulated
time (163.14 s, the `sim_minmaxvolt` trip instant). Consumed by
`tests/test_nordic.py` via `tools/compare_trj.py compare`.

This file is byte-identical to `stepss-ramses/tests/baselines/nordic_baseline.npz`.
The RAMSES standalone executable and the shared library reach the same
trajectory bit-exactly, so one baseline serves both repositories. Keep them in
step.

## Refresh policy

Regenerate ONLY when a change legitimately alters trajectories — a model or
solver change in RAMSES. In exactly that situation the gate is *supposed* to
fail against the old baseline, and the fix is a deliberate baseline update in
a reviewed pull request, never an automatic pass.

A failing gate blocks the release and files an issue. That is working as
designed.

## Regeneration

    python -m venv /tmp/rebase && /tmp/rebase/bin/pip install ./src
    D=$(mktemp -d); cp tests/data/nordic/* "$D/"
    ( cd "$D" && /tmp/rebase/bin/python - <<'EOF'
    import pyramses
    from pyramses.globals import RAMSESError
    case = pyramses.cfg()
    for f in ('dyn_A.dat', 'volt_rat_A.dat', 'settings1.dat'):
        case.addData(f)
    case.addObs('obs.dat'); case.addDst('short_trip_branch.dst')
    case.addTrj('obs.trj'); case.addOut('output.trace')
    case.addInit('init.trace'); case.addCont('cont.trace'); case.addDisc('disc.trace')
    ram = pyramses.sim()
    try:
        ram.execSim(case)
    except RAMSESError as exc:
        print('expected trip:', exc)
    EOF
    )
    python tools/compare_trj.py make-baseline "$D/obs.trj" \
      -o tests/baselines/nordic_baseline.npz --meta "$(git rev-parse --short HEAD)"

If `obs.dat` or the case files change, the observable count changes: pass the
new `--ncols` (the tool aborts with a time-axis error when it is wrong;
current value 1417).
```

- [ ] **Step 4: Verify the comparator runs and the baseline loads**

Run:

```bash
python tools/compare_trj.py --help
python -c "import numpy as np; b=np.load('tests/baselines/nordic_baseline.npz'); print('ncols', int(b['ncols']), 'final', float(b['final_time']), 'M', b['M'].shape)"
```

Expected: help text listing `make-baseline` and `compare`; then `ncols 1417 final 163.14 M (751, 1417)`.

- [ ] **Step 5: Commit**

```bash
git add tools/compare_trj.py tests/data/nordic tests/baselines
git commit -m "Vendor the Nordic regression case, baseline and comparator

Taken from stepss-ramses. The standalone executable and the shared
library reach the same trajectory bit-exactly, so the baseline is
shared rather than regenerated here."
```

---

### Task 2: The Nordic regression test

**Files:**
- Create: `tests/test_nordic.py`

**Interfaces:**
- Consumes: `tools/compare_trj.py` and `tests/baselines/nordic_baseline.npz` from Task 1.
- Produces: `pytest tests/test_nordic.py` as a gate. Tasks 5 and 6 run it as part of `pytest tests/`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_nordic.py`:

```python
"""Nordic voltage-collapse regression gate for the bundled RAMSES library.

Drives the same case the stepss-ramses release gate runs -- dyn_A +
volt_rat_A + short_trip_branch.dst -- but through the C API rather than the
standalone executable, and compares the trajectory against the shared
baseline.

The collapse is by design: sim_minmaxvolt trips at t = 163.14 s, RAMSES
returns flag -1, and pyramses turns that into a RAMSESError. A run that
completes without raising is a regression, not a success.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = REPO_ROOT / "tests" / "data" / "nordic"
BASELINE = REPO_ROOT / "tests" / "baselines" / "nordic_baseline.npz"
COMPARATOR = REPO_ROOT / "tools" / "compare_trj.py"

# Measured on the bundled library; the comparator also enforces it to +/- 1 s.
EXPECTED_TRIP_TIME = 163.14
TRIP_TOL = 1.0


@pytest.fixture(scope="module")
def nordic_run(tmp_path_factory):
    """Run the Nordic case once in an isolated directory; yield that directory.

    RAMSES writes roughly 100 MB of output and resolves every path relative to
    the working directory, so the case is copied into a fresh tmp dir.
    """
    import pyramses
    from pyramses.globals import RAMSESError

    run_dir = tmp_path_factory.mktemp("nordic")
    for src in sorted(CASE_DIR.glob("*")):
        if src.suffix in {".dat", ".dst"}:
            shutil.copy(src, run_dir / src.name)

    cwd = Path.cwd()
    import os

    os.chdir(run_dir)
    try:
        case = pyramses.cfg()
        case.addData("dyn_A.dat")
        case.addData("volt_rat_A.dat")
        case.addData("settings1.dat")
        case.addObs("obs.dat")
        case.addDst("short_trip_branch.dst")
        case.addTrj("obs.trj")
        case.addOut("output.trace")
        case.addInit("init.trace")
        case.addCont("cont.trace")
        case.addDisc("disc.trace")

        ram = pyramses.sim()
        trip = None
        try:
            ram.execSim(case)
        except RAMSESError as exc:
            trip = exc
        sim_time = ram.getSimTime()
        # Deliberately NOT calling ram.endSim(): after the trip it raises a
        # second, unrelated RAMSESError ("Load records") that masks the real
        # result. obs.trj is already complete at this point.
    finally:
        os.chdir(cwd)

    return {"dir": run_dir, "trip": trip, "sim_time": sim_time}


def test_collapse_trips(nordic_run):
    """The case must trip on under-voltage, not run to completion."""
    trip = nordic_run["trip"]
    assert trip is not None, "Nordic case completed without tripping; expected sim_minmaxvolt"
    assert "sim_minmaxvolt" in str(trip)


def test_trip_time(nordic_run):
    """The trip instant is the headline regression signal."""
    assert nordic_run["sim_time"] == pytest.approx(EXPECTED_TRIP_TIME, abs=TRIP_TOL)


def test_trajectory_matches_baseline(nordic_run):
    """Full trajectory comparison against the shared stepss-ramses baseline."""
    trj = nordic_run["dir"] / "obs.trj"
    assert trj.is_file() and trj.stat().st_size > 0, "obs.trj was not written"

    result = subprocess.run(
        [sys.executable, str(COMPARATOR), "compare", str(trj), str(BASELINE)],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    assert result.returncode == 0, "trajectory diverged from baseline"
```

- [ ] **Step 2: Run the test to verify it passes against the bundled library**

Run:

```bash
python -m venv /tmp/pyr-nordic && /tmp/pyr-nordic/bin/pip install -q ./src pytest
/tmp/pyr-nordic/bin/python -m pytest tests/test_nordic.py -v
```

Expected: 3 passed. The run takes a couple of minutes and writes ~100 MB into a temp directory.

If `test_trajectory_matches_baseline` fails, the bundled library and the baseline genuinely disagree — stop and investigate rather than regenerating the baseline.

- [ ] **Step 3: Confirm the comparison has teeth**

A trajectory check that cannot fail is worse than none, because it reads as
coverage. Perturb a copy of the baseline and confirm the comparator rejects
it. This exercises the same code path the test asserts on, without editing
the test.

The Nordic run from Step 2 has already been discarded with its tmp dir, so
regenerate one trajectory to compare against:

```bash
D=$(mktemp -d); cp tests/data/nordic/*.dat tests/data/nordic/*.dst "$D/"
( cd "$D" && /tmp/pyr-nordic/bin/python - <<'EOF'
import pyramses
from pyramses.globals import RAMSESError
case = pyramses.cfg()
for f in ('dyn_A.dat', 'volt_rat_A.dat', 'settings1.dat'):
    case.addData(f)
case.addObs('obs.dat'); case.addDst('short_trip_branch.dst')
case.addTrj('obs.trj'); case.addOut('output.trace')
case.addInit('init.trace'); case.addCont('cont.trace'); case.addDisc('disc.trace')
ram = pyramses.sim()
try:
    ram.execSim(case)
except RAMSESError as exc:
    print('expected trip:', exc)
EOF
)

# A perturbed baseline: every observable shifted by 1.0, far outside tolerance.
/tmp/pyr-nordic/bin/python - <<'EOF'
import numpy as np
b = dict(np.load('tests/baselines/nordic_baseline.npz'))
b['M'] = b['M'].copy(); b['M'][:, 1:] += 1.0
np.savez_compressed('/tmp/bad_baseline.npz', **b)
EOF

echo "--- against the real baseline (expect exit 0) ---"
/tmp/pyr-nordic/bin/python tools/compare_trj.py compare "$D/obs.trj" tests/baselines/nordic_baseline.npz; echo "exit=$?"
echo "--- against the perturbed baseline (expect exit 1) ---"
/tmp/pyr-nordic/bin/python tools/compare_trj.py compare "$D/obs.trj" /tmp/bad_baseline.npz; echo "exit=$?"
rm -rf "$D" /tmp/bad_baseline.npz
```

Expected: the first prints `PASS` and `exit=0`; the second prints
`FAIL: trajectory outside tolerance` and `exit=1`. Nothing in the repository
is modified by this step.

- [ ] **Step 4: Commit**

```bash
git add tests/test_nordic.py
git commit -m "Add the Nordic regression gate for the bundled RAMSES library

Drives the stepss-ramses CI case through the C API and compares the
trajectory against the shared baseline. The under-voltage trip is
by design, so a clean run is the failure mode."
```

---

### Task 3: Bundled-version metadata and the version bumper

**Files:**
- Create: `src/pyramses/_bundled.py`
- Create: `tools/bump_version.sh`
- Create: `tools/test_bump_version.sh`
- Modify: `src/pyramses/__init__.py` (export the bundled versions)

**Interfaces:**
- Consumes: nothing.
- Produces: `tools/bump_version.sh <ramses|helios> <upstream-tag>` — bumps the patch component of `__version__` in `src/pyramses/__init__.py`, rewrites `src/pyramses/_bundled.py` setting the named upstream's version and carrying the other forward, and prints the new pyramses version to stdout with no `v` prefix (e.g. `0.3.1`). Exit 0 success, 1 failure, 2 usage. Task 5's `fetch` job consumes the printed version.

- [ ] **Step 1: Create the initial bundled-version record**

Create `src/pyramses/_bundled.py`. The values are what is bundled **today**, measured from the library banner and the git history:

```python
"""Upstream component versions bundled in this pyramses release.

Written by tools/bump_version.sh, which the release automation invokes when
stepss-ramses or stepss-helios publishes. Do not edit by hand: a manual edit
is silently overwritten by the next sync.

Only the upstream that triggered a sync changes; the other is carried forward.
"""

RAMSES_VERSION = "v3.51"
HELIOS_VERSION = "v1.2.0"
```

- [ ] **Step 2: Export them from the package**

In `src/pyramses/__init__.py`, after the existing `from .helios import HeliosSession` line, add:

```python
from ._bundled import RAMSES_VERSION as __ramses_version__
from ._bundled import HELIOS_VERSION as __helios_version__
```

- [ ] **Step 3: Write the failing script test**

Create `tools/test_bump_version.sh`:

```bash
#!/usr/bin/env bash
# Local test for tools/bump_version.sh.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/tools/bump_version.sh"
FAILURES=0
fail() { echo "FAIL: $*"; FAILURES=$((FAILURES + 1)); }
ok()   { echo "ok: $*"; }

TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT

# A miniature package tree: the script must only ever touch these two files.
mkdir -p "$TMPD/src/pyramses"
cat > "$TMPD/src/pyramses/__init__.py" <<'EOF'
__package_name__ = "pyramses"
__version__ = '0.3.0'
__author__ = "Petros Aristidou"
EOF
cat > "$TMPD/src/pyramses/_bundled.py" <<'EOF'
RAMSES_VERSION = "v3.51"
HELIOS_VERSION = "v1.2.0"
EOF

g() { sed -n "s/^$2[[:space:]]*=[[:space:]]*[\"']\([^\"']*\)[\"'].*/\1/p" "$1" | head -n1; }

# --- usage errors --------------------------------------------------------
"$SCRIPT" >/dev/null 2>&1
[ $? -eq 2 ] && ok "no args exits 2" || fail "no args should exit 2"
"$SCRIPT" ramses >/dev/null 2>&1
[ $? -eq 2 ] && ok "one arg exits 2" || fail "one arg should exit 2"
PYRAMSES_ROOT="$TMPD" "$SCRIPT" banana v1.0 >/dev/null 2>&1
[ $? -eq 2 ] && ok "unknown source exits 2" || fail "unknown source should exit 2"

# --- ramses bump ---------------------------------------------------------
OUT="$(PYRAMSES_ROOT="$TMPD" "$SCRIPT" ramses v3.55)"
[ "$OUT" = "0.3.1" ] && ok "prints the new version" || fail "printed '$OUT', want '0.3.1'"
[ "$(g "$TMPD/src/pyramses/__init__.py" __version__)" = "0.3.1" ] \
    && ok "__version__ bumped" || fail "__version__=$(g "$TMPD/src/pyramses/__init__.py" __version__)"
[ "$(g "$TMPD/src/pyramses/_bundled.py" RAMSES_VERSION)" = "v3.55" ] \
    && ok "RAMSES_VERSION updated" || fail "RAMSES_VERSION=$(g "$TMPD/src/pyramses/_bundled.py" RAMSES_VERSION)"
# The whole point: the untouched upstream must survive.
[ "$(g "$TMPD/src/pyramses/_bundled.py" HELIOS_VERSION)" = "v1.2.0" ] \
    && ok "HELIOS_VERSION carried forward" || fail "HELIOS_VERSION=$(g "$TMPD/src/pyramses/_bundled.py" HELIOS_VERSION)"

# --- helios bump, from the already-bumped state --------------------------
OUT="$(PYRAMSES_ROOT="$TMPD" "$SCRIPT" helios v1.3.0)"
[ "$OUT" = "0.3.2" ] && ok "second bump increments again" || fail "printed '$OUT', want '0.3.2'"
[ "$(g "$TMPD/src/pyramses/_bundled.py" HELIOS_VERSION)" = "v1.3.0" ] \
    && ok "HELIOS_VERSION updated" || fail "HELIOS_VERSION=$(g "$TMPD/src/pyramses/_bundled.py" HELIOS_VERSION)"
[ "$(g "$TMPD/src/pyramses/_bundled.py" RAMSES_VERSION)" = "v3.55" ] \
    && ok "RAMSES_VERSION carried forward" || fail "RAMSES_VERSION=$(g "$TMPD/src/pyramses/_bundled.py" RAMSES_VERSION)"

# --- rollover across a two-digit patch -----------------------------------
sed -i "s/__version__ = '0.3.2'/__version__ = '0.3.9'/" "$TMPD/src/pyramses/__init__.py"
OUT="$(PYRAMSES_ROOT="$TMPD" "$SCRIPT" ramses v3.56)"
[ "$OUT" = "0.3.10" ] && ok "0.3.9 -> 0.3.10 (numeric, not lexical)" || fail "printed '$OUT', want '0.3.10'"

# --- the file must stay importable ---------------------------------------
python3 -c "
import ast, sys
ast.parse(open('$TMPD/src/pyramses/_bundled.py').read())
ast.parse(open('$TMPD/src/pyramses/__init__.py').read())
" && ok "both files still parse as Python" || fail "a rewritten file is not valid Python"

echo ""
if [ "$FAILURES" -eq 0 ]; then echo "PASS: all assertions held"; exit 0; fi
echo "$FAILURES failure(s)"; exit 1
```

```bash
chmod +x tools/test_bump_version.sh
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `bash tools/test_bump_version.sh`
Expected: FAIL — `tools/bump_version.sh` does not exist yet, so every assertion errors.

- [ ] **Step 5: Write the implementation**

Create `tools/bump_version.sh`:

```bash
#!/usr/bin/env bash
# Bump the pyramses patch version and record the bundled upstream versions.
#
#   bump_version.sh <ramses|helios> <upstream-tag>
#
# Bumps the patch component of __version__ in src/pyramses/__init__.py, then
# rewrites src/pyramses/_bundled.py so the named upstream carries <upstream-tag>
# and the other keeps whatever it already had. Prints the new pyramses version
# (no 'v' prefix) on stdout; the release workflow reads that.
#
# PYRAMSES_ROOT overrides the repository root, for tests.
set -u

if [ $# -ne 2 ]; then
    echo "usage: $0 <ramses|helios> <upstream-tag>" >&2
    exit 2
fi
SOURCE="$1"
TAG="$2"
case "$SOURCE" in
    ramses|helios) ;;
    *) echo "usage: $0 <ramses|helios> <upstream-tag>" >&2; exit 2 ;;
esac

ROOT="${PYRAMSES_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
INIT="$ROOT/src/pyramses/__init__.py"
BUNDLED="$ROOT/src/pyramses/_bundled.py"

[ -f "$INIT" ] || { echo "FAIL: not found: $INIT" >&2; exit 1; }

read_assign() {  # read_assign <file> <name>
    [ -f "$1" ] || return 0
    sed -n "s/^$2[[:space:]]*=[[:space:]]*[\"']\([^\"']*\)[\"'].*/\1/p" "$1" | head -n1
}

CUR="$(read_assign "$INIT" __version__)"
[ -n "$CUR" ] || { echo "FAIL: __version__ not found in $INIT" >&2; exit 1; }

# Split on dots and bump the last component numerically. Guard against a
# non-numeric patch so a malformed version fails loudly instead of producing
# a nonsense tag that then gets published.
MAJOR="${CUR%%.*}"
REST="${CUR#*.}"
MINOR="${REST%%.*}"
PATCH="${REST#*.}"
case "$MAJOR$MINOR$PATCH" in
    *[!0-9]*) echo "FAIL: __version__ '$CUR' is not major.minor.patch with numeric parts" >&2; exit 1 ;;
esac
NEW="$MAJOR.$MINOR.$((PATCH + 1))"

RAMSES_VER="$(read_assign "$BUNDLED" RAMSES_VERSION)"
HELIOS_VER="$(read_assign "$BUNDLED" HELIOS_VERSION)"
if [ "$SOURCE" = "ramses" ]; then
    RAMSES_VER="$TAG"
else
    HELIOS_VER="$TAG"
fi
[ -n "$RAMSES_VER" ] || { echo "FAIL: no RAMSES_VERSION to carry forward" >&2; exit 1; }
[ -n "$HELIOS_VER" ] || { echo "FAIL: no HELIOS_VERSION to carry forward" >&2; exit 1; }

# Rewrite __version__ in place. Anchored to the start of the line so a
# docstring mentioning __version__ cannot be hit.
python3 - "$INIT" "$CUR" "$NEW" <<'PYEOF'
import re, sys
path, cur, new = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(path, encoding='utf-8').read()
out, n = re.subn(r"(?m)^__version__\s*=\s*['\"]%s['\"]" % re.escape(cur),
                 "__version__ = '%s'" % new, src)
if n != 1:
    sys.exit("FAIL: expected exactly one __version__ assignment, found %d" % n)
open(path, 'w', encoding='utf-8').write(out)
PYEOF

cat > "$BUNDLED" <<EOF
"""Upstream component versions bundled in this pyramses release.

Written by tools/bump_version.sh, which the release automation invokes when
stepss-ramses or stepss-helios publishes. Do not edit by hand: a manual edit
is silently overwritten by the next sync.

Only the upstream that triggered a sync changes; the other is carried forward.
"""

RAMSES_VERSION = "$RAMSES_VER"
HELIOS_VERSION = "$HELIOS_VER"
EOF

echo "$NEW"
```

```bash
chmod +x tools/bump_version.sh
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `bash tools/test_bump_version.sh`
Expected: `PASS: all assertions held`

- [ ] **Step 7: Confirm the real package still imports**

Run:

```bash
/tmp/pyr-nordic/bin/pip install -q ./src
/tmp/pyr-nordic/bin/python -c "import pyramses; print(pyramses.__version__, pyramses.__ramses_version__, pyramses.__helios_version__)"
```

Expected: `0.3.0 v3.51 v1.2.0` — the bumper was only run against the throwaway tree in the test, so the real version is untouched.

- [ ] **Step 8: Commit**

```bash
git add src/pyramses/_bundled.py src/pyramses/__init__.py tools/bump_version.sh tools/test_bump_version.sh
git commit -m "Record bundled upstream versions and add the version bumper

_bundled.py names the RAMSES and Helios builds a given pyramses
release carries. bump_version.sh advances the patch version and
updates only the upstream that released, carrying the other forward."
```

---

### Task 4: The RAMSES library refresh script

**Files:**
- Create: `tools/update_ramses_libs.sh`
- Create: `tools/test_update_ramses_libs.sh`

**Interfaces:**
- Consumes: nothing.
- Produces: `tools/update_ramses_libs.sh <tag>` — downloads `pyramses-libs-{linux,windows,macos-arm64}-<tag>.zip` from `SPS-L/stepss-ramses` and installs `ramses.so`, `ramses.dll`, `ramses.so` into `src/pyramses/libs/{lin,win,mac}/`. Exit 0 success, 1 failure, 2 usage. Mirrors the existing `tools/update_helios_libs.sh`, which Task 5 calls unchanged for the Helios path.

- [ ] **Step 1: Write the failing script test**

Create `tools/test_update_ramses_libs.sh`. It shadows `gh` on `PATH` — the technique `stepss-ramses/tools/test_write_buildinfo.sh` uses for `brew`/`pacman` — so it runs offline:

```bash
#!/usr/bin/env bash
# Local test for tools/update_ramses_libs.sh, with a fake `gh` so no network
# or credentials are needed.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/tools/update_ramses_libs.sh"
FAILURES=0
fail() { echo "FAIL: $*"; FAILURES=$((FAILURES + 1)); }
ok()   { echo "ok: $*"; }

TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT

mkdir -p "$TMPD/libs"/{lin,win,mac}

# Build the three archives the real release carries, each holding one
# recognisable payload file.
STAGE="$TMPD/stage"; mkdir -p "$STAGE"
printf 'LINUX-SO-PAYLOAD\n'  > "$STAGE/ramses.so"
( cd "$STAGE" && zip -q "$TMPD/pyramses-libs-linux-v9.99.zip" ramses.so )
printf 'WINDOWS-DLL-PAYLOAD\n' > "$STAGE/ramses.dll"
( cd "$STAGE" && zip -q "$TMPD/pyramses-libs-windows-v9.99.zip" ramses.dll )
printf 'MACOS-SO-PAYLOAD\n'  > "$STAGE/ramses_mac.so"
( cd "$STAGE" && cp ramses_mac.so ramses.so && zip -q "$TMPD/pyramses-libs-macos-arm64-v9.99.zip" ramses.so )

FAKEBIN="$TMPD/fakebin"; mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/gh" <<EOF
#!/usr/bin/env bash
# Fake "gh": serve the prepared archives for 'release download --pattern P --dir D'.
DIR=""; PATTERN=""
while [ \$# -gt 0 ]; do
  case "\$1" in
    --dir) DIR="\$2"; shift 2 ;;
    --pattern) PATTERN="\$2"; shift 2 ;;
    *) shift ;;
  esac
done
[ -n "\$DIR" ] || exit 1
shopt -s nullglob
matched=0
for f in "$TMPD"/\$PATTERN; do cp "\$f" "\$DIR/"; matched=1; done
[ "\$matched" = 1 ] || { echo "fake gh: no asset matching \$PATTERN" >&2; exit 1; }
EOF
chmod +x "$FAKEBIN/gh"

# --- usage ---------------------------------------------------------------
"$SCRIPT" >/dev/null 2>&1
[ $? -eq 2 ] && ok "no args exits 2" || fail "no args should exit 2"

# --- happy path ----------------------------------------------------------
PATH="$FAKEBIN:$PATH" PYRAMSES_LIBS_DIR="$TMPD/libs" "$SCRIPT" v9.99 >"$TMPD/out.log" 2>&1
rc=$?
[ $rc -eq 0 ] && ok "happy path exits 0" || { fail "happy path exited $rc"; cat "$TMPD/out.log"; }

grep -q 'LINUX-SO-PAYLOAD'   "$TMPD/libs/lin/ramses.so"  && ok "lin/ramses.so installed"  || fail "lin/ramses.so wrong or missing"
grep -q 'WINDOWS-DLL-PAYLOAD' "$TMPD/libs/win/ramses.dll" && ok "win/ramses.dll installed" || fail "win/ramses.dll wrong or missing"
grep -q 'MACOS-SO-PAYLOAD'   "$TMPD/libs/mac/ramses.so"  && ok "mac/ramses.so installed"  || fail "mac/ramses.so wrong or missing"

# macOS must be a .so, never a .dylib: pyramses splits platforms by directory.
[ ! -e "$TMPD/libs/mac/ramses.dylib" ] && ok "no stray mac/ramses.dylib" || fail "mac kit wrote a .dylib"

# The Linux and macOS archives share the member name ramses.so; a flat
# extraction would let one clobber the other.
if ! cmp -s "$TMPD/libs/lin/ramses.so" "$TMPD/libs/mac/ramses.so"; then
    ok "lin and mac .so are distinct (no cross-platform clobber)"
else
    fail "lin/ramses.so and mac/ramses.so are identical -- extraction clobbered one"
fi

# --- a missing asset must fail loudly ------------------------------------
rm -f "$TMPD/pyramses-libs-windows-v9.99.zip"
PATH="$FAKEBIN:$PATH" PYRAMSES_LIBS_DIR="$TMPD/libs" "$SCRIPT" v9.99 >/dev/null 2>&1
[ $? -ne 0 ] && ok "missing asset exits non-zero" || fail "missing asset should fail"

echo ""
if [ "$FAILURES" -eq 0 ]; then echo "PASS: all assertions held"; exit 0; fi
echo "$FAILURES failure(s)"; exit 1
```

```bash
chmod +x tools/test_update_ramses_libs.sh
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash tools/test_update_ramses_libs.sh`
Expected: FAIL — `tools/update_ramses_libs.sh` does not exist.

- [ ] **Step 3: Write the implementation**

Create `tools/update_ramses_libs.sh`:

```bash
#!/usr/bin/env bash
# Download the RAMSES shared libraries from a stepss-ramses GitHub release and
# copy them into src/pyramses/libs/ for bundling.
#
# Usage: tools/update_ramses_libs.sh <tag>        e.g. tools/update_ramses_libs.sh v3.55
#
# Requires the GitHub CLI (gh) authenticated with access to SPS-L/stepss-ramses.
# Review and commit the updated binaries afterwards:
#   git add src/pyramses/libs/ && git commit -m "Bundle RAMSES <tag> libraries"
#
# Companion to tools/update_helios_libs.sh; the release automation calls both.
#
# PYRAMSES_LIBS_DIR overrides the destination, for tests.
set -euo pipefail

TAG="${1:?usage: $0 <ramses-release-tag> (e.g. v3.55)}"
REPO="SPS-L/stepss-ramses"
LIBS_DIR="${PYRAMSES_LIBS_DIR:-$(cd "$(dirname "$0")/.." && pwd)/src/pyramses/libs}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "Downloading RAMSES $TAG libraries from $REPO ..."
gh release download "$TAG" --repo "$REPO" \
    --pattern "pyramses-libs-*-$TAG.zip" --dir "$WORK_DIR"

# The Linux and macOS archives both contain a member named ramses.so, so each
# is unzipped into its own directory rather than a shared one. A flat
# extraction would silently leave one platform holding the other's library.
for plat in linux windows macos-arm64; do
    zip="$WORK_DIR/pyramses-libs-$plat-$TAG.zip"
    [ -f "$zip" ] || { echo "FAIL: RAMSES $TAG has no pyramses-libs-$plat-$TAG.zip" >&2; exit 1; }
    unzip -q "$zip" -d "$WORK_DIR/$plat"
done

install -m 644 "$WORK_DIR/linux/ramses.so"      "$LIBS_DIR/lin/ramses.so"
install -m 644 "$WORK_DIR/windows/ramses.dll"   "$LIBS_DIR/win/ramses.dll"
# macOS keeps the .so name: pyramses separates platforms by directory.
install -m 644 "$WORK_DIR/macos-arm64/ramses.so" "$LIBS_DIR/mac/ramses.so"

echo
echo "Updated $LIBS_DIR:"
ls -l "$LIBS_DIR"/lin "$LIBS_DIR"/win "$LIBS_DIR"/mac | grep -i ramses || true
echo
echo "Done. Review the changes and commit, e.g.:"
echo "  git add src/pyramses/libs && git commit -m \"Bundle RAMSES $TAG libraries\""
```

```bash
chmod +x tools/update_ramses_libs.sh
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bash tools/test_update_ramses_libs.sh`
Expected: `PASS: all assertions held`

- [ ] **Step 5: Prove it against the real release**

This needs `gh` authenticated against the private repo. It also refreshes the stale v3.51 binaries to v3.55, which is a genuine improvement to commit.

```bash
tools/update_ramses_libs.sh v3.55
git status --short src/pyramses/libs
/tmp/pyr-nordic/bin/pip install -q ./src
/tmp/pyr-nordic/bin/python -m pytest tests/test_nordic.py -v
```

Expected: the three libraries change; the Nordic gate still passes (v3.51 and v3.55 produce identical trajectories, as established by probing).

- [ ] **Step 6: Commit**

```bash
git add tools/update_ramses_libs.sh tools/test_update_ramses_libs.sh src/pyramses/libs
git commit -m "Add the RAMSES library refresh script and bundle v3.55

Mirrors tools/update_helios_libs.sh. Each platform archive is unzipped
into its own directory because the Linux and macOS archives share the
member name ramses.so.

The bundled library was still v3.51; this brings it to v3.55. The
Nordic gate passes unchanged across both."
```

Then update `src/pyramses/_bundled.py` to `RAMSES_VERSION = "v3.55"` and amend, or commit separately — the automation will maintain it from here.

---

### Task 5: The sync workflow — fetch, build and gate

**Files:**
- Create: `.github/workflows/sync-upstream-release.yml`
- Modify: `.github/workflows/python-publish.yml` (drop the `release:` trigger)
- Modify: `.github/workflows/tests.yml` (Nordic on ordinary CI)

**Interfaces:**
- Consumes: `tools/update_ramses_libs.sh` (Task 4), `tools/update_helios_libs.sh` (existing), `tools/bump_version.sh` (Task 3), `tests/test_nordic.py` (Task 2).
- Produces: workflow outputs `source`, `upstream_tag`, `pyramses_tag`, `branch`, `head_sha`, `base_sha`, `rehearsal` from the `fetch` job, and a `dist` artifact holding the sdist and wheel. Task 6 consumes all of them.

- [ ] **Step 1: Stop the old publish workflow from firing on releases**

Replace the `on:` block of `.github/workflows/python-publish.yml`:

```yaml
name: Publish Python Package

# Break-glass only. The normal path is sync-upstream-release.yml, which
# publishes the exact wheel its gate tested. Leaving `release: published`
# here would race that upload for the same version, and rebuild from master
# rather than shipping the tested bytes.
#
# Use this when the sync workflow cut a release and tagged it, but the PyPI
# upload alone failed. Download the wheel from that release first.
on:
  workflow_dispatch:
```

Leave the rest of the file unchanged.

- [ ] **Step 2: Run Nordic in ordinary CI too**

In `.github/workflows/tests.yml`, replace **only** the `strategy:` block, pinning the matrix to the same images the release gate uses so an ordinary PR fails here rather than on release day. The existing `run: pytest tests/ -v` already collects `tests/test_nordic.py`, so leave every other line alone:

```yaml
    strategy:
      fail-fast: false
      matrix:
        # Same images the release gate pins, so an ordinary PR fails here
        # rather than during a release.
        os: [ubuntu-24.04, windows-latest, macos-15]
        python-version: ['3.10', '3.12']
```

The existing `run: pytest tests/ -v` already picks up `tests/test_nordic.py`; no change needed there.

- [ ] **Step 3: Write the workflow**

Create `.github/workflows/sync-upstream-release.yml`:

```yaml
name: sync-upstream-release

# Fired by stepss-ramses or stepss-helios when either publishes a release.
# Refreshes the binaries pyramses bundles, proves the built wheel works on
# every platform, and only then releases and publishes.
on:
  repository_dispatch:
    types: [ramses-release, helios-release]
  # Rehearsal only. The release job is gated on repository_dispatch, so no
  # amount of hand-triggering can move master, cut a release or reach PyPI.
  workflow_dispatch:
    inputs:
      source:
        description: 'Upstream to rehearse against'
        required: true
        type: choice
        options: [ramses, helios]
      tag:
        description: 'Upstream release tag, e.g. v3.55'
        required: true
        type: string

permissions:
  contents: read

# Two upstream releases in quick succession must not race for master.
concurrency:
  group: pyramses-sync
  cancel-in-progress: false

jobs:
  fetch:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    permissions:
      contents: write
    outputs:
      source: ${{ steps.vars.outputs.source }}
      upstream_tag: ${{ steps.vars.outputs.upstream_tag }}
      rehearsal: ${{ steps.vars.outputs.rehearsal }}
      pyramses_tag: ${{ steps.bump.outputs.pyramses_tag }}
      branch: ${{ steps.commit.outputs.branch }}
      head_sha: ${{ steps.commit.outputs.head_sha }}
      base_sha: ${{ steps.commit.outputs.base_sha }}
    steps:
      # The payload is untrusted input: validate its shape, and never let it
      # reach a run: script except through env.
      - name: Resolve and validate the trigger
        id: vars
        env:
          EVENT: ${{ github.event_name }}
          ACTION: ${{ github.event.action }}
          DISPATCH_TAG: ${{ github.event.client_payload.tag }}
          INPUT_SOURCE: ${{ inputs.source }}
          INPUT_TAG: ${{ inputs.tag }}
        run: |
          if [ "$EVENT" = "repository_dispatch" ]; then
            # The event type identifies the sender, so no 'source' field in
            # the payload is ever trusted.
            case "$ACTION" in
              ramses-release) SOURCE=ramses ;;
              helios-release) SOURCE=helios ;;
              *) echo "FAIL: unexpected dispatch type '$ACTION'"; exit 1 ;;
            esac
            TAG="$DISPATCH_TAG"
            REHEARSAL=false
          else
            SOURCE="$INPUT_SOURCE"
            TAG="$INPUT_TAG"
            REHEARSAL=true
          fi

          # Validate the tag as a single whole string before anything is
          # written to $GITHUB_OUTPUT. `grep -z` treats the entire input
          # (embedded newlines included) as one record, so ^...$ must match
          # start-to-end of the whole value. A line-oriented check here would
          # let a value like $'v3.55\ntag=EVIL' through.
          if ! printf '%s' "$TAG" | grep -qzE '^v[0-9][0-9A-Za-z.+-]*$'; then
            echo "FAIL: refusing tag: it must match ^v[0-9][0-9A-Za-z.+-]*\$ as a single line, with no embedded newlines"
            exit 1
          fi
          echo "source=$SOURCE"        >> "$GITHUB_OUTPUT"
          echo "upstream_tag=$TAG"     >> "$GITHUB_OUTPUT"
          echo "rehearsal=$REHEARSAL"  >> "$GITHUB_OUTPUT"
          echo "Syncing $SOURCE $TAG (rehearsal=$REHEARSAL)"

      - uses: actions/checkout@v5
        with:
          # repository_dispatch freezes github.sha to the default branch's tip
          # at dispatch time, and a concurrency-queued or re-run job replays
          # that stale value. Naming the branch makes every execution resolve
          # master as it stands right now.
          ref: master
          fetch-depth: 0

      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'

      - name: Refresh the bundled libraries
        env:
          SOURCE: ${{ steps.vars.outputs.source }}
          TAG: ${{ steps.vars.outputs.upstream_tag }}
          GH_TOKEN: ${{ secrets.RAMSES_READ_TOKEN }}
        run: |
          if [ "$SOURCE" = "ramses" ]; then
            bash tools/update_ramses_libs.sh "$TAG"
          else
            bash tools/update_helios_libs.sh "$TAG"
          fi
          git status --short src/pyramses/libs

      - name: Bump the version and record the bundled upstreams
        id: bump
        env:
          SOURCE: ${{ steps.vars.outputs.source }}
          TAG: ${{ steps.vars.outputs.upstream_tag }}
        run: |
          NEW="$(bash tools/bump_version.sh "$SOURCE" "$TAG")"
          echo "pyramses_tag=v$NEW" >> "$GITHUB_OUTPUT"
          echo "New pyramses version: $NEW"
          cat src/pyramses/_bundled.py

      - name: Refuse to re-release an existing tag
        if: steps.vars.outputs.rehearsal == 'false'
        env:
          TAG: ${{ steps.bump.outputs.pyramses_tag }}
          GH_TOKEN: ${{ github.token }}
        run: |
          if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
            echo "FAIL: tag $TAG already exists in stepss-pyramses"
            exit 1
          fi
          if gh release view "$TAG" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
            echo "FAIL: release $TAG already exists in stepss-pyramses"
            exit 1
          fi
          echo "OK: $TAG is free"

      - name: Commit to a sync branch
        id: commit
        env:
          SOURCE: ${{ steps.vars.outputs.source }}
          TAG: ${{ steps.vars.outputs.upstream_tag }}
          PYTAG: ${{ steps.bump.outputs.pyramses_tag }}
          REHEARSAL: ${{ steps.vars.outputs.rehearsal }}
        run: |
          BRANCH="sync/$SOURCE-$TAG"
          BASE_SHA="$(git rev-parse HEAD)"
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git checkout -b "$BRANCH"
          git add -A src/pyramses/libs src/pyramses/_bundled.py src/pyramses/__init__.py
          git status --short
          git commit -m "Bundle $SOURCE $TAG and release $PYTAG"
          if [ "$REHEARSAL" = "true" ]; then
            # A rehearsal leaves no branch behind. The build and gate jobs
            # check this commit out from the artifact-free local history via
            # the workflow's own checkout of the same ref, so nothing is
            # pushed.
            echo "Rehearsal: not pushing $BRANCH"
          else
            git push origin "$BRANCH"
          fi
          echo "branch=$BRANCH"                 >> "$GITHUB_OUTPUT"
          echo "head_sha=$(git rev-parse HEAD)" >> "$GITHUB_OUTPUT"
          echo "base_sha=$BASE_SHA"             >> "$GITHUB_OUTPUT"

      # A rehearsal has no pushed branch for later jobs to check out, so the
      # refreshed tree travels as an artifact instead.
      - name: Upload the refreshed tree (rehearsal only)
        if: steps.vars.outputs.rehearsal == 'true'
        uses: actions/upload-artifact@v4
        with:
          name: rehearsal-tree
          path: |
            src/
            tests/
            tools/
          if-no-files-found: error

  build-wheel:
    needs: [fetch]
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v5
        with:
          # Pinned to the exact commit the release job will publish, not the
          # mutable branch head, so the tree that was gated is provably the
          # tree that ships.
          ref: ${{ needs.fetch.outputs.rehearsal == 'true' && 'master' || needs.fetch.outputs.head_sha }}

      - name: Overlay the rehearsal tree
        if: needs.fetch.outputs.rehearsal == 'true'
        uses: actions/download-artifact@v4
        with:
          name: rehearsal-tree

      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'

      - name: Build the sdist and wheel
        run: |
          python -m pip install --upgrade pip build
          cd src
          python -m build --sdist --wheel --outdir dist

      - name: Show what was built
        run: |
          ls -l src/dist
          python - <<'EOF'
          import glob, zipfile
          whl = glob.glob('src/dist/*.whl')[0]
          names = zipfile.ZipFile(whl).namelist()
          # The bundled binaries are the whole point of this package; a
          # package_data glob that silently drops one would otherwise only
          # surface as a runtime failure for a user on that platform.
          for want in ('pyramses/libs/lin/ramses.so',
                       'pyramses/libs/win/ramses.dll',
                       'pyramses/libs/mac/ramses.so',
                       'pyramses/libs/lin/libhelios_api.so',
                       'pyramses/libs/win/helios_api.dll',
                       'pyramses/libs/mac/libhelios_api.dylib'):
              assert want in names, 'wheel is missing %s' % want
              print('ok:', want)
          EOF

      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: src/dist/*
          if-no-files-found: error

  nordic:
    needs: [fetch, build-wheel]
    strategy:
      fail-fast: false
      matrix:
        # macos-15 is arm64, which the arm64-only RAMSES macOS build needs.
        os: [ubuntu-24.04, windows-latest, macos-15]
    runs-on: ${{ matrix.os }}
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@v5
        with:
          ref: ${{ needs.fetch.outputs.rehearsal == 'true' && 'master' || needs.fetch.outputs.head_sha }}

      - name: Overlay the rehearsal tree
        if: needs.fetch.outputs.rehearsal == 'true'
        uses: actions/download-artifact@v4
        with:
          name: rehearsal-tree

      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'

      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist

      # Installing the built wheel, not the source tree: the artifact users
      # get is the artifact the gate runs against.
      - name: Install the built wheel
        shell: bash
        run: |
          python -m pip install --upgrade pip
          python -m pip install pytest
          python -m pip install "$(ls dist/*.whl)"
          python -c "import pyramses; print(pyramses.__version__, pyramses.__ramses_version__, pyramses.__helios_version__)"

      - name: Full test suite against the installed wheel
        shell: bash
        run: pytest tests/ -v
```

- [ ] **Step 4: Validate the YAML and the trigger logic**

Run:

```bash
python - <<'EOF'
import yaml
for p in ('.github/workflows/sync-upstream-release.yml',
          '.github/workflows/python-publish.yml',
          '.github/workflows/tests.yml'):
    d = yaml.safe_load(open(p))
    # PyYAML parses the `on:` key as boolean True.
    print(p, '->', sorted((d.get('on') or d.get(True)).keys()))
    for name, job in d['jobs'].items():
        print('   ', name, '->', job.get('runs-on'))
EOF
```

Expected: `sync-upstream-release.yml -> ['repository_dispatch', 'workflow_dispatch']`; `python-publish.yml -> ['workflow_dispatch']` (no `release`); `tests.yml` matrix pinned to the three images.

- [ ] **Step 5: Commit and push**

```bash
git add .github/workflows/
git commit -m "Add the upstream sync workflow: refresh, build, gate

Refreshes whichever upstream released, bumps the version, builds the
fat wheel once and runs the full suite against that exact wheel on all
three platforms.

python-publish.yml stops firing on release: it would race the sync
workflow for the same version and rebuild from master rather than
shipping the bytes the gate tested. It stays as a break-glass
workflow_dispatch."
git push origin HEAD:master
```

- [ ] **Step 6: Rehearse against the real v3.55 release**

This is the first end-to-end exercise. It requires `RAMSES_READ_TOKEN` to be present in `stepss-pyramses`.

```bash
gh workflow run sync-upstream-release.yml --repo SPS-L/stepss-pyramses \
  -f source=ramses -f tag=v3.55
sleep 10
gh run list --repo SPS-L/stepss-pyramses --workflow sync-upstream-release.yml --limit 2
gh run watch <run-id> --repo SPS-L/stepss-pyramses --exit-status --interval 20
```

Expected: `fetch`, `build-wheel` and all three `nordic` jobs succeed. No `sync/` branch is created, no release is cut, nothing reaches PyPI.

Then rehearse the other upstream:

```bash
gh workflow run sync-upstream-release.yml --repo SPS-L/stepss-pyramses \
  -f source=helios -f tag=v1.2.0
```

Expected: the same, proving `RAMSES_READ_TOKEN` reaches `stepss-helios`. If this one fails at the download step with a 404, the token is scoped to `stepss-ramses` only and needs widening.

---

### Task 6: The release and failure-reporting jobs

**Files:**
- Modify: `.github/workflows/sync-upstream-release.yml` (append two jobs)

**Interfaces:**
- Consumes: `fetch` outputs and the `dist` artifact from Task 5.
- Produces: the published release and PyPI upload. Nothing consumes these.

- [ ] **Step 1: Append the release job**

Add to `.github/workflows/sync-upstream-release.yml`:

```yaml
  release:
    needs: [fetch, build-wheel, nordic]
    # Belt and braces: a workflow_dispatch rehearsal must never reach this
    # job. Either condition alone would do; both are cheap.
    if: github.event_name == 'repository_dispatch' && needs.fetch.outputs.rehearsal == 'false'
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    permissions:
      contents: write
    outputs:
      master_moved: ${{ steps.ff.outputs.moved }}
      release_published: ${{ steps.publish.outputs.published }}
      # Set by a step of our own, not by the third-party publish action,
      # which exposes no outputs.
      pypi_published: ${{ steps.pypi_done.outputs.published }}
    steps:
      - uses: actions/checkout@v5
        with:
          ref: ${{ needs.fetch.outputs.head_sha }}
          fetch-depth: 0

      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist

      - name: Fast-forward master
        id: ff
        env:
          HEAD_SHA: ${{ needs.fetch.outputs.head_sha }}
          BASE_SHA: ${{ needs.fetch.outputs.base_sha }}
        run: |
          git fetch origin master
          CURRENT="$(git rev-parse origin/master)"
          if [ "$CURRENT" != "$BASE_SHA" ]; then
            echo "FAIL: master moved from $BASE_SHA to $CURRENT while the wheel was being gated."
            echo "Rebasing would publish a tree that was never gated. Use 'Re-run all jobs'"
            echo "(not 'Re-run failed jobs') to retry from the current state, and delete the"
            echo "leftover sync branch first or the re-run's own push will be a non-fast-forward."
            exit 1
          fi
          # Rejected by the server if it is not a fast-forward.
          git push origin "$HEAD_SHA:refs/heads/master"
          echo "OK: master is now $HEAD_SHA"
          echo "moved=true" >> "$GITHUB_OUTPUT"

      - name: Cut the GitHub release
        id: publish
        env:
          TAG: ${{ needs.fetch.outputs.pyramses_tag }}
          HEAD_SHA: ${{ needs.fetch.outputs.head_sha }}
          SOURCE: ${{ needs.fetch.outputs.source }}
          UPSTREAM_TAG: ${{ needs.fetch.outputs.upstream_tag }}
          GH_TOKEN: ${{ github.token }}
        run: |
          RAMSES_VER="$(sed -n 's/^RAMSES_VERSION = "\(.*\)"/\1/p' src/pyramses/_bundled.py)"
          HELIOS_VER="$(sed -n 's/^HELIOS_VERSION = "\(.*\)"/\1/p' src/pyramses/_bundled.py)"
          cat > notes.md <<EOF
          Automated release: **$SOURCE $UPSTREAM_TAG** was published upstream and the
          bundled libraries were refreshed to match.

          | Component | Version |
          | --- | --- |
          | RAMSES | $RAMSES_VER |
          | Helios C API | $HELIOS_VER |

          The wheel attached here is the exact artifact the regression gate ran
          against on Linux, Windows and macOS: the full test suite, including the
          Nordic voltage-collapse trajectory check, passed on all three before this
          release was cut. The same file was uploaded to PyPI.
          EOF
          # --target creates the tag as part of publishing, collapsing what
          # would otherwise be two points of no return into one.
          gh release create "$TAG" \
            --repo "$GITHUB_REPOSITORY" \
            --target "$HEAD_SHA" \
            --title "PyRAMSES $TAG" \
            --notes-file notes.md \
            dist/*
          echo "published=true" >> "$GITHUB_OUTPUT"

      # Last, deliberately. A PyPI version can never be reclaimed, so it runs
      # only once master has moved and the release exists. If this step alone
      # fails, the tested wheel is attached to the release above and
      # python-publish.yml can upload it by hand.
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.PYPI_API_TOKEN }}
          packages-dir: dist/

      # Only reached if the upload above succeeded, so this is a faithful
      # record of whether the version was spent. report-failure keys the
      # difference between "retryable" and "gone" off it.
      - name: Mark PyPI published
        id: pypi_done
        run: echo "published=true" >> "$GITHUB_OUTPUT"

      - name: Delete the sync branch
        env:
          BRANCH: ${{ needs.fetch.outputs.branch }}
        run: git push origin --delete "$BRANCH"
```

- [ ] **Step 2: Append the failure-reporting job**

```yaml
  report-failure:
    needs: [fetch, build-wheel, nordic, release]
    if: failure() && github.event_name == 'repository_dispatch'
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    permissions:
      issues: write
    steps:
      - name: File or update an issue
        env:
          VALIDATED_TAG: ${{ needs.fetch.outputs.upstream_tag }}
          RAW_TAG: ${{ github.event.client_payload.tag }}
          SOURCE: ${{ needs.fetch.outputs.source }}
          MASTER_MOVED: ${{ needs.release.outputs.master_moved }}
          RELEASE_PUBLISHED: ${{ needs.release.outputs.release_published }}
          PYPI_PUBLISHED: ${{ needs.release.outputs.pypi_published }}
          RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
          GH_TOKEN: ${{ github.token }}
        run: |
          TAG="$VALIDATED_TAG"
          if [ -z "$TAG" ]; then
            # Validation itself is what failed, so the raw payload is still
            # untrusted free text: strip everything outside the tag charset
            # and clamp the length before it reaches a public issue.
            TAG="$(printf '%s' "$RAW_TAG" | tr -cd 'A-Za-z0-9.+-' | cut -c1-80)"
            [ -n "$TAG" ] || TAG="(unknown)"
          fi
          SRC="${SOURCE:-unknown}"

          if [ "$PYPI_PUBLISHED" = "true" ]; then
            STATE="\`master\` moved, the release was cut AND **PyPI was published**. That version number cannot be reused; any fix needs a further patch release."
          elif [ "$RELEASE_PUBLISHED" = "true" ]; then
            STATE="\`master\` moved and the release was cut, but **PyPI was not published**. The tested wheel is attached to the release; upload it with the \`Publish Python Package\` workflow rather than rebuilding."
          elif [ "$MASTER_MOVED" = "true" ]; then
            STATE="\`master\` WAS fast-forwarded, but no release was cut and nothing reached PyPI."
          else
            STATE="\`master\` was NOT moved, no release was cut and nothing reached PyPI."
          fi

          TITLE="$SRC $TAG: pyramses sync failed"
          BODY="$(cat <<-EOF
          	The sync-upstream-release workflow failed for $SRC \`$TAG\`.

          	Run: $RUN_URL

          	$STATE

          	The sync branch \`sync/$SRC-$TAG\` is left in place for inspection;
          	delete it once the cause is fixed and re-run the workflow (Re-run all
          	jobs, not just the failed ones) from the Actions UI.
          	EOF
          )"
          # `in:title` search is word-based, not exact, so fetch titles and
          # compare exactly instead.
          EXISTING="$(gh issue list --repo "$GITHUB_REPOSITORY" --state open --json number,title \
            | jq -r --arg t "$TITLE" '.[] | select(.title == $t) | .number' | head -n1)"
          if [ -n "$EXISTING" ]; then
            gh issue comment "$EXISTING" --repo "$GITHUB_REPOSITORY" --body "$BODY"
            echo "Commented on existing issue #$EXISTING"
          else
            if ! gh issue create --repo "$GITHUB_REPOSITORY" \
                  --title "$TITLE" --body "$BODY" --label ci; then
              echo "WARN: creating the issue with the 'ci' label failed (it may not exist yet); filing without a label"
              gh issue create --repo "$GITHUB_REPOSITORY" --title "$TITLE" --body "$BODY"
            fi
            echo "Opened a new issue"
          fi
```

- [ ] **Step 3: Validate the YAML**

Run:

```bash
python - <<'EOF'
import yaml
d = yaml.safe_load(open('.github/workflows/sync-upstream-release.yml'))
jobs = d['jobs']
print('jobs:', list(jobs))
rel = jobs['release']
print('release if:', rel['if'])
assert 'repository_dispatch' in rel['if'], 'release job is reachable from a rehearsal'
print('report-failure if:', jobs['report-failure']['if'])
EOF
```

Expected: five jobs; the `release` guard names `repository_dispatch`.

- [ ] **Step 4: Re-run the rehearsal and confirm release is skipped**

```bash
gh workflow run sync-upstream-release.yml --repo SPS-L/stepss-pyramses \
  -f source=ramses -f tag=v3.55
gh run watch <run-id> --repo SPS-L/stepss-pyramses --exit-status --interval 20
gh run view <run-id> --repo SPS-L/stepss-pyramses --json jobs \
  -q '.jobs[] | .name + " -> " + .conclusion'
```

Expected: `fetch`, `build-wheel` and the three `nordic` jobs succeed; `release` and `report-failure` are **skipped**. Confirm no new release and no new PyPI version exist.

- [ ] **Step 5: Commit and push**

```bash
git add .github/workflows/sync-upstream-release.yml
git commit -m "Add the release and failure-reporting jobs

PyPI runs last: master moves, the release is cut with the tested wheel
attached, and only then is that wheel uploaded. A version number cannot
be reclaimed, so the ordering keeps the common failure retryable.

report-failure states how far the run got, because recovery differs
sharply between 'master untouched' and 'already on PyPI'."
git push origin HEAD:master
```

---

### Task 7: Wire up the upstream notify jobs

**Files:**
- Modify: `../stepss-ramses/.github/workflows/release.yml`
- Modify: `../stepss-helios/.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the `repository_dispatch` contract from Task 5 — event types `ramses-release` and `helios-release`, payload `client_payload[tag]` and `client_payload[sha]`.
- Produces: nothing downstream.

- [ ] **Step 1: Add the RAMSES notify job**

In `stepss-ramses/.github/workflows/release.yml`, append after `notify-uramses`:

```yaml
  # pyramses bundles the shared libraries published above. Tell it a new
  # release exists so it can refresh, gate and publish its own package.
  # Prereleases are skipped: an -rc tag must not reach PyPI.
  notify-pyramses:
    needs: [publish]
    if: github.event_name == 'release' && github.event.release.prerelease == false
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Dispatch to stepss-pyramses
        env:
          GH_TOKEN: ${{ secrets.PYRAMSES_DISPATCH_TOKEN }}
          RELEASE_TAG: ${{ github.event.release.tag_name }}
        run: |
          # -f/--raw-field sends plain strings. -F/--field applies magic type
          # conversion, including reading the value from a local file when it
          # starts with "@" -- git permits a tag named "@evil", so -F here
          # would let a maliciously named tag make gh read a file instead.
          gh api /repos/SPS-L/stepss-pyramses/dispatches \
            -f event_type=ramses-release \
            -f "client_payload[tag]=$RELEASE_TAG" \
            -f "client_payload[sha]=$GITHUB_SHA"
          echo "Dispatched ramses-release for $RELEASE_TAG"
```

- [ ] **Step 2: Add the Helios notify job**

In `stepss-helios/.github/workflows/ci.yml`, append after the `release` job:

```yaml
  # pyramses bundles the C API libraries released above.
  #
  # Unlike stepss-ramses, this repo releases straight off a v* tag push and
  # has no prerelease flag to test, so the guard is on tag shape: anything
  # containing a hyphen (v1.3.0-rc1) is treated as a prerelease and skipped.
  notify-pyramses:
    needs: [release]
    if: startsWith(github.ref, 'refs/tags/') && !contains(github.ref_name, '-')
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - name: Dispatch to stepss-pyramses
        env:
          GH_TOKEN: ${{ secrets.PYRAMSES_DISPATCH_TOKEN }}
          RELEASE_TAG: ${{ github.ref_name }}
        run: |
          # -f, never -F: see the note in stepss-ramses' release.yml.
          gh api /repos/SPS-L/stepss-pyramses/dispatches \
            -f event_type=helios-release \
            -f "client_payload[tag]=$RELEASE_TAG" \
            -f "client_payload[sha]=$GITHUB_SHA"
          echo "Dispatched helios-release for $RELEASE_TAG"
```

- [ ] **Step 3: Validate both workflows**

```bash
python - <<'EOF'
import yaml
for p in ('../stepss-ramses/.github/workflows/release.yml',
          '../stepss-helios/.github/workflows/ci.yml'):
    d = yaml.safe_load(open(p))
    assert 'notify-pyramses' in d['jobs'], p
    print(p, '-> notify-pyramses if:', d['jobs']['notify-pyramses']['if'])
EOF
```

Expected: both parse and carry the guard.

- [ ] **Step 4: Commit and push each repo separately**

```bash
cd ../stepss-ramses
git add .github/workflows/release.yml
git commit -m "Notify stepss-pyramses when a release is published

pyramses bundles the shared libraries this workflow publishes and now
refreshes, gates and releases itself in response. Prereleases are
skipped so an -rc tag cannot reach PyPI."
git push origin HEAD:master

cd ../stepss-helios
git add .github/workflows/ci.yml
git commit -m "Notify stepss-pyramses when a release is published

This repo releases off a v* tag push and has no prerelease flag, so
the guard is on tag shape: a hyphenated tag is treated as a
prerelease and skipped."
git push origin HEAD:main
```

Note `stepss-helios` uses `main`, not `master`. Confirm with `git branch --show-current` before pushing.

- [ ] **Step 5: End-to-end live verification**

The next genuine upstream release exercises the whole chain. To verify sooner without publishing anything, re-run the RAMSES `release-binaries` workflow via `workflow_dispatch` — `notify-pyramses` is gated on `github.event_name == 'release'`, so it will be **skipped**, confirming the guard works.

For a true end-to-end test, the next real RAMSES or Helios release is the trigger. Watch both sides:

```bash
gh run list --repo SPS-L/stepss-ramses --workflow release.yml --limit 1
gh run list --repo SPS-L/stepss-pyramses --workflow sync-upstream-release.yml --limit 1
```

Expected: RAMSES `notify-pyramses` succeeds; a pyramses sync run appears within seconds, gates on three platforms, cuts a release and publishes to PyPI.

---

## Post-implementation checks

- [ ] `pip install pyramses==<new version>` in a clean venv on Linux, and `python -c "import pyramses; print(pyramses.__ramses_version__)"` reports the expected upstream tag.
- [ ] The GitHub release carries both the `.whl` and the `.tar.gz`.
- [ ] `docs/superpowers/specs/2026-08-06-pyramses-release-automation-design.md` open items 1–4 are all resolved; update the Secrets table if anything changed.
- [ ] `stepss-pyramses/CLAUDE.md` does not yet exist. Consider adding one recording that `src/pyramses/libs/` and `src/pyramses/_bundled.py` are CI-managed and must not be hand-edited — the same warning `stepss-uramses/CLAUDE.md` carries for its module kits.
