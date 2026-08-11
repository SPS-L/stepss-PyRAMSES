#!/usr/bin/env python
"""Contingency screening: automatic N-1 and file-driven contingency lists."""

from pathlib import Path

from stepss.helios import HeliosSession

DATA_DIR = Path(__file__).resolve().parents[2] / "tests" / "data"

with HeliosSession() as pf:
    pf.load_file(DATA_DIR / "6bus_mg.dat")
    pf.solve()

    # Automatic N-1 over branches and generators, with a tight voltage band
    # so some contingencies are rejected.
    results = pf.run_contingencies(branches=True, generators=True,
                                   v_min=0.95, v_max=1.05)

    print(f"{'contingency':<16s} {'conv':<5s} {'accepted':<9s} "
          f"{'Vmin':>7s} {'Vmax':>7s}  violations")
    for r in results:
        print(f"{r.name:<16s} {str(r.converged):<5s} {str(r.accepted):<9s} "
              f"{r.min_v_pu:7.4f} {r.max_v_pu:7.4f}  {len(r.violations)}")
        for violation in r.violations:
            print(f"    - {violation}")

    # The same engine also reads Fortran-format contingency files
    # (BT/GT/ST/HC actions, end_contingency terminated).
    results = pf.run_contingencies(file=DATA_DIR / "6bus_mg_contingency.txt")
    print(f"\nfrom file: {[r.name for r in results]}")
