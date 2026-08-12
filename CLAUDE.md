# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

stepss is the Python interface to RAMSES, the time-domain dynamic simulator
in the STEPSS platform, plus `stepss.helios`, a wrapper over the Helios AC
power-flow engine. It builds neither native component: it **bundles** shared
libraries built by `stepss-ramses` and `stepss-helios` (both private) and
ships them inside a single fat `py3-none-any` wheel on PyPI.

Package source lives under `src/`; `src/setup.py` parses `__version__` out of
`src/stepss/__init__.py` by regex rather than importing it, so that
assignment must stay a plain `__version__ = 'x.y.z'` at the start of a line.

## CI-managed paths: do not hand-edit

- `src/stepss/libs/{lin,win,mac}/`: the bundled binaries
- `src/stepss/_bundled.py`: records which upstream versions are bundled
- `src/stepss/__init__.py`'s `__version__`: bumped by the automation

These are written by `.github/workflows/sync-upstream-release.yml`. A manual
edit is silently overwritten by the next sync, and editing `_bundled.py` by
hand will make a genuine sync look like a duplicate and be skipped.

To refresh binaries deliberately, run the same scripts CI runs:

```sh
tools/update_ramses_libs.sh v3.55     # needs gh auth for SPS-L/stepss-ramses
tools/update_helios_libs.sh v1.2.0    # needs gh auth for SPS-L/stepss-helios
```

## Version numbers

The version is `<bundled RAMSES version>[.<counter>]`, so its leading
components always name the RAMSES shared library inside the wheel. Same rule
and same algorithm as `next_version` in stepss-java-ui's `tools/ci/release.py`:

| Trigger | Version |
|---|---|
| ramses publishes v3.57 | `3.57` |
| helios publishes after that | `3.57.1` |
| python-only release after that | `3.57.2` |
| ramses publishes v3.58 | `3.58` |

`tools/bump_version.sh` derives the counter from **the tags that already
exist**, not from a stored number, so there is nothing to drift out of step: a
RAMSES bump restarts the sequence by itself, because no tag on the new base
exists yet, and re-running a failed release recomputes the same value. The
checkout it runs under therefore needs the tags, hence `fetch-depth: 0`.

The bare version goes to whichever release is *first* on a given RAMSES base,
whatever triggered it; a helios release is `.1` only if a release on that base
already happened.

Versions up to and including `0.3.5` predate this scheme: they were a plain
incrementing patch with no relation to the bundled RAMSES. `0.3.5` already
bundles v3.57, so the first release under the new rule is `3.57`.

## Release automation

Publishing a release in either upstream fires `repository_dispatch` at this
repo (`ramses-release` / `helios-release`). The sync workflow then refreshes
only that upstream's binaries, computes the version, builds the wheel
**once**, and gates *that exact wheel* with the full pytest suite on
`ubuntu-24.04`, `windows-latest` and `macos-15`. Only if all three pass does it
fast-forward `master`, cut a release, and publish to PyPI.

A **python-only release** takes the same path, triggered by hand:
`workflow_dispatch` with source `manual` and `publish` ticked. It refreshes no
binaries and changes no bundled version; it just takes the next counter on the
current base and puts the package through the identical build-and-gate.

Things that are easy to get wrong here:

- **PyPI runs last, deliberately.** A version number can never be reclaimed, so
  every recoverable step happens first. If the upload alone fails, the tested
  wheel is already attached to the GitHub release and
  `python-publish.yml` (break-glass, `workflow_dispatch` with a tag input)
  uploads that file. It does **not** rebuild: rebuilding would ship bytes no
  gate ever saw.
- **`workflow_dispatch` rehearses unless `publish` is ticked.** Left off, it
  runs fetch → build → gate and stops, reaching neither `master` nor PyPI, which
  is how the pipeline is tested. `release` is gated on
  `needs.fetch.outputs.rehearsal == 'false'` alone, so ticking `publish` is what
  makes a hand-triggered run real. Do not "simplify" that guard: the quoting on
  the `'true'` / `'false'` string comparisons is load-bearing, since an
  unquoted comparison coerces an empty input and would fail *open*; an
  unset `publish` must land on rehearsal.
- **A duplicate dispatch is skipped**, by comparing the incoming tag against
  `_bundled.py`. `client_payload[force]=true` bypasses that one guard and
  nothing else, for the case where a bundle was refreshed outside the
  automation and never published. It is a deliberate human action; an upstream
  must never set it, or every re-run of its release workflow spends a PyPI
  version.
- **A superseded sync is silent.** GitHub keeps one pending run per concurrency
  group, and a run cancelled while queued executes *zero* jobs, so nothing
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
  fail on a legitimate solver change: that is a reviewed baseline update, not
  an automatic pass.
- **The collapse trip is by design.** `execSim()` raises `RAMSESError` with flag
  `-1` and a message naming `sim_minmaxvolt`; a run that completes cleanly is
  the regression. `RAMSESError` is not exported at package level: import it
  from `stepss.globals`.
- **Do not call `endSim()` after the trip.** It raises a second, unrelated
  `RAMSESError` ("Load records") that masks the real result. `obs.trj` is
  already complete without it.

Helper scripts in `tools/` each have a `tools/test_*.sh` alongside them (the
convention `stepss-uramses` uses). Run them after any change:

```sh
bash tools/test_bump_version.sh
bash tools/test_update_ramses_libs.sh
bash tools/test_compare_versions.sh
bash tools/test_compat_shim.sh
```

**Logic that a workflow depends on belongs in `tools/`, not in a heredoc.**
`bundled-drift-check.yml` used to compare versions with an inlined Python
snippet that required exactly three numeric components, justified by a comment
claiming `bump_version.sh` enforced that shape. When the scheme changed to
`<ramses-version>[.<counter>]`, the commit updated `bump_version.sh`, its
tests, the sync workflow and this file, but not that snippet. Nothing tested
it, so the mismatch stayed invisible until the first bare release (`3.58`)
turned the scheduled run red. It now lives in `tools/compare_versions.py` with
a test beside it, which is the only reason that class of drift is catchable.

## Bundled binaries have system dependencies

`ramses.so` is dynamically linked against OpenBLAS and the GCC/gfortran
runtimes. A machine without them fails at library load, not at import:

- Linux: `libopenblas0 libgfortran5 libgomp1`
- macOS: `brew install openblas gcc`, and RAMSES on macOS is **arm64 only**
- Windows: nothing; that build is statically linked and self-contained

Every CI job that loads the library installs these. Windows needs no step, and
adding one is wasted time. `libhelios_api.so` needs only `libstdc++`, which is
why the Helios tests passed for a long time before any test exercised RAMSES.

## Conventions

- Never chain git commands with `&&`, `||` or `;`. Run each separately.
- Never use `gh api -F`; always `-f`. `-F` reads a value from a local file when
  it starts with `@`, and git permits a tag named `@evil`.
- The RAMSES API is camelCase (`addData`, `execSim`); `stepss.helios` is
  deliberately PEP 8 snake_case.
- The `pyramses` distribution is a frozen forwarding shim in `compat/pyramses/`,
  published once by `publish-compat-shim.yml`. Do not release it again, and do
  not rename that workflow file: the PyPI trusted publisher binds to it.
