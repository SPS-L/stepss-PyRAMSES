"""The two engine entries: run_ssa and get_state_matrix, through stepss.sim."""

import shutil
from pathlib import Path

import numpy as np
import pytest

import stepss
from stepss import ssa
from stepss.globals import RAMSESError

CASE_DIR = Path(__file__).resolve().parents[1] / "examples" / "eigenanalysis"
CASE_FILES = ("lf.dat", "dyn_noPSS.dat", "solveroptions.dat", "nothing.dst",
              "obs.dat")


@pytest.fixture
def kundur(tmp_path, monkeypatch):
    """The Kundur no-PSS case, copied into a fresh directory and paused at t = 0.

    solveroptions.dat already carries $SCHEME DE and $OMEGA_REF SYN, which the
    analysis requires and which ssa.run() supplies for a case that does not.
    """
    for name in CASE_FILES:
        shutil.copy(CASE_DIR / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    case = stepss.cfg()
    case.addData("lf.dat")
    case.addData("dyn_noPSS.dat")
    case.addData("solveroptions.dat")
    case.addDst("nothing.dst")
    case.addObs("obs.dat")
    case.addTrj("out.trj")
    ram = stepss.sim()
    ram.execSim(case, 0.0)
    yield ram, tmp_path


def test_runSsa_writes_the_three_files(kundur):
    ram, work = kundur
    assert ram.runSsa("ssa") == "ssa"
    for suffix in ssa.RESULT_SUFFIXES:
        assert (work / ("ssa" + suffix)).is_file()


def test_runSsa_does_not_write_the_jacobian(kundur):
    """dumpjac and dumpeig are independent flags; run_ssa sets only dumpeig."""
    ram, work = kundur
    ram.runSsa("ssa")
    for suffix in ssa.JACOBIAN_SUFFIXES:
        assert not (work / ("ssa" + suffix)).exists()


@pytest.mark.parametrize("bad", ["it's", "sub/dir", ""])
def test_runSsa_refuses_a_basename_that_would_close_the_record(kundur, bad):
    ram, _ = kundur
    with pytest.raises(RAMSESError, match="basename"):
        ram.runSsa(bad)


def test_runSsa_refuses_a_time_below_the_floor(kundur):
    ram, _ = kundur
    with pytest.raises(RAMSESError, match="0.001"):
        ram.runSsa("ssa", t=0.0)


def test_runSsa_advances_to_a_later_time(kundur):
    ram, work = kundur
    ram.runSsa("ssa", t=0.5)
    assert ram.getSimTime() >= 0.5
    assert (work / "ssa_modes.dat").is_file()


def test_runSsa_refuses_a_time_already_passed(kundur):
    ram, _ = kundur
    ram.contSim(0.5)
    with pytest.raises(RAMSESError, match="already passed"):
        ram.runSsa("ssa", t=0.1)


def test_getStateMatrix_matches_the_modes_file(kundur):
    ram, work = kundur
    ram.runSsa("ssa")
    a_sys = ram.getStateMatrix()
    res = ssa.load(work, "ssa")
    assert a_sys.shape == (res.nstates, res.nstates)
    # The engine's own spectrum, recomputed here from the retained matrix. A
    # transposed or row-major read would give a different set.
    mine = np.sort_complex(np.linalg.eigvals(a_sys))
    theirs = np.sort_complex(res.modes["re"] + 1j * res.modes["im"])
    assert np.allclose(mine, theirs, atol=1e-6, rtol=1e-6)


def test_getStateMatrix_raises_before_any_analysis(kundur):
    ram, _ = kundur
    with pytest.raises(RAMSESError, match="no small-signal"):
        ram.getStateMatrix()


def test_the_analysis_counter_advances_on_every_run(kundur):
    ram, _ = kundur
    assert ram._ssaGeneration == 0
    ram.runSsa("first")
    assert ram._ssaGeneration == 1
    ram.runSsa("second", t=0.5)
    assert ram._ssaGeneration == 2
