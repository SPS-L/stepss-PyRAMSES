# A `stepss.ssa` module: small-signal workflows in the Python interface

**Date:** 2026-08-25
**Status:** Draft, awaiting review

## Summary

Add `stepss.ssa`, a module that drives a small-signal run, reads its three
results files, filters them and plots them, so that a user of the Python
interface reaches the same result as a user of the graphical one without
writing a parser first.

The work is prompted by `examples/eigenanalysis/kundur_small_signal.ipynb`,
which carries seven code cells that are boilerplate rather than analysis:
`read_modes` with its banner branch, `read_pf`, `read_ms`, `electromechanical`,
`dominant`, a run driver built from `chdir`, symlinks, `execSim`, `addDisturb`,
`contSim` and `endSim`, and roughly fifty lines of matplotlib. Every one of
those already exists in `stepss-java-ui/src/my/stepss/ssa/` as a tested class,
so the Python interface is the only one of the two in which a user must
reimplement them.

Three safeguards the graphical interface applies and the notebook does not are
adopted with it: the generated solver-settings override, the clearing of a
previous run's outputs before a new one starts, and basename validation.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Module name | `stepss.ssa` | Already promised by name in the notebook's Prerequisites cell, so the name is fixed by a published document rather than chosen now. |
| Naming convention | snake_case in `ssa.py`, camelCase for the two new `sim` methods | Follows the split `CLAUDE.md` records: the RAMSES API is camelCase, `stepss.helios` is deliberately PEP 8. The new methods sit beside `getJac` and `execSim`. |
| Default trigger | `run_ssa` C entry, wrapped as `sim.runSsa` | One call after `execSim(case, 0.0)`, no disturbance records, and it is the only route that leaves a state matrix retrievable through `get_state_matrix`. |
| Jacobian | `jacobian=True` supported, `False` by default | `dumpjac` and `dumpeig` are independent flags and each C entry advances the clock by one millisecond, so `runSsa` followed by `getJac` is not one instant. The `True` path therefore uses paired `JAC`/`EIG` disturbance records, which is what the graphical interface does. |
| Analysis time | `t` keyword, floor and default both 0.001 s | Mirrors `SsaDisturbance.MIN_TIME` and the graphical interface's default. The C entry takes no time, so the wrapper advances the run to `t` first. |
| Degenerate modes | Refused, not warned | Matches `ModeShapePanel` and the participation panel, both of which decline to draw a mode whose eigenvectors are not unique. An `allow_degenerate=True` escape hatch is provided because a scripting API has bulk uses a graphical one does not. |
| Parsing | Fixed column offsets | Corrects a defect: the notebook splits on whitespace, and `Columns.java` documents that a device name may carry a leading or embedded blank. |
| Plot interactivity | matplotlib `pick_event` and `RectangleSelector` | Reproduces `SplanePanel`'s two interactions with no addition to `requirements.txt`. `live._canDraw()` already distinguishes an inline backend from an interactive one. |
| Archive | `zipfile` and `tarfile` from the standard library | The `.ssa` format is fully specified by `SsaArchive` and needs no third-party reader. |
| State matrix | Lazy property, guarded by a generation counter | `nx` can reach 5000, at which the dense matrix is 200 MB, so capturing eagerly would charge every run for a result most never read. The engine refuses only an order mismatch, so a counter is needed to stop a stale result handing back a later run's matrix. |
| Analysis records | Injected with `addDisturb`, never written into a file | The one mechanism that works whether the disturbance file is the generated one or the caller's own. |

### Alternatives considered and rejected

- **Reading and plotting only, leaving the run to the user.** Rejected because
  the three safeguards above are precisely what a user driving the run by hand
  omits, and each fails silently: a case under the default `$OMEGA_REF COI` is
  refused, a stale `_modes.dat` is read as the current run's, and an apostrophe
  in a basename closes the `EIG` record early and produces no files at all.
- **Keeping the `EIG` disturbance as the only trigger.** Rejected because it
  cannot reach `get_state_matrix` through a documented path, and because it
  obliges the caller to advance past the event and to supply a disturbance file
  whose only purpose is to satisfy the format.
- **An interactive s-plane built on plotly or ipywidgets.** Rejected: the
  package ships as a single self-contained fat wheel, and matplotlib alone
  provides both interactions.
- **A pandas `DataFrame` as the result type.** Rejected as the primary type
  because pandas is not a dependency and the results carry per-run header
  metadata (`nstates`, `pf_floor`, `gap_tol`) that a frame has nowhere to put.
  A `to_frame()` accessor is provided where pandas is importable.

## What is deliberately held constant

- **The engine's file formats.** Nothing in RAMSES changes. The module reads
  v2 files, as `SsaModes` does, and refuses any other version.
- **The `.ssa` archive format.** Archive format v1 as `SsaArchive` writes it,
  so an archive written by either interface opens in the other.
- **Filter semantics.** `dominant` uses `Re(lambda) > limit`, strictly greater
  than, and `electromechanical` uses 0.1 to 2.5 Hz with `Im > 0` sorted by
  frequency, both exactly as `SsaResults.aboveRealLimit` and
  `SsaResults.electromechanical` define them. The same limit must select the
  same modes in both interfaces.
- **The existing `sim` API.** Two methods are added. Nothing is changed or
  removed, and `getJac` keeps writing under the `py` basename it hardcodes.

## Scope

In scope:

1. `sim.runSsa` and `sim.getStateMatrix` in `src/stepss/simulator.py`.
2. A new `src/stepss/ssa.py` holding the run driver, the results model, the
   parsers, the filters, the plots and the archive reader and writer.
3. Export from `src/stepss/__init__.py`.
4. Tests, most of which need no licence.
5. A rewritten notebook and a corrected example README.
6. Documentation-site updates in `stepss-docs`.

Out of scope:

- Any change to RAMSES. The C entries and the file formats are used as they
  stand.
- Sparse or shift-invert eigensolution above `$EIG_MAX_STATES`. The refusal is
  reported with its reason; `getJac` and `scipy.sparse.linalg.eigs` remain the
  documented route for that regime.
- Any change to `stepss-java-ui`. The parity is one-directional: Python adopts
  what Java already does.

## Component 1: engine bindings

`src/stepss/libs/ramses.h` already declares the three entries at lines 42 to
44, and `_setcalls()` binds every declaration in that header, so the ctypes
signatures exist today with nothing calling them.

### `sim.runSsa(basename, t=0.001)`

```python
def runSsa(self, basename, t=0.001):
    """Run the small-signal analysis and write its three results files."""
```

Order of operations:

1. Validate `basename` against the rule `SsaDisturbance.validBasename`
   applies: non-empty, and only ASCII letters, digits, `.`, `_` and `-`. The
   basename becomes both a file name and a quoted Fortran string, so an
   apostrophe closes the `EIG` argument early and a path separator writes the
   files where no loader looks. Raise `RAMSESError` naming the offending
   character.
2. Validate `t`: finite, and at least `MIN_TIME = 0.001`, which is
   `SsaDisturbance.MIN_TIME`.
3. Compare `t` against `getSimTime()`. When `t` is greater, call `contSim(t)`
   so the analysis linearises about the requested operating point. When `t` is
   earlier than the current simulated time, raise: the engine linearises about
   wherever the run currently sits, so the difference between "at `t`" and "at
   now" is invisible in the results and must not be resolved silently.
4. Call `run_ssa(basename)`. Treat 0 and 112 as success, exactly as `getJac`
   treats `get_Jac`'s return, since 112 is `ramses()` reporting that it paused
   again after completing the request. Any other value, 78 in particular, is
   `ssa_refusal_exit_code`; raise `RAMSESError` carrying `getLastErr()`, which
   is where the `$SCHEME IN`, `$OMEGA_REF COI` and `$EIG_MAX_STATES` refusals
   arrive with their own explanations.

The time is implemented here rather than in the engine because `run_ssa` takes
a basename and nothing else: it sets `jacfile`, `dumpeig` and `forcejac`,
advances `pause_time` by one millisecond and resumes. Advancing to `t` first
is what the graphical interface achieves by placing `EIG` at `t` in a
disturbance file that carries no other events.

A caveat to document: when the case's own disturbance file carries events
before `t`, advancing applies them, and the analysis then describes the state
that resulted. That is the correct reading of "linearise at `t`", and it is why
the driver in Component 2 generates an event-free disturbance file when the
case has none.

### `sim.getStateMatrix()`

```python
def getStateMatrix(self):
    """Return A_sys from the last analysis as an (nx, nx) ndarray."""
```

Calls `get_state_matrix_size` for the order, raises `RAMSESError` when it is
zero (no analysis attempted in this process, or the last one refused),
allocates `nx*nx` doubles, calls `get_state_matrix`, and reshapes with
`order='F'`, which is what the C entry's own documentation names as the
reconstruction its column-major fill expects.

Lifetime, verified in `src/core/ssa.f90`: `ssa_clear_retained` is called only
at the top of `solve_small_signal` and by `run_ssa` itself. Nothing in the
finalisation path clears it, so the retained matrix survives `endSim()` and is
invalidated only by the next analysis in the same process. Both triggers retain
it, so this works on the `jacobian=True` route as well.

**A second analysis silently replaces it, and the engine cannot detect that on
the caller's behalf.** `get_state_matrix` refuses only an order mismatch, so
two runs of the same case with different data, which have the same state count
by construction, would let a stale `Results` hand back the later run's matrix
with no error at all. That is exactly the substitution the clearing step in
Component 2 exists to prevent one level up, so the same guard is applied here:
`sim` carries a counter, `_ssaGeneration`, incremented on every successful
analysis, by `runSsa` and by the driver's disturbance route alike. A `Results`
records the counter's value when it was produced, and `Results.state_matrix`
raises when the counter has since advanced, naming the run that replaced it.
The counter is what makes the guard sound: comparing `nx`, or basenames, or
directories cannot distinguish two runs that agree on them.

## Component 2: the run driver

```python
def run(case, basename='ssa', t=0.001, workdir=None,
        jacobian=False, ram=None, keep_open=False):
    """Run one small-signal analysis and return its results."""
```

`case` is a `stepss.cfg`. It is deep-copied and never mutated: the caller's
case must be reusable for an ordinary time-domain run afterwards.

Steps, in this order, because the order is what makes each safeguard hold:

1. **Validate** `basename` and `t` before anything is written or deleted, so a
   run that never starts leaves the previous run intact. This mirrors the
   ordering `StepssUI.ssaButton1ActionPerformed` documents at length.
2. **Write the settings override** `<basename>Eig.dat`, byte-for-byte the text
   `SsaSettings.text()` produces: `$SCHEME DE` and `$OMEGA_REF SYN`, and
   nothing else. `addData` it last on the copied case. `cfg.writeCmdFile` emits
   data files in insertion order and the engine keeps the last record of each
   kind it reads, so last means winning. Refuse when a file of that name is
   already among the case's data files, as the graphical interface does, rather
   than overwriting the user's file.
3. **Write a disturbance file** `<basename>Eig.dst` when the case has none.
   `cfg.writeCmdFile` refuses a case without one, and `_dstProblem` requires a
   record carrying a timed `STOP`. The generated file is
   `SsaDisturbance.text(basename, t)` with its `JAC` and `EIG` lines omitted:
   the solver record, then `STOP` at `t + 0.010`. The analysis records are
   injected with `addDisturb` rather than written into the file, on both paths,
   because that is the one mechanism that works whether the disturbance file is
   this generated one or the caller's own.

   When the case supplies its own disturbance file, `t` must fall before that
   file's `STOP`, since a run that has already stopped cannot be advanced to
   `t`. The driver cannot check this without parsing the caller's file, so it
   is documented rather than enforced, and the failure is loud: `runSsa` raises
   on a `t` earlier than the simulated time already reached.
4. **Clear the previous run**, deleting exactly the set
   `SsaArchive.members(basename)` names: `_modes.dat`, `_pf.dat`, `_ms.dat`,
   `_eqs.dat`, `_var.dat`, `_val.dat`, `_struc.dat`. Nothing else in the
   directory is touched, because the basename exists so that several runs can
   share one directory and the case's data files usually live there too. A name
   that will not delete is collected and the rest are still attempted; a
   non-empty list refuses the run. File existence is the only evidence a run
   produced anything, so without this a refused run reads as the previous run's
   spectrum under this run's heading.
5. **Run.** Create a `sim` unless one was passed as `ram`, `execSim(case, 0.0)`
   to initialise and pause at the operating point, then either `runSsa` or, on
   the `jacobian=True` path, `addDisturb(t, "JAC '<base>'")`,
   `addDisturb(t, "EIG '<base>'")` and `contSim(t + 0.010)`. The paired route
   is the only one that dumps the Jacobian at the instant of the reduction:
   `simul_decomp.f90` calls `dump_jacobian` then `dump_eig` in the same step,
   whereas `run_ssa` sets `dumpeig` alone and `get_Jac` both hardcodes
   `jacfile="py"` and advances the clock a second time.
6. **Check.** Raise when `<basename>_modes.dat` is absent, with the message the
   graphical interface uses: the run was given `$SCHEME DE` and
   `$OMEGA_REF SYN`, so the reason lies elsewhere, usually a state count above
   `$EIG_MAX_STATES` or a model with no differential states, and the engine
   says which.
7. **Finalise** with `endSim()` unless `keep_open=True`, because a paused
   simulation is not finished and loading a new case without finalising
   silently resumes the old one. `keep_open=True` is for a caller who wants to
   go on interrogating the same run.
8. **Load** the three files and return a `Results`.

`workdir` names where the run happens and where the files land. When given, the
driver runs there and restores the previous working directory afterwards, in a
`finally`. Relative paths in the case are resolved against the caller's
directory before the change, so a case built with relative file names keeps
working; this replaces the symlink dance in the notebook's `run_ssa` helper.

## Component 3: results model and parsers

```python
class Results:
    modes          # ndarray, structured: index, re, im, zeta, freq, simple
    nstates, nalg, time, pf_floor, gap_tol, format_version
    directory, basename
    state_matrix   # lazy property, live runs only
```

`state_matrix` is a lazy property rather than a captured array, because `nx`
can reach 5000 and the dense matrix is then 200 MB, which every run would pay
for a result most never read. It is available only on a `Results` that came
from `ssa.run`: the matrix lives in the engine and is in none of the files, so
on results from `ssa.load` or `ssa.load_archive` it raises and says so. On a
live run it raises when the generation counter described in Component 1 has
advanced past the one it recorded.

`ssa.load(directory, basename)` reads a run from disk, whatever produced it,
and `ssa.basenames(directory)` lists the runs present, mirroring
`SsaResults.basenames`: a name is offered only when `<name>_modes.dat` is a
regular file, so a directory of that name is not offered and then refused.

`_pf.dat` and `_ms.dat` are optional and load as empty when absent, as
`SsaResults` treats them, because their absence is not a reason to refuse the
run that is present.

Parsing is by fixed offset throughout, from the table in the appendix. The
banner is checked before a single row is read: v1 put a dominance column
exactly where v2 puts `smp`, at the same width with the same two legal values,
so a positional reader that skips the banner does not fail, it reports the
simplicity flag as the dominance flag. Any version other than 2 is refused,
naming the version and, when it is lower, naming RAMSES 3.79 as the change.

Two accessors, both refusing a degenerate mode by default:

```python
res.participation(mode, floor=0.05, allow_degenerate=False)
res.mode_shape(mode, allow_degenerate=False)
```

`floor` is applied here and not by the engine. The file carries every entry
above the run's own `pf_floor`, recorded in the header from `$PF_THRES`, so
lowering `floor` shows more without re-running anything, down to that floor
alone. `mode` accepts an integer index or a row from `res.modes`.

The refusal on a degenerate mode matches `ModeShapePanel` and the participation
panel: in a degenerate eigenspace the eigenvectors are not unique, so both
quantities are basis-dependent and would come out differently on another LAPACK
build while looking exactly as authoritative. Twenty of Kundur's seventy modes
are degenerate. `allow_degenerate=True` returns the rows unchanged and is the
scripting escape hatch the graphical interface has no need of.

## Component 4: filters

```python
res.electromechanical(lo=0.1, hi=2.5)   # -> ModeView
res.dominant(real_limit=-1.0)           # -> ModeView
```

Both return a view that keeps its link to the parent `Results`, so
`res.electromechanical().splane()` draws and `view.participation(view[0])`
resolves. Views compose, and `dominant` preserves input order so composing it
after `electromechanical` keeps that method's sort by frequency, which is the
property `SsaResults.aboveRealLimit` documents.

`res.summary()` prints the header metadata and the mode counts;
`view.table()` prints the per-mode table the notebook formats by hand, and
`view.to_frame()` returns a pandas `DataFrame` where pandas is importable.

## Component 5: plots

```python
view.splane(ax=None, zeta=0.05, annotate=True, interactive=None)
res.mode_shape_plot(mode, ax=None)
res.participation_plot(mode, floor=0.05, ax=None)
```

Each takes and returns an `Axes`, following `curplot`, so two runs go side by
side in one figure the way the notebook compares the two PSS variants.

`splane` draws the stability boundary at `Re = 0` in crimson, one dashed
constant-damping ray at `zeta` (default 0.05, `SplanePanel.DEFAULT_DAMPING_ZETA`),
and one circle per mode, crimson when the mode is unstable. One glyph per mode
and no overplotted cross, which is the state both interfaces converged on. The
window is fitted to the modes on screen with a six per cent margin and a
minimum absolute pad, rather than the notebook's hardcoded limits, so it works
on systems other than Kundur and so that filtering actually zooms; the fitted
window always contains `Re = 0`, because the boundary is what the plot is read
against.

`interactive` defaults to `None`, meaning "when the backend can". Detection
reuses `live._canDraw()`, which already treats the inline backend as unable to
animate. Where it can: `pick_event` selects a pole and fills its circle,
`RectangleSelector` zooms to a dragged rectangle, and a double click restores
the fitted window. Where it cannot, the figure is static and a single note says
so and names `%matplotlib widget`. `interactive=False` forces static.

`mode_shape_plot` is the polar dial: an arrow per machine from the origin to
`(angle, magnitude)`, labelled at 1.12 times its magnitude, `rmax` 1.3. It
refuses a degenerate mode, and distinguishes that refusal from an empty mode,
which means the file is missing or incomplete rather than filtered, since the
engine writes a shape for every mode.

## Component 6: archive interop

```python
res.save(path, saved_by=None)      # .zip or .tar.gz, chosen by extension
ssa.load_archive(path)             # -> (Results, Manifest)
```

Format v1 as `SsaArchive` defines it: one top-level directory named for the
run, `stepss-ssa.txt` written first so that a listing puts what the archive is
at the top, then whichever of the seven members exist. `save` refuses without a
modes file and returns the names it could not find, as the Java side does.
`load_archive` unpacks into a temporary directory, refuses an archive with no
manifest, refuses a format version above 1, and holds the basename in the
manifest to the same validity rule the writer applies, because it arrives from
a file someone else wrote.

`saved_by` defaults to `stepss <__version__>`. Entry paths are checked against
the destination before extraction, as `safeChild` does, so a crafted archive
cannot write outside the temporary directory.

## Component 7: notebook, examples and documentation

The notebook keeps every word of its physics commentary and loses the
boilerplate: `read_modes`, `read_pf`, `read_ms`, `electromechanical`,
`dominant`, the run driver and both plotting cells become calls into the
module, roughly 120 lines removed. The Prerequisites cell loses the sentence
saying no such module exists.

`examples/eigenanalysis/README.md` needs correcting independently of this work:
it states that the example requires a RAMSES newer than 3.60, while the
notebook requires 3.79.

In `stepss-docs`, `python/api-reference.md` gains a `stepss.ssa` section
alongside `stepss.cfg`, `stepss.sim` and `stepss.extractor`, and
`user-guide/eigenanalysis.md` points the Python reader at it instead of at the
hand-written parsing it currently shows.

## Cross-repo contracts

Two facts become contracts with a second reader and belong in the umbrella
`CLAUDE.md` once this lands:

- **The v2 banner and the fixed column offsets now have two readers.** RAMSES
  writes them, `SsaModes` and friends read them, and `stepss.ssa` reads them.
  A column change requires all three to move together.
- **Archive format v1 now has two writers and two readers.** A field added to
  the manifest on one side is ignored on the other, which is the format's own
  rule, but a change to the magic line or to the member set is breaking.

## Order of operations

1. `sim.runSsa` and `sim.getStateMatrix`, with tests against a real run.
2. Parsers and the `Results` model, with tests against checked-in fixtures.
3. Filters and `table()`, tested against the values the example README records.
4. The run driver, including the settings override, the generated disturbance
   file and the clearing step.
5. Plots.
6. Archive reader and writer, tested by round trip and against an archive
   written by the graphical interface.
7. Export from `__init__.py`.
8. Notebook rewrite, README correction, documentation-site updates.

Steps 2, 3 and 6 need neither a licence nor an engine, so they are gated by
ordinary unit tests. Steps 1 and 4 need both.

## Testing

`tests/test_ssa.py`, following the conventions in `tests/`:

- **Parsers.** Fixtures under `tests/data/ssa/`, small and checked in: a v2
  modes file, a `_pf.dat` whose device names carry a leading and an embedded
  blank, a `_ms.dat`, a v1 modes file that must be refused, and a file with no
  banner that must be refused.
- **Filters.** `electromechanical` and `dominant` against the fixture, with the
  strict inequality at the boundary tested explicitly, since that is the
  property that keeps the two interfaces in step.
- **Degeneracy.** `participation` and `mode_shape` refuse a mode with
  `simple = 0` and return rows with `allow_degenerate=True`.
- **Archive.** Round trip in both formats; an archive with no manifest, one
  with format version 2, and one with a traversal entry are each refused.
- **Live run**, gated the way `test_nordic.py` is: the Kundur case with and
  without its stabilisers, asserting the inter-area damping ratio changes sign
  and matching the three frequencies and three damping ratios the example
  README records for each variant. This is the gate that would catch an engine
  change to the file format.
- **The generation guard.** Two analyses in one process, the second with the
  same state count as the first, and `state_matrix` on the first `Results`
  raises rather than returning the second's matrix. Also that it raises on a
  `Results` from `ssa.load`.
- **Plots** under the `agg` backend, asserting that each returns an `Axes` and
  that `interactive=None` produces a static figure there.

## Risks

- **The retained state matrix is process-global**, and the engine's own guard
  is insufficient. `get_state_matrix` refuses an order mismatch alone, so two
  runs agreeing on `nx`, which is the ordinary case when the same case is
  re-run with changed data, would let a stale `Results` return the newer
  matrix silently. The generation counter in Component 1 is what closes that,
  and it is the part of this design most likely to be dropped as redundant by
  someone reading the engine's documentation alone. The documented advice
  remains to read the matrix before starting the next analysis.
- **`jacobian=True` doubles the file volume** and produces tables that are
  large for a big case. It is off by default for that reason.
- **The fixed offsets are a silent dependency.** A column change in
  `ssa.f90` produces numbers that parse. The live Kundur test is the guard, and
  the banner is the guard against the one change already known to have moved a
  column.
- **`workdir` changes the process working directory.** It is restored in a
  `finally`, but a caller running two analyses from threads would interleave
  them. `sim` already documents that concurrent instances are unsupported, so
  this adds no new constraint, and it is stated in the module docstring.

## Appendix: file format reference

Fixed field offsets, zero-based, half-open, as `Columns.java` applies them.
Trailing blanks are padding and are stripped; a leading blank is part of a name
and is kept, which is why the two name fields below are marked as such.

`<base>_modes.dat`, banner `# STEPSS SSA modes v2`:

| Field | Columns |
|---|---|
| `index` | 0 to 8 |
| `re` | 9 to 33 |
| `im` | 34 to 58 |
| `zeta` | 59 to 83 |
| `freq_hz` | 84 to 108 |
| `smp` | 109 to 111 |

Header keys, read by name so that a later engine adding one breaks nothing:
`nstates`, `nalg`, `time`, `pf_floor`, `gap_tol`. An absent key is `None`
rather than zero.

`<base>_pf.dat`:

| Field | Columns |
|---|---|
| `mode` | 0 to 8 |
| `state` | 9 to 17 |
| `pf` | 18 to 42 |
| `family` | 43 to 51, trimmed |
| `device` | 52 to 72, leading blank kept |
| `variable` | 73 to 93, trimmed |

`<base>_ms.dat`:

| Field | Columns |
|---|---|
| `mode` | 0 to 8 |
| `state` | 9 to 17 |
| `magnitude` | 18 to 42 |
| `angle_deg` | 43 to 67 |
| `device` | 68 to 88, leading blank kept |

Archive manifest `stepss-ssa.txt`, first line
`# STEPSS small-signal archive v1`, then one key per line, absent keys omitted
rather than written as zero: `basename`, `engine_version` (`%.2f`), `t`
(`%.6f`), `saved_by`.
