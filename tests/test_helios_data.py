"""Structured data extraction tests: counts, names, info objects, bulk arrays, options."""

import numpy
import pytest

from stepss.globals import HeliosError
from stepss.helios import BusType, Option


def test_element_counts(solved):
    assert solved.bus_count == 6
    assert solved.branch_count == 6  # 2 lines + 4 transformers
    assert solved.generator_count == 2
    assert solved.svc_count == 0
    assert solved.zone_count == 0
    assert solved.cut_count == 0


def test_names_and_find_round_trip(solved):
    assert solved.bus_names() == ["A", "B", "C", "D", "E", "F"]
    for i, name in enumerate(solved.branch_names()):
        assert solved.find_branch(name) == i
    for i, name in enumerate(solved.generator_names()):
        assert solved.find_generator(name) == i


def test_bus_info(solved):
    info = solved.get_bus_info("A")
    assert info.bus_type == BusType.SLACK
    assert info.vnom_kv == pytest.approx(6.0)
    info = solved.get_bus_info("D")
    assert info.bus_type == BusType.PQ
    assert info.p_load_mw == pytest.approx(1.0)
    assert info.q_load_mvar == pytest.approx(0.3)


def test_branch_info(solved):
    br = solved.get_branch_info("B-C")
    assert (br.from_bus, br.to_bus) == ("B", "C")
    assert br.closed and not br.is_transformer
    assert br.snom_mva == pytest.approx(5.0)
    p, q = solved.get_branch_flow("B-C")
    assert br.p_from_mw == pytest.approx(p, abs=1e-12)
    trfo = solved.get_branch_info("A-B")
    assert trfo.is_transformer


def test_generator_info(solved):
    g = solved.get_generator_info("F")
    assert g.bus == "F" and g.in_service
    assert g.p_mw == pytest.approx(2.0, abs=1e-6)
    assert g.q_max_mvar > 0 > g.q_min_mvar
    assert not g.has_p_limits


def test_bulk_arrays_match_scalar_getters(solved):
    v, angle = solved.get_bus_voltages()
    assert isinstance(v, numpy.ndarray) and v.shape == (6,)
    for i, name in enumerate(solved.bus_names()):
        vi, ai = solved.get_bus_voltage(name)
        assert v[i] == pytest.approx(vi, abs=1e-15)
        assert angle[i] == pytest.approx(ai, abs=1e-15)

    p, q = solved.get_bus_loads()
    assert p[solved.find_bus("E")] == pytest.approx(4.0)
    assert q[solved.find_bus("E")] == pytest.approx(1.2)

    pf, qf, pt, qt = solved.get_branch_flows()
    assert pf.shape == (6,)
    named_p, _ = solved.get_branch_flow("B-C")
    assert pf[solved.find_branch("B-C")] == pytest.approx(named_p, abs=1e-12)

    gp, gq, gstatus = solved.get_generator_outputs()
    assert gp[solved.find_generator("F")] == pytest.approx(2.0, abs=1e-6)
    assert gstatus.tolist() == [1, 1]

    assert solved.get_branch_status().tolist() == [1] * 6

    q_svc, s_svc = solved.get_svc_outputs()
    assert q_svc.shape == (0,)


def test_options_round_trip(solved):
    # Values come from the $PARAM records of the data file
    assert solved.get_option(Option.TOLAC) == pytest.approx(0.01)
    assert solved.get_option(Option.MAX_ITER) == pytest.approx(20)
    assert solved.get_option(Option.SBASE) == pytest.approx(100.0)

    solved.set_option(Option.TOLAC, 0.5)
    assert solved.get_option(Option.TOLAC) == pytest.approx(0.5)
    assert solved.solve()  # still converges with the relaxed tolerance

    with pytest.raises(HeliosError):
        solved.set_option(999, 1.0)
