"""Lifecycle, versioning, solving, and error-channel tests for HeliosSession."""

import pytest

from stepss.globals import HeliosError
from stepss.helios import HeliosSession, SolverStatus

from conftest import LIB_DIR


def test_context_manager_and_double_close(case_6bus):
    with HeliosSession(lib_dir=LIB_DIR) as pf:
        pf.load_file(case_6bus)
        assert pf.solve()
    pf.close()  # second close is a no-op
    with pytest.raises(HeliosError):
        pf.bus_names()  # using a closed session raises


def test_api_version_and_build_info(session):
    major, minor, patch = session.api_version()
    assert major >= 1
    assert minor >= 0 and patch >= 0
    assert "helios" in session.build_info()


def test_load_missing_file_raises_with_filename(session):
    with pytest.raises(HeliosError, match="definitely_missing.dat"):
        session.load_file("definitely_missing.dat")


def test_solve_without_network_raises(session):
    with pytest.raises(HeliosError):
        session.solve()


def test_solve_converges_on_6bus(solved):
    assert solved.converged
    assert solved.solver_status == SolverStatus.CONVERGED
    assert solved.iterations > 0
    mw, mvar = solved.max_mismatch
    assert mw <= 0.01  # $TOLAC from the data file
    assert mvar <= 0.01


def test_known_voltage_values(solved):
    # Reference values from the helios CLI on 6bus_mg.dat
    v, angle = solved.get_bus_voltage("A")
    assert v == pytest.approx(1.0, abs=1e-3)
    assert angle == pytest.approx(0.0, abs=1e-3)
    v, _ = solved.get_bus_voltage("B")
    assert v == pytest.approx(0.9801, abs=1e-3)


def test_unknown_names_raise(solved):
    with pytest.raises(HeliosError, match="NOPE"):
        solved.get_bus_voltage("NOPE")
    with pytest.raises(HeliosError, match="NOPE"):
        solved.get_branch_flow("NOPE")
    with pytest.raises(HeliosError, match="NOPE"):
        solved.find_bus("NOPE")


def test_last_error_channel(session, case_6bus):
    assert session.last_error == ""
    with pytest.raises(HeliosError):
        session.load_file("gone.dat")
    assert "gone.dat" in session.last_error
    session.load_file(case_6bus)  # success leaves the message readable
    assert "gone.dat" in session.last_error
    session.clear_last_error()
    assert session.last_error == ""


def test_two_sessions_are_independent(case_6bus):
    with HeliosSession(lib_dir=LIB_DIR) as a, HeliosSession(lib_dir=LIB_DIR) as b:
        a.load_file(case_6bus)
        assert a.solve()
        a.trip_branch("B-C")
        assert a.apply_changes()
        b.load_file(case_6bus)
        assert b.solve()
        # b never saw a's modification
        assert b.get_branch_status().tolist() == [1] * b.branch_count
