# PyRAMSES upstream release automation — design

Date: 2026-08-06
Status: approved, not yet implemented

## Problem

`stepss-pyramses` bundles two binaries it does not build: RAMSES
(`ramses.so` / `ramses.dll`) and the Helios C API (`libhelios_api.so` /
`libhelios_api.dylib` / `helios_api.dll`). Both come from private upstream
repositories that release on their own schedule.

Today the refresh is manual. `tools/update_helios_libs.sh` downloads a Helios
release by tag and copies the libraries into `src/pyramses/libs/`; a human then
reviews, commits, bumps the version, cuts a release, and lets
`python-publish.yml` ship to PyPI. Nothing equivalent exists for RAMSES — the
RAMSES release notes simply instruct a human to unzip three archives into
`libs/lin`, `libs/win` and `libs/mac`.

Nothing verifies the result. The pyramses test suite covers Helios only; no
test drives RAMSES at all, so a broken or mismatched RAMSES binary would reach
PyPI unnoticed.

## Goal

When either upstream publishes a release, pyramses should refresh the
corresponding binaries, prove the resulting package works on all three
platforms, and publish a new version to PyPI — without a human in the loop, and
without any path by which an unverified binary reaches PyPI.

## Decisions

These were settled during design and are not open:

| Decision | Choice |
|---|---|
| pyramses version | Automatic patch bump, plus bundled upstream versions recorded in `src/pyramses/_bundled.py` and in the release notes |
| Gate breadth | Full pytest suite (Helios tests *and* the new Nordic test) on Linux, Windows and macOS |
| Binaries in git | Committed as-is. No stripping |
| Trigger | `repository_dispatch` pushed from both upstreams |
| Download credential | Reuse the existing `RAMSES_READ_TOKEN` |
| What gets gated | The built wheel itself, not the source tree |
| PyPI ordering | Last, after the fast-forward and the GitHub release |

### Why the wheel is the gated artifact

pyramses builds a single fat `py3-none-any` wheel carrying all three
platforms' binaries (`package_data` in `src/setup.py` lists `libs/win/*.dll`,
`libs/lin/*.so`, `libs/mac/*.so`, `libs/mac/*.dylib`). One artifact therefore
serves every platform, and one artifact can be gated on every platform.

`build-wheel` produces it once; the three `nordic` jobs `pip install` that
exact file; `release` uploads those same bytes to PyPI. Nothing is rebuilt from
`master` at publish time. This closes two gaps in the obvious alternative of
gating the source tree: packaging errors (a `package_data` glob that silently
omits `libs/mac/*.dylib`, say) would otherwise be exercised only *after* the
gate passed, and a `master` that moved between gate and publish would ship
untested bytes.

Consequence: `python-publish.yml` must stop firing on `release: published`, or
two uploads race for the same version. It is narrowed to `workflow_dispatch`
only and kept as a break-glass path for the case where PyPI upload fails but
everything upstream of it succeeded.

## Architecture

```
stepss-ramses  release.yml                stepss-helios  ci.yml
  publish ──► notify-pyramses               release ──► notify-pyramses
     (skip if prerelease)                      (skip if tag has a '-')
              │  repository_dispatch                    │  repository_dispatch
              │  type: ramses-release                   │  type: helios-release
              │  payload: {tag, sha}                    │  payload: {tag, sha}
              └──────────────┬──────────────────────────┘
                             ▼
        stepss-pyramses  sync-upstream-release.yml
        concurrency: pyramses-sync (queue, never cancel)

  fetch ──► build-wheel ──► nordic (matrix ×3) ──► release
    │            │                  │                  │
    │            │                  │                  ├─ 1. fast-forward master
    │            │                  │                  ├─ 2. cut GH release
    │            │                  │                  ├─ 3. publish wheel to PyPI
    │            │                  │                  └─ 4. delete sync branch
    │            │                  │
    │            │                  └─ ubuntu-24.04 / windows-latest / macos-15
    │            │                     each: pip install THE wheel, full pytest
    │            │
    │            └─ build sdist + fat wheel once, upload as artifact
    │
    └─ validate payload → download assets (RAMSES_READ_TOKEN)
       → refresh libs/ → bump patch version → write _bundled.py
       → commit to sync/<source>-<tag>, push

  report-failure (if: failure()) ──► file/update a CI issue
```

Each upstream refreshes only its own binaries. A RAMSES release touches
`ramses.so` / `ramses.dll` and leaves the Helios libraries alone; a Helios
release does the converse. `_bundled.py` records both versions, with the
untouched one carried forward from its previous value.

## Components

### stepss-ramses — one file

`.github/workflows/release.yml` gains a `notify-pyramses` job: `needs:
[publish]`, skipped when `release.prerelease` is true, dispatching
`event_type=ramses-release` with `client_payload[tag]` and
`client_payload[sha]`.

The event type is what identifies the source, so pyramses never has to trust a
`source` field in the payload. `stepss-helios` dispatches
`event_type=helios-release`, and the receiving workflow listens for both.

It is a near-copy of the existing `notify-uramses`, including its use of `-f`
(raw-field) rather than `-F`: `-F` applies type conversion and reads a value
from a local file when it starts with `@`, and git permits a tag named
`@evil`. Both notify jobs run in parallel off the same `publish`.

Requires a new `PYRAMSES_DISPATCH_TOKEN` secret.

### stepss-helios — one file

`.github/workflows/ci.yml` gains the equivalent job after `release`.

Helios differs from RAMSES in two ways that matter. It releases directly off a
`v*` tag push via `softprops/action-gh-release`, and it has no prerelease
concept — so the guard is on tag shape: skip any tag containing `-`, so
`v1.3.0-rc1` does not cut a pyramses release. This matches RAMSES' semantics
by a different mechanism.

Requires the same `PYRAMSES_DISPATCH_TOKEN` secret in this repository.

### stepss-pyramses

| File | Status | Purpose |
|---|---|---|
| `.github/workflows/sync-upstream-release.yml` | new | the pipeline above |
| `.github/workflows/python-publish.yml` | narrowed | drop the `release:` trigger; keep `workflow_dispatch` |
| `.github/workflows/tests.yml` | extended | Nordic runs on ordinary pushes and PRs too |
| `tools/update_ramses_libs.sh` | new | RAMSES mirror of `update_helios_libs.sh` |
| `tools/bump_version.sh` | new | patch bump and `_bundled.py` write |
| `tools/compare_trj.py` | ported | trajectory comparator, from stepss-ramses |
| `tools/test_update_ramses_libs.sh` | new | script test, uramses convention |
| `tools/test_bump_version.sh` | new | script test |
| `src/pyramses/_bundled.py` | new | `RAMSES_VERSION`, `HELIOS_VERSION` |
| `tests/data/nordic/` | new | vendored case, Apache-2.0, with attribution |
| `tests/baselines/nordic_baseline.npz` | new | committed once |
| `tests/baselines/README.md` | new | how and when to regenerate |
| `tests/test_nordic.py` | new | drives `pyramses.sim`, compares trajectory |

Organising principle: **CI invokes the same `tools/` scripts a human would.**
`update_ramses_libs.sh <tag>` refreshes `libs/` exactly as the existing Helios
script does, and the workflow calls it rather than reimplementing the logic.
One implementation, and the manual path keeps working. This is the pattern
uramses already uses with `refresh_kit.sh` plus `test_refresh_kit.sh`.

## Data flow

### Upstream assets

The two upstreams name assets differently, and the automation must not assume
a shared convention.

RAMSES assets are tag-suffixed:

| Asset | Extract to |
|---|---|
| `pyramses-libs-linux-<tag>.zip` | `src/pyramses/libs/lin/ramses.so` |
| `pyramses-libs-windows-<tag>.zip` | `src/pyramses/libs/win/ramses.dll` |
| `pyramses-libs-macos-arm64-<tag>.zip` | `src/pyramses/libs/mac/ramses.so` |

Helios assets are not:

| Asset | Extract to |
|---|---|
| `helios-api-linux-x86_64.tar.gz` | `src/pyramses/libs/lin/libhelios_api.so` |
| `helios-api-macos-universal.tar.gz` | `src/pyramses/libs/mac/libhelios_api.dylib` |
| `helios-api-windows-x64.zip` | `src/pyramses/libs/win/helios_api.dll` |
| (from the Linux archive) | `src/pyramses/libs/helios_api.h` |

Note the macOS asymmetry: the RAMSES macOS build is arm64-only, while the
Helios macOS build is a universal binary. The `macos-15` runner is arm64 and
satisfies both. macOS RAMSES keeps the filename `ramses.so`, not `.dylib` —
pyramses separates platforms by directory, not by extension.

### Versioning

`fetch` bumps the patch component of `__version__` in
`src/pyramses/__init__.py` (`0.3.0` → `0.3.1`) and writes
`src/pyramses/_bundled.py`:

```python
RAMSES_VERSION = "v3.55"
HELIOS_VERSION = "v1.2.0"
```

The value for the upstream that did *not* release is read from the existing
`_bundled.py` and carried forward. Release notes state both.

The pyramses tag is `v<new-version>`, independent of upstream tags.

## Error handling

| Failure | Response |
|---|---|
| Malformed dispatch tag | `grep -qzE '^v[0-9][0-9A-Za-z.+-]*$'` against the whole string, so an embedded newline cannot smuggle a second `key=value` into `$GITHUB_OUTPUT`. Source is taken from the event type, never the payload |
| Tag already synced | `fetch` refuses if the computed pyramses tag exists as either a tag or a release, making a duplicate dispatch a no-op |
| Expected asset missing | Hard fail in `fetch`, naming the asset, before anything is committed |
| `master` moved mid-run | `base_sha` captured in `fetch` and re-checked before the fast-forward; refuse rather than rebase a tree that was never gated |
| Gate red on any platform | No fast-forward, no release, no PyPI. Sync branch left in place for inspection; issue filed |
| Two upstream releases at once | `concurrency: pyramses-sync`, queued not cancelled. `fetch` checks out `master` by name, so a queued run resolves it at run time rather than replaying a stale dispatch-time SHA |

`report-failure` reports how far the run got — whether `master` moved, whether
the GitHub release was cut, whether PyPI was published — because recovery
differs sharply between them. The PyPI case is the one that cannot be retried:
that version number is spent and the fix is a further patch bump.

Ordering exists to make that case rare. PyPI runs last, so the common failure
leaves the version unspent. If PyPI alone fails, the tested wheel is still
attached to the GitHub release and `python-publish.yml` can upload it by hand.

## Testing

Three layers.

**Script tests** (`tools/test_*.sh`, uramses convention). A fake `gh` on
`PATH` — the technique `stepss-ramses/tools/test_write_buildinfo.sh` uses to
fake `brew` and `pacman` — lets these run on a laptop with no network. They
assert that assets land in the correct per-platform directories, that `0.3.0`
becomes `0.3.1`, and that `_bundled.py` carries the untouched upstream's
version forward rather than blanking it.

**`tests/test_nordic.py`.** Drives the Nordic voltage-collapse case through
`pyramses.cfg()` / `pyramses.sim()` using the CI variant (`dyn_A.dat`,
`volt_rat_A.dat`, `settings1.dat`, `obs.dat`, `short_trip_branch.dst`),
extracts the trajectory and compares it against the baseline.

The case is vendored into `tests/data/nordic/`. It is Apache-2.0 and is
already published as PyRAMSES teaching material, so it is safe to carry in a
public repository; attribution and the licence travel with it.

Note that the collapse is a *by-design* trip. RAMSES' own gate asserts exit
code 255 (Linux) or 127 (MSYS2) for the `sim_minmaxvolt` trip and treats 0 as
a failure. Through the C API this will surface differently — most likely as a
pyramses exception rather than a process exit code. The test asserts that the
trip occurred, and the exact mechanism is to be confirmed against the real
library during implementation.

**The gate matrix.** Full `pytest tests/` against the installed wheel on
`ubuntu-24.04`, `windows-latest` and `macos-15`. This covers the existing
Helios suite (`test_helios_basic`, `test_helios_outputs`, `test_helios_modify`,
`test_helios_data`, `test_examples`) as well as `test_nordic`, and both run on
every sync regardless of which upstream triggered it — so a RAMSES refresh
cannot silently break Helios, and vice versa.

### Baseline

First attempt is to reuse `stepss-ramses`' `nordic_baseline.npz` unchanged.
The inputs are identical, so the library path should reproduce the executable
path's trajectory, and a single shared baseline across both repositories is
worth having. If the two paths diverge, a pyramses-specific baseline is
generated from the known-good v3.55 library instead.

`tests/baselines/README.md` records how to regenerate it. A future RAMSES that
legitimately changes numerics *should* fail this gate: that is a deliberate
baseline update in a reviewed pull request, not an automatic pass.

### Rehearsing the workflow

`sync-upstream-release.yml` also accepts `workflow_dispatch` with `source`
(`ramses` or `helios`) and `tag` inputs.

**A `workflow_dispatch` run is always a rehearsal.** There is no toggle. It
runs `fetch`, `build-wheel` and `nordic`, then stops: the `release` job is
gated on `github.event_name == 'repository_dispatch'`, so the fast-forward,
the GitHub release and the PyPI upload are unreachable by hand. `fetch` also
skips the branch push on this path, leaving no `sync/` branch behind.

This exists so the pipeline can be proven end-to-end against the real v3.55
and v1.2.0 assets before either upstream is wired up, rather than discovering
problems during a live release. Making it unconditional rather than an opt-in
flag means there is exactly one route to PyPI, and it starts at an upstream
release.

## Secrets

The dispatch token lives in the *sending* repositories and the read token in
the *receiving* one, mirroring how the working RAMSES → URAMSES pair is wired
(`stepss-ramses` holds `URAMSES_DISPATCH_TOKEN`; `stepss-uramses` holds
`RAMSES_READ_TOKEN`).

| Repository | Role | Secret | State as of 2026-08-06 |
|---|---|---|---|
| `stepss-ramses` | sender | `PYRAMSES_DISPATCH_TOKEN` | present |
| `stepss-helios` | sender | `PYRAMSES_DISPATCH_TOKEN` | present |
| `stepss-pyramses` | receiver | `RAMSES_READ_TOKEN` | **missing** |
| `stepss-pyramses` | receiver | `PYPI_API_TOKEN` | present |

`RAMSES_READ_TOKEN` is the one remaining gap. Without it `fetch` cannot
download release assets from either private upstream, so every sync fails at
its first download step. It must be able to read releases in **both**
`stepss-ramses` and `stepss-helios` — see the open items below.

## Open items for implementation

1. **Secrets** must be placed as tabulated above before either upstream path
   works.
2. **`RAMSES_READ_TOKEN` scope.** In `stepss-uramses` it is used only against
   `stepss-ramses`. The pyramses copy must also read `stepss-helios` releases.
   If the token is fine-grained and scoped to a single repository, it needs
   widening or Helios needs a separate read token. Secret scope is not
   introspectable, so this must be confirmed by trying it.
3. **Nordic trip semantics through the C API** — confirm how the by-design
   collapse surfaces in pyramses, and assert on that.
4. **Baseline reuse** — confirm the library path reproduces the executable
   path's trajectory; generate a pyramses-specific baseline if not.

## Out of scope

- Moving PyPI publishing to Trusted Publishing (OIDC). The existing
  `PYPI_API_TOKEN` is reused.
- Per-platform wheels. The fat `py3-none-any` wheel is retained.
- Stripping binaries or otherwise addressing repository growth. Binaries are
  committed as they arrive, matching how uramses commits its module kits.
- The Windows/Intel RAMSES route, which no CI produces.
