"""The pure helpers a run needs: validation, the two generated files, clearing."""

import os

import pytest

from stepss import ssa
from stepss.globals import RAMSESError


@pytest.mark.parametrize("name", ["ssa", "run-1", "a.b_c", "X9"])
def test_valid_basenames(name):
    assert ssa.valid_basename(name)


@pytest.mark.parametrize("name", ["", "it's", "sub/dir", "back\\slash", "a b", None])
def test_invalid_basenames(name):
    assert not ssa.valid_basename(name)


def test_check_time_accepts_the_floor():
    assert ssa.check_time(ssa.MIN_TIME) == pytest.approx(ssa.MIN_TIME)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_check_time_refuses(bad):
    with pytest.raises(RAMSESError):
        ssa.check_time(bad)


def test_check_time_refuses_text():
    with pytest.raises(RAMSESError, match="number"):
        ssa.check_time("soon")


def test_settings_text_carries_exactly_the_two_records():
    text = ssa.settings_text()
    assert "$SCHEME DE" in text
    assert "$OMEGA_REF SYN" in text
    records = [line for line in text.splitlines()
               if line.strip() and not line.startswith("#")]
    assert len(records) == 2, "anything else would change the user's run for no reason"


def test_settings_name_uses_the_graphical_interfaces_suffix():
    assert ssa.settings_name("ssa") == "ssaEig.dat"
    with pytest.raises(RAMSESError):
        ssa.settings_name("it's")


def test_disturbance_name_cannot_collide_with_a_results_file():
    generated = {ssa.settings_name("ssa"), ssa.disturbance_name("ssa")}
    assert generated.isdisjoint(set(ssa.members("ssa")))


def test_disturbance_text_stops_after_the_analysis_time():
    lines = [line for line in ssa.disturbance_text(0.5).splitlines() if line.strip()]
    assert lines[0].startswith("0.000")
    assert "STOP" in lines[-1]
    assert float(lines[-1].split()[0]) > 0.5
    # No events: the engine linearises about whatever state it is in, so an
    # event before the analysis would describe that instant, not an operating
    # point.
    assert not any("FAULT" in line or "TRIP" in line for line in lines)


def test_disturbance_text_writes_a_plain_decimal():
    assert "E-" not in ssa.disturbance_text(0.001)


def test_members_are_the_three_results_then_the_four_jacobian_tables():
    assert ssa.members("run") == (
        "run_modes.dat", "run_pf.dat", "run_ms.dat",
        "run_eqs.dat", "run_var.dat", "run_val.dat", "run_struc.dat")


def test_clear_previous_run_removes_only_this_runs_members(tmp_path):
    for name in ssa.members("ssa"):
        (tmp_path / name).write_text("x")
    (tmp_path / "other_modes.dat").write_text("keep")
    (tmp_path / "lf.dat").write_text("keep")

    assert ssa.clear_previous_run(tmp_path, "ssa") == []
    for name in ssa.members("ssa"):
        assert not (tmp_path / name).exists()
    assert (tmp_path / "other_modes.dat").exists()
    assert (tmp_path / "lf.dat").exists()


def test_clear_previous_run_on_an_empty_directory_is_clean(tmp_path):
    assert ssa.clear_previous_run(tmp_path, "ssa") == []


def test_clear_previous_run_reports_what_would_not_go(tmp_path, monkeypatch):
    (tmp_path / "ssa_modes.dat").write_text("x")
    (tmp_path / "ssa_pf.dat").write_text("x")

    real_remove = os.remove

    def refuse_one(path, *args, **kwargs):
        if str(path).endswith("ssa_modes.dat"):
            raise OSError("still open")
        real_remove(path, *args, **kwargs)

    monkeypatch.setattr(os, "remove", refuse_one)
    assert ssa.clear_previous_run(tmp_path, "ssa") == ["ssa_modes.dat"]
    # The rest are still attempted, so one stuck file cannot leave others
    # behind to be mistaken for the next run's.
    assert not (tmp_path / "ssa_pf.dat").exists()
