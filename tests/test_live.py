"""Unit tests for stepss.monitor, the live simulation plotter.

The engine is faked: monitor only ever calls the public sim accessors, so a
stand-in that records its calls exercises every path without loading RAMSES.
tests/test_live_engine.py covers the real library.
"""

import matplotlib

matplotlib.use("Agg")  # no window, on any runner

import numpy as np
import pytest

import stepss
from stepss.globals import RAMSESError


class FakeSim(object):
    """Records every accessor call and advances a clock on contSim()."""

    def __init__(self, tstop=5.0, advance=True, fail_at=None):
        self.t = 0.0
        self.tstop = tstop
        self.advance = advance
        self.fail_at = fail_at
        self.calls = []
        self.ended = False

    # -- the subset of stepss.sim that monitor uses -----------------------

    def getSimTime(self):
        return self.t

    def getEndSim(self):
        return 1 if self.ended else 0

    def contSim(self, pause=None):
        self.calls.append(("contSim", pause))
        if len(self.calls) > 200:
            raise AssertionError("monitor.run did not terminate")
        if self.fail_at is not None and len(self.calls) >= self.fail_at:
            raise RAMSESError("RAMSES: fake failure")
        if self.advance:
            self.t = min(pause, self.tstop)
            if self.t >= self.tstop:
                self.ended = True
        return 0

    def getBusVolt(self, busNames):
        self.calls.append(("getBusVolt", list(busNames)))
        return [1.0 + 0.01 * self.t for _ in busNames]

    def getBusPha(self, busNames):
        self.calls.append(("getBusPha", list(busNames)))
        return [10.0 for _ in busNames]

    def getBranchPow(self, branchName):
        self.calls.append(("getBranchPow", list(branchName)))
        return [[1.0, 2.0, 3.0, 4.0] for _ in branchName]

    def getObs(self, comp_type, comp_name, obs_name):
        self.calls.append(("getObs", comp_type, comp_name, obs_name))
        return [42.0]

    def reads(self):
        """The accessor calls, contSim excluded."""
        return [c for c in self.calls if c[0] != "contSim"]


@pytest.fixture
def ram():
    return FakeSim()


# -- descriptor vocabulary ------------------------------------------------

@pytest.mark.parametrize("descriptor,label", [
    ("BV 4044", "4044: voltage magnitude (pu)"),
    ("BA 4044", "4044: voltage phase (deg)"),
    ("MS g6", "g6: machine speed (pu)"),
    ("BPO 4041-4044", "4041-4044: active power at the origin (MW)"),
    ("BQO 4041-4044", "4041-4044: reactive power at the origin (Mvar)"),
    ("BPE 4041-4044", "4041-4044: active power at the extremity (MW)"),
    ("BQE 4041-4044", "4041-4044: reactive power at the extremity (Mvar)"),
    ("ON WT1a Pw", "WT1a: Pw"),
    ("TO hvdc1 P1", "hvdc1: P1"),
    ("OBS EXC g1 vf", "g1: vf"),
    ("RT RT", "elapsed real time (s)"),
])
def test_descriptor_label(ram, descriptor, label):
    mon = stepss.monitor(ram, descriptor, show=False)
    assert mon.curves()[0].msg == label


@pytest.mark.parametrize("descriptor,expected", [
    ("BV 4044", ("getBusVolt", ["4044"])),
    ("BA 4044", ("getBusPha", ["4044"])),
    ("MS g6", ("getObs", "SYN", "g6", "Omega")),
    ("BPO 4041-4044", ("getBranchPow", ["4041-4044"])),
    ("ON WT1a Pw", ("getObs", "INJ", "WT1a", "Pw")),
    ("TO hvdc1 P1", ("getObs", "TWOP", "hvdc1", "P1")),
    ("OBS exc g1 vf", ("getObs", "EXC", "g1", "vf")),
])
def test_descriptor_polls_the_matching_accessor(ram, descriptor, expected):
    stepss.monitor(ram, descriptor, show=False).sample()
    assert ram.reads() == [expected]


def test_branch_fields_select_different_columns(ram):
    mon = stepss.monitor(ram, ["BPO b", "BQO b", "BPE b", "BQE b"], show=False)
    mon.sample()
    assert [c.value[0] for c in mon.curves()] == [1.0, 2.0, 3.0, 4.0]


def test_rt_starts_at_zero_and_never_goes_back(ram):
    mon = stepss.monitor(ram, "RT RT", show=False)
    mon.sample()
    mon.sample()
    values = mon.curves()[0].value
    assert values[0] == 0.0
    assert values[1] >= 0.0


@pytest.mark.parametrize("descriptor", ["", "   ", "XX 4044", "BV", "BV a b", "ON g1", "OBS EXC g1"])
def test_bad_descriptor_raises(ram, descriptor):
    with pytest.raises(ValueError):
        stepss.monitor(ram, descriptor, show=False)


def test_no_observables_raises(ram):
    with pytest.raises(ValueError):
        stepss.monitor(ram, [], show=False)


def test_unusable_spec_raises(ram):
    with pytest.raises(ValueError):
        stepss.monitor(ram, [17], show=False)


# -- callables ------------------------------------------------------------

def test_labelled_callable_observable(ram):
    mon = stepss.monitor(ram, ("twice the time", lambda r: 2.0 * r.getSimTime()), show=False)
    ram.t = 3.0
    mon.sample()
    curve = mon.curves()[0]
    assert curve.msg == "twice the time"
    assert curve.value[0] == 6.0


def test_bare_callable_takes_its_own_name(ram):
    def headroom(r):
        return 0.5

    mon = stepss.monitor(ram, headroom, show=False)
    mon.sample()
    assert mon.curves()[0].msg == "headroom"


# -- the stepping loop ----------------------------------------------------

def test_run_steps_at_the_requested_cadence(ram):
    stepss.monitor(ram, "BV 4044", show=False).run(step=1.0)
    assert [c[1] for c in ram.calls if c[0] == "contSim"] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_run_samples_before_the_first_step_and_after_each(ram):
    curves = stepss.monitor(ram, "BV 4044", show=False).run(step=1.0)
    assert list(curves[0].time) == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]


def test_run_stops_at_until_without_overshooting(ram):
    curves = stepss.monitor(ram, "BV 4044", show=False).run(step=2.0, until=3.0)
    assert [c[1] for c in ram.calls if c[0] == "contSim"] == [2.0, 3.0]
    assert list(curves[0].time) == [0.0, 2.0, 3.0]


def test_run_stops_when_the_engine_stops_advancing():
    stalled = FakeSim(advance=False)
    curves = stepss.monitor(stalled, "BV 4044", show=False).run(step=1.0)
    assert len([c for c in stalled.calls if c[0] == "contSim"]) == 1
    assert len(curves[0].time) == 2


def test_run_returns_immediately_on_an_ended_simulation(ram):
    ram.ended = True
    curves = stepss.monitor(ram, "BV 4044", show=False).run(step=1.0)
    assert [c for c in ram.calls if c[0] == "contSim"] == []
    assert len(curves[0].time) == 1


@pytest.mark.parametrize("step", [0.0, -1.0])
def test_run_rejects_a_nonpositive_step(ram, step):
    with pytest.raises(ValueError):
        stepss.monitor(ram, "BV 4044", show=False).run(step=step)


def test_samples_survive_an_engine_failure():
    failing = FakeSim(fail_at=3)
    mon = stepss.monitor(failing, "BV 4044", show=False)
    with pytest.raises(RAMSESError):
        mon.run(step=1.0)
    assert list(mon.curves()[0].time) == [0.0, 1.0]


# -- curves ---------------------------------------------------------------

def test_curves_are_numpy_arrays_of_equal_length(ram):
    curves = stepss.monitor(ram, ["BV 4044", "MS g6"], show=False).run(step=1.0)
    assert len(curves) == 2
    for curve in curves:
        assert isinstance(curve.time, np.ndarray)
        assert isinstance(curve.value, np.ndarray)
        assert curve.time.shape == curve.value.shape


def test_curves_keep_the_order_they_were_given(ram):
    mon = stepss.monitor(ram, ["MS g6", "BV 4044", "RT RT"], show=False)
    assert [c.msg.split(":")[0] for c in mon.curves()] == ["g6", "4044", "elapsed real time (s)"]


def test_curves_feed_curplot(ram, monkeypatch):
    import matplotlib.pyplot as plt

    monkeypatch.setattr(plt, "show", lambda *a, **k: None)
    curves = stepss.monitor(ram, "BV 4044", show=False).run(step=1.0)
    stepss.curplot(curves)  # must accept its own output
    plt.close("all")


# -- the figure -----------------------------------------------------------

def test_one_panel_per_observable(ram):
    mon = stepss.monitor(ram, ["BV 4044", "MS g6", "RT RT"], title="Nordic")
    try:
        assert len(mon.axes) == 3
        assert mon.axes[-1].get_xlabel() == "time (s)"
        assert mon.axes[0].get_ylabel() == "pu"
    finally:
        mon.close()


def test_show_false_builds_no_figure(ram):
    mon = stepss.monitor(ram, "BV 4044", show=False)
    assert mon.figure is None
    with pytest.raises(RuntimeError):
        mon.savefig("never-written.png")


def test_savefig_writes_the_chart(ram, tmp_path):
    mon = stepss.monitor(ram, ["BV 4044", "MS g6"])
    try:
        mon.run(step=1.0)
        target = tmp_path / "run.png"
        mon.savefig(str(target))
        assert target.stat().st_size > 0
    finally:
        mon.close()


def test_the_figure_holds_every_sample(ram):
    mon = stepss.monitor(ram, "BV 4044")
    try:
        mon.run(step=1.0)
        assert list(mon.axes[0].lines[0].get_xdata()) == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    finally:
        mon.close()


def test_refresh_throttles_between_forced_draws(ram):
    mon = stepss.monitor(ram, "BV 4044", refresh=1.0e6)
    try:
        mon.sample()
        mon.refresh(force=True)
        mon.sample()
        mon.refresh()
        assert len(mon.axes[0].lines[0].get_xdata()) == 1
        mon.refresh(force=True)
        assert len(mon.axes[0].lines[0].get_xdata()) == 2
    finally:
        mon.close()


@pytest.mark.parametrize("backend,live", [
    ("agg", False),
    ("Agg", False),
    ("pdf", False),
    ("template", False),
    ("qtagg", True),
    ("TkAgg", True),
    ("macosx", True),
    ("module://matplotlib_inline.backend_inline", False),
    ("module://ipympl.backend_nbagg", True),
])
def test_backend_classification(monkeypatch, backend, live):
    monkeypatch.setattr(matplotlib, "get_backend", lambda: backend)
    assert stepss.live._canDraw() is live


def test_refresh_pushes_to_the_canvas_when_the_backend_is_live(ram, monkeypatch):
    """The live path is the one no file backend exercises: drive it directly."""
    mon = stepss.monitor(ram, "BV 4044", refresh=0.0)
    try:
        pushes = []
        monkeypatch.setattr(mon.figure.canvas, "draw_idle", lambda: pushes.append("draw"))
        monkeypatch.setattr(mon.figure.canvas, "flush_events", lambda: pushes.append("flush"))
        monkeypatch.setattr(stepss.live.plt, "fignum_exists", lambda number: True)
        mon._drawing = True
        mon.sample()
        mon.refresh()
        assert pushes == ["draw", "flush"]
    finally:
        mon.close()


def test_a_closed_window_stops_the_draws_but_not_the_samples(ram, monkeypatch):
    mon = stepss.monitor(ram, "BV 4044", refresh=0.0)
    try:
        monkeypatch.setattr(mon.figure.canvas, "draw_idle", lambda: pytest.fail("drew into a closed window"))
        monkeypatch.setattr(stepss.live.plt, "fignum_exists", lambda number: False)
        mon._drawing = True
        mon.run(step=1.0)
        assert len(mon.curves()[0].time) == 6
    finally:
        mon.close()


def test_close_is_idempotent(ram):
    mon = stepss.monitor(ram, "BV 4044")
    mon.close()
    mon.close()
    assert mon.figure is None
    assert len(mon.curves()) == 1


def test_monitor_works_as_a_context_manager(ram):
    with stepss.monitor(ram, "BV 4044") as mon:
        mon.run(step=1.0)
    assert mon.figure is None
