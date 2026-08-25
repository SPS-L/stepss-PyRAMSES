"""The three plots, under the agg backend."""

import shutil
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("agg")
import matplotlib.pyplot as plt  # noqa: E402

from stepss import ssa  # noqa: E402
from stepss.globals import RAMSESError  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "data" / "ssa"


@pytest.fixture
def res(tmp_path):
    for suffix in ("modes", "pf", "ms"):
        shutil.copy(FIXTURES / ("kundur_nopss_%s.dat" % suffix),
                    tmp_path / ("ssa_%s.dat" % suffix))
    return ssa.load(tmp_path, "ssa")


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close("all")


def interarea(res):
    return [m for m in res.electromechanical().rows if 0.4 < m["freq"] < 0.9][0]


def test_splane_returns_an_axes_and_keeps_the_stability_boundary_in_view(res):
    ax = res.electromechanical().splane()
    left, right = ax.get_xlim()
    assert left <= 0.0 <= right, "the boundary the plot is read against must be in view"


def test_splane_draws_into_a_given_axes(res):
    _, axes = plt.subplots(1, 2)
    res.electromechanical().splane(ax=axes[0])
    res.dominant(-1.0).splane(ax=axes[1])
    assert axes[0].collections and axes[1].collections


def test_splane_is_static_on_a_file_only_backend(res):
    """agg has no window to update, so interaction is skipped rather than attempted."""
    ax = res.electromechanical().splane()
    assert ax._stepss_splane_interactive is False


def test_splane_honours_an_explicit_interactive_false(res):
    ax = res.electromechanical().splane(interactive=False)
    assert ax._stepss_splane_interactive is False


def test_splane_of_an_empty_selection_still_draws(res):
    assert res.dominant(1e6).splane() is not None


def test_splane_of_the_whole_spectrum_draws(res):
    assert res.splane(annotate=False) is not None


def test_mode_shape_plot_is_polar_and_labels_every_machine(res):
    ax = res.mode_shape_plot(interarea(res))
    assert ax.name == "polar"
    labels = {text.get_text().strip() for text in ax.texts}
    assert {"G1", "G2", "G3", "G4"} <= labels


def test_mode_shape_plot_refuses_a_degenerate_mode(res):
    degenerate = res.modes[~res.modes["simple"]][0]
    with pytest.raises(RAMSESError, match="degenerate"):
        res.mode_shape_plot(degenerate)


def test_participation_plot_returns_an_axes_with_bars(res):
    assert res.participation_plot(interarea(res)).patches
