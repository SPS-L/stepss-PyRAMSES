"""The Results model, its filters and its accessors."""

import shutil
from pathlib import Path

import numpy as np
import pytest

from stepss import ssa
from stepss.globals import RAMSESError

FIXTURES = Path(__file__).resolve().parent / "data" / "ssa"


@pytest.fixture
def run_dir(tmp_path):
    """The committed Kundur no-PSS run, laid out as a run on disk."""
    for suffix in ("modes", "pf", "ms"):
        shutil.copy(FIXTURES / ("kundur_nopss_%s.dat" % suffix),
                    tmp_path / ("ssa_%s.dat" % suffix))
    return tmp_path


@pytest.fixture
def res(run_dir):
    return ssa.load(run_dir, "ssa")


def test_load_reads_the_header(res):
    assert res.basename == "ssa"
    assert res.format_version == 2
    assert res.nstates == len(res.modes)
    assert res.pf_floor > 0.0
    assert res.gap_tol > 0.0


def test_load_refuses_a_missing_run(tmp_path):
    with pytest.raises(RAMSESError, match="no ssa_modes.dat"):
        ssa.load(tmp_path, "ssa")


def test_load_treats_absent_optional_files_as_empty(tmp_path):
    shutil.copy(FIXTURES / "kundur_nopss_modes.dat", tmp_path / "ssa_modes.dat")
    loaded = ssa.load(tmp_path, "ssa")
    assert len(loaded.modes) > 0
    first = int(loaded.modes["index"][0])
    assert loaded.participation(first, allow_degenerate=True) == []
    assert loaded.mode_shape(first, allow_degenerate=True) == []


def test_basenames_lists_runs_and_ignores_a_directory_of_that_name(run_dir):
    (run_dir / "decoy_modes.dat").mkdir()
    assert ssa.basenames(run_dir) == ["ssa"]


def test_electromechanical_selects_the_rotor_band_sorted_by_frequency(res):
    em = res.electromechanical()
    assert len(em) >= 3
    assert np.all(em.rows["freq"] > 0.1)
    assert np.all(em.rows["freq"] < 2.5)
    assert np.all(em.rows["im"] > 0.0)
    assert np.all(np.diff(em.rows["freq"]) >= 0.0)


def test_dominant_is_strictly_greater_than(res):
    limit = float(res.modes["re"].max())
    assert len(res.dominant(limit)) == 0, "a mode exactly on the limit is excluded"


def test_dominant_preserves_the_order_it_was_given(res):
    em = res.electromechanical()
    assert list(em.dominant(-1e9).rows["index"]) == list(em.rows["index"])


def test_lam_recombines_the_two_columns(res):
    em = res.electromechanical()
    assert em.lam[0] == pytest.approx(em.rows["re"][0] + 1j * em.rows["im"][0])


def test_participation_of_the_interarea_mode_lists_all_four_machines(res):
    interarea = [m for m in res.electromechanical().rows if 0.4 < m["freq"] < 0.9]
    assert len(interarea) == 1
    rows = res.participation(interarea[0], floor=0.05)
    devices = {r.device.strip() for r in rows if r.variable == "omega"}
    assert devices == {"G1", "G2", "G3", "G4"}


def test_participation_floor_is_applied_here_not_by_the_engine(res):
    local = [m for m in res.electromechanical().rows if m["freq"] > 0.9][0]
    assert len(res.participation(local, floor=0.001)) > \
        len(res.participation(local, floor=0.05))


def test_participation_refuses_a_degenerate_mode(res):
    degenerate = res.modes[~res.modes["simple"]][0]
    with pytest.raises(RAMSESError, match="degenerate"):
        res.participation(degenerate)
    assert isinstance(res.participation(degenerate, allow_degenerate=True), list)


def test_mode_shape_refuses_a_degenerate_mode(res):
    degenerate = res.modes[~res.modes["simple"]][0]
    with pytest.raises(RAMSESError, match="degenerate"):
        res.mode_shape(degenerate)
    assert isinstance(res.mode_shape(degenerate, allow_degenerate=True), list)


def test_mode_accepts_an_index_or_a_row(res):
    row = res.electromechanical().rows[0]
    assert res.mode_shape(row) == res.mode_shape(int(row["index"]))


def test_index_of_refuses_something_that_is_neither(res):
    with pytest.raises(RAMSESError, match="neither a mode index"):
        res._index_of("mode 3")


def test_index_of_refuses_an_index_not_in_this_run(res):
    with pytest.raises(RAMSESError, match="not in this run"):
        res._index_of(99999)


def test_participation_refuses_an_index_not_in_this_run(res):
    with pytest.raises(RAMSESError, match="not in this run"):
        res.participation(99999)


def test_mode_shape_refuses_an_index_not_in_this_run(res):
    with pytest.raises(RAMSESError, match="not in this run"):
        res.mode_shape(99999)


def test_view_participation_delegates_to_the_run(res):
    view = res.electromechanical()
    assert view.participation(view[0]) == res.participation(view[0])


def test_view_mode_shape_delegates_to_the_run(res):
    view = res.electromechanical()
    assert view.mode_shape(view[0]) == res.mode_shape(view[0])


def test_view_copies_so_mutating_rows_does_not_corrupt_modes(res):
    before = float(res.modes["re"][0])
    res.view().rows["re"][0] = 999.0
    assert float(res.modes["re"][0]) == before


def test_table_and_summary_print_something(res, capsys):
    res.summary()
    res.electromechanical().table()
    assert capsys.readouterr().out.strip()
