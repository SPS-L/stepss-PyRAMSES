#!/usr/bin/env python
"""Export the solved operating point: data-file dump, LFRESV voltages,
MATLAB script, and an SVG one-line diagram."""

import tempfile
from pathlib import Path

from pyramses.helios import HeliosSession

DATA_DIR = Path(__file__).resolve().parents[2] / "tests" / "data"

with HeliosSession() as pf, tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp)
    pf.load_file(DATA_DIR / "6bus_mg.dat")
    pf.solve()

    # A dump re-loads as a regular data file reproducing this operating point
    pf.write_dump(out / "solved_case.dat")

    # LFRESV records: power-flow solution usable as RAMSES initial conditions
    pf.write_voltrat(out / "volt_rat.dat")

    # Operating point + Y-bus as a MATLAB script
    pf.write_matlab(out / "system.m")

    # SVG one-line diagram from a placeholder template
    pf.write_diagram(DATA_DIR / "6bus_mg.svg", out / "diagram.svg")

    for f in sorted(out.iterdir()):
        print(f"{f.name:16s} {f.stat().st_size:6d} bytes")
