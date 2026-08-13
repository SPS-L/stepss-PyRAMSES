# Small-signal stability analysis: Kundur two-area system

`kundur_small_signal.ipynb` computes the eigenvalues, damping ratios,
participation factors and mode shapes of the Kundur two-area benchmark, with and
without its power system stabilisers, and shows that the inter-area mode is
unstable without them. No MATLAB is involved.

```sh
pip install stepss notebook
jupyter notebook kundur_small_signal.ipynb
```

## Requires a RAMSES newer than 3.59

The notebook drives the analysis with an `EIG` disturbance, which was added to
the engine after the 3.59 release. On an older bundle the disturbance is
accepted and no results files appear.

The `stepss` version's leading components name the bundled RAMSES, so
`stepss.__version__` tells you directly:

```python
import stepss; print(stepss.__version__)   # needs > 3.59
```

## What you should see

| | inter-area mode | area 1 local | area 2 local |
|---|---|---|---|
| **without PSS** | 0.625 Hz, zeta = **-0.0233** | 1.085 Hz, zeta = 0.099 | 1.116 Hz, zeta = 0.097 |
| **with PSS** | 0.624 Hz, zeta = **+0.1087** | 1.242 Hz, zeta = 0.288 | 1.295 Hz, zeta = 0.287 |

The sign of the inter-area damping ratio flips with the stabilisers: negative
means the 0.62 Hz oscillation between the two areas grows, so the operating
point is small-signal unstable. This reproduces Kundur, *Power System Stability
and Control*, Example 12.6.

Participation factors separate the two local modes on their own, without any
prior knowledge of the topology: the 1.085 Hz mode lists only G1 and G2, the
1.116 Hz mode only G3 and G4, and the inter-area mode lists all four.

## Files

| File | Purpose |
|---|---|
| `kundur_small_signal.ipynb` | The example, with commentary on each step |
| `lf.dat` | Power flow: buses, lines, transformers, operating point |
| `dyn.dat` | Dynamic data with the PSS enabled (`KSTAB = 20.0`) |
| `dyn_noPSS.dat` | Identical except `KSTAB = 0.0` on all four exciters |
| `solveroptions.dat` | Solver settings, including the two the analysis requires |
| `obs.dat` | Observables selection |
| `nothing.dst` | An empty disturbance set, required by the case format |

Running the notebook creates `run_pss/` and `run_nopss/`, one per variant, so
that the two sets of results files do not overwrite each other.

## Two settings the analysis requires

`solveroptions.dat` already carries both, but they matter if you adapt this to
your own system:

- **`$OMEGA_REF SYN`.** Under the default centre-of-inertia reference frame the
  engine refuses the analysis. The COI equations are computed by finite
  differences at export time and never enter the assembled Jacobian, so reducing
  under COI would silently hold COI speed constant and produce a plausible,
  wrong spectrum. The engine refuses rather than doing that.
- **`$SCHEME DE`.** Under the integrated scheme the pure differential-algebraic
  values exist only briefly inside the Newton loop, so the analysis refuses
  there too.

Both refusals are loud: the process exits 78 and the reason is available from
`getLastErr()`.

## Larger systems

The engine solves the reduced state matrix densely, which is tractable to a few
thousand states. Above `$EIG_MAX_STATES` (default 5000) it refuses and says so.
That regime needs sparse shift-invert methods, which
`scipy.sparse.linalg.eigs` can drive from the descriptor matrices `getJac()`
returns.

## Attribution

The Kundur data files are copied from
[SPS-L/stepss-test-systems](https://github.com/SPS-L/stepss-test-systems)
(Apache-2.0, `LICENSE` included here). The RAMSES implementation of the system
data is by Dr. Thierry Van Cutsem, University of Liege, 2024. Please cite the
original source of the system data:

> P. Kundur, *Power System Stability and Control*, McGraw-Hill, 1994
> (two-area system, Example 12.6).
