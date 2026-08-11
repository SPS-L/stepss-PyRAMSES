"""File-writer and contingency-analysis tests."""

import pytest

from stepss.globals import HeliosError
from stepss.helios import HeliosSession
from conftest import LIB_DIR


def test_dump_round_trip(solved, tmp_path):
    dump = tmp_path / "dumped.dat"
    solved.write_dump(dump)
    assert dump.exists()

    with HeliosSession(lib_dir=LIB_DIR) as reloaded:
        reloaded.load_file(dump)
        assert reloaded.solve()
        v0, _ = solved.get_bus_voltages()
        v1, _ = reloaded.get_bus_voltages()
        assert v1 == pytest.approx(v0, abs=1e-6)


def test_voltrat_and_matlab_markers(solved, tmp_path):
    voltrat = tmp_path / "volt_rat.dat"
    solved.write_voltrat(voltrat)
    assert "LFRESV" in voltrat.read_text()

    matlab = tmp_path / "system.m"
    solved.write_matlab(matlab)
    text = matlab.read_text()
    assert ").name=" in text
    assert "Y=zeros" in text


def test_diagram_substitution(solved, data_dir, tmp_path):
    out = tmp_path / "diagram.svg"
    solved.write_diagram(data_dir / "6bus_mg.svg", out)
    svg = out.read_text()
    assert svg
    assert "%AE" not in svg  # placeholders resolved


def test_writer_bad_path(solved, tmp_path):
    with pytest.raises(HeliosError):
        solved.write_dump(tmp_path / "no_dir" / "out.dat")


def test_contingency_file_mode(solved, data_dir):
    v_before, _ = solved.get_bus_voltages()
    results = solved.run_contingencies(file=data_dir / "6bus_mg_contingency.txt")
    assert [r.name for r in results] == [
        "Trip line B-C", "Trip generator F", "Double fault B-C and gen F"]
    for r in results:
        assert r.converged
        assert 0.0 < r.min_v_pu <= r.max_v_pu
        assert r.min_v_bus

    # Base case untouched
    v_after, _ = solved.get_bus_voltages()
    assert v_after.tolist() == v_before.tolist()


def test_contingency_n1_mode(solved):
    results = solved.run_contingencies(branches=True, generators=True, svcs=True)
    assert len(results) == 7  # 6 branches + generator F (slack excluded)
    assert all(r.converged for r in results)


def test_contingency_violations(solved):
    # An absurd voltage band forces violations
    results = solved.run_contingencies(branches=True, v_min=0.999, v_max=1.001)
    flagged = [r for r in results if r.violations]
    assert flagged
    assert all(not r.accepted for r in flagged)
    assert any("voltage" in v for r in flagged for v in r.violations)


def test_contingency_argument_validation(solved):
    with pytest.raises(HeliosError, match="at least one"):
        solved.run_contingencies()
    with pytest.raises(HeliosError):
        solved.run_contingencies(file="missing_contingencies.txt")
