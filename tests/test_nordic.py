"""Nordic voltage-collapse regression gate for the bundled RAMSES library.

Drives the same case the stepss-ramses release gate runs -- dyn_A +
volt_rat_A + short_trip_branch.dst -- but through the C API rather than the
standalone executable, and compares the trajectory against the shared
baseline.

The collapse is by design: sim_minmaxvolt trips at t = 163.14 s, RAMSES
returns flag -1, and stepss turns that into a RAMSESError. A run that
completes without raising is a regression, not a success.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = REPO_ROOT / "tests" / "data" / "nordic"
BASELINE = REPO_ROOT / "tests" / "baselines" / "nordic_baseline.npz"
COMPARATOR = REPO_ROOT / "tools" / "compare_trj.py"

# Measured on the bundled library; the comparator also enforces it to +/- 1 s.
EXPECTED_TRIP_TIME = 163.14
TRIP_TOL = 1.0


@pytest.fixture(scope="module")
def nordic_run(tmp_path_factory):
    """Run the Nordic case once in an isolated directory; yield that directory.

    RAMSES writes roughly 100 MB of output and resolves every path relative to
    the working directory, so the case is copied into a fresh tmp dir.
    """
    import stepss
    from stepss.globals import RAMSESError

    run_dir = tmp_path_factory.mktemp("nordic")
    for src in sorted(CASE_DIR.glob("*")):
        if src.suffix in {".dat", ".dst"}:
            shutil.copy(src, run_dir / src.name)

    cwd = Path.cwd()
    import os

    os.chdir(run_dir)
    try:
        case = stepss.cfg()
        case.addData("dyn_A.dat")
        case.addData("volt_rat_A.dat")
        case.addData("settings1.dat")
        case.addObs("obs.dat")
        case.addDst("short_trip_branch.dst")
        case.addTrj("obs.trj")
        case.addOut("output.trace")
        case.addInit("init.trace")
        case.addCont("cont.trace")
        case.addDisc("disc.trace")

        ram = stepss.sim()
        trip = None
        try:
            ram.execSim(case)
        except RAMSESError as exc:
            trip = exc
        sim_time = ram.getSimTime()
        # Deliberately NOT calling ram.endSim(): after the trip it raises a
        # second, unrelated RAMSESError ("Load records") that masks the real
        # result. obs.trj is already complete at this point.
    finally:
        os.chdir(cwd)

    return {"dir": run_dir, "trip": trip, "sim_time": sim_time}


def test_collapse_trips(nordic_run):
    """The case must trip on under-voltage, not run to completion."""
    trip = nordic_run["trip"]
    assert trip is not None, "Nordic case completed without tripping; expected sim_minmaxvolt"
    assert "sim_minmaxvolt" in str(trip)


def test_trip_time(nordic_run):
    """The trip instant is the headline regression signal."""
    assert nordic_run["sim_time"] == pytest.approx(EXPECTED_TRIP_TIME, abs=TRIP_TOL)


def test_trajectory_matches_baseline(nordic_run):
    """Full trajectory comparison against the shared stepss-ramses baseline."""
    trj = nordic_run["dir"] / "obs.trj"
    assert trj.is_file() and trj.stat().st_size > 0, "obs.trj was not written"

    result = subprocess.run(
        [sys.executable, str(COMPARATOR), "compare", str(trj), str(BASELINE)],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    assert result.returncode == 0, "trajectory diverged from baseline"
