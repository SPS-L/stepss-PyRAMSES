"""End-to-end check that stepss.monitor drives the bundled RAMSES library.

The unit tests in test_live.py fake the engine. This one runs the real thing:
it initialises the Nordic case, steps it forward with monitor.run() and checks
that every descriptor came back with physically plausible numbers.

The run happens in a subprocess. RAMSES keeps its state in Fortran module
variables shared by every sim() in a process, so a test that initialises a case
of its own cannot share an interpreter with test_nordic.py. The subprocess also
pins MPLBACKEND, so no runner ever tries to open a window.
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = REPO_ROOT / "tests" / "data" / "nordic"

UNTIL = 10.0
STEP = 1.0

DRIVER = textwrap.dedent(
    """
    import json
    import stepss

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
    ram.execSim(case, 0.0)

    mon = stepss.monitor(ram, ["BV 4044", "BA 4044", "MS g6",
                               "BPO 4041-4044", "RT RT"], title="Nordic")
    curves = mon.run(step=%(step)r, until=%(until)r)
    mon.savefig("live.png")

    json.dump({c.msg: {"time": c.time.tolist(), "value": c.value.tolist()}
               for c in curves}, open("curves.json", "w"))
    """
) % {"step": STEP, "until": UNTIL}


@pytest.fixture(scope="module")
def live_run(tmp_path_factory):
    """Run the driver once against the bundled library; yield its curves."""
    run_dir = tmp_path_factory.mktemp("live")
    for src in sorted(CASE_DIR.glob("*")):
        if src.suffix in {".dat", ".dst"}:
            shutil.copy(src, run_dir / src.name)
    (run_dir / "driver.py").write_text(DRIVER)

    # The subprocess must import the same stepss this session imported: the
    # installed wheel under CI, a working tree when one is on the path. Naming
    # the source tree here instead would shadow the wheel the release gate is
    # there to test.
    import stepss

    env = dict(os.environ)
    env["MPLBACKEND"] = "Agg"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path(stepss.__file__).resolve().parents[1])]
        + ([env["PYTHONPATH"]] if "PYTHONPATH" in env else []))
    done = subprocess.run([sys.executable, "driver.py"], cwd=run_dir, env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads((run_dir / "curves.json").read_text()), run_dir


def curve(live_run, prefix):
    """The one curve whose label starts with *prefix*."""
    curves = live_run[0]
    matches = [v for k, v in curves.items() if k.startswith(prefix)]
    assert len(matches) == 1, sorted(curves)
    return matches[0]


def test_every_descriptor_came_back(live_run):
    assert len(live_run[0]) == 5


def test_the_time_axis_is_the_requested_window(live_run):
    times = curve(live_run, "4044: voltage magnitude")["time"]
    # The engine pauses at the first internal step at or after the requested
    # time, so t = 0 is reported as the first step instead.
    assert times[0] == pytest.approx(0.0, abs=0.05)
    assert times[-1] == pytest.approx(UNTIL, abs=0.5)
    assert times == sorted(times)
    assert len(times) == int(UNTIL / STEP) + 1


def test_every_curve_shares_the_time_axis(live_run):
    times = {tuple(c["time"]) for c in live_run[0].values()}
    assert len(times) == 1


def test_bus_voltage_is_plausible(live_run):
    values = curve(live_run, "4044: voltage magnitude")["value"]
    assert all(0.5 < v < 1.2 for v in values), values
    assert values[0] == pytest.approx(1.0, abs=0.1)


def test_bus_phase_is_read(live_run):
    values = curve(live_run, "4044: voltage phase")["value"]
    assert all(-180.0 <= v <= 180.0 for v in values), values


def test_machine_speed_stays_near_synchronism(live_run):
    values = curve(live_run, "g6: machine speed")["value"]
    assert all(0.95 < v < 1.05 for v in values), values


def test_branch_power_flows(live_run):
    values = curve(live_run, "4041-4044: active power at the origin")["value"]
    assert any(abs(v) > 1.0 for v in values), values


def test_real_time_is_measured_and_never_goes_back(live_run):
    values = curve(live_run, "elapsed real time")["value"]
    assert values[0] == 0.0
    assert values == sorted(values)
    assert values[-1] > 0.0


def test_the_chart_is_written(live_run):
    assert (live_run[1] / "live.png").stat().st_size > 0
