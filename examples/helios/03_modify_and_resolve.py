#!/usr/bin/env python
"""Modify the network (trip a branch, change loads) and re-solve.

Modifications accumulate an active-power imbalance that apply_changes()
settles: connectivity check, redispatch onto the remaining generators, and
a re-solve — the same workflow as the interactive modify menu.
"""

from pathlib import Path

from pyramses.helios import HeliosSession

DATA = Path(__file__).resolve().parents[2] / "tests" / "data" / "6bus_mg.dat"

with HeliosSession() as pf:
    pf.load_file(DATA)
    pf.solve()

    print("Base case:")
    for name in ("B-C", "D-E"):
        p, q = pf.get_branch_flow(name)
        print(f"  {name:6s} {p:8.3f} MW")

    # Trip a line and settle
    pf.trip_branch("B-C")
    converged = pf.apply_changes()
    print(f"\nAfter tripping B-C (converged: {converged}):")
    for name in ("B-C", "D-E"):
        p, q = pf.get_branch_flow(name)
        print(f"  {name:6s} {p:8.3f} MW")

    # Back to the base case, then grow the load at bus D by 50%
    pf.reset()
    pf.solve()
    base = pf.get_bus_info("D")
    pf.set_load("D", base.p_load_mw * 1.5, base.q_load_mvar * 1.5)
    pf.apply_changes()
    print(f"\nAfter 50% load increase at D: {pf.last_error.strip()}")
    p_gen, q_gen, status = pf.get_generator_outputs()
    for name, p in zip(pf.generator_names(), p_gen):
        print(f"  generator {name}: {p:6.3f} MW")
