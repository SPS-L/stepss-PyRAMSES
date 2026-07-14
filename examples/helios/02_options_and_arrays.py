#!/usr/bin/env python
"""Solver options and vectorized (NumPy) result extraction."""

from pathlib import Path

from pyramses.helios import HeliosSession, Option

DATA = Path(__file__).resolve().parents[2] / "tests" / "data" / "6bus_mg.dat"

with HeliosSession() as pf:
    pf.load_file(DATA)

    # Options are read from the data file's $PARAM records at load time and
    # can be overridden afterwards (always set options AFTER load_file).
    print(f"tolerance from file: {pf.get_option(Option.TOLAC)} MW")
    pf.set_option(Option.TOLAC, 0.001)
    pf.set_option(Option.TOLREAC, 0.001)
    pf.set_option(Option.MAX_ITER, 30)

    pf.solve()

    # Bulk getters return NumPy arrays indexed like the *_names() lists.
    v_pu, angle_rad = pf.get_bus_voltages()
    p_load, q_load = pf.get_bus_loads()
    p_from, q_from, p_to, q_to = pf.get_branch_flows()
    p_gen, q_gen, gen_status = pf.get_generator_outputs()

    print(f"voltage range: {v_pu.min():.4f} - {v_pu.max():.4f} pu")
    print(f"total load: {p_load.sum():.2f} MW")
    print(f"total generation: {p_gen.sum():.2f} MW")
    print(f"total series loss: {(p_from + p_to).sum():.4f} MW")
