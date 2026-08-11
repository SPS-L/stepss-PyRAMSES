"""Network modification tests: trip/connect, load changes, apply, reset."""

import pytest

from stepss.globals import HeliosError


def test_trip_branch_redistributes_flow(solved):
    p_before, _ = solved.get_branch_flow("D-E")
    solved.trip_branch("B-C")
    assert solved.apply_changes()

    assert solved.get_branch_status()[solved.find_branch("B-C")] == 0
    p_bc, _ = solved.get_branch_flow("B-C")
    assert p_bc == pytest.approx(0.0, abs=1e-12)
    p_after, _ = solved.get_branch_flow("D-E")
    assert abs(p_after) > abs(p_before)


def test_reset_restores_initial_state(solved, case_6bus):
    from stepss.helios import HeliosSession, SolverStatus
    from conftest import LIB_DIR

    solved.trip_branch("B-C")
    assert solved.apply_changes()
    solved.change_load("D", 0.5, 0.1)  # leave a pending change too
    solved.reset()

    assert solved.solver_status == SolverStatus.NOT_RUN
    assert solved.get_branch_status().tolist() == [1] * 6

    with HeliosSession(lib_dir=LIB_DIR) as fresh:
        fresh.load_file(case_6bus)
        v_reset, a_reset = solved.get_bus_voltages()
        v_fresh, a_fresh = fresh.get_bus_voltages()
        assert v_reset.tolist() == v_fresh.tolist()
        assert a_reset.tolist() == a_fresh.tolist()
        p_reset, _ = solved.get_bus_loads()
        p_fresh, _ = fresh.get_bus_loads()
        assert p_reset.tolist() == p_fresh.tolist()


def test_change_load_with_redispatch(solved):
    gp0, _, _ = solved.get_generator_outputs()
    solved.change_load("D", 0.5, 0.1)
    assert solved.get_bus_info("D").p_load_mw == pytest.approx(1.5)
    assert solved.apply_changes()
    assert "Deficit of active power" in solved.last_error
    gp1, _, _ = solved.get_generator_outputs()
    assert gp1.sum() > gp0.sum() + 0.4  # generation covers the added load


def test_set_load_absolute(solved):
    solved.set_load("D", 2.0, 0.5)
    info = solved.get_bus_info("D")
    assert info.p_load_mw == pytest.approx(2.0)
    assert info.q_load_mvar == pytest.approx(0.5)
    assert solved.apply_changes()


def test_trip_generator_and_redispatch(solved):
    with pytest.raises(HeliosError, match="slack"):
        solved.trip_generator("A")

    solved.trip_generator("F")
    assert solved.apply_changes()
    assert "Deficit of active power" in solved.last_error
    assert not solved.get_generator_info("F").in_service

    solved.connect_generator("F")
    assert solved.apply_changes()
    assert solved.get_generator_info("F").in_service


def test_set_generator_voltage(solved):
    solved.set_generator_voltage("F", 1.02)
    assert solved.apply_changes()
    v, _ = solved.get_bus_voltage("F")
    assert v == pytest.approx(1.02, abs=1e-3)


def test_modify_error_paths(solved):
    with pytest.raises(HeliosError, match="NOPE"):
        solved.trip_branch("NOPE")
    with pytest.raises(HeliosError, match="already connected"):
        solved.connect_branch("B-C")
    with pytest.raises(HeliosError):
        solved.change_zone_load("NOPE", 1.0)
