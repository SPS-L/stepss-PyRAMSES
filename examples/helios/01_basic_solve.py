#!/usr/bin/env python
"""Basic helios workflow: load a network, solve, and read the results."""

from pathlib import Path

from stepss.helios import HeliosSession

DATA = Path(__file__).resolve().parents[2] / "tests" / "data" / "6bus_mg.dat"

with HeliosSession() as pf:
    pf.load_file(DATA)

    converged = pf.solve()
    print(f"converged: {converged} in {pf.iterations} iterations")
    print(f"largest remaining mismatch: {pf.max_mismatch[0]:.4f} MW, "
          f"{pf.max_mismatch[1]:.4f} Mvar")

    print("\nBus voltages:")
    for name in pf.bus_names():
        v, angle = pf.get_bus_voltage(name)
        print(f"  {name:8s} {v:7.4f} pu  {angle:+8.4f} rad")

    print("\nBranch flows (from-end):")
    for name in pf.branch_names():
        p, q = pf.get_branch_flow(name)
        print(f"  {name:8s} {p:8.3f} MW  {q:8.3f} Mvar")
