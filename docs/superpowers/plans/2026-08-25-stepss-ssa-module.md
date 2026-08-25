# `stepss.ssa` Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `stepss.ssa`, a module that runs a small-signal analysis, reads its three results files, filters them and plots them, so that a Python user reaches the same result as a user of `stepss-java-ui` without writing a parser first.

**Architecture:** One new module, `src/stepss/ssa.py`, plus two new methods on `stepss.sim` over C entries that `src/stepss/libs/ramses.h` already declares. The module parses the engine's fixed-width output by column offset, models one run as a `Results` object with composable `ModeView` filters, draws the s-plane and the mode-shape dial with matplotlib alone, and reads and writes the `.ssa` archive the graphical interface exchanges.

**Tech Stack:** Python 3, ctypes, numpy, matplotlib, `zipfile` and `tarfile` from the standard library, pytest. No new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-08-25-stepss-ssa-module-design.md`

## Global Constraints

- **No new runtime dependency.** `requirements.txt` and `src/setup.py` are not touched. pandas is optional and imported inside the one function that uses it.
- **Naming.** `src/stepss/ssa.py` is PEP 8 snake_case throughout, as `stepss.helios` is. The two new `sim` methods are camelCase (`runSsa`, `getStateMatrix`) because they sit beside `getJac` and `execSim`.
- **Format version.** Only `# STEPSS SSA modes v2` is read. Any other version is refused before a single data row is parsed.
- **Filter semantics, copied exactly from `SsaResults`.** `dominant` is `Re(lambda) > limit`, strictly greater than. `electromechanical` is `0.1 < f < 2.5` Hz with `Im > 0`, sorted by frequency ascending, and preserves input order under later filtering.
- **Defaults, copied from the graphical interface.** `MIN_TIME = 0.001`, `DEFAULT_REAL_LIMIT = -1.0`, `DEFAULT_PF_FLOOR = 0.05`, `DEFAULT_DAMPING_ZETA = 0.05`.
- **Basename rule.** Non-empty, and only ASCII letters, digits, `.`, `_` and `-`. It becomes both a file name and a quoted Fortran string.
- **Result file suffixes.** `('_modes.dat', '_pf.dat', '_ms.dat')`. Jacobian suffixes: `('_eqs.dat', '_var.dat', '_val.dat', '_struc.dat')`. The archive member set is the two concatenated, in that order.
- **Errors** are raised as `stepss.globals.RAMSESError`, which is what the rest of the RAMSES side of this package raises. It is not exported at package level; import it from `stepss.globals`.
- **Git.** Never chain git commands with `&&`, `||` or `;`. Run each separately. Work on the branch `ssa-module`.
- **No em-dashes** in any prose, comment or docstring this plan adds.

---

### Task 1: Module skeleton, fixed-column readers and the modes parser

**Files:**
- Create: `src/stepss/ssa.py`
- Create: `tests/test_ssa_parsers.py`
- Create: `tests/data/ssa/kundur_nopss_modes.dat` (generated, then committed)
- Create: `tests/data/ssa/kundur_nopss_pf.dat` (generated, then committed)
- Create: `tests/data/ssa/kundur_nopss_ms.dat` (generated, then committed)
- Modify: `src/stepss/__init__.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `stepss.ssa` importable. `ssa.FORMAT_VERSION == 2`, `ssa.MIN_TIME`, `ssa.DEFAULT_REAL_LIMIT`, `ssa.DEFAULT_PF_FLOOR`, `ssa.DEFAULT_DAMPING_ZETA`, `ssa.RESULT_SUFFIXES`, `ssa.JACOBIAN_SUFFIXES`, `ssa.MODE_DTYPE`. Private helpers `ssa._slice(line, start, stop) -> str`, `ssa._num(line, start, stop, lineno) -> float`, `ssa._int(line, start, stop, lineno) -> int`, `ssa._keyed(header, key) -> float or None`, `ssa._read_modes(text) -> (ndarray, dict)` where the array has dtype `[('index','i4'),('re','f8'),('im','f8'),('zeta','f8'),('freq','f8'),('simple','?')]` and the dict has keys `nstates`, `nalg`, `time`, `pf_floor`, `gap_tol`, `format_version`.

- [ ] **Step 1: Generate the reference fixtures from a real run**

The three committed fixtures must be genuine engine output, because the parser reads by column offset and only real output proves the offsets. Run the bundled Kundur example without its stabilisers:

```bash
mkdir -p "$TMPDIR/ssa-fixture"
cp examples/eigenanalysis/lf.dat examples/eigenanalysis/dyn_noPSS.dat \
   examples/eigenanalysis/solveroptions.dat examples/eigenanalysis/nothing.dst \
   examples/eigenanalysis/obs.dat "$TMPDIR/ssa-fixture/"
python - <<'PY'
import os
import stepss

os.chdir(os.path.join(os.environ["TMPDIR"], "ssa-fixture"))
case = stepss.cfg()
case.addData("lf.dat")
case.addData("dyn_noPSS.dat")
case.addData("solveroptions.dat")
case.addDst("nothing.dst")
case.addObs("obs.dat")
case.addTrj("out.trj")
ram = stepss.sim()
ram.execSim(case, 0.0)
ram.addDisturb(0.001, "EIG 'ssa'")
ram.contSim(0.01)
ram.endSim()
print(sorted(f for f in os.listdir(".") if f.startswith("ssa")))
PY
mkdir -p tests/data/ssa
cp "$TMPDIR/ssa-fixture/ssa_modes.dat" tests/data/ssa/kundur_nopss_modes.dat
cp "$TMPDIR/ssa-fixture/ssa_pf.dat"    tests/data/ssa/kundur_nopss_pf.dat
cp "$TMPDIR/ssa-fixture/ssa_ms.dat"    tests/data/ssa/kundur_nopss_ms.dat
```

Expected: the print lists `ssa_modes.dat`, `ssa_ms.dat` and `ssa_pf.dat`. Confirm the banner:

```bash
head -3 tests/data/ssa/kundur_nopss_modes.dat
```

Expected: the first line is exactly `# STEPSS SSA modes v2`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_ssa_parsers.py`:

```python
"""Fixed-column parsing of the three results files ssa.f90 writes.

The happy path is checked against genuine engine output committed under
tests/data/ssa/, because the parser reads by column offset and only real
output proves the offsets. The refusals are checked against text built here,
so that regenerating a fixture cannot turn a refusal into a pass.
"""

from pathlib import Path

import numpy as np
import pytest

from stepss import ssa
from stepss.globals import RAMSESError

FIXTURES = Path(__file__).resolve().parent / "data" / "ssa"


def en(value):
    """One number in the 24-column field ssa.f90's en24.15 edit descriptor fills."""
    return "%24s" % ("%.15E" % value)


def modes_line(index, re, im, zeta, freq, smp, dom=None):
    """One modes row at the offsets (i8,1x,4(en24.15,1x),i2) produces.

    Passing `dom` produces the v1 layout, which carried a dominance flag where
    v2 puts smp and pushed smp two columns further right.
    """
    row = "%8d %s %s %s %s " % (index, en(re), en(im), en(zeta), en(freq))
    if dom is None:
        return row + "%2d" % smp
    return row + "%2d %2d" % (dom, smp)


V2_HEADER = (
    "# STEPSS SSA modes v2\n"
    "# nstates 4 nalg 12 time %s pf_floor %s gap_tol %s\n"
) % (en(0.0), en(1e-3), en(1e-6))


def test_slice_keeps_leading_blank_and_drops_trailing():
    assert ssa._slice("  g1                ", 0, 20) == "  g1"


def test_slice_past_end_of_line_is_empty():
    assert ssa._slice("short", 40, 60) == ""


def test_num_names_the_columns_it_could_not_read():
    with pytest.raises(RAMSESError, match="columns 1-8"):
        ssa._num("not a number", 0, 8, 7)


def test_keyed_reads_a_header_value_by_name():
    header = "# nstates 70 nalg 250 time %s" % en(0.5)
    assert ssa._keyed(header, "nstates") == 70.0
    assert ssa._keyed(header, "time") == pytest.approx(0.5)
    assert ssa._keyed(header, "absent") is None


def test_read_modes_parses_the_engines_own_output():
    modes, header = ssa._read_modes((FIXTURES / "kundur_nopss_modes.dat").read_text())

    assert header["format_version"] == 2
    assert header["nstates"] == len(modes)
    assert header["nalg"] > 0
    assert header["pf_floor"] > 0.0
    assert modes["index"][0] == 1
    assert np.all(np.diff(modes["index"]) == 1)
    # Power system spectra are heavily degenerate; both flags occur here.
    assert modes["simple"].any()
    assert (~modes["simple"]).any()
    # One mode near 0.62 Hz with negative damping: the unstable inter-area mode.
    band = (modes["freq"] > 0.4) & (modes["freq"] < 0.9) & (modes["im"] > 0)
    assert band.sum() == 1
    assert modes["zeta"][band][0] < 0.0


def test_read_modes_reads_smp_from_the_v2_column():
    modes, _ = ssa._read_modes(
        V2_HEADER + modes_line(1, -0.5, 3.9, 0.13, 0.62, 1) + "\n")
    assert modes["simple"][0]
    assert modes["re"][0] == pytest.approx(-0.5)
    assert modes["freq"][0] == pytest.approx(0.62)


def test_read_modes_refuses_v1_naming_the_engine_version():
    text = ("# STEPSS SSA modes v1\n"
            + modes_line(1, -0.5, 3.9, 0.13, 0.62, smp=1, dom=0) + "\n")
    with pytest.raises(RAMSESError, match="older than 3.79"):
        ssa._read_modes(text)


def test_read_modes_refuses_a_newer_version():
    text = ("# STEPSS SSA modes v3\n"
            + modes_line(1, -0.5, 3.9, 0.13, 0.62, 1) + "\n")
    with pytest.raises(RAMSESError, match="version 3"):
        ssa._read_modes(text)


def test_read_modes_refuses_a_file_with_no_banner():
    with pytest.raises(RAMSESError, match="banner"):
        ssa._read_modes(modes_line(1, -0.5, 3.9, 0.13, 0.62, 1) + "\n")


def test_read_modes_refuses_a_banner_with_no_rows():
    with pytest.raises(RAMSESError, match="no mode rows"):
        ssa._read_modes(V2_HEADER)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_ssa_parsers.py -v`
Expected: every test FAILS with `ImportError: cannot import name 'ssa' from 'stepss'`.

- [ ] **Step 4: Write the module skeleton and the modes parser**

Create `src/stepss/ssa.py`:

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Small-signal stability analysis: run it, read it, filter it, plot it.

RAMSES performs the analysis itself. It linearises about the operating point
the run is paused at, reduces the differential-algebraic Jacobian to the state
matrix, solves the dense eigenproblem, and writes three files named from a
basename: ``<base>_modes.dat``, ``<base>_pf.dat`` and ``<base>_ms.dat``.

This module drives that run, reads the three files and presents them, so that a
caller writes no parser. It also reads and writes the ``.ssa`` archive the
graphical interface exchanges, so a run made in either interface opens in the
other.

Every mode is in all three files, and the filtering happens here, against
results already in hand: :meth:`Results.electromechanical` selects the rotor
band and :meth:`Results.dominant` the modes above a real part limit, both with
the semantics the graphical interface uses.

:Example:

>>> import stepss
>>> from stepss import ssa
>>> case = stepss.cfg('cmd.txt')
>>> res = ssa.run(case, basename='ssa')
>>> em = res.electromechanical()
>>> em.table()
>>> em.splane()

.. note:: The engine retains one analysis at a time in a process, and the
          working directory is process-wide, so two analyses must not run
          concurrently from threads. :class:`stepss.simulator.sim` carries the
          same restriction.
"""

import os
from collections import namedtuple

import numpy as np

from .globals import RAMSESError

#: The one ``_modes.dat`` format version this module reads. RAMSES has written
#: it since 3.79. v1 put a dominance flag exactly where v2 puts ``smp``, at the
#: same width with the same two legal values, so a positional reader that
#: skipped the banner would report one as the other and then read simplicity
#: off the end of the line. Hence the banner check before any row is parsed.
FORMAT_VERSION = 2

_MODES_BANNER = '# STEPSS SSA modes v'

#: What the analysis writes, in the order an archive carries them.
RESULT_SUFFIXES = ('_modes.dat', '_pf.dat', '_ms.dat')

#: What a JAC record writes beside them, under the same basename.
JACOBIAN_SUFFIXES = ('_eqs.dat', '_var.dat', '_val.dat', '_struc.dat')

#: Earliest analysis time offered, and the default. The engine needs at least
#: one step before it can apply an event.
MIN_TIME = 0.001

#: The real part limit the retired ``real_limit`` parameter defaulted to, so
#: that this default selects exactly what that default used to select.
DEFAULT_REAL_LIMIT = -1.0

#: The participation floor the retired ``pf_threshold`` parameter defaulted to.
#: The engine's own floor, ``pf_floor`` from ``$PF_THRES``, is lower, so this
#: trims a file that already holds more.
DEFAULT_PF_FLOOR = 0.05

#: Damping ratio of the s-plane's dashed ray, the usual planning criterion.
DEFAULT_DAMPING_ZETA = 0.05

#: One mode: the columns of ``<base>_modes.dat``, with lambda split into its
#: real and imaginary parts. ``simple`` false means the eigenvalue is
#: degenerate, its eigenvectors are not unique, and its participation factors
#: and mode shape are basis-dependent.
MODE_DTYPE = np.dtype([('index', 'i4'), ('re', 'f8'), ('im', 'f8'),
                       ('zeta', 'f8'), ('freq', 'f8'), ('simple', '?')])

# Field offsets, zero-based and half-open, as ssa.f90's edit descriptors
# produce them and as Columns.java in stepss-java-ui reads them. Splitting
# these lines on whitespace is wrong and fails silently: the a8 and a20 name
# fields are written as stored, so a leading blank is part of a name while
# trailing blanks are padding, and a device name may contain an embedded blank.
_MODES_FIELDS = ((0, 8), (9, 33), (34, 58), (59, 83), (84, 108), (109, 111))


def _slice(line, start, stop):
    """The field at ``[start, stop)``, trailing blanks removed.

    A leading blank is kept, because it is part of the name the engine stored.
    The end is clamped to the line length, since an all-blank trailing field is
    routinely stripped by editors and by CRLF normalisation.

    :param str line: one line of a results file, without its line ending
    :param int start: first column, zero-based
    :param int stop: one past the last column
    :returns: the field text
    :rtype: str
    """
    if start >= len(line):
        return ''
    return line[start:min(stop, len(line))].rstrip(' ')


def _num(line, start, stop, lineno):
    """The field at ``[start, stop)`` read as a float.

    :param str line: one line of a results file
    :param int start: first column, zero-based
    :param int stop: one past the last column
    :param int lineno: 1-based line number, used in the error message
    :returns: the value
    :rtype: float
    :raises RAMSESError: if the field does not parse, naming the columns
    """
    text = _slice(line, start, stop).strip()
    try:
        return float(text)
    except ValueError:
        raise RAMSESError('RAMSES: line %d: cannot read a number from <%s> at '
                          'columns %d-%d' % (lineno, text, start + 1, stop))


def _int(line, start, stop, lineno):
    """The field at ``[start, stop)`` read as an int.

    :param str line: one line of a results file
    :param int start: first column, zero-based
    :param int stop: one past the last column
    :param int lineno: 1-based line number, used in the error message
    :returns: the value
    :rtype: int
    :raises RAMSESError: if the field does not parse, naming the columns
    """
    text = _slice(line, start, stop).strip()
    try:
        return int(text)
    except ValueError:
        raise RAMSESError('RAMSES: line %d: cannot read an integer from <%s> at '
                          'columns %d-%d' % (lineno, text, start + 1, stop))


def _keyed(header, key):
    """One value out of a header comment, read by name rather than position.

    Reading by name is what lets a later engine add a field without breaking
    this, and lets an absent key stay None rather than failing the load.

    :param str header: the header line, including its leading ``#``
    :param str key: the key to look for
    :returns: the value, or None when the key is absent or does not parse
    :rtype: float or None
    """
    at = header.find(' ' + key + ' ')
    if at < 0:
        return None
    rest = header[at + len(key) + 2:].strip()
    token = rest.split(' ', 1)[0] if ' ' in rest else rest
    try:
        return float(token)
    except ValueError:
        return None


def _read_modes(text):
    """Parse ``<base>_modes.dat``.

    :param str text: the file's contents
    :returns: ``(modes, header)``, the modes as a :data:`MODE_DTYPE` array in
              file order, and the header as a dict with keys ``nstates``,
              ``nalg``, ``time``, ``pf_floor``, ``gap_tol`` and
              ``format_version``. An absent header key is None.
    :rtype: tuple
    :raises RAMSESError: if the banner is absent, names a version this module
                         does not read, or no mode rows follow it
    """
    version = 0
    header = {'nstates': None, 'nalg': None, 'time': None,
              'pf_floor': None, 'gap_tol': None}
    rows = []
    for i, line in enumerate(text.splitlines()):
        lineno = i + 1
        if not line.strip():
            continue
        if line[0] == '#':
            if line.startswith(_MODES_BANNER):
                tail = line[len(_MODES_BANNER):].strip()
                if tail.isdigit():
                    version = int(tail)
            if ' nstates ' in line:
                for key in header:
                    header[key] = _keyed(line, key)
            continue
        # Refused before the first row rather than after the last: a version
        # read as though it were v2 produces numbers, and numbers that parsed
        # are the hardest kind of wrong to notice.
        if version != FORMAT_VERSION:
            if version == 0:
                raise RAMSESError('RAMSES: no "%sN" banner; is this a '
                                  '_modes.dat file?' % _MODES_BANNER)
            raise RAMSESError(
                'RAMSES: unsupported _modes.dat format version %d; stepss reads '
                'v%d only%s' % (
                    version, FORMAT_VERSION,
                    '. It was written by a RAMSES older than 3.79.'
                    if version < FORMAT_VERSION else '.'))
        cols = _MODES_FIELDS
        rows.append((_int(line, cols[0][0], cols[0][1], lineno),
                     _num(line, cols[1][0], cols[1][1], lineno),
                     _num(line, cols[2][0], cols[2][1], lineno),
                     _num(line, cols[3][0], cols[3][1], lineno),
                     _num(line, cols[4][0], cols[4][1], lineno),
                     _int(line, cols[5][0], cols[5][1], lineno) == 1))
    if not rows:
        raise RAMSESError('RAMSES: no mode rows found; is this a _modes.dat file?')
    header['nstates'] = None if header['nstates'] is None else int(header['nstates'])
    header['nalg'] = None if header['nalg'] is None else int(header['nalg'])
    header['format_version'] = version
    return np.array(rows, dtype=MODE_DTYPE), header
```

- [ ] **Step 5: Export the module**

In `src/stepss/__init__.py`, add to the docstring's public API list, after the `monitor` line:

```
- :mod:`stepss.ssa` - run and read a small-signal stability analysis.
```

Add the import beside the existing `from . import helios`:

```python
from . import ssa
```

and add `"ssa"` to `__all__`, after `"helios"`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_ssa_parsers.py -v`
Expected: every test in the file passes, none skipped, none xfailed. The count is not a requirement: several tests are parametrised, so the number pytest reports is larger than the number of test functions.

Run: `pytest tests/ -v -k "not nordic"`
Expected: PASS, nothing else broken by the new import.

- [ ] **Step 7: Commit**

```bash
git add src/stepss/ssa.py src/stepss/__init__.py tests/test_ssa_parsers.py tests/data/ssa
git commit -m "feat(ssa): fixed-column readers and the _modes.dat parser"
```

---

### Task 2: The participation and mode-shape parsers

**Files:**
- Modify: `src/stepss/ssa.py`
- Modify: `tests/test_ssa_parsers.py`

**Interfaces:**
- Consumes: `ssa._slice`, `ssa._num`, `ssa._int` from Task 1.
- Produces: `ssa.Participation`, a namedtuple with fields `mode`, `state`, `pf`, `family`, `device`, `variable`. `ssa.ModeShapeEntry`, a namedtuple with fields `mode`, `state`, `magnitude`, `angle_deg`, `device`. `ssa._read_pf(text) -> dict` mapping mode index to a list of `Participation`, sorted by `pf` descending within each mode. `ssa._read_ms(text) -> dict` mapping mode index to a list of `ModeShapeEntry` in file order.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ssa_parsers.py`:

```python
def pf_line(mode, state, pf, family, device, variable):
    """One row at the offsets (i8,1x,i8,1x,en24.15,1x,a8,1x,a20,1x,a20) produces."""
    return "%8d %8d %s %-8s %-20s %-20s" % (mode, state, en(pf), family, device,
                                            variable)


def ms_line(mode, state, magnitude, angle_deg, device):
    """One row at the offsets (i8,1x,i8,1x,2(en24.15,1x),a20) produces."""
    return "%8d %8d %s %s %-20s" % (mode, state, en(magnitude), en(angle_deg),
                                    device)


def test_read_pf_parses_the_engines_own_output():
    rows = ssa._read_pf((FIXTURES / "kundur_nopss_pf.dat").read_text())
    assert rows
    # Normalisation puts one entry at exactly 1 in every mode, so no mode can
    # be emptied by the floor: a mode missing from a v2 file means the file is
    # incomplete.
    for entries in rows.values():
        assert max(e.pf for e in entries) == pytest.approx(1.0)
        assert [e.pf for e in entries] == sorted((e.pf for e in entries),
                                                 reverse=True)
    assert any(e.variable == "omega" for entries in rows.values() for e in entries)


def test_read_pf_keeps_a_device_name_with_an_embedded_blank():
    """Splitting on whitespace shifts every field after such a name."""
    text = ("# STEPSS SSA participation factors v2\n"
            + pf_line(3, 7, 0.5, "SYN", "g 1", "omega") + "\n")
    rows = ssa._read_pf(text)
    assert rows[3][0].device == "g 1"
    assert rows[3][0].variable == "omega"
    assert rows[3][0].family == "SYN"


def test_read_pf_keeps_a_leading_blank_in_a_device_name():
    text = ("# STEPSS SSA participation factors v2\n"
            + pf_line(3, 7, 0.5, "SYN", " g1", "omega") + "\n")
    assert ssa._read_pf(text)[3][0].device == " g1"


def test_read_pf_of_an_empty_file_is_empty():
    assert ssa._read_pf("") == {}


def test_read_ms_parses_the_engines_own_output():
    rows = ssa._read_ms((FIXTURES / "kundur_nopss_ms.dat").read_text())
    assert rows
    all_zero = 0
    for entries in rows.values():
        peak = max(e.magnitude for e in entries)
        if peak == 0.0:
            # A mode whose omega entries are all exactly zero is written as
            # magnitude 0, angle 0 for every omega state, rather than being
            # skipped or divided by zero, so that the row count is the same
            # for every mode. See the mmax <= 0 branch in ssa.f90's
            # write_ssa_mode_shapes. Such a mode has no rotor content at all.
            assert all(e.angle_deg == 0.0 for e in entries)
            all_zero += 1
            continue
        assert peak == pytest.approx(1.0)
        # Angles are relative to the largest entry, which therefore sits at 0.
        reference = max(entries, key=lambda e: e.magnitude)
        assert reference.angle_deg == pytest.approx(0.0, abs=1e-9)
    assert all_zero == 4, (
        "the committed fixture carries four modes with no rotor content; "
        "if this fails the fixture was edited, and it must not be")


def test_read_ms_keeps_file_order():
    """File order is state order, and the phase reference is a row in it."""
    text = ("# STEPSS SSA mode shapes v2\n"
            + ms_line(1, 9, 0.4, -178.0, "g4") + "\n"
            + ms_line(1, 3, 1.0, 0.0, "g1") + "\n")
    assert [e.device for e in ssa._read_ms(text)[1]] == ["g4", "g1"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ssa_parsers.py -v -k "pf or ms"`
Expected: FAIL with `AttributeError: module 'stepss.ssa' has no attribute '_read_pf'`.

- [ ] **Step 3: Write the parsers**

Append to `src/stepss/ssa.py`, after `_read_modes`:

```python
_PF_FIELDS = ((0, 8), (9, 17), (18, 42), (43, 51), (52, 72), (73, 93))
_MS_FIELDS = ((0, 8), (9, 17), (18, 42), (43, 67), (68, 88))

Participation = namedtuple('Participation',
                           'mode state pf family device variable')
Participation.__doc__ = """One row of ``<base>_pf.dat``.

``pf`` is the participation factor, normalised so that the largest in each mode
is exactly 1. ``family`` is one of SYN, TOR, EXC, INJ, DCTL. A device absent
from a mode is below the run's ``pf_floor``, never zero.
"""

ModeShapeEntry = namedtuple('ModeShapeEntry',
                            'mode state magnitude angle_deg device')
ModeShapeEntry.__doc__ = """One row of ``<base>_ms.dat``: a machine's rotor-speed phasor in one mode.

``magnitude`` is normalised so the largest in the mode is 1, and ``angle_deg``
is relative to that largest entry, because an eigenvector's absolute phase is
arbitrary and would otherwise vary from run to run.
"""


def _read_pf(text):
    """Parse ``<base>_pf.dat``, indexed by mode.

    Rows within a mode are sorted by participation factor, largest first.

    :param str text: the file's contents, or '' when the file is absent
    :returns: mode index to list of :class:`Participation`
    :rtype: dict
    :raises RAMSESError: if a field does not parse
    """
    by_mode = {}
    for i, line in enumerate(text.splitlines()):
        if not line.strip() or line[0] == '#':
            continue
        lineno = i + 1
        row = Participation(
            _int(line, _PF_FIELDS[0][0], _PF_FIELDS[0][1], lineno),
            _int(line, _PF_FIELDS[1][0], _PF_FIELDS[1][1], lineno),
            _num(line, _PF_FIELDS[2][0], _PF_FIELDS[2][1], lineno),
            _slice(line, _PF_FIELDS[3][0], _PF_FIELDS[3][1]).strip(),
            _slice(line, _PF_FIELDS[4][0], _PF_FIELDS[4][1]),
            _slice(line, _PF_FIELDS[5][0], _PF_FIELDS[5][1]).strip())
        by_mode.setdefault(row.mode, []).append(row)
    for rows in by_mode.values():
        rows.sort(key=lambda r: r.pf, reverse=True)
    return by_mode


def _read_ms(text):
    """Parse ``<base>_ms.dat``, indexed by mode.

    File order is kept, which is state order, because the phase reference is
    the largest-magnitude entry and reordering would obscure which machine that
    was.

    :param str text: the file's contents, or '' when the file is absent
    :returns: mode index to list of :class:`ModeShapeEntry`
    :rtype: dict
    :raises RAMSESError: if a field does not parse
    """
    by_mode = {}
    for i, line in enumerate(text.splitlines()):
        if not line.strip() or line[0] == '#':
            continue
        lineno = i + 1
        row = ModeShapeEntry(
            _int(line, _MS_FIELDS[0][0], _MS_FIELDS[0][1], lineno),
            _int(line, _MS_FIELDS[1][0], _MS_FIELDS[1][1], lineno),
            _num(line, _MS_FIELDS[2][0], _MS_FIELDS[2][1], lineno),
            _num(line, _MS_FIELDS[3][0], _MS_FIELDS[3][1], lineno),
            _slice(line, _MS_FIELDS[4][0], _MS_FIELDS[4][1]))
        by_mode.setdefault(row.mode, []).append(row)
    return by_mode
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_ssa_parsers.py -v`
Expected: every test in the file passes, none skipped, none xfailed. The count is not a requirement: several tests are parametrised, so the number pytest reports is larger than the number of test functions.

- [ ] **Step 5: Commit**

```bash
git add src/stepss/ssa.py tests/test_ssa_parsers.py
git commit -m "feat(ssa): participation and mode-shape parsers"
```

---

### Task 3: `Results`, `ModeView`, the filters and the loaders

**Files:**
- Modify: `src/stepss/ssa.py`
- Create: `tests/test_ssa_results.py`

**Interfaces:**
- Consumes: `ssa._read_modes`, `ssa._read_pf`, `ssa._read_ms`, `ssa.MODE_DTYPE`, `ssa.RESULT_SUFFIXES`, `ssa.DEFAULT_REAL_LIMIT`, `ssa.DEFAULT_PF_FLOOR` from Tasks 1 and 2.
- Produces: `ssa.Results` with attributes `modes` (ndarray), `nstates`, `nalg`, `time`, `pf_floor`, `gap_tol`, `format_version`, `directory`, `basename`, and methods `view()`, `electromechanical(lo=0.1, hi=2.5)`, `dominant(real_limit=-1.0)`, `participation(mode, floor=0.05, allow_degenerate=False)`, `mode_shape(mode, allow_degenerate=False)`, `summary()`, plus the private `_index_of(mode)` and `_check_simple(index, allow_degenerate)` that Tasks 6 and 7 call. `ssa.ModeView` with `__len__`, `__getitem__`, `__iter__`, `rows`, `lam`, `electromechanical()`, `dominant()`, `table()`, `to_frame()`. `ssa.load(directory, basename) -> Results`. `ssa.basenames(directory) -> list of str`. Private `ssa._read_text(path)` and `ssa._optional_text(directory, basename, suffix)`, used by Task 6.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ssa_results.py`:

```python
"""The Results model, its filters and its accessors."""

import shutil
from pathlib import Path

import numpy as np
import pytest

from stepss import ssa
from stepss.globals import RAMSESError

FIXTURES = Path(__file__).resolve().parent / "data" / "ssa"


@pytest.fixture
def run_dir(tmp_path):
    """The committed Kundur no-PSS run, laid out as a run on disk."""
    for suffix in ("modes", "pf", "ms"):
        shutil.copy(FIXTURES / ("kundur_nopss_%s.dat" % suffix),
                    tmp_path / ("ssa_%s.dat" % suffix))
    return tmp_path


@pytest.fixture
def res(run_dir):
    return ssa.load(run_dir, "ssa")


def test_load_reads_the_header(res):
    assert res.basename == "ssa"
    assert res.format_version == 2
    assert res.nstates == len(res.modes)
    assert res.pf_floor > 0.0
    assert res.gap_tol > 0.0


def test_load_refuses_a_missing_run(tmp_path):
    with pytest.raises(RAMSESError, match="no ssa_modes.dat"):
        ssa.load(tmp_path, "ssa")


def test_load_treats_absent_optional_files_as_empty(tmp_path):
    shutil.copy(FIXTURES / "kundur_nopss_modes.dat", tmp_path / "ssa_modes.dat")
    loaded = ssa.load(tmp_path, "ssa")
    assert len(loaded.modes) > 0
    first = int(loaded.modes["index"][0])
    assert loaded.participation(first, allow_degenerate=True) == []
    assert loaded.mode_shape(first, allow_degenerate=True) == []


def test_basenames_lists_runs_and_ignores_a_directory_of_that_name(run_dir):
    (run_dir / "decoy_modes.dat").mkdir()
    assert ssa.basenames(run_dir) == ["ssa"]


def test_electromechanical_selects_the_rotor_band_sorted_by_frequency(res):
    em = res.electromechanical()
    assert len(em) >= 3
    assert np.all(em.rows["freq"] > 0.1)
    assert np.all(em.rows["freq"] < 2.5)
    assert np.all(em.rows["im"] > 0.0)
    assert np.all(np.diff(em.rows["freq"]) >= 0.0)


def test_dominant_is_strictly_greater_than(res):
    limit = float(res.modes["re"].max())
    assert len(res.dominant(limit)) == 0, "a mode exactly on the limit is excluded"


def test_dominant_preserves_the_order_it_was_given(res):
    em = res.electromechanical()
    assert list(em.dominant(-1e9).rows["index"]) == list(em.rows["index"])


def test_lam_recombines_the_two_columns(res):
    em = res.electromechanical()
    assert em.lam[0] == pytest.approx(em.rows["re"][0] + 1j * em.rows["im"][0])


def test_participation_of_the_interarea_mode_lists_all_four_machines(res):
    interarea = [m for m in res.electromechanical().rows if 0.4 < m["freq"] < 0.9]
    assert len(interarea) == 1
    rows = res.participation(interarea[0], floor=0.05)
    devices = {r.device.strip() for r in rows if r.variable == "omega"}
    assert devices == {"G1", "G2", "G3", "G4"}


def test_participation_floor_is_applied_here_not_by_the_engine(res):
    local = [m for m in res.electromechanical().rows if m["freq"] > 0.9][0]
    assert len(res.participation(local, floor=0.001)) > \
        len(res.participation(local, floor=0.05))


def test_participation_refuses_a_degenerate_mode(res):
    degenerate = res.modes[~res.modes["simple"]][0]
    with pytest.raises(RAMSESError, match="degenerate"):
        res.participation(degenerate)
    assert isinstance(res.participation(degenerate, allow_degenerate=True), list)


def test_mode_shape_refuses_a_degenerate_mode(res):
    degenerate = res.modes[~res.modes["simple"]][0]
    with pytest.raises(RAMSESError, match="degenerate"):
        res.mode_shape(degenerate)
    assert isinstance(res.mode_shape(degenerate, allow_degenerate=True), list)


def test_mode_accepts_an_index_or_a_row(res):
    row = res.electromechanical().rows[0]
    assert res.mode_shape(row) == res.mode_shape(int(row["index"]))


def test_index_of_refuses_something_that_is_neither(res):
    with pytest.raises(RAMSESError, match="neither a mode index"):
        res._index_of("mode 3")


def test_table_and_summary_print_something(res, capsys):
    res.summary()
    res.electromechanical().table()
    assert capsys.readouterr().out.strip()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ssa_results.py -v`
Expected: FAIL with `AttributeError: module 'stepss.ssa' has no attribute 'load'`.

- [ ] **Step 3: Write the model and the loaders**

Append to `src/stepss/ssa.py`:

```python
class ModeView(object):
    """A selection of modes, still attached to the run they came from.

    Filters return one of these rather than a bare array so that they compose,
    and so that the run's participation factors and mode shapes stay reachable
    through the selection.
    """

    def __init__(self, results, rows):
        """:param Results results: the run these modes came from
        :param numpy.ndarray rows: a :data:`MODE_DTYPE` array
        """
        self.results = results
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, item):
        return self.rows[item]

    def __iter__(self):
        return iter(self.rows)

    @property
    def lam(self):
        """The eigenvalues as a complex array.

        :rtype: numpy.ndarray
        """
        return self.rows['re'] + 1j * self.rows['im']

    def electromechanical(self, lo=0.1, hi=2.5):
        """The rotor band, one member of each conjugate pair, sorted by frequency.

        Rotor oscillations sit roughly between 0.1 and 2.5 Hz; below that are
        slow controller modes and above it exciter and network dynamics. The
        ``Im > 0`` test is what collapses each conjugate pair to a single row,
        since the two members are one physical oscillation.

        :param float lo: lower frequency bound in Hz, exclusive
        :param float hi: upper frequency bound in Hz, exclusive
        :returns: the selection
        :rtype: ModeView
        """
        sel = ((self.rows['freq'] > lo) & (self.rows['freq'] < hi)
               & (self.rows['im'] > 0.0))
        kept = self.rows[sel]
        return ModeView(self.results, kept[np.argsort(kept['freq'], kind='stable')])

    def dominant(self, real_limit=DEFAULT_REAL_LIMIT):
        """The modes whose real part is above ``real_limit``.

        Strictly greater than, which is what the engine's retired
        ``real_limit`` was, so a given limit selects exactly the modes it would
        have selected before. Input order is preserved, so composing this after
        :meth:`electromechanical` keeps that method's sort.

        :param float real_limit: the limit, in 1/s
        :returns: the selection
        :rtype: ModeView
        """
        return ModeView(self.results, self.rows[self.rows['re'] > real_limit])

    def table(self):
        """Print one line per mode: index, frequency, damping ratio, lambda, simplicity.

        .. note:: This prints and returns None. Use :meth:`to_frame` or
                  :attr:`rows` to work with the values.
        """
        print('  %-6s %-9s %-11s %-26s %s'
              % ('mode', 'f [Hz]', 'zeta', 'lambda', 'simple'))
        for row in self.rows:
            print('  %-6d %-9.4f %-+11.4f %-26s %s'
                  % (row['index'], row['freq'], row['zeta'],
                     '%+.4f %+.4fj' % (row['re'], row['im']),
                     'yes' if row['simple'] else 'NO'))

    def to_frame(self):
        """The same rows as a pandas DataFrame.

        :rtype: pandas.DataFrame
        :raises RAMSESError: if pandas is not installed. It is not a dependency
                             of this package, which is why this is the only
                             place that imports it.
        """
        try:
            import pandas
        except ImportError:
            raise RAMSESError('RAMSES: to_frame() needs pandas, which stepss does '
                              'not depend on. Install it, or use .rows.')
        return pandas.DataFrame(self.rows)


class Results(object):
    """One small-signal run: the three files the engine wrote, and its header.

    ``_pf.dat`` and ``_ms.dat`` are optional and load as empty when absent,
    because their absence is not a reason to refuse the run that is present.
    """

    def __init__(self, modes, header, participation, shapes, directory,
                 basename, ram=None, generation=None):
        """:param numpy.ndarray modes: a :data:`MODE_DTYPE` array
        :param dict header: as :func:`_read_modes` returns
        :param dict participation: as :func:`_read_pf` returns
        :param dict shapes: as :func:`_read_ms` returns
        :param str directory: where the files were read from
        :param str basename: the run's basename
        :param ram: the simulator this run was made with, for the state matrix
        :type ram: stepss.simulator.sim or None
        :param generation: the value of the simulator's analysis counter when
                           this run was produced
        :type generation: int or None
        """
        self.modes = modes
        self.nstates = header['nstates']
        self.nalg = header['nalg']
        self.time = header['time']
        self.pf_floor = header['pf_floor']
        self.gap_tol = header['gap_tol']
        self.format_version = header['format_version']
        self.directory = str(directory)
        self.basename = basename
        self._participation = participation
        self._shapes = shapes
        self._ram = ram
        self._generation = generation

    def view(self):
        """Every mode, as a selection.

        :rtype: ModeView
        """
        return ModeView(self, self.modes)

    def electromechanical(self, lo=0.1, hi=2.5):
        """See :meth:`ModeView.electromechanical`.

        :rtype: ModeView
        """
        return self.view().electromechanical(lo, hi)

    def dominant(self, real_limit=DEFAULT_REAL_LIMIT):
        """See :meth:`ModeView.dominant`.

        :rtype: ModeView
        """
        return self.view().dominant(real_limit)

    def _index_of(self, mode):
        """The mode index named by an int or by a row of :attr:`modes`.

        :param mode: a 1-based mode index, or a row of :attr:`modes`
        :returns: the index
        :rtype: int
        :raises RAMSESError: if *mode* is neither
        """
        if isinstance(mode, (int, np.integer)):
            return int(mode)
        try:
            return int(mode['index'])
        except (TypeError, ValueError, IndexError, KeyError):
            raise RAMSESError('RAMSES: %r is neither a mode index nor a row of '
                              '.modes' % (mode,))

    def _check_simple(self, index, allow_degenerate):
        """Refuse a degenerate mode unless the caller insists.

        In a degenerate eigenspace the individual eigenvectors are not unique,
        so participation factors and mode shapes are basis-dependent: they are
        real numbers that mean nothing physically and would come out
        differently on another LAPACK build. The graphical interface declines
        to show either, and so does this by default.

        :param int index: the mode index
        :param bool allow_degenerate: return the rows anyway
        :raises RAMSESError: if the mode is degenerate and *allow_degenerate*
                             is False
        """
        if allow_degenerate:
            return
        row = self.modes[self.modes['index'] == index]
        if len(row) and not row['simple'][0]:
            raise RAMSESError(
                'RAMSES: mode %d is degenerate (simple = 0). Its eigenvectors '
                'are not unique, so its participation factors and mode shape '
                'are basis-dependent and would come out differently on another '
                'machine. Pass allow_degenerate=True to read them anyway.'
                % index)

    def participation(self, mode, floor=DEFAULT_PF_FLOOR, allow_degenerate=False):
        """Participation factors for one mode, largest first.

        ``floor`` is applied here and not by the engine. The file carries every
        entry above the run's own :attr:`pf_floor`, so lowering this shows more
        without re-running anything, down to that floor. Only below it is an
        entry genuinely absent from the file rather than merely filtered here.

        :param mode: a mode index, or a row of :attr:`modes`
        :param float floor: smallest participation factor to return
        :param bool allow_degenerate: read a degenerate mode anyway
        :returns: the rows
        :rtype: list of Participation
        :raises RAMSESError: if the mode is degenerate and not allowed
        """
        index = self._index_of(mode)
        self._check_simple(index, allow_degenerate)
        return [row for row in self._participation.get(index, [])
                if row.pf >= floor]

    def mode_shape(self, mode, allow_degenerate=False):
        """The rotor-speed phasor of each machine in one mode, in state order.

        :param mode: a mode index, or a row of :attr:`modes`
        :param bool allow_degenerate: read a degenerate mode anyway
        :returns: the rows
        :rtype: list of ModeShapeEntry
        :raises RAMSESError: if the mode is degenerate and not allowed
        """
        index = self._index_of(mode)
        self._check_simple(index, allow_degenerate)
        return list(self._shapes.get(index, []))

    def summary(self):
        """Print the run's header and its mode counts.

        .. note:: This prints and returns None.
        """
        print('%s in %s' % (self.basename, self.directory))
        print('  %d states, %d algebraic variables, modes file v%d'
              % (self.nstates or 0, self.nalg or 0, self.format_version))
        if self.time is not None:
            print('  linearised at t = %g s' % self.time)
        print('  %d modes, %d simple, %d degenerate'
              % (len(self.modes), int(self.modes['simple'].sum()),
                 int((~self.modes['simple']).sum())))
        if self.pf_floor is not None:
            print('  participation written down to %g ($PF_THRES)' % self.pf_floor)


def load(directory, basename):
    """Read one run from disk, whatever produced it.

    :param directory: the directory holding the run
    :type directory: str or pathlib.Path
    :param str basename: the run's basename
    :returns: the run
    :rtype: Results
    :raises RAMSESError: if the modes file is absent or does not parse
    """
    directory = str(directory)
    modes_path = os.path.join(directory, basename + RESULT_SUFFIXES[0])
    if not os.path.isfile(modes_path):
        raise RAMSESError('RAMSES: no %s%s in %s'
                          % (basename, RESULT_SUFFIXES[0], directory))
    modes, header = _read_modes(_read_text(modes_path))
    return Results(modes, header,
                   _read_pf(_optional_text(directory, basename, '_pf.dat')),
                   _read_ms(_optional_text(directory, basename, '_ms.dat')),
                   directory, basename)


def basenames(directory):
    """Every basename in *directory* for which a modes file exists, sorted.

    A directory named ``<x>_modes.dat`` is not offered, because it would then
    be refused by :func:`load` about a name that plainly exists.

    :param directory: the directory to look in
    :type directory: str or pathlib.Path
    :returns: the basenames
    :rtype: list of str
    """
    directory = str(directory)
    suffix = RESULT_SUFFIXES[0]
    found = []
    try:
        names = os.listdir(directory)
    except OSError:
        return found
    for name in names:
        if (name.endswith(suffix) and len(name) > len(suffix)
                and os.path.isfile(os.path.join(directory, name))):
            found.append(name[:-len(suffix)])
    return sorted(found)


def _read_text(path):
    """The whole of a text file, decoded as UTF-8.

    :param str path: the file
    :returns: its contents
    :rtype: str
    """
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        return handle.read()


def _optional_text(directory, basename, suffix):
    """The contents of an optional results file, or '' when it is absent.

    :param str directory: the run's directory
    :param str basename: the run's basename
    :param str suffix: the file suffix, including its leading underscore
    :returns: the contents, or ''
    :rtype: str
    """
    path = os.path.join(str(directory), basename + suffix)
    return _read_text(path) if os.path.isfile(path) else ''
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_ssa_results.py -v`
Expected: every test in the file passes, none skipped, none xfailed. The count is not a requirement: several tests are parametrised, so the number pytest reports is larger than the number of test functions.

- [ ] **Step 5: Commit**

```bash
git add src/stepss/ssa.py tests/test_ssa_results.py
git commit -m "feat(ssa): Results, ModeView, the filters and the loaders"
```

---

### Task 4: Run helpers, the generated files and the clearing step

**Files:**
- Modify: `src/stepss/ssa.py`
- Create: `tests/test_ssa_run_helpers.py`

**Interfaces:**
- Consumes: `ssa.MIN_TIME`, `ssa.RESULT_SUFFIXES`, `ssa.JACOBIAN_SUFFIXES` from Task 1.
- Produces: `ssa.SETTINGS_SUFFIX`, `ssa.DISTURBANCE_SUFFIX`, `ssa.valid_basename(name) -> bool`, `ssa.check_time(t) -> float`, `ssa.settings_text() -> str`, `ssa.settings_name(basename) -> str`, `ssa.disturbance_text(t) -> str`, `ssa.disturbance_name(basename) -> str`, `ssa.members(basename) -> tuple of str`, `ssa.clear_previous_run(directory, basename) -> list of str`, and the private `ssa._STOP_MARGIN` that Task 6 uses.

This task comes before Task 5 because `sim.runSsa` calls `valid_basename` and `check_time`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ssa_run_helpers.py`:

```python
"""The pure helpers a run needs: validation, the two generated files, clearing."""

import os

import pytest

from stepss import ssa
from stepss.globals import RAMSESError


@pytest.mark.parametrize("name", ["ssa", "run-1", "a.b_c", "X9"])
def test_valid_basenames(name):
    assert ssa.valid_basename(name)


@pytest.mark.parametrize("name", ["", "it's", "sub/dir", "back\\slash", "a b", None])
def test_invalid_basenames(name):
    assert not ssa.valid_basename(name)


def test_check_time_accepts_the_floor():
    assert ssa.check_time(ssa.MIN_TIME) == pytest.approx(ssa.MIN_TIME)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_check_time_refuses(bad):
    with pytest.raises(RAMSESError):
        ssa.check_time(bad)


def test_check_time_refuses_text():
    with pytest.raises(RAMSESError, match="number"):
        ssa.check_time("soon")


def test_settings_text_carries_exactly_the_two_records():
    text = ssa.settings_text()
    assert "$SCHEME DE" in text
    assert "$OMEGA_REF SYN" in text
    records = [line for line in text.splitlines()
               if line.strip() and not line.startswith("#")]
    assert len(records) == 2, "anything else would change the user's run for no reason"


def test_settings_name_uses_the_graphical_interfaces_suffix():
    assert ssa.settings_name("ssa") == "ssaEig.dat"
    with pytest.raises(RAMSESError):
        ssa.settings_name("it's")


def test_disturbance_name_cannot_collide_with_a_results_file():
    generated = {ssa.settings_name("ssa"), ssa.disturbance_name("ssa")}
    assert generated.isdisjoint(set(ssa.members("ssa")))


def test_disturbance_text_stops_after_the_analysis_time():
    lines = [line for line in ssa.disturbance_text(0.5).splitlines() if line.strip()]
    assert lines[0].startswith("0.000")
    assert "STOP" in lines[-1]
    assert float(lines[-1].split()[0]) > 0.5
    # No events: the engine linearises about whatever state it is in, so an
    # event before the analysis would describe that instant, not an operating
    # point.
    assert not any("FAULT" in line or "TRIP" in line for line in lines)


def test_disturbance_text_writes_a_plain_decimal():
    assert "E-" not in ssa.disturbance_text(0.001)


def test_members_are_the_three_results_then_the_four_jacobian_tables():
    assert ssa.members("run") == (
        "run_modes.dat", "run_pf.dat", "run_ms.dat",
        "run_eqs.dat", "run_var.dat", "run_val.dat", "run_struc.dat")


def test_clear_previous_run_removes_only_this_runs_members(tmp_path):
    for name in ssa.members("ssa"):
        (tmp_path / name).write_text("x")
    (tmp_path / "other_modes.dat").write_text("keep")
    (tmp_path / "lf.dat").write_text("keep")

    assert ssa.clear_previous_run(tmp_path, "ssa") == []
    for name in ssa.members("ssa"):
        assert not (tmp_path / name).exists()
    assert (tmp_path / "other_modes.dat").exists()
    assert (tmp_path / "lf.dat").exists()


def test_clear_previous_run_on_an_empty_directory_is_clean(tmp_path):
    assert ssa.clear_previous_run(tmp_path, "ssa") == []


def test_clear_previous_run_reports_what_would_not_go(tmp_path, monkeypatch):
    (tmp_path / "ssa_modes.dat").write_text("x")
    (tmp_path / "ssa_pf.dat").write_text("x")

    real_remove = os.remove

    def refuse_one(path, *args, **kwargs):
        if str(path).endswith("ssa_modes.dat"):
            raise OSError("still open")
        real_remove(path, *args, **kwargs)

    monkeypatch.setattr(os, "remove", refuse_one)
    assert ssa.clear_previous_run(tmp_path, "ssa") == ["ssa_modes.dat"]
    # The rest are still attempted, so one stuck file cannot leave others
    # behind to be mistaken for the next run's.
    assert not (tmp_path / "ssa_pf.dat").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ssa_run_helpers.py -v`
Expected: FAIL with `AttributeError: module 'stepss.ssa' has no attribute 'valid_basename'`.

- [ ] **Step 3: Write the helpers**

Append to `src/stepss/ssa.py`:

```python
#: What is appended to a run's basename to name the generated settings file.
#: It mirrors the disturbance file the same run generates, and cannot collide
#: with a results file or a Jacobian table, all of which begin with an
#: underscore.
SETTINGS_SUFFIX = 'Eig.dat'

#: What is appended to a run's basename to name the generated disturbance file.
DISTURBANCE_SUFFIX = 'Eig.dst'

#: Gap between the analysis and the STOP record. The analysis is complete when
#: it returns, so this only has to be positive.
_STOP_MARGIN = 0.010

_BASENAME_OK = frozenset(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-')


def valid_basename(basename):
    """Whether *basename* is safe as both a file name stem and a quoted record.

    An apostrophe would terminate the analysis record's quoted argument early
    and the engine would write nothing, and a path separator would put the
    results where the loader does not look.

    :param basename: the candidate
    :returns: True when it may be used
    :rtype: bool
    """
    if not basename or not isinstance(basename, str):
        return False
    return all(char in _BASENAME_OK for char in basename)


def check_time(t):
    """Validate an analysis time.

    :param t: the time in seconds
    :returns: the time as a float
    :rtype: float
    :raises RAMSESError: if it is not a finite number, or is earlier than
                         :data:`MIN_TIME`
    """
    try:
        value = float(t)
    except (TypeError, ValueError):
        raise RAMSESError('RAMSES: the analysis time must be a number, not %r'
                          % (t,))
    if value != value or value in (float('inf'), float('-inf')):
        raise RAMSESError('RAMSES: the analysis time must be a finite number.')
    if value < MIN_TIME:
        raise RAMSESError('RAMSES: the analysis time must be at least %g s; the '
                          'engine needs at least one step before it can apply '
                          'an event.' % MIN_TIME)
    return value


def settings_text():
    """The solver settings a small-signal run is given, read after the case's own.

    Two records and nothing else. Every record here overrides whatever the case
    set, so anything beyond what the analysis requires would silently change
    the run for no reason. ``$EIG_MAX_STATES`` in particular is deliberately
    absent: it is a memory guard rather than a correctness one, and the
    eigensolve holds nine times the square of the state count in doubles at its
    peak, so raising it on the caller's behalf would trade a clear refusal for
    an out-of-memory kill.

    :returns: the file text, newline terminated
    :rtype: str
    """
    return ('# Written by stepss for the small-signal run, and read after the\n'
            "# case's own data files. The engine keeps the last record of each\n"
            '# kind it reads, so these two are the ones the analysis runs under\n'
            '# whatever the case set. Nothing else here is changed.\n'
            '\n'
            '$SCHEME DE                         ;\n'
            '$OMEGA_REF SYN                     ;\n')


def settings_name(basename):
    """What the generated settings file is called for a given run.

    :param str basename: the run's basename
    :returns: the file name, with no directory part
    :rtype: str
    :raises RAMSESError: if the basename is rejected
    """
    if not valid_basename(basename):
        raise RAMSESError('RAMSES: invalid results basename %r' % (basename,))
    return basename + SETTINGS_SUFFIX


def disturbance_name(basename):
    """What the generated disturbance file is called for a given run.

    :param str basename: the run's basename
    :returns: the file name, with no directory part
    :rtype: str
    :raises RAMSESError: if the basename is rejected
    """
    if not valid_basename(basename):
        raise RAMSESError('RAMSES: invalid results basename %r' % (basename,))
    return basename + DISTURBANCE_SUFFIX


def disturbance_text(t):
    """A disturbance file carrying no events, ending just after *t*.

    A disturbance file is mandatory even when the analysis is injected from
    Python, and this one deliberately carries no events: the engine linearises
    about whatever state the system is in when the analysis fires, so an event
    before then would describe that instant rather than an operating point.
    Running to a later time with no events lets the initialisation settle and
    linearises about the same operating point.

    :param float t: the analysis time in seconds
    :returns: the file text, newline terminated
    :rtype: str
    :raises RAMSESError: if the time is rejected
    """
    stop = check_time(t) + _STOP_MARGIN
    # Fixed point rather than repr, which emits scientific notation for small
    # values: the engine reads these records list-directed and would accept
    # 1.0E-3, but a plain decimal is what every other disturbance file in this
    # project uses and is what a reader comparing the two will expect.
    return ('0.000 CONTINUE SOLVER TR 0.010 0.001 0. ALL\n'
            '%.6f STOP\n' % stop)


def members(basename):
    """Every file a run of *basename* writes, results first.

    This is also exactly what an archive of the run carries besides its
    manifest, and exactly what :func:`clear_previous_run` deletes: the files a
    run writes and the files an archive of it holds are the same files.

    :param str basename: the run's basename
    :returns: the file names, with no directory part
    :rtype: tuple of str
    """
    return tuple(basename + suffix
                 for suffix in RESULT_SUFFIXES + JACOBIAN_SUFFIXES)


def clear_previous_run(directory, basename):
    """Delete what a previous run of *basename* left, and report what would not go.

    Why a run has to start by doing this. The engine writes its results itself
    and reports nothing on the way out about whether it managed to, so the only
    evidence a caller has is whether the modes file is on disk afterwards. A
    run whose initialisation failed writes nothing at all, and in a directory
    already holding an earlier run under the same basename that test passes on
    the earlier run's file. Clearing first is what makes "the modes file is
    there" mean "this run wrote it".

    Nothing else in the directory is touched: the basename exists so that
    several runs can share one directory, and the case's own data files usually
    live there too.

    :param directory: where the run will write, which need not exist
    :type directory: str or pathlib.Path
    :param str basename: the run's basename
    :returns: the names still present, in :func:`members` order; empty when the
              directory is clear
    :rtype: list of str
    """
    stuck = []
    for name in members(basename):
        path = os.path.join(str(directory), name)
        # exists() first, so that "was never there" and "is there and will not
        # go" stay distinguishable: only the second is a reason to refuse a run.
        if not os.path.exists(path):
            continue
        try:
            os.remove(path)
        except OSError:
            stuck.append(name)
    return stuck
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_ssa_run_helpers.py -v`
Expected: every test in the file passes, none skipped, none xfailed. The count is not a requirement: several tests are parametrised, so the number pytest reports is larger than the number of test functions.

- [ ] **Step 5: Commit**

```bash
git add src/stepss/ssa.py tests/test_ssa_run_helpers.py
git commit -m "feat(ssa): run helpers, generated settings and disturbance, clearing"
```

---

### Task 5: `sim.runSsa`, `sim.getStateMatrix` and the analysis counter

**Files:**
- Modify: `src/stepss/simulator.py`
- Create: `tests/test_ssa_engine.py`

**Interfaces:**
- Consumes: `ssa.MIN_TIME`, `ssa.valid_basename`, `ssa.check_time` from Task 4.
- Produces: `sim.runSsa(basename, t=None) -> str`, `sim.getStateMatrix() -> numpy.ndarray`, `sim._ssaGeneration` (int, starts at 0), `sim._noteSsaAnalysis()` which increments it. Task 6 calls `_noteSsaAnalysis` on its disturbance route and reads `_ssaGeneration`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ssa_engine.py`:

```python
"""The two engine entries: run_ssa and get_state_matrix, through stepss.sim."""

import shutil
from pathlib import Path

import numpy as np
import pytest

import stepss
from stepss import ssa
from stepss.globals import RAMSESError

# sim.__del__ warns on every collection by design, and each test here creates a
# simulator, so without this the suite reports one warning per test. The filter
# is narrow on purpose: the point of a pristine test log is that a genuinely
# new warning is visible in it, and only this one notice is silenced.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Simulator with number:UserWarning")

CASE_DIR = Path(__file__).resolve().parents[1] / "examples" / "eigenanalysis"
CASE_FILES = ("lf.dat", "dyn_noPSS.dat", "solveroptions.dat", "nothing.dst",
              "obs.dat")


@pytest.fixture
def kundur(tmp_path, monkeypatch):
    """The Kundur no-PSS case, copied into a fresh directory and paused at t = 0.

    solveroptions.dat already carries $SCHEME DE and $OMEGA_REF SYN, which the
    analysis requires and which ssa.run() supplies for a case that does not.
    """
    for name in CASE_FILES:
        shutil.copy(CASE_DIR / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    case = stepss.cfg()
    case.addData("lf.dat")
    case.addData("dyn_noPSS.dat")
    case.addData("solveroptions.dat")
    case.addDst("nothing.dst")
    case.addObs("obs.dat")
    case.addTrj("out.trj")
    ram = stepss.sim()
    ram.execSim(case, 0.0)
    yield ram, tmp_path


def test_runSsa_writes_the_three_files(kundur):
    ram, work = kundur
    assert ram.runSsa("ssa") == "ssa"
    for suffix in ssa.RESULT_SUFFIXES:
        assert (work / ("ssa" + suffix)).is_file()


def test_runSsa_does_not_write_the_jacobian(kundur):
    """dumpjac and dumpeig are independent flags; run_ssa sets only dumpeig."""
    ram, work = kundur
    ram.runSsa("ssa")
    for suffix in ssa.JACOBIAN_SUFFIXES:
        assert not (work / ("ssa" + suffix)).exists()


@pytest.mark.parametrize("bad", ["it's", "sub/dir", ""])
def test_runSsa_refuses_a_basename_that_would_close_the_record(kundur, bad):
    ram, _ = kundur
    with pytest.raises(RAMSESError, match="basename"):
        ram.runSsa(bad)


def test_runSsa_refuses_a_time_below_the_floor(kundur):
    ram, _ = kundur
    with pytest.raises(RAMSESError, match="0.001"):
        ram.runSsa("ssa", t=0.0)


def test_runSsa_advances_to_a_later_time(kundur):
    ram, work = kundur
    ram.runSsa("ssa", t=0.5)
    assert ram.getSimTime() >= 0.5
    assert (work / "ssa_modes.dat").is_file()


def test_runSsa_refuses_a_time_already_passed(kundur):
    ram, _ = kundur
    ram.contSim(0.5)
    with pytest.raises(RAMSESError, match="already passed"):
        ram.runSsa("ssa", t=0.1)


def test_getStateMatrix_matches_the_modes_file(kundur):
    ram, work = kundur
    ram.runSsa("ssa")
    a_sys = ram.getStateMatrix()
    res = ssa.load(work, "ssa")
    assert a_sys.shape == (res.nstates, res.nstates)
    # The engine's own spectrum, recomputed here from the retained matrix. A
    # transposed or row-major read would give a different set.
    mine = np.sort_complex(np.linalg.eigvals(a_sys))
    theirs = np.sort_complex(res.modes["re"] + 1j * res.modes["im"])
    assert np.allclose(mine, theirs, atol=1e-6, rtol=1e-6)


def test_getStateMatrix_raises_before_any_analysis(kundur):
    ram, _ = kundur
    with pytest.raises(RAMSESError, match="no small-signal"):
        ram.getStateMatrix()


def test_the_analysis_counter_advances_on_every_run(kundur):
    ram, _ = kundur
    assert ram._ssaGeneration == 0
    ram.runSsa("first")
    assert ram._ssaGeneration == 1
    ram.runSsa("second", t=0.5)
    assert ram._ssaGeneration == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ssa_engine.py -v`
Expected: FAIL with `AttributeError: 'sim' object has no attribute 'runSsa'`.

- [ ] **Step 3: Add the counter to `sim.__init__`**

In `src/stepss/simulator.py`, inside `sim.__init__`, after `self._ramsesNum = sim.ramsesCount`, add:

```python
        # How many small-signal analyses this instance has completed. The
        # engine retains one state matrix at a time and get_state_matrix
        # refuses only an order mismatch, so two runs agreeing on nx, which is
        # what re-running one case with changed data produces, would let a
        # stale result hand back the newer matrix. A stepss.ssa.Results
        # compares against this to refuse that instead.
        self._ssaGeneration = 0
```

- [ ] **Step 4: Add the two methods**

In `src/stepss/simulator.py`, after `getJac`, add:

```python
    def _noteSsaAnalysis(self):
        """Record that a small-signal analysis has completed on this instance.

        Called by :meth:`runSsa` and by :func:`stepss.ssa.run`'s disturbance
        route, which are the two ways an analysis can be triggered. Both
        replace the state matrix the engine retains.
        """
        self._ssaGeneration += 1

    def runSsa(self, basename, t=None):
        """Run the small-signal analysis and write its three results files.

        The engine linearises about the operating point the run is currently
        paused at, reduces the Jacobian to the state matrix, solves the dense
        eigenproblem, and writes ``<basename>_modes.dat``, ``_pf.dat`` and
        ``_ms.dat`` in the working directory.

        The C entry takes a basename and nothing else, so *t* is honoured here:
        when it is later than the simulated time already reached, the run is
        advanced to it first, with whatever disturbances the case carries. A
        *t* that has already passed is refused rather than silently answered
        with the current operating point, because the difference is invisible
        in the results.

        The analysis needs ``$SCHEME DE`` and ``$OMEGA_REF SYN``. Under
        ``$SCHEME IN`` the global Jacobian is algebraized and carries the step
        size; under the centre-of-inertia reference frame the COI equations are
        computed by finite differences at export time and never enter the
        assembled Jacobian. The engine refuses both rather than producing a
        plausible, wrong spectrum. :func:`stepss.ssa.run` supplies both itself.

        :param str basename: names the three results files and is written into
                             the engine's own record, so it may contain only
                             letters, digits, dot, underscore and hyphen.
        :param t: when to linearise, in seconds; defaults to
                  :data:`stepss.ssa.MIN_TIME`.
        :type t: float or None
        :returns: *basename*, so the call can be chained.
        :rtype: str
        :raises RAMSESError: if the basename or the time is rejected, or the
                             engine refuses the analysis. The engine's own
                             reason is included, from :meth:`getLastErr`.

        :Example:

        >>> import stepss
        >>> ram = stepss.sim()
        >>> case = stepss.cfg("cmd.txt")
        >>> ram.execSim(case, 0.0)      # initialise and pause at t = 0
        >>> ram.runSsa("ssa")
        'ssa'
        """
        from . import ssa as _ssa

        if t is None:
            t = _ssa.MIN_TIME
        if not _ssa.valid_basename(basename):
            raise RAMSESError(
                'RAMSES: the results basename %r cannot be used. It names the '
                'three results files and is written into the analysis record, '
                'so it may contain only letters, digits, dot, underscore and '
                'hyphen.' % (basename,))
        when = _ssa.check_time(t)
        now = self.getSimTime()
        if when < now - 1e-12:
            raise RAMSESError(
                'RAMSES: the analysis time %g s has already passed; the '
                'simulation is at %g s. The engine linearises about wherever '
                'the run currently sits, so this would answer a different '
                'question silently.' % (when, now))
        if when > now:
            self.contSim(when)

        try:
            retval = self._ramseslib.run_ssa(basename.encode('utf-8'))
        except (AttributeError, KeyError):
            raise RAMSESError('RAMSES: the bundled library exports no run_ssa; '
                              'small-signal analysis needs RAMSES 3.79 or newer.')
        # 112 is ramses() reporting that it paused again after completing the
        # request, exactly as get_Jac's return can also be 112.
        if (retval != 0) and (retval != 112):
            raise RAMSESError('RAMSES: Function runSsa() failed with the flag %i. '
                              'Last message was: %s' % (retval, self.getLastErr()))
        self._noteSsaAnalysis()
        return basename

    def getStateMatrix(self):
        """Return the state matrix of the last small-signal analysis.

        This is the Schur complement the engine formed before solving the
        eigenproblem, retained by the library rather than written to any file.

        The engine keeps one at a time, so read this before starting the next
        analysis.

        :returns: the matrix, of order ``nstates``
        :rtype: numpy.ndarray
        :raises RAMSESError: if no analysis has been run in this process, or
                             the last one refused.

        :Example:

        >>> import stepss
        >>> ram = stepss.sim()
        >>> case = stepss.cfg("cmd.txt")
        >>> ram.execSim(case, 0.0)
        >>> ram.runSsa("ssa")
        'ssa'
        >>> A = ram.getStateMatrix()
        >>> A.shape[0] == A.shape[1]
        True
        """
        nx = ctypes.c_int(0)
        try:
            self._ramseslib.get_state_matrix_size(ctypes.byref(nx))
        except (AttributeError, KeyError):
            raise RAMSESError('RAMSES: the bundled library exports no '
                              'get_state_matrix_size; small-signal analysis '
                              'needs RAMSES 3.79 or newer.')
        order = nx.value
        if order <= 0:
            raise RAMSESError('RAMSES: no small-signal analysis is retained. Run '
                              'one with runSsa() first; a refused analysis '
                              'retains nothing.')
        buffer = (ctypes.c_double * (order * order))()
        retval = self._ramseslib.get_state_matrix(order, buffer)
        if retval != 0:
            raise RAMSESError('RAMSES: Function getStateMatrix() failed with the '
                              'flag %i. Last message was: %s'
                              % (retval, self.getLastErr()))
        # Column-major: entry (i, j) of the nx by nx matrix sits at
        # a_sys[(j-1)*nx + (i-1)], which is what order='F' reconstructs. The
        # copy detaches the array from the ctypes buffer, which is freed with
        # this call's frame.
        return np.reshape(np.frombuffer(buffer, dtype=np.float64,
                                        count=order * order),
                          (order, order), order='F').copy()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_ssa_engine.py -v`
Expected: every test in the file passes, none skipped, none xfailed. The count is not a requirement: several tests are parametrised, so the number pytest reports is larger than the number of test functions.

- [ ] **Step 6: Commit**

```bash
git add src/stepss/simulator.py tests/test_ssa_engine.py
git commit -m "feat(ssa): sim.runSsa and sim.getStateMatrix over the engine entries"
```

---

### Task 6: The `ssa.run` driver and `Results.state_matrix`

**Files:**
- Modify: `src/stepss/ssa.py`
- Create: `tests/test_ssa_driver.py`

**Interfaces:**
- Consumes: everything from Tasks 1 to 5.
- Produces: `ssa.run(case, basename='ssa', t=None, workdir=None, jacobian=False, ram=None, keep_open=False) -> Results`, and `Results.state_matrix`, a property.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ssa_driver.py`:

```python
"""The run driver: settings override, generated disturbance, clearing, loading."""

import shutil
from pathlib import Path

import pytest

import stepss
from stepss import ssa
from stepss.globals import RAMSESError

# sim.__del__ warns on every collection by design, and ssa.run() creates a
# simulator per call, so without this the suite reports one warning per test.
# The filter is narrow on purpose: the point of a pristine test log is that a
# genuinely new warning is visible in it, and only this one notice is silenced.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Simulator with number:UserWarning")

CASE_DIR = Path(__file__).resolve().parents[1] / "examples" / "eigenanalysis"


def kundur_case(work, dynfile):
    """Copy the Kundur case into *work* and return a cfg naming it by absolute path."""
    for name in ("lf.dat", dynfile, "solveroptions.dat", "nothing.dst", "obs.dat"):
        shutil.copy(CASE_DIR / name, work / name)
    case = stepss.cfg()
    case.addData(str(work / "lf.dat"))
    case.addData(str(work / dynfile))
    case.addData(str(work / "solveroptions.dat"))
    case.addDst(str(work / "nothing.dst"))
    case.addObs(str(work / "obs.dat"))
    case.addTrj("out.trj")
    return case


def interarea(res):
    band = [m for m in res.electromechanical().rows if 0.4 < m["freq"] < 0.9]
    assert len(band) == 1
    return band[0]


def test_run_reproduces_kundur_example_12_6(tmp_path):
    """Without the stabilisers the inter-area mode is unstable; with them it is not.

    The numbers are the ones examples/eigenanalysis/README.md records.
    """
    modes = {}
    for tag, dynfile in (("nopss", "dyn_noPSS.dat"), ("pss", "dyn.dat")):
        work = tmp_path / tag
        work.mkdir()
        modes[tag] = interarea(ssa.run(kundur_case(work, dynfile),
                                       basename="ssa", workdir=work))

    assert modes["nopss"]["freq"] == pytest.approx(0.625, abs=5e-3)
    assert modes["nopss"]["zeta"] == pytest.approx(-0.0233, abs=5e-3)
    assert modes["pss"]["freq"] == pytest.approx(0.624, abs=5e-3)
    assert modes["pss"]["zeta"] == pytest.approx(0.1087, abs=5e-3)


def test_run_does_not_mutate_the_callers_case(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    before = list(case.getData())
    ssa.run(case, basename="ssa", workdir=tmp_path)
    assert list(case.getData()) == before


def test_run_writes_the_settings_override_and_leaves_the_case_alone(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    original = (tmp_path / "solveroptions.dat").read_text()
    ssa.run(case, basename="ssa", workdir=tmp_path)
    assert (tmp_path / ssa.settings_name("ssa")).is_file()
    assert (tmp_path / "solveroptions.dat").read_text() == original


def test_run_clears_a_previous_run_before_starting(tmp_path):
    """A run that produces nothing must not read the previous run's spectrum."""
    ssa.run(kundur_case(tmp_path, "dyn_noPSS.dat"), basename="ssa", workdir=tmp_path)
    assert (tmp_path / "ssa_modes.dat").is_file()

    broken = kundur_case(tmp_path, "dyn_noPSS.dat")
    broken.clearData()
    broken.addData(str(tmp_path / "lf.dat"))  # no dynamic data to linearise
    with pytest.raises(RAMSESError):
        ssa.run(broken, basename="ssa", workdir=tmp_path)
    assert not (tmp_path / "ssa_modes.dat").exists(), (
        "the previous run's file survived and would have been read as this run's")


def test_run_refuses_a_basename_colliding_with_a_data_file(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    collision = tmp_path / ssa.settings_name("ssa")
    collision.write_text("$SCHEME DE                         ;\n")
    case.addData(str(collision))
    with pytest.raises(RAMSESError, match="loaded data file"):
        ssa.run(case, basename="ssa", workdir=tmp_path)
    assert collision.read_text() == "$SCHEME DE                         ;\n"


def test_run_generates_a_disturbance_file_when_the_case_has_none(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    case.clearDst()
    ssa.run(case, basename="ssa", workdir=tmp_path)
    assert (tmp_path / ssa.disturbance_name("ssa")).is_file()
    assert (tmp_path / "ssa_modes.dat").is_file()


def test_run_with_jacobian_writes_all_seven_members(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    ssa.run(case, basename="ssa", workdir=tmp_path, jacobian=True)
    for name in ssa.members("ssa"):
        assert (tmp_path / name).is_file(), name


def test_run_without_jacobian_writes_only_the_results(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    ssa.run(case, basename="ssa", workdir=tmp_path)
    for suffix in ssa.JACOBIAN_SUFFIXES:
        assert not (tmp_path / ("ssa" + suffix)).exists()


def test_run_makes_the_working_directory_if_it_is_missing(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    target = tmp_path / "fresh"
    res = ssa.run(case, basename="ssa", workdir=target)
    assert (target / "ssa_modes.dat").is_file()
    assert Path(res.directory) == target


def test_run_restores_the_working_directory(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    import os
    before = os.getcwd()
    ssa.run(case, basename="ssa", workdir=tmp_path / "elsewhere")
    assert os.getcwd() == before


def test_state_matrix_is_available_from_a_live_run(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    res = ssa.run(case, basename="ssa", workdir=tmp_path)
    assert res.state_matrix.shape == (res.nstates, res.nstates)


def test_state_matrix_refuses_after_a_later_analysis(tmp_path, monkeypatch):
    """The engine retains one at a time and checks only the order."""
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    # The second analysis is triggered directly rather than through ssa.run(),
    # so nothing changes the working directory for it and the engine would
    # write its three files wherever pytest was started, which is the
    # repository root. This is the only test that reaches the engine outside
    # ssa.run(), and so the only one that needs this.
    monkeypatch.chdir(tmp_path)
    ram = stepss.sim()
    first = ssa.run(case, basename="one", workdir=tmp_path, ram=ram, keep_open=True)
    assert first.state_matrix.shape[0] == first.nstates
    ram.runSsa("two", t=0.5)
    with pytest.raises(RAMSESError, match="replaced"):
        first.state_matrix
    ram.endSim()


def test_state_matrix_is_absent_from_results_read_from_disk(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    ssa.run(case, basename="ssa", workdir=tmp_path)
    reloaded = ssa.load(tmp_path, "ssa")
    with pytest.raises(RAMSESError, match="live run"):
        reloaded.state_matrix
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ssa_driver.py -v`
Expected: FAIL with `AttributeError: module 'stepss.ssa' has no attribute 'run'`.

- [ ] **Step 3: Add the `state_matrix` property**

In `src/stepss/ssa.py`, add to `Results`, after `mode_shape`:

```python
    @property
    def state_matrix(self):
        """The state matrix the engine reduced for this run.

        Lazy rather than captured, because ``nstates`` can reach the engine's
        ceiling of 5000, at which the dense matrix is 200 MB, and most runs
        never read it.

        The engine retains one matrix at a time and ``get_state_matrix``
        refuses only an order mismatch, so a later analysis of a case with the
        same state count would otherwise be handed back silently. This checks
        the simulator's analysis counter instead.

        :rtype: numpy.ndarray
        :raises RAMSESError: if this run was read from disk rather than made
                             here, or a later analysis has replaced the matrix
        """
        if self._ram is None:
            raise RAMSESError(
                'RAMSES: the state matrix lives in the engine and is in none of '
                'the results files, so it is available on a live run made with '
                'ssa.run() only.')
        if self._ram._ssaGeneration != self._generation:
            raise RAMSESError(
                'RAMSES: a later analysis has replaced the retained state '
                'matrix; this run was analysis %d and the engine now holds %d. '
                'Read the state matrix before starting the next analysis.'
                % (self._generation, self._ram._ssaGeneration))
        return self._ram.getStateMatrix()
```

- [ ] **Step 4: Write the driver**

Append to `src/stepss/ssa.py`:

```python
# Which of a case's file lists name inputs. These are resolved to absolute
# paths before the working directory changes, so that a case built with
# relative names keeps working. The output lists are deliberately left alone,
# so that the trajectory and the traces land in the run's own directory.
_INPUT_LISTS = ('_dataset', '_dstset', '_obs', '_init')


def _absolutise(case):
    """A copy of *case* whose input paths are absolute.

    The lists are rewritten directly rather than through the ``add`` methods,
    because those resolve against the current directory and validate on the
    way in, and this runs before the directory changes.

    :param stepss.cases.cfg case: the caller's case, which is not modified
    :returns: the copy
    :rtype: stepss.cases.cfg
    """
    copy = deepcopy(case)
    for name in _INPUT_LISTS:
        entries = getattr(copy, name, None)
        if entries:
            entries[:] = [os.path.abspath(entry) for entry in entries]
    return copy


def _same_file(left, right):
    """Whether two paths name the same file, whether or not it exists.

    :param str left: one path
    :param str right: the other
    :rtype: bool
    """
    try:
        if os.path.exists(left) and os.path.exists(right):
            return os.path.samefile(left, right)
    except OSError:
        pass
    return (os.path.normcase(os.path.abspath(left))
            == os.path.normcase(os.path.abspath(right)))


def run(case, basename='ssa', t=None, workdir=None, jacobian=False,
        ram=None, keep_open=False):
    """Run one small-signal analysis and return its results.

    The case is copied, never modified: it stays usable for an ordinary
    time-domain run afterwards. The copy is given one extra data file carrying
    ``$SCHEME DE`` and ``$OMEGA_REF SYN``, read last so that it wins whatever
    the case set, because the engine refuses the analysis under either of the
    values a case that says nothing about them lands on.

    Anything already on disk under *basename* is deleted before the run starts,
    since the only evidence an analysis produced results is that its modes file
    is there afterwards.

    :param stepss.cases.cfg case: the case to analyse
    :param str basename: names the three results files
    :param t: when to linearise, in seconds; defaults to :data:`MIN_TIME`
    :type t: float or None
    :param workdir: where to run and where the results land; the current
                    directory when None. It is created if it does not exist,
                    and the previous working directory is restored afterwards.
    :type workdir: str or pathlib.Path or None
    :param bool jacobian: also write the four Jacobian tables, at the instant
                          of the reduction. This uses paired disturbance
                          records rather than the direct entry, because
                          ``dumpjac`` and ``dumpeig`` are independent flags and
                          the two direct entries each advance the clock by a
                          millisecond, so calling them in turn would dump a
                          Jacobian taken after the reduction rather than at it.
    :param ram: an existing simulator to run in, or None to make one
    :type ram: stepss.simulator.sim or None
    :param bool keep_open: leave the simulation paused instead of finalising
                           it. A paused simulation is not finished, and loading
                           another case without finalising silently resumes it,
                           so this is for a caller who means to go on
                           interrogating this run.
    :returns: the run
    :rtype: Results

    .. note:: When the case carries a disturbance file of its own, *t* must
              fall before that file's STOP record, because a run that has
              already stopped cannot be advanced to *t*. That cannot be checked
              here without parsing the caller's file, so it is stated rather
              than enforced; the failure is loud, since :meth:`runSsa` refuses
              a *t* earlier than the simulated time already reached. The
              generated file used when the case has none stops just after *t*.
    :raises RAMSESError: if the basename or time is rejected, the generated
                         settings file would overwrite one of the case's own
                         data files, a previous run cannot be cleared, or the
                         analysis produced no modes file

    :Example:

    >>> import stepss
    >>> from stepss import ssa
    >>> case = stepss.cfg('cmd.txt')
    >>> res = ssa.run(case, basename='ssa', workdir='run1')
    >>> res.electromechanical().table()
    """
    if not valid_basename(basename):
        raise RAMSESError(
            'RAMSES: the results basename %r cannot be used. It names the three '
            'results files and is written into the analysis record, so it may '
            'contain only letters, digits, dot, underscore and hyphen.'
            % (basename,))
    when = check_time(MIN_TIME if t is None else t)

    prepared = _absolutise(case)
    here = os.getcwd()
    target = here if workdir is None else os.path.abspath(str(workdir))
    if not os.path.isdir(target):
        os.makedirs(target)

    settings_path = os.path.join(target, settings_name(basename))
    # Refused rather than written: a loaded data file of this name is the
    # caller's, and writing over it would destroy it silently, the run
    # continuing on the two records that replaced their case.
    for data_file in prepared.getData():
        if _same_file(data_file, settings_path):
            raise RAMSESError(
                'RAMSES: the run needs to write %s, which is one of the loaded '
                'data files. Choose a different results basename, or move that '
                'file, so the analysis does not overwrite it.'
                % os.path.basename(settings_path))

    owns_sim = ram is None
    os.chdir(target)
    try:
        with open(settings_name(basename), 'w') as handle:
            handle.write(settings_text())
        prepared.addData(os.path.abspath(settings_name(basename)))

        if not prepared.getDst():
            with open(disturbance_name(basename), 'w') as handle:
                handle.write(disturbance_text(when))
            prepared.addDst(os.path.abspath(disturbance_name(basename)))

        # Last, after every refusal above, because it destroys the previous run
        # under this basename: a run that never starts must leave that run
        # intact.
        stuck = clear_previous_run(target, basename)
        if stuck:
            raise RAMSESError(
                'RAMSES: a previous "%s" run is still in %s and could not be '
                'removed: %s. It would be read as this run\'s, so the analysis '
                'was not started.' % (basename, target, ', '.join(stuck)))

        if ram is None:
            from .simulator import sim
            ram = sim()
        ram.execSim(prepared, 0.0)
        if jacobian:
            # JAC and EIG fire at the same t and the engine acts on them in
            # that order within one step (simul_decomp: dump_jacobian then
            # dump_eig), so the dumped Jacobian is necessarily the one the
            # analysis reduced rather than one taken a moment later.
            if when > ram.getSimTime():
                ram.contSim(when)
            ram.addDisturb(when, "JAC '%s'" % basename)
            ram.addDisturb(when, "EIG '%s'" % basename)
            ram.contSim(when + _STOP_MARGIN)
            ram._noteSsaAnalysis()
        else:
            ram.runSsa(basename, when)
        generation = ram._ssaGeneration

        modes_path = os.path.join(target, basename + RESULT_SUFFIXES[0])
        if not os.path.isfile(modes_path):
            raise RAMSESError(
                'RAMSES: no results were produced. The run was given $SCHEME DE '
                'and $OMEGA_REF SYN, so the reason is elsewhere: usually a '
                'system with more states than $EIG_MAX_STATES allows, or one '
                'with no differential states at all. The engine says which: %s'
                % ram.getLastErr())

        modes, header = _read_modes(_read_text(modes_path))
        return Results(modes, header,
                       _read_pf(_optional_text(target, basename, '_pf.dat')),
                       _read_ms(_optional_text(target, basename, '_ms.dat')),
                       target, basename, ram=ram, generation=generation)
    finally:
        if ram is not None and owns_sim and not keep_open:
            try:
                ram.endSim()
            except RAMSESError:
                # A run that already stopped, or one that failed before it
                # started, has nothing to finalise. The failure worth reporting
                # is the one on the way out of the try block, not this one.
                pass
        os.chdir(here)
```

Add to the imports at the top of the module, after `from collections import namedtuple`:

```python
from copy import deepcopy
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_ssa_driver.py -v`
Expected: every test in the file passes, none skipped, none xfailed. The count is not a requirement: several tests are parametrised, so the number pytest reports is larger than the number of test functions.

Run: `pytest tests/ -v -k "not nordic"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stepss/ssa.py tests/test_ssa_driver.py
git commit -m "feat(ssa): the run driver, with settings override and stale-output clearing"
```

---

### Task 7: The plots

**Files:**
- Modify: `src/stepss/ssa.py`
- Create: `tests/test_ssa_plots.py`

**Interfaces:**
- Consumes: `ssa.ModeView`, `ssa.Results`, `ssa.DEFAULT_DAMPING_ZETA`, `ssa.DEFAULT_PF_FLOOR`, `Results._index_of`, `Results.mode_shape`, `Results.participation`.
- Produces: `ModeView.splane(ax=None, zeta=0.05, annotate=True, interactive=None) -> matplotlib.axes.Axes`, `Results.splane(**kwargs)`, `Results.mode_shape_plot(mode, ax=None, allow_degenerate=False) -> Axes`, `Results.participation_plot(mode, floor=0.05, ax=None, allow_degenerate=False) -> Axes`. Each axes carries `_stepss_splane_interactive`, a bool, for the s-plane.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ssa_plots.py`:

```python
"""The three plots, under the agg backend."""

import shutil
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("agg")
import matplotlib.pyplot as plt  # noqa: E402

from stepss import ssa  # noqa: E402
from stepss.globals import RAMSESError  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "data" / "ssa"


@pytest.fixture
def res(tmp_path):
    for suffix in ("modes", "pf", "ms"):
        shutil.copy(FIXTURES / ("kundur_nopss_%s.dat" % suffix),
                    tmp_path / ("ssa_%s.dat" % suffix))
    return ssa.load(tmp_path, "ssa")


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close("all")


def interarea(res):
    return [m for m in res.electromechanical().rows if 0.4 < m["freq"] < 0.9][0]


def test_splane_returns_an_axes_and_keeps_the_stability_boundary_in_view(res):
    ax = res.electromechanical().splane()
    left, right = ax.get_xlim()
    assert left <= 0.0 <= right, "the boundary the plot is read against must be in view"


def test_splane_draws_into_a_given_axes(res):
    _, axes = plt.subplots(1, 2)
    res.electromechanical().splane(ax=axes[0])
    res.dominant(-1.0).splane(ax=axes[1])
    assert axes[0].collections and axes[1].collections


def test_splane_is_static_on_a_file_only_backend(res):
    """agg has no window to update, so interaction is skipped rather than attempted."""
    ax = res.electromechanical().splane()
    assert ax._stepss_splane_interactive is False


def test_splane_honours_an_explicit_interactive_false(res):
    ax = res.electromechanical().splane(interactive=False)
    assert ax._stepss_splane_interactive is False


def test_splane_of_an_empty_selection_still_draws(res):
    assert res.dominant(1e6).splane() is not None


def test_splane_of_the_whole_spectrum_draws(res):
    assert res.splane(annotate=False) is not None


def test_mode_shape_plot_is_polar_and_labels_every_machine(res):
    ax = res.mode_shape_plot(interarea(res))
    assert ax.name == "polar"
    labels = {text.get_text().strip() for text in ax.texts}
    assert {"G1", "G2", "G3", "G4"} <= labels


def test_mode_shape_plot_refuses_a_degenerate_mode(res):
    degenerate = res.modes[~res.modes["simple"]][0]
    with pytest.raises(RAMSESError, match="degenerate"):
        res.mode_shape_plot(degenerate)


def test_participation_plot_returns_an_axes_with_bars(res):
    assert res.participation_plot(interarea(res)).patches
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ssa_plots.py -v`
Expected: FAIL with `AttributeError: 'ModeView' object has no attribute 'splane'`.

- [ ] **Step 3: Add `splane` to `ModeView`**

Append to the `ModeView` class in `src/stepss/ssa.py`:

```python
    def splane(self, ax=None, zeta=DEFAULT_DAMPING_ZETA, annotate=True,
               interactive=None):
        """Draw the modes on the complex plane.

        The vertical axis is oscillation frequency and the horizontal axis the
        decay rate. Everything strictly left of the crimson line at ``Re = 0``
        is stable. The dashed ray marks constant damping ratio, the usual
        planning criterion being 0.05.

        One dashed ray rather than two, because a ray of constant zeta leaves
        the origin at ``asin(zeta)`` from the imaginary axis, so 0.05 and 0.10
        sit 2.87 and 5.74 degrees off vertical and arrive as a single smudge
        beside the boundary. The one that remains is adjustable, which is the
        more useful of the two answers.

        The window is fitted to the modes on screen rather than fixed, so this
        works on any system and so that filtering actually zooms. The fitted
        window always contains ``Re = 0``, because a view that has scrolled off
        the boundary shows damping with nothing to measure it from.

        :param ax: the axes to draw into, or None to make a figure
        :type ax: matplotlib.axes.Axes or None
        :param float zeta: damping ratio of the dashed ray; no ray is drawn
                           when it is outside (0, 1)
        :param bool annotate: label each mode with its frequency
        :param interactive: enable click-to-select and drag-to-zoom; None means
                            whenever the backend can update a window
        :type interactive: bool or None
        :returns: the axes drawn into
        :rtype: matplotlib.axes.Axes
        """
        import matplotlib.pyplot as plt

        from .live import _canDraw

        if ax is None:
            _, ax = plt.subplots(figsize=(6, 5))

        re = self.rows['re']
        im = self.rows['im']
        ax.axvline(0.0, color='crimson', lw=1.5, zorder=1)

        lo_re, hi_re, lo_im, hi_im = _fit_window(re, im)
        if 0.0 < zeta < 1.0:
            # The ray reaches the top of the window, or the far left of it,
            # whichever is further, and is then clipped to the axes.
            root = (1.0 - zeta ** 2) ** 0.5
            reach = max(hi_im, abs(lo_re) * root / zeta)
            ax.plot([0.0, -reach * zeta / root], [0.0, reach], '--',
                    color='0.6', lw=1, zorder=1)

        unstable = self.rows['zeta'] < 0.0
        ax.scatter(re, im, s=90, facecolors='none',
                   edgecolors=np.where(unstable, 'crimson', 'tab:blue'),
                   linewidths=np.where(unstable, 1.8, 1.2), zorder=3, picker=6)
        if annotate:
            for row in self.rows:
                ax.annotate(' %.2f Hz' % row['freq'], (row['re'], row['im']),
                            fontsize=8)
        if unstable.any():
            # An empty scatter carrying the marker itself, so the key and the
            # plot cannot come to disagree about what an unstable mode is.
            ax.scatter([], [], s=90, facecolors='none', edgecolors='crimson',
                       linewidths=1.8, label='unstable')
            ax.legend(loc='lower left')

        ax.set_xlim(lo_re, hi_re)
        ax.set_ylim(lo_im, hi_im)
        ax.set_xlabel(r'Re$(\lambda)$  [1/s]')
        ax.set_ylabel(r'Im$(\lambda)$  [rad/s]')
        ax.grid(alpha=0.3)

        live = _canDraw() if interactive is None else bool(interactive)
        ax._stepss_splane_interactive = live
        if live:
            _attach_splane_interaction(ax, self, (lo_re, hi_re, lo_im, hi_im))
        elif interactive is None:
            print('s-plane drawn without interaction: this backend has no window '
                  'to update. Use %matplotlib widget for click-to-select and '
                  'drag-to-zoom.')
        return ax
```

- [ ] **Step 4: Add the three plot methods to `Results`**

Append to the `Results` class, after `summary`:

```python
    def splane(self, **kwargs):
        """Draw every mode. See :meth:`ModeView.splane`.

        :rtype: matplotlib.axes.Axes
        """
        return self.view().splane(**kwargs)

    def mode_shape_plot(self, mode, ax=None, allow_degenerate=False):
        """Draw one mode's rotor-speed phasors on a polar dial.

        For an inter-area mode the expected picture is two groups roughly 180
        degrees apart: the areas swinging against each other.

        :param mode: a mode index, or a row of :attr:`modes`
        :param ax: a polar axes to draw into, or None to make one
        :type ax: matplotlib.axes.Axes or None
        :param bool allow_degenerate: draw a degenerate mode anyway. The
                                      picture would be basis-dependent and
                                      would look exactly as authoritative,
                                      which is why this is off by default.
        :returns: the axes drawn into
        :rtype: matplotlib.axes.Axes
        :raises RAMSESError: if the mode is degenerate and not allowed
        """
        import matplotlib.pyplot as plt

        entries = self.mode_shape(mode, allow_degenerate)
        index = self._index_of(mode)
        if ax is None:
            _, ax = plt.subplots(figsize=(5, 5),
                                 subplot_kw={'projection': 'polar'})
        for entry in entries:
            theta = np.deg2rad(entry.angle_deg)
            ax.annotate('', xy=(theta, entry.magnitude), xytext=(0, 0),
                        arrowprops=dict(arrowstyle='->', lw=2))
            ax.text(theta, entry.magnitude * 1.12, entry.device.strip(),
                    ha='center', va='center')
        ax.set_rmax(1.3)
        ax.set_title('Mode %d shape (rotor speeds)' % index, pad=18)
        return ax

    def participation_plot(self, mode, floor=DEFAULT_PF_FLOOR, ax=None,
                           allow_degenerate=False):
        """Draw one mode's participation factors as a horizontal bar chart.

        :param mode: a mode index, or a row of :attr:`modes`
        :param float floor: smallest participation factor to draw
        :param ax: the axes to draw into, or None to make a figure
        :type ax: matplotlib.axes.Axes or None
        :param bool allow_degenerate: draw a degenerate mode anyway
        :returns: the axes drawn into
        :rtype: matplotlib.axes.Axes
        :raises RAMSESError: if the mode is degenerate and not allowed
        """
        import matplotlib.pyplot as plt

        rows = self.participation(mode, floor, allow_degenerate)
        index = self._index_of(mode)
        if ax is None:
            _, ax = plt.subplots(figsize=(6, max(2.0, 0.3 * len(rows) + 1.0)))
        positions = np.arange(len(rows))
        ax.barh(positions, [row.pf for row in rows], color='tab:blue')
        ax.set_yticks(positions)
        ax.set_yticklabels(['%s %s' % (row.device.strip(), row.variable)
                            for row in rows])
        ax.invert_yaxis()
        ax.set_xlabel('participation factor')
        ax.set_title('Mode %d, entries at or above %g' % (index, floor))
        return ax
```

- [ ] **Step 5: Add the two plot helpers**

Append at module level in `src/stepss/ssa.py`:

```python
#: Margin around the fitted extent, as a fraction of it.
_FIT_PAD = 0.06

#: Smallest margin in data units, which is what keeps a window around a single
#: mode, or around a set sharing one real part, from collapsing to zero width.
#: A zero span maps every coordinate to the same pixel.
_MIN_PAD = 0.5


def _fit_window(re, im):
    """The axis window that holds these modes, with a margin and ``Re = 0``.

    :param numpy.ndarray re: real parts
    :param numpy.ndarray im: imaginary parts
    :returns: ``(lo_re, hi_re, lo_im, hi_im)``
    :rtype: tuple
    """
    if len(re) == 0:
        return -3.0, 0.5, 0.0, 9.0
    lo_re, hi_re = min(float(re.min()), 0.0), max(float(re.max()), 0.0)
    lo_im, hi_im = min(float(im.min()), 0.0), max(float(im.max()), 0.0)
    pad_re = max((hi_re - lo_re) * _FIT_PAD, _MIN_PAD)
    pad_im = max((hi_im - lo_im) * _FIT_PAD, _MIN_PAD)
    return lo_re - pad_re, hi_re + pad_re, lo_im - pad_im, hi_im + pad_im


def _attach_splane_interaction(ax, view, home):
    """Wire click-to-select and drag-to-zoom onto an s-plane.

    Both use matplotlib's own event machinery, so no other library is needed.
    The selector is stashed on the axes because matplotlib holds only a weak
    reference to a widget and would otherwise garbage-collect it, leaving a
    plot that looks interactive and is not.

    :param matplotlib.axes.Axes ax: the axes drawn by :meth:`ModeView.splane`
    :param ModeView view: the modes it is showing
    :param tuple home: the fitted window, restored on a double click
    """
    from matplotlib.widgets import RectangleSelector

    def on_pick(event):
        if event.artist.axes is not ax or not len(event.ind):
            return
        row = view.rows[event.ind[0]]
        print('mode %d: f = %.4f Hz, zeta = %+.4f, lambda = %+.4f %+.4fj, %s'
              % (row['index'], row['freq'], row['zeta'], row['re'], row['im'],
                 'simple' if row['simple'] else 'DEGENERATE'))

    def on_zoom(press, release):
        if press.xdata is None or release.xdata is None:
            return
        ax.set_xlim(min(press.xdata, release.xdata),
                    max(press.xdata, release.xdata))
        ax.set_ylim(min(press.ydata, release.ydata),
                    max(press.ydata, release.ydata))
        ax.figure.canvas.draw_idle()

    def on_click(event):
        if event.inaxes is ax and event.dblclick:
            ax.set_xlim(home[0], home[1])
            ax.set_ylim(home[2], home[3])
            ax.figure.canvas.draw_idle()

    ax._stepss_splane_selector = RectangleSelector(
        ax, on_zoom, useblit=False, button=[1], interactive=False)
    ax.figure.canvas.mpl_connect('pick_event', on_pick)
    ax.figure.canvas.mpl_connect('button_press_event', on_click)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_ssa_plots.py -v`
Expected: every test in the file passes, none skipped, none xfailed. The count is not a requirement: several tests are parametrised, so the number pytest reports is larger than the number of test functions.

- [ ] **Step 7: Check the interaction by hand**

Automated tests cannot exercise a window. In a notebook:

```python
%matplotlib widget
from stepss import ssa
res = ssa.load("run_nopss", "ssa")
res.electromechanical().splane()
```

Expected: clicking a circle prints that mode's line, dragging a rectangle zooms into it, and a double click restores the fitted window.

- [ ] **Step 8: Commit**

```bash
git add src/stepss/ssa.py tests/test_ssa_plots.py
git commit -m "feat(ssa): s-plane, mode-shape dial and participation plots"
```

---

### Task 8: Archive reading and writing

**Files:**
- Modify: `src/stepss/ssa.py`
- Create: `tests/test_ssa_archive.py`

**Interfaces:**
- Consumes: `ssa.members`, `ssa.valid_basename`, `ssa.load`, `ssa.Results`, `ssa._read_text`.
- Produces: `ssa.ARCHIVE_FORMAT_VERSION == 1`, `ssa.MANIFEST_NAME == 'stepss-ssa.txt'`, `ssa.Manifest`, a namedtuple subclass with fields `basename`, `engine_version`, `time`, `saved_by` and methods `text()` and `parse(text)`. `ssa.save(results, path, saved_by=None) -> list of str` returning the members that were absent, `Results.save(path, saved_by=None)` delegating to it, and `ssa.load_archive(path, into=None) -> (Results, Manifest)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ssa_archive.py`:

```python
"""The .ssa archive, which both interfaces read and write."""

import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

from stepss import ssa
from stepss.globals import RAMSESError

FIXTURES = Path(__file__).resolve().parent / "data" / "ssa"


@pytest.fixture
def res(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    for suffix in ("modes", "pf", "ms"):
        shutil.copy(FIXTURES / ("kundur_nopss_%s.dat" % suffix),
                    run / ("ssa_%s.dat" % suffix))
    return ssa.load(run, "ssa")


@pytest.mark.parametrize("name", ["run.zip", "run.tar.gz"])
def test_round_trip(res, tmp_path, name):
    target = tmp_path / name
    absent = ssa.save(res, target)
    assert set(absent) == set(ssa.members("ssa")[3:]), "no Jacobian was written"

    loaded, manifest = ssa.load_archive(target)
    assert manifest.basename == "ssa"
    assert manifest.saved_by.startswith("stepss ")
    assert len(loaded.modes) == len(res.modes)
    assert loaded.participation(res.electromechanical().rows[0])


def test_results_save_is_the_same_call(res, tmp_path):
    target = tmp_path / "run.zip"
    res.save(target)
    assert zipfile.is_zipfile(target)


def test_zip_puts_the_manifest_first_under_a_directory_named_for_the_run(res, tmp_path):
    target = tmp_path / "run.zip"
    ssa.save(res, target)
    with zipfile.ZipFile(target) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
    assert names[0] == "ssa/" + ssa.MANIFEST_NAME
    assert all(n.startswith("ssa/") for n in names)


def test_save_refuses_a_run_whose_modes_file_is_gone(res, tmp_path):
    Path(res.directory, "ssa_modes.dat").unlink()
    with pytest.raises(RAMSESError, match="no analysis to archive"):
        ssa.save(res, tmp_path / "run.zip")


def test_load_archive_refuses_a_file_that_is_neither_format(tmp_path):
    plain = tmp_path / "run.zip"
    plain.write_text("not an archive")
    with pytest.raises(RAMSESError, match="neither a zip nor a gzipped tar"):
        ssa.load_archive(plain)


def test_load_archive_refuses_an_archive_with_no_manifest(tmp_path):
    target = tmp_path / "run.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("ssa/ssa_modes.dat",
                         (FIXTURES / "kundur_nopss_modes.dat").read_text())
    with pytest.raises(RAMSESError, match=ssa.MANIFEST_NAME):
        ssa.load_archive(target)


def test_load_archive_refuses_a_newer_format_version(tmp_path):
    target = tmp_path / "run.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("ssa/" + ssa.MANIFEST_NAME,
                         "# STEPSS small-signal archive v2\nbasename ssa\n")
        archive.writestr("ssa/ssa_modes.dat",
                         (FIXTURES / "kundur_nopss_modes.dat").read_text())
    with pytest.raises(RAMSESError, match="archive format v2"):
        ssa.load_archive(target)


def test_load_archive_refuses_an_unusable_basename(tmp_path):
    target = tmp_path / "run.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("ssa/" + ssa.MANIFEST_NAME,
                         "# STEPSS small-signal archive v1\nbasename ../evil\n")
    with pytest.raises(RAMSESError, match="unusable basename"):
        ssa.load_archive(target)


def test_load_archive_refuses_an_entry_that_escapes_the_destination(tmp_path):
    payload = tmp_path / "payload"
    payload.write_text("x")
    target = tmp_path / "run.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(payload, arcname="../escaped.dat")
    with pytest.raises(RAMSESError, match="outside"):
        ssa.load_archive(target)


def test_manifest_omits_absent_keys():
    text = ssa.Manifest("ssa", None, None, None).text()
    assert "basename ssa" in text
    assert "engine_version" not in text
    assert "\nt " not in text


def test_manifest_round_trips_every_key():
    original = ssa.Manifest("ssa", 3.81, 0.001, "stepss 3.81")
    back = ssa.Manifest.parse(original.text())
    assert back.basename == "ssa"
    assert back.engine_version == pytest.approx(3.81)
    assert back.time == pytest.approx(0.001)
    assert back.saved_by == "stepss 3.81"


def test_manifest_ignores_a_key_it_does_not_know():
    """A field added on one side is ignored on the other; that is the format's rule."""
    text = ("# STEPSS small-signal archive v1\nbasename ssa\n"
            "real_limit -1.0\nsaved_by STEPSS 3.74\n")
    assert ssa.Manifest.parse(text).saved_by == "STEPSS 3.74"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ssa_archive.py -v`
Expected: FAIL with `AttributeError: module 'stepss.ssa' has no attribute 'save'`.

- [ ] **Step 3: Write the archive support**

Append to `src/stepss/ssa.py`:

```python
#: The archive format this module writes, and the newest it reads.
ARCHIVE_FORMAT_VERSION = 1

#: Names the manifest inside an archive.
MANIFEST_NAME = 'stepss-ssa.txt'

_MANIFEST_MAGIC = '# STEPSS small-signal archive v'


class Manifest(namedtuple('Manifest', 'basename engine_version time saved_by')):
    """What an archive records about the run inside it.

    Every field but the basename may be None, and None means "not recorded"
    rather than zero. There are no threshold fields: the analysis record has no
    thresholds to record, and the one floor the engine applies is written into
    the modes file itself as ``pf_floor``.
    """

    __slots__ = ()

    def text(self):
        """The manifest file's contents.

        A key per line, absent keys omitted rather than written as zero, read
        back by name so that a later format can add one without breaking this.
        The prose at the top is for whoever opens the archive in a file manager
        and wants to know what they have without installing anything.

        :returns: the file text, newline terminated
        :rtype: str
        """
        lines = [
            _MANIFEST_MAGIC + str(ARCHIVE_FORMAT_VERSION),
            '#',
            '# One small-signal run, as it was analysed: the dynamic Jacobian the',
            '# engine reduced, the modes, participation factors and mode shapes',
            '# it produced, and this file. The data files, solver settings and',
            '# disturbance that produced them are NOT here, so this records a',
            '# result rather than reproducing it.',
            '#',
            '# Open it with Load dynamic Jacobian on the STEPSS Analysis tab, or',
            '# with stepss.ssa.load_archive() in Python.',
            '#',
            'basename ' + self.basename,
        ]
        if self.engine_version is not None:
            lines.append('engine_version %.2f' % self.engine_version)
        if self.time is not None:
            lines.append('t %.6f' % self.time)
        if self.saved_by:
            lines.append('saved_by ' + self.saved_by)
        return '\n'.join(lines) + '\n'

    @classmethod
    def parse(cls, text):
        """Read a manifest back.

        :param str text: the manifest file's contents
        :returns: the run it describes
        :rtype: Manifest
        :raises RAMSESError: if the text is not a manifest, was written by a
                             newer STEPSS, or names a basename this module
                             would refuse to write
        """
        version = -1
        fields = {'basename': None, 'engine_version': None, 't': None,
                  'saved_by': None}
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith(_MANIFEST_MAGIC):
                tail = line[len(_MANIFEST_MAGIC):].strip()
                version = int(tail) if tail.isdigit() else -1
                continue
            if line[0] == '#':
                continue
            key, _, value = line.partition(' ')
            if key in fields:
                fields[key] = value.strip()
        if version < 0:
            raise RAMSESError('RAMSES: its %s does not start with "%s".'
                              % (MANIFEST_NAME, _MANIFEST_MAGIC))
        if version > ARCHIVE_FORMAT_VERSION:
            raise RAMSESError('RAMSES: it is in archive format v%d and stepss '
                              'reads v%d. Update stepss to open it.'
                              % (version, ARCHIVE_FORMAT_VERSION))
        # The basename becomes a file name the moment it is used, and it
        # arrives from a file someone else wrote, so it is held to exactly the
        # rule this module holds its own basenames to rather than trusted.
        if not valid_basename(fields['basename']):
            raise RAMSESError('RAMSES: its %s names an unusable basename %r.'
                              % (MANIFEST_NAME, fields['basename']))
        return cls(fields['basename'],
                   _float_or_none(fields['engine_version']),
                   _float_or_none(fields['t']),
                   fields['saved_by'])


def _float_or_none(token):
    """*token* as a float, or None when it is absent or does not parse.

    :param token: the text
    :type token: str or None
    :rtype: float or None
    """
    if token is None:
        return None
    try:
        return float(token)
    except ValueError:
        return None


def save(results, path, saved_by=None):
    """Write one run to a ``.ssa`` archive the graphical interface can open.

    The format is chosen from the file name: ``.tar.gz`` or ``.tgz`` for a
    gzipped tar, anything else for a zip. Everything goes under one directory
    named for the run, so unpacking by hand produces a folder rather than eight
    loose files, and the manifest is written first so that a listing puts what
    the archive is at the top.

    :param Results results: the run to archive
    :param path: where to write it
    :type path: str or pathlib.Path
    :param saved_by: what to record as the writer; defaults to this package and
                     its version
    :type saved_by: str or None
    :returns: the member names that were not on disk, in :func:`members` order.
              The three results files are optional in the sense that
              ``_pf.dat`` and ``_ms.dat`` may legitimately be absent, and the
              four Jacobian tables are absent from every run made without
              ``jacobian=True``.
    :rtype: list of str
    :raises RAMSESError: if the run has no modes file to archive
    """
    from . import __version__

    directory = getattr(results, 'directory', None)
    basename = getattr(results, 'basename', None)
    if not directory or not basename:
        raise RAMSESError('RAMSES: this Results names no directory to archive.')
    modes_path = os.path.join(directory, basename + RESULT_SUFFIXES[0])
    if not os.path.isfile(modes_path):
        raise RAMSESError('RAMSES: there is no %s in %s, so there is no analysis '
                          'to archive.'
                          % (os.path.basename(modes_path), directory))

    present, absent = [], []
    for name in members(basename):
        (present if os.path.isfile(os.path.join(directory, name))
         else absent).append(name)

    manifest = Manifest(basename, None, results.time,
                        saved_by or ('stepss %s' % __version__)).text()
    target = str(path)
    prefix = basename + '/'
    if _is_tar_name(target):
        with tarfile.open(target, 'w:gz') as archive:
            _tar_add_bytes(archive, prefix + MANIFEST_NAME,
                           manifest.encode('utf-8'))
            for name in present:
                archive.add(os.path.join(directory, name), arcname=prefix + name)
    else:
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(prefix + MANIFEST_NAME, manifest)
            for name in present:
                archive.write(os.path.join(directory, name), arcname=prefix + name)
    return absent


def load_archive(path, into=None):
    """Unpack a ``.ssa`` archive and read the run in it.

    :param path: the archive, in ``.zip`` or gzipped tar
    :type path: str or pathlib.Path
    :param into: where to unpack; a temporary directory when None. The results
                 files are read from there and the returned :class:`Results`
                 keeps naming that directory, which is why the default one is
                 not cleaned up here.
    :type into: str or pathlib.Path or None
    :returns: ``(results, manifest)``
    :rtype: tuple
    :raises RAMSESError: if the file is neither a zip nor a gzipped tar, holds
                         no manifest, is in a newer format, names an unusable
                         basename, or carries an entry that would be written
                         outside the destination
    """
    target = str(path)
    into = tempfile.mkdtemp(prefix='stepss-ssa-') if into is None else str(into)
    if zipfile.is_zipfile(target):
        with zipfile.ZipFile(target) as archive:
            for name in archive.namelist():
                _safe_child(into, name)
            archive.extractall(into)
    elif tarfile.is_tarfile(target):
        with tarfile.open(target, 'r:*') as archive:
            for member in archive.getmembers():
                _safe_child(into, member.name)
            archive.extractall(into)
    else:
        raise RAMSESError('RAMSES: could not open %s: it is neither a zip nor a '
                          'gzipped tar, so it is not a small-signal archive.'
                          % os.path.basename(target))

    manifest_path = _find_manifest(into)
    if manifest_path is None:
        raise RAMSESError('RAMSES: could not open %s: it carries no %s, so it '
                          'was not written by STEPSS.'
                          % (os.path.basename(target), MANIFEST_NAME))
    manifest = Manifest.parse(_read_text(manifest_path))
    return load(os.path.dirname(manifest_path), manifest.basename), manifest


def _is_tar_name(name):
    """Whether *name* spells a gzipped tar.

    ``.tgz`` is accepted on the way in because many tools produce it, and never
    written: one spelling per format keeps the writer honest about what it made.

    :param str name: the file name
    :rtype: bool
    """
    lower = name.lower()
    return lower.endswith('.tar.gz') or lower.endswith('.tgz')


def _tar_add_bytes(archive, name, payload):
    """Add an in-memory member to an open tar archive.

    :param tarfile.TarFile archive: the archive
    :param str name: the member name
    :param bytes payload: its contents
    """
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def _safe_child(into, entry_name):
    """Refuse an archive entry that would be written outside *into*.

    :param str into: the destination directory
    :param str entry_name: the entry's name as the archive spells it
    :returns: the resolved path
    :rtype: str
    :raises RAMSESError: if the entry escapes the destination
    """
    root = os.path.realpath(into)
    resolved = os.path.realpath(os.path.join(root, entry_name))
    if resolved != root and not resolved.startswith(root + os.sep):
        raise RAMSESError('RAMSES: the archive entry %r would be written outside '
                          'the destination directory.' % (entry_name,))
    return resolved


def _find_manifest(root):
    """The manifest inside an unpacked archive, at the root or one level down.

    :param str root: the unpacked directory
    :returns: the path, or None when there is none
    :rtype: str or None
    """
    direct = os.path.join(root, MANIFEST_NAME)
    if os.path.isfile(direct):
        return direct
    for name in sorted(os.listdir(root)):
        nested = os.path.join(root, name, MANIFEST_NAME)
        if os.path.isfile(nested):
            return nested
    return None
```

Add to `Results`, after `summary`:

```python
    def save(self, path, saved_by=None):
        """Write this run to a ``.ssa`` archive. See :func:`save`.

        :param path: where to write it
        :type path: str or pathlib.Path
        :param saved_by: what to record as the writer
        :type saved_by: str or None
        :returns: the member names that were not on disk
        :rtype: list of str
        """
        return save(self, path, saved_by)
```

Add to the imports at the top of the module, after `import os`:

```python
import io
import tarfile
import tempfile
import zipfile
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_ssa_archive.py -v`
Expected: every test in the file passes, none skipped, none xfailed. The count is not a requirement: several tests are parametrised, so the number pytest reports is larger than the number of test functions.

Run: `pytest tests/ -v -k "not nordic"`
Expected: PASS.

- [ ] **Step 5: Cross-check against an archive the graphical interface wrote**

This is a manual check, not an automated test, because it needs `stepss-java-ui` built. Skip it if that repository is not to hand, and say so in the commit message.

In `stepss-java-ui`, run the Kundur example on the Analysis tab, click Save dynamic Jacobian, then in Python:

```python
from stepss import ssa
res, manifest = ssa.load_archive("kundur.zip")
res.summary()
print(manifest)
```

Expected: the summary prints, and `manifest.engine_version` is the version the graphical interface recorded. Then write one from Python with `res.save("from-python.zip")` and open it with Load dynamic Jacobian.

- [ ] **Step 6: Commit**

```bash
git add src/stepss/ssa.py tests/test_ssa_archive.py
git commit -m "feat(ssa): read and write the .ssa archive both interfaces exchange"
```

---

### Task 9: Rewrite the notebook and correct the example README

**Files:**
- Modify: `examples/eigenanalysis/kundur_small_signal.ipynb`
- Modify: `examples/eigenanalysis/README.md`

**Interfaces:**
- Consumes: the whole public surface of `stepss.ssa`.
- Produces: nothing other code depends on.

Keep every markdown cell's physics commentary. Only the code cells and the two paragraphs named below change.

- [ ] **Step 1: Replace the imports cell (cell 2)**

```python
import os

import matplotlib.pyplot as plt

import stepss
from stepss import ssa

print("stepss version:", stepss.__version__)

# Each variant runs in its own directory, because the results files are named
# from the basename and would otherwise overwrite each other.
os.makedirs("run_pss", exist_ok=True)
os.makedirs("run_nopss", exist_ok=True)
```

- [ ] **Step 2: Replace the case builder (cell 4)**

```python
def build_case(dynfile, trj):
    """Assemble a Kundur case. `dynfile` selects the PSS variant."""
    case = stepss.cfg()
    case.addData("lf.dat")             # power flow: buses, lines, transformers
    case.addData(dynfile)              # dynamic data: machines, AVR/PSS, governors
    case.addData("solveroptions.dat")  # the case's own solver settings
    case.addDst("nothing.dst")
    case.addObs("obs.dat")
    case.addTrj(trj)
    return case


# The two variants differ in exactly one parameter: the PSS gain KSTAB, 20.0 in
# dyn.dat and 0.0 in dyn_noPSS.dat, on all four exciters. Everything else is
# identical, so any difference in the results is attributable to the PSS alone.
print(open("dyn.dat").readlines()[9].strip())
print(open("dyn_noPSS.dat").readlines()[9].strip())
```

- [ ] **Step 3: Replace the run cell (cell 6)**

```python
res_pss = ssa.run(build_case("dyn.dat", "out.trj"),
                  basename="ssa", workdir="run_pss")
res_nopss = ssa.run(build_case("dyn_noPSS.dat", "out.trj"),
                    basename="ssa", workdir="run_nopss")

res_nopss.summary()
```

- [ ] **Step 4: Replace the three reading and filtering cells (cells 8, 10 and 12)**

Cell 8 becomes:

```python
for tag, res in (("with PSS", res_pss), ("without PSS", res_nopss)):
    print("%-12s %3d modes, %3d simple, %3d degenerate"
          % (tag, len(res.modes), int(res.modes["simple"].sum()),
             int((~res.modes["simple"]).sum())))
```

Cell 10 becomes:

```python
for tag, res in (("WITH PSS", res_pss), ("WITHOUT PSS", res_nopss)):
    print("\n%s" % tag)
    res.electromechanical().table()
```

Cell 12 becomes:

```python
for limit in (-1.0, -0.5, -0.1):
    kept = res_pss.dominant(limit)
    print("real part above %-6g : %2d of %d modes, leftmost Re = %+.2f"
          % (limit, len(kept), len(res_pss.modes), kept.rows["re"].min()))

print("\nunfiltered, the spectrum reaches Re = %+.1f" % res_pss.modes["re"].min())
```

- [ ] **Step 5: Replace the inter-area cell (cell 14)**

```python
def interarea(res, lo=0.4, hi=0.9):
    """The single mode in the inter-area band."""
    band = res.electromechanical(lo, hi)
    assert len(band) == 1, "expected one inter-area mode, found %d" % len(band)
    return band[0]


print("inter-area mode")
for tag, res in (("without PSS", res_nopss), ("with    PSS", res_pss)):
    mode = interarea(res)
    print("  %s: f = %.4f Hz, zeta = %+.4f  -> %s"
          % (tag, mode["freq"], mode["zeta"],
             "UNSTABLE" if mode["zeta"] < 0 else "stable"))
```

- [ ] **Step 6: Replace the participation cell (cell 16)**

```python
def omega_rows(res, mode, floor):
    """Rotor-speed participation of each machine in one mode."""
    return [(row.device.strip(), row.pf)
            for row in res.participation(mode, floor=floor)
            if row.variable == "omega"]


print("omega participation, without PSS\n")
mode = interarea(res_nopss)
print("  inter-area %.3f Hz:" % mode["freq"])
for device, pf in sorted(omega_rows(res_nopss, mode, 0.05)):
    print("    %-6s %.3f" % (device, pf))

for local in res_nopss.electromechanical(0.9, 2.5):
    print("\n  local mode %.3f Hz:" % local["freq"])
    for device, pf in sorted(omega_rows(res_nopss, local, 0.05)):
        print("    %-6s %.3f" % (device, pf))

# The same mode with the floor dropped: the other area's machines were in the
# file all along, two orders of magnitude below the participating pair. Nothing
# was re-run to see them.
local = res_nopss.electromechanical(0.9, 2.5)[0]
print("\n  the same mode at floor 0.001:")
for device, pf in sorted(omega_rows(res_nopss, local, 0.001)):
    print("    %-6s %.3f" % (device, pf))
```

- [ ] **Step 7: Replace the mode-shape cell (cell 19)**

```python
mode = interarea(res_nopss)
print("inter-area mode shape, without PSS\n")
for row in res_nopss.mode_shape(mode):
    print("  %-6s magnitude %.3f   angle %+8.2f deg"
          % (row.device.strip(), row.magnitude, row.angle_deg))

ax = res_nopss.mode_shape_plot(mode)
ax.set_title("Inter-area mode shape (rotor speeds), no PSS", pad=18)
plt.show()
```

- [ ] **Step 8: Replace the two s-plane cells (cells 22 and 24)**

Cell 22 becomes:

```python
fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharex=True, sharey=True)
for ax, (tag, res) in zip(axes, (("without PSS", res_nopss), ("with PSS", res_pss))):
    res.electromechanical().splane(ax=ax)
    ax.set_title("Electromechanical modes, %s" % tag)
plt.tight_layout()
plt.show()
```

Cell 24 becomes:

```python
LIMIT = -1.0
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
res_pss.splane(ax=axes[0], annotate=False)
axes[0].set_title("With PSS, all %d modes" % len(res_pss.modes))
res_pss.dominant(LIMIT).splane(ax=axes[1], annotate=False)
axes[1].set_title("With PSS, real part above %g" % LIMIT)
plt.tight_layout()
plt.show()

print("full spectrum   Re from %+8.2f to %+6.2f"
      % (res_pss.modes["re"].min(), res_pss.modes["re"].max()))
kept = res_pss.dominant(LIMIT)
print("above %-6g    Re from %+8.2f to %+6.2f   (%d modes)"
      % (LIMIT, kept.rows["re"].min(), kept.rows["re"].max(), len(kept)))
```

- [ ] **Step 9: Update the two paragraphs that describe machinery that has gone**

In cell 1, delete the paragraph beginning "**There is no `stepss.ssa` module yet.**" and put in its place:

```
**Everything below goes through `stepss.ssa`.** `ssa.run()` supplies the two
solver settings the analysis requires, clears any previous run under the same
basename, drives the engine and returns a result object; the filtering and the
plots are methods on it. The `EIG` disturbance record and the `sim.runSsa()`
entry both remain available to a caller who would rather drive the run
themselves.
```

In cell 3, the bullet beginning "**`solveroptions.dat` must set `$OMEGA_REF SYN`.**" keeps its physics but gains a closing sentence:

```
The bundled `solveroptions.dat` already sets `SYN`, and `ssa.run()` supplies
both records itself in a generated file read last, so a case of your own needs
no edit.
```

In cell 5, delete the sentence "We then advance just past `t` so the event actually fires.", which describes the disturbance route the notebook no longer takes, and delete the paragraph beginning "The record takes a basename and nothing else."

In cell 25, keep the `getJac()` bullet, which still applies above `$EIG_MAX_STATES`, and add:

```
- Read the reduced state matrix directly with `res.state_matrix` and drive
  your own eigensolver over it.
```

- [ ] **Step 10: Correct the README**

In `examples/eigenanalysis/README.md`, replace the heading "## Requires a RAMSES newer than 3.60" and the two paragraphs under it with:

````markdown
## Requires RAMSES 3.79 or newer

The analysis writes v2 results files from 3.79 onwards, which is what
`stepss.ssa` reads. An older bundle accepts the run and writes files this
notebook will not open.

The `stepss` version's leading components name the bundled RAMSES, so
`stepss.__version__` tells you directly:

```python
import stepss; print(stepss.__version__)   # needs >= 3.79
```
````

At the end of the "Two settings the analysis requires" section, add:

```markdown
`ssa.run()` supplies both itself, in a generated file read after the case's own
data files, so a case of your own needs no edit. They are documented here
because a run driven by hand, through the `EIG` record or `sim.runSsa()`, still
needs them.
```

- [ ] **Step 11: Run the notebook end to end**

```bash
pip install nbconvert
```

Then, from `examples/eigenanalysis`:

```bash
jupyter nbconvert --to notebook --execute --inplace kundur_small_signal.ipynb
```

Expected: exits 0. Confirm the headline result survived:

```bash
grep -c UNSTABLE kundur_small_signal.ipynb
```

Expected: at least 1, since the no-PSS inter-area mode is unstable.

- [ ] **Step 12: Commit**

```bash
git add examples/eigenanalysis/kundur_small_signal.ipynb examples/eigenanalysis/README.md
git commit -m "docs(ssa): drive the Kundur notebook through stepss.ssa"
```

---

### Task 10: Documentation site

**Files:**
- Modify: `stepss-docs/src/content/docs/python/api-reference.md`
- Modify: `stepss-docs/src/content/docs/user-guide/eigenanalysis.md`

**Interfaces:**
- Consumes: the public surface of `stepss.ssa`.
- Produces: nothing other code depends on.

**This task is in a different repository.** `stepss-docs` is a sibling submodule of the umbrella repo. Commit there separately, and do not bump the umbrella's pointers until both repositories have been pushed, because a pinned commit that is not on the remote breaks cloning for everyone else.

- [ ] **Step 1: Add the API reference section**

In `src/content/docs/python/api-reference.md`, after the `stepss.monitor` section and before `## Complete Example`, add:

````markdown
---

## `stepss.ssa`: Small-Signal Stability Analysis

RAMSES performs the analysis itself and writes three files named from a
basename. `stepss.ssa` drives that run and reads them back, so no parsing is
needed.

Needs RAMSES 3.79 or newer, which is what writes the v2 files this module
reads.

### Running

#### `ssa.run(case, basename='ssa', t=0.001, workdir=None, jacobian=False, ram=None, keep_open=False)`

Run one analysis and return its results. The case is copied rather than
modified, and the copy is given `$SCHEME DE` and `$OMEGA_REF SYN` in a
generated file read last, because the engine refuses the analysis under either
of the values a case that says nothing about them lands on. Anything already on
disk under `basename` is cleared first, since the only evidence a run produced
results is that its modes file is there afterwards.

```python
import stepss
from stepss import ssa

case = stepss.cfg('cmd.txt')
res = ssa.run(case, basename='ssa', workdir='run1')
res.summary()
```

Pass `jacobian=True` to write the four Jacobian tables at the instant of the
reduction as well.

#### `ssa.load(directory, basename)` and `ssa.basenames(directory)`

Read a run produced anywhere, and list the runs in a directory.

```python
print(ssa.basenames('run1'))     # ['ssa']
res = ssa.load('run1', 'ssa')
```

#### `ssa.load_archive(path)`

Open a `.ssa` archive written by the graphical interface, in `.zip` or
`.tar.gz`. Returns `(results, manifest)`. `res.save(path)` writes one.

### Filtering

#### `res.electromechanical(lo=0.1, hi=2.5)`

The rotor band, one member of each conjugate pair, sorted by frequency.

#### `res.dominant(real_limit=-1.0)`

The modes whose real part is above the limit, strictly greater than. This is
the filter that used to be a parameter of the run, and it is now a question
asked of results already in hand: widening it costs nothing.

Both return a `ModeView`, which composes and carries `.rows`, `.lam`,
`.table()` and `.to_frame()`:

```python
res.electromechanical().dominant(-1.0).table()
```

### Reading one mode

#### `res.participation(mode, floor=0.05, allow_degenerate=False)`

Participation factors, largest first. `floor` is applied here, not by the
engine: the file carries every entry above the run's own `pf_floor`, so
lowering it shows more without re-running anything.

#### `res.mode_shape(mode, allow_degenerate=False)`

Each machine's rotor-speed phasor: magnitude normalised so the largest is 1,
angle relative to that entry.

Both refuse a mode whose `simple` flag is false. In a degenerate eigenspace the
eigenvectors are not unique, so both quantities are basis-dependent and would
come out differently on another machine.

### Plotting

#### `view.splane(ax=None, zeta=0.05, annotate=True, interactive=None)`

The s-plane, fitted to the modes on screen. Under an interactive backend
(`%matplotlib widget`) clicking a pole prints it, dragging a rectangle zooms,
and a double click restores the fitted window.

#### `res.mode_shape_plot(mode, ax=None)` and `res.participation_plot(mode, floor=0.05, ax=None)`

The polar dial and a horizontal bar chart. Each takes and returns an `Axes`, so
two runs go side by side in one figure.

### The state matrix

#### `res.state_matrix`

The matrix the engine reduced, as an `(nstates, nstates)` array. It lives in
the engine rather than in any file, so it is available on a live run only, and
a later analysis replaces it: read it before starting the next one.

#### `sim.runSsa(basename, t=0.001)` and `sim.getStateMatrix()`

The low-level entries `ssa.run` is built on, for a caller driving the run
themselves.
````

- [ ] **Step 2: Point the eigenanalysis guide at the module**

In `src/content/docs/user-guide/eigenanalysis.md`, replace the Python example around line 62 with:

````markdown
or drive it from Python, which supplies the two solver settings itself:

```python
import stepss
from stepss import ssa

case = stepss.cfg()
case.addData("lf.dat")
case.addData("dyn.dat")
case.addDst("nothing.dst")
case.addObs("obs.dat")
case.addTrj("out.trj")

res = ssa.run(case, basename="ssa")
res.electromechanical().table()
res.electromechanical().splane()
```

See the [`stepss.ssa` reference](/python/api-reference/#stepssssa-small-signal-stability-analysis)
for the filters, the participation and mode-shape accessors, and the archive
both interfaces exchange.
````

Around line 213, where the page says results made elsewhere "are read by the Python API rather than by", name `ssa.load()` explicitly and check the sentence still reads correctly now that a module exists.

- [ ] **Step 3: Build the site**

```bash
npm install
```

Then:

```bash
npm run build
```

Expected: exits 0, with no broken-link warning naming the new anchor.

- [ ] **Step 4: Commit in stepss-docs**

```bash
git add src/content/docs/python/api-reference.md src/content/docs/user-guide/eigenanalysis.md
git commit -m "docs: document the stepss.ssa module"
```

---

## After both repositories are pushed

Two facts become cross-repo contracts and belong in the umbrella `CLAUDE.md`,
under the "Eigenanalysis moved into the engine" section:

- The v2 banner and the fixed column offsets now have **two** readers, `SsaModes`
  and its neighbours in `stepss-java-ui` and `stepss.ssa` in
  `stepss-python-ui`. A column change requires the writer and both readers to
  move in the same pass.
- Archive format v1 now has two writers and two readers. A field added to the
  manifest on one side is ignored on the other, which is the format's own rule,
  but a change to the magic line or to the member set is breaking.

Then bump the umbrella's submodule pointers for `stepss-python-ui` and
`stepss-docs`, in that order, and commit the gitlink change there.
