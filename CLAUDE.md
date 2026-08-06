# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PyRAMSES is the Python interface to RAMSES, the time-domain dynamic simulator
in the STEPSS platform, plus `pyramses.helios`, a wrapper over the Helios AC
power-flow engine. It builds neither native component: it **bundles** shared
libraries built by `stepss-ramses` and `stepss-helios` (both private) and
ships them inside a single fat `py3-none-any` wheel on PyPI.

Package source lives under `src/`; `src/setup.py` parses `__version__` out of
`src/pyramses/__init__.py` by regex rather than importing it, so that
assignment must stay a plain `__version__ = 'x.y.z'` at the start of a line.

## CI-managed paths — do not hand-edit

- `src/pyramses/libs/{lin,win,mac}/` — the bundled binaries
- `src/pyramses/_bundled.py` — records which upstream versions are bundled
- `src/pyramses/__init__.py`'s `__version__` — bumped by the automation

These are written by `.github/workflows/sync-upstream-release.yml`. A manual
edit is silently overwritten by the next sync, and editing `_bundled.py` by
hand will make a genuine sync look like a duplicate and be skipped.

To refresh binaries deliberately, run the same scripts CI runs:

```sh
tools/update_ramses_libs.sh v3.55     # needs gh auth for SPS-L/stepss-ramses
tools/update_helios_libs.sh v1.2.0    # needs gh auth for SPS-L/stepss-helios
```

## Release automation

Publishing a release in either upstream fires `repository_dispatch` at this
repo (`ramses-release` / `helios-release`). The sync workflow then refreshes
only that upstream's binaries, bumps the patch version, builds the wheel
**once**, and gates *that exact wheel* with the full pytest suite on
`ubuntu-24.04`, `windows-latest` and `macos-15`. Only if all three pass does it
fast-forward `master`, cut a release, and publish to PyPI.

Things that are easy to get wrong here:

- **PyPI runs last, deliberately.** A version number can never be reclaimed, so
  every recoverable step happens first. If the upload alone fails, the tested
  wheel is already attached to the GitHub release and
  `python-publish.yml` (break-glass, `workflow_dispatch` with a tag input)
  uploads that file. It does **not** rebuild — rebuilding would ship bytes no
  gate ever saw.
- **`workflow_dispatch` is rehearsal-only.** It runs fetch → build → gate and
  stops; `release` requires `github.event_name == 'repository_dispatch'`. This
  is how the pipeline is tested without publishing. Do not "simplify" that
  guard: the `== 'false'` quoting on the rehearsal check is load-bearing, since
  an unquoted comparison coerces an empty string to `false` and would fail
  *open*.
- **A duplicate dispatch is skipped**, by comparing the incoming tag against
  `_bundled.py`. `client_payload[force]=true` bypasses that one guard and
  nothing else — for the case where a bundle was refreshed outside the
  automation and never published. It is a deliberate human action; an upstream
  must never set it, or every re-run of its release workflow spends a PyPI
  version.
- **A superseded sync is silent.** GitHub keeps one pending run per concurrency
  group, and a run cancelled while queued executes *zero* jobs — so nothing
  inside the workflow can report it. `bundled-drift-check.yml` is the backstop:
  it compares bundled versions against each upstream's latest, and `master`'s
  version against PyPI, and files an issue on divergence.

## Testing

```sh
pip install ./src pytest
pytest tests/ -v
```

`tests/test_nordic.py` is the RAMSES regression gate: it drives the Nordic
voltage-collapse case through the shared library and compares the trajectory
against `tests/baselines/nordic_baseline.npz` via `tools/compare_trj.py`.

- **The baseline is shared byte-for-byte with `stepss-ramses`.** The shared
  library and the standalone executable reach the same trajectory bit-exactly
  on all three platforms, so one baseline serves both repos. Keep them in step;
  see `tests/baselines/README.md` before regenerating, and expect the gate to
  fail on a legitimate solver change — that is a reviewed baseline update, not
  an automatic pass.
- **The collapse trip is by design.** `execSim()` raises `RAMSESError` with flag
  `-1` and a message naming `sim_minmaxvolt`; a run that completes cleanly is
  the regression. `RAMSESError` is not exported at package level — import it
  from `pyramses.globals`.
- **Do not call `endSim()` after the trip.** It raises a second, unrelated
  `RAMSESError` ("Load records") that masks the real result. `obs.trj` is
  already complete without it.

Helper scripts in `tools/` each have a `tools/test_*.sh` alongside them (the
convention `stepss-uramses` uses). Run them after any change:

```sh
bash tools/test_bump_version.sh
bash tools/test_update_ramses_libs.sh
```

## Bundled binaries have system dependencies

`ramses.so` is dynamically linked against OpenBLAS and the GCC/gfortran
runtimes. A machine without them fails at library load, not at import:

- Linux: `libopenblas0 libgfortran5 libgomp1`
- macOS: `brew install openblas gcc` — and RAMSES on macOS is **arm64 only**
- Windows: nothing; that build is statically linked and self-contained

Every CI job that loads the library installs these. Windows needs no step, and
adding one is wasted time. `libhelios_api.so` needs only `libstdc++`, which is
why the Helios tests passed for a long time before any test exercised RAMSES.

## Conventions

- Never chain git commands with `&&`, `||` or `;` — run each separately.
- Never use `gh api -F`; always `-f`. `-F` reads a value from a local file when
  it starts with `@`, and git permits a tag named `@evil`.
- The RAMSES API is camelCase (`addData`, `execSim`); `pyramses.helios` is
  deliberately PEP 8 snake_case.
