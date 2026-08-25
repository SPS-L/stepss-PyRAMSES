"""The run driver: settings override, generated disturbance, clearing, loading."""

import shutil
from pathlib import Path

import pytest

import stepss
from stepss import ssa
from stepss.globals import RAMSESError

# sim.__del__ warns on every collection by design, and ssa.run() creates a
# simulator per call, so without this the suite reports one warning per test.
# The filter is narrow on purpose: the point of a pristine test log is that a
# genuinely new warning is visible in it, and only this one notice is silenced.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Simulator with number:UserWarning")

CASE_DIR = Path(__file__).resolve().parents[1] / "examples" / "eigenanalysis"


def kundur_case(work, dynfile):
    """Copy the Kundur case into *work* and return a cfg naming it by absolute path."""
    for name in ("lf.dat", dynfile, "solveroptions.dat", "nothing.dst", "obs.dat"):
        shutil.copy(CASE_DIR / name, work / name)
    case = stepss.cfg()
    case.addData(str(work / "lf.dat"))
    case.addData(str(work / dynfile))
    case.addData(str(work / "solveroptions.dat"))
    case.addDst(str(work / "nothing.dst"))
    case.addObs(str(work / "obs.dat"))
    case.addTrj("out.trj")
    return case


def interarea(res):
    band = [m for m in res.electromechanical().rows if 0.4 < m["freq"] < 0.9]
    assert len(band) == 1
    return band[0]


def test_run_reproduces_kundur_example_12_6(tmp_path):
    """Without the stabilisers the inter-area mode is unstable; with them it is not.

    The numbers are the ones examples/eigenanalysis/README.md records.
    """
    modes = {}
    for tag, dynfile in (("nopss", "dyn_noPSS.dat"), ("pss", "dyn.dat")):
        work = tmp_path / tag
        work.mkdir()
        modes[tag] = interarea(ssa.run(kundur_case(work, dynfile),
                                       basename="ssa", workdir=work))

    assert modes["nopss"]["freq"] == pytest.approx(0.625, abs=5e-3)
    assert modes["nopss"]["zeta"] == pytest.approx(-0.0233, abs=5e-3)
    assert modes["pss"]["freq"] == pytest.approx(0.624, abs=5e-3)
    assert modes["pss"]["zeta"] == pytest.approx(0.1087, abs=5e-3)


def test_run_does_not_mutate_the_callers_case(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    before = list(case.getData())
    ssa.run(case, basename="ssa", workdir=tmp_path)
    assert list(case.getData()) == before


def test_run_writes_the_settings_override_and_leaves_the_case_alone(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    original = (tmp_path / "solveroptions.dat").read_text()
    ssa.run(case, basename="ssa", workdir=tmp_path)
    assert (tmp_path / ssa.settings_name("ssa")).is_file()
    assert (tmp_path / "solveroptions.dat").read_text() == original


def test_run_clears_a_previous_run_before_starting(tmp_path):
    """A run that produces nothing must not read the previous run's spectrum."""
    ssa.run(kundur_case(tmp_path, "dyn_noPSS.dat"), basename="ssa", workdir=tmp_path)
    assert (tmp_path / "ssa_modes.dat").is_file()

    broken = kundur_case(tmp_path, "dyn_noPSS.dat")
    broken.clearData()
    broken.addData(str(tmp_path / "lf.dat"))  # no dynamic data to linearise
    with pytest.raises(RAMSESError):
        ssa.run(broken, basename="ssa", workdir=tmp_path)
    assert not (tmp_path / "ssa_modes.dat").exists(), (
        "the previous run's file survived and would have been read as this run's")


def test_run_refuses_a_basename_colliding_with_a_data_file(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    collision = tmp_path / ssa.settings_name("ssa")
    collision.write_text("$SCHEME DE                         ;\n")
    case.addData(str(collision))
    with pytest.raises(RAMSESError, match="loaded data file"):
        ssa.run(case, basename="ssa", workdir=tmp_path)
    assert collision.read_text() == "$SCHEME DE                         ;\n"


def test_run_generates_a_disturbance_file_when_the_case_has_none(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    case.clearDst()
    ssa.run(case, basename="ssa", workdir=tmp_path)
    assert (tmp_path / ssa.disturbance_name("ssa")).is_file()
    assert (tmp_path / "ssa_modes.dat").is_file()


def test_run_with_jacobian_writes_all_seven_members(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    ssa.run(case, basename="ssa", workdir=tmp_path, jacobian=True)
    for name in ssa.members("ssa"):
        assert (tmp_path / name).is_file(), name


def test_run_without_jacobian_writes_only_the_results(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    ssa.run(case, basename="ssa", workdir=tmp_path)
    for suffix in ssa.JACOBIAN_SUFFIXES:
        assert not (tmp_path / ("ssa" + suffix)).exists()


def test_run_makes_the_working_directory_if_it_is_missing(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    target = tmp_path / "fresh"
    res = ssa.run(case, basename="ssa", workdir=target)
    assert (target / "ssa_modes.dat").is_file()
    assert Path(res.directory) == target


def test_run_restores_the_working_directory(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    import os
    before = os.getcwd()
    ssa.run(case, basename="ssa", workdir=tmp_path / "elsewhere")
    assert os.getcwd() == before


def test_state_matrix_is_available_from_a_live_run(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    res = ssa.run(case, basename="ssa", workdir=tmp_path)
    assert res.state_matrix.shape == (res.nstates, res.nstates)


def test_state_matrix_refuses_after_a_later_analysis(tmp_path):
    """The engine retains one at a time and checks only the order."""
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    ram = stepss.sim()
    first = ssa.run(case, basename="one", workdir=tmp_path, ram=ram, keep_open=True)
    assert first.state_matrix.shape[0] == first.nstates
    ram.runSsa("two", t=0.5)
    with pytest.raises(RAMSESError, match="replaced"):
        first.state_matrix
    ram.endSim()


def test_state_matrix_is_absent_from_results_read_from_disk(tmp_path):
    case = kundur_case(tmp_path, "dyn_noPSS.dat")
    ssa.run(case, basename="ssa", workdir=tmp_path)
    reloaded = ssa.load(tmp_path, "ssa")
    with pytest.raises(RAMSESError, match="live run"):
        reloaded.state_matrix
