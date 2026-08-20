#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Live plotting of a running RAMSES simulation.

Provides :class:`monitor`, which steps a simulation forward in slices, reads
the chosen quantities out of the engine at every pause, and redraws a stacked
matplotlib figure as the run proceeds.

The engine is polled in process, through the same accessors a script would
call by hand (:meth:`~stepss.simulator.sim.getBusVolt`,
:meth:`~stepss.simulator.sim.getObs` and the rest): no file is read and
nothing is piped anywhere. Run-time observables declared with
:meth:`~stepss.cases.cfg.addRunObs` are a separate mechanism, in which the
engine writes a curve file of its own; the two are independent and may be used
together.

One panel per observable, stacked and sharing the time axis.

:Example:

>>> import stepss
>>> ram = stepss.sim()
>>> case = stepss.cfg('cmd.txt')
>>> ram.execSim(case, 0.0)                    # initialise, pause at t = 0
>>> mon = stepss.monitor(ram, ['BV 4044', 'MS g6'])
>>> curves = mon.run(step=0.5)                # run to the end of the scenario
>>> stepss.curplot(curves)                    # replot the same data afterwards
"""

import time

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from .extractor import cur

# Backends that render to a file and have no window to update. Live redraw is
# skipped on these; sampling and the final figure are unaffected, so
# monitor.savefig() produces the same chart a window would have shown. The list
# is matplotlib's own set of non-interactive built-ins, copied rather than
# imported: matplotlib.rcsetup.non_interactive_bk is deprecated since 3.9 and
# removed in 3.11, and this package supports matplotlib 3.0 upwards. A backend
# missing from the list is treated as interactive, which costs a draw call that
# does nothing.
_STATIC_BACKENDS = frozenset(['agg', 'cairo', 'pdf', 'pgf', 'ps', 'svg', 'template'])

# Sim-time comparisons. RAMSES pauses at the first internal step at or after
# the requested time, so equality is never exact.
_EPS = 1e-9

# Branch quantity -> (index into getBranchPow, description, unit).
_BRANCH_POW = {
    'BPO': (0, 'active power at the origin', 'MW'),
    'BQO': (1, 'reactive power at the origin', 'Mvar'),
    'BPE': (2, 'active power at the extremity', 'MW'),
    'BQE': (3, 'reactive power at the extremity', 'Mvar'),
}


def _canDraw():
    """Return True if the active matplotlib backend can update a live window.

    :returns: False for the file-only backends, True otherwise.
    :rtype: bool
    """
    name = matplotlib.get_backend().lower()
    if name.startswith('module://'):
        # Jupyter's inline backend emits a static image per draw and cannot
        # animate one; ipympl and the nbagg family can.
        return 'inline' not in name
    return name not in _STATIC_BACKENDS


class _Clock(object):
    """Wall-clock seconds elapsed since the first sample.

    Backs the ``RT`` descriptor: plotted against simulated time it shows how
    far the simulation runs behind, or ahead of, real time.
    """

    def __init__(self):
        self._start = None

    def __call__(self, ram):
        """Return seconds elapsed, starting the clock on the first call.

        :param ram: the simulator instance (unused).
        :returns: elapsed wall-clock time in seconds.
        :rtype: float
        """
        now = time.monotonic()
        if self._start is None:
            self._start = now
        return now - self._start


def _namedObs(comp_type, comp_name, obs_name):
    """Return a reader for one named engine observable.

    :param str comp_type: component type accepted by :meth:`~stepss.simulator.sim.getObs`.
    :param str comp_name: component name.
    :param str obs_name: observable name.
    :returns: a callable taking the simulator and returning a float.
    :rtype: callable
    """

    def read(ram):
        return ram.getObs(comp_type, comp_name, obs_name)[0]

    return read


def _branchPow(branch_name, index):
    """Return a reader for one field of :meth:`~stepss.simulator.sim.getBranchPow`.

    :param str branch_name: branch name.
    :param int index: 0 to 3, selecting p_orig, q_orig, p_extr or q_extr.
    :returns: a callable taking the simulator and returning a float.
    :rtype: callable
    """

    def read(ram):
        return ram.getBranchPow([branch_name])[0][index]

    return read


def _expect(descriptor, args, count):
    """Raise unless *args* holds exactly *count* items.

    :param str descriptor: the descriptor being parsed, for the message.
    :param list args: the fields following the descriptor code.
    :param int count: the number of fields the code takes.
    :raises ValueError: if the count does not match.
    """
    if len(args) != count:
        raise ValueError(
            "RAMSES: the observable descriptor '%s' takes %i field(s) after the code, got %i"
            % (descriptor, count, len(args)))


def _parse(descriptor):
    """Turn one descriptor string into a label, a unit and a reader.

    The vocabulary is tabulated in :class:`monitor`.

    :param str descriptor: the descriptor to parse.
    :returns: ``(label, unit, reader)``; *unit* is empty when the engine does
              not define one.
    :rtype: tuple
    :raises ValueError: if the descriptor is empty, unknown, or carries the
                        wrong number of fields.
    """
    fields = descriptor.split()
    if not fields:
        raise ValueError('RAMSES: the observable descriptor is empty')
    code = fields[0].upper()
    args = fields[1:]

    if code == 'RT':
        return 'elapsed real time', 's', _Clock()

    if code == 'BV':
        _expect(descriptor, args, 1)
        name = args[0]
        return '%s: voltage magnitude' % name, 'pu', lambda ram: ram.getBusVolt([name])[0]

    if code == 'BA':
        _expect(descriptor, args, 1)
        name = args[0]
        return '%s: voltage phase' % name, 'deg', lambda ram: ram.getBusPha([name])[0]

    if code == 'MS':
        _expect(descriptor, args, 1)
        name = args[0]
        return '%s: machine speed' % name, 'pu', _namedObs('SYN', name, 'Omega')

    if code in _BRANCH_POW:
        _expect(descriptor, args, 1)
        name = args[0]
        index, what, unit = _BRANCH_POW[code]
        return '%s: %s' % (name, what), unit, _branchPow(name, index)

    if code in ('ON', 'TO'):
        _expect(descriptor, args, 2)
        name, obs_name = args
        comp_type = 'INJ' if code == 'ON' else 'TWOP'
        return '%s: %s' % (name, obs_name), '', _namedObs(comp_type, name, obs_name)

    if code == 'OBS':
        _expect(descriptor, args, 3)
        comp_type, name, obs_name = args
        return '%s: %s' % (name, obs_name), '', _namedObs(comp_type.upper(), name, obs_name)

    raise ValueError(
        "RAMSES: unknown observable descriptor '%s'. Expected one of "
        "BV, BA, MS, BPO, BQO, BPE, BQE, ON, TO, OBS or RT." % descriptor)


def _isPair(item):
    """Return True if *item* is a ``(label, callable)`` observable spec."""
    return (isinstance(item, (tuple, list)) and len(item) == 2
            and isinstance(item[0], str) and callable(item[1]))


def _reader(item):
    """Turn one observable spec into a label, a unit and a reader.

    :param item: a descriptor string, a ``(label, callable)`` pair, or a bare
                 callable taking the simulator and returning a float.
    :returns: ``(label, unit, reader)``.
    :rtype: tuple
    :raises ValueError: if the spec is of none of those forms.
    """
    if isinstance(item, str):
        return _parse(item)
    if _isPair(item):
        return item[0], '', item[1]
    if callable(item):
        return getattr(item, '__name__', 'observable'), '', item
    raise ValueError(
        'RAMSES: an observable must be a descriptor string, a (label, callable) '
        'pair or a callable, not %s' % type(item).__name__)


def _asList(observables):
    """Normalise the *observables* argument to a list of specs."""
    if isinstance(observables, str) or callable(observables) or _isPair(observables):
        return [observables]
    return list(observables)


class monitor(object):
    """Plot chosen quantities of a RAMSES simulation while it runs.

    The simulation must already be initialised and paused, which
    :meth:`~stepss.simulator.sim.execSim` does when given a *pause* time.
    :meth:`run` then advances it in slices, sampling and redrawing at each
    pause, and returns the collected curves.

    Each observable gets its own panel; the panels are stacked and share the
    time axis.

    **Instance attributes:**

    - ``figure`` (*matplotlib.figure.Figure* or *None*): the chart, or None
      when built with ``show=False``.
    - ``axes`` (*list*): one axes per observable, top to bottom.

    :param ram: the simulator driving the run.
    :type ram: :class:`stepss.sim`
    :param observables: what to plot: descriptor strings such as ``'BV 4044'``
                        (tabulated below), ``(label,
                        callable)`` pairs, or bare callables taking the
                        simulator and returning a float. A single spec need
                        not be wrapped in a list.
    :param str title: figure title, or None for none.
    :param float refresh: minimum wall-clock seconds between redraws. Samples
                          are never skipped, only draws; 0 redraws at every
                          sample.
    :param bool show: False builds no figure at all and only collects data.
    :raises ValueError: if *observables* is empty or holds a spec that cannot
                        be read.

    **Descriptors.** The vocabulary is the one :meth:`~stepss.cases.cfg.addRunObs` uses, plus
    ``BA`` and the generic ``OBS`` escape hatch:

    ==================  =========================================  ======
    Descriptor          Quantity                                   Unit
    ==================  =========================================  ======
    ``BV BUS``          voltage magnitude of a bus                  pu
    ``BA BUS``          voltage phase of a bus                      deg
    ``MS SYN``          speed of a synchronous machine              pu
    ``BPO BRANCH``      active power at the branch origin           MW
    ``BQO BRANCH``      reactive power at the branch origin         Mvar
    ``BPE BRANCH``      active power at the branch extremity        MW
    ``BQE BRANCH``      reactive power at the branch extremity      Mvar
    ``ON INJ OBS``      named observable of an injector             engine
    ``TO TWOP OBS``     named observable of a two-port              engine
    ``OBS TYPE NAME O`` named observable of any component type      engine
    ``RT RT``           elapsed wall-clock time                     s
    ==================  =========================================  ======


    :Example:

    >>> import stepss
    >>> ram = stepss.sim()
    >>> case = stepss.cfg('cmd.txt')
    >>> ram.execSim(case, 0.0)
    >>> mon = stepss.monitor(ram, ['BV 4044', 'MS g6', 'RT RT'], title='Nordic')
    >>> mon.run(step=0.5)
    >>> mon.savefig('run.png')

    .. note:: The buffers survive a failed run: if the engine raises part way
              through, the samples taken up to that point are still available
              from :meth:`curves`.
    """

    def __init__(self, ram, observables, title=None, refresh=0.2, show=True):
        specs = _asList(observables)
        if not specs:
            raise ValueError('RAMSES: a monitor needs at least one observable')

        self._ram = ram
        self._refresh = float(refresh)
        self._labels = []
        self._units = []
        self._readers = []
        for spec in specs:
            label, unit, read = _reader(spec)
            self._labels.append('%s (%s)' % (label, unit) if unit else label)
            self._units.append(unit)
            self._readers.append(read)

        self._time = []
        self._values = [[] for _ in self._readers]
        self._lines = []
        self._lastDraw = None
        self._wasInteractive = None
        self._drawing = False
        self.figure = None
        self.axes = []
        if show:
            self._openFigure(title)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def _openFigure(self, title):
        """Build the stacked figure, one panel per observable.

        :param str title: figure title, or None.
        """
        count = len(self._readers)
        self.figure, grid = plt.subplots(count, 1, sharex=True, squeeze=False,
                                         figsize=(8.0, 1.0 + 2.0 * count))
        self.axes = [row[0] for row in grid]
        for axes, label, unit in zip(self.axes, self._labels, self._units):
            line, = axes.plot([], [])
            self._lines.append(line)
            axes.set_title(label, loc='left', fontsize='small')
            axes.set_ylabel(unit)
            axes.grid(True)
        self.axes[-1].set_xlabel('time (s)')
        if title:
            self.figure.suptitle(title)
        self.figure.tight_layout()

        self._drawing = _canDraw()
        if self._drawing:
            self._wasInteractive = plt.isinteractive()
            plt.ion()
            self.figure.show()

    def sample(self):
        """Read every observable once, at the current simulated time.

        Called by :meth:`run` at each pause. Call it directly when driving the
        simulation yourself.

        :returns: None.
        """
        self._time.append(self._ram.getSimTime())
        for values, read in zip(self._values, self._readers):
            values.append(read(self._ram))

    def refresh(self, force=False):
        """Push the samples into the figure and redraw it.

        Does nothing when the monitor was built with ``show=False``. A draw
        that falls inside the *refresh* interval is skipped unless *force*.

        :param bool force: redraw regardless of the interval.
        :returns: None.
        """
        if self.figure is None:
            return
        if self._drawing and not plt.fignum_exists(self.figure.number):
            self._drawing = False  # the window was closed; keep sampling
        now = time.monotonic()
        if not force and self._lastDraw is not None and now - self._lastDraw < self._refresh:
            return
        self._lastDraw = now
        for line, values, axes in zip(self._lines, self._values, self.axes):
            line.set_data(self._time, values)
            axes.relim()
            axes.autoscale_view()
        if self._drawing:
            self.figure.canvas.draw_idle()
            self.figure.canvas.flush_events()

    def run(self, step=1.0, until=None):
        """Advance the simulation in slices, sampling and redrawing at each pause.

        Returns when the engine reports the end of the scenario, when *until*
        is reached, or when a slice fails to advance the simulated time.

        :param float step: simulated seconds per slice.
        :param until: simulated time to stop at, or None to run to the end of
                      the disturbance scenario.
        :type until: float or None
        :returns: one curve per observable.
        :rtype: list of :class:`stepss.cur`
        :raises ValueError: if *step* is not positive.
        :raises RAMSESError: propagated from the engine. The samples taken
                             before the failure remain available from
                             :meth:`curves`.
        """
        if step <= 0.0:
            raise ValueError('RAMSES: monitor.run needs a positive step, got %r' % step)

        self.sample()
        self.refresh(force=True)
        try:
            while not self._ram.getEndSim():
                start = self._ram.getSimTime()
                if until is not None and start >= until - _EPS:
                    break
                target = start + step
                if until is not None:
                    target = min(target, until)
                self._ram.contSim(target)
                self.sample()
                self.refresh()
                if self._ram.getSimTime() <= start + _EPS:
                    break  # the scenario is over; the engine is not advancing
        finally:
            self.refresh(force=True)
        return self.curves()

    def curves(self):
        """Return everything sampled so far.

        :returns: one :class:`stepss.cur` per observable, in the order given
                  to the constructor, all sharing the same time array.
        :rtype: list of :class:`stepss.cur`
        """
        times = np.asarray(self._time, dtype=float)
        return [cur(times, np.asarray(values, dtype=float), label)
                for values, label in zip(self._values, self._labels)]

    def savefig(self, fname, **kwargs):
        """Redraw and write the figure to a file.

        :param fname: path or file object, passed to
                      :meth:`matplotlib.figure.Figure.savefig`.
        :param kwargs: forwarded to :meth:`~matplotlib.figure.Figure.savefig`.
        :returns: None.
        :raises RuntimeError: if the monitor was built with ``show=False``.
        """
        if self.figure is None:
            raise RuntimeError('RAMSES: this monitor has no figure (show=False)')
        self.refresh(force=True)
        self.figure.savefig(fname, **kwargs)

    def close(self):
        """Close the figure and restore matplotlib's interactive mode.

        The collected samples are unaffected: :meth:`curves` keeps working.

        :returns: None.
        """
        if self.figure is not None:
            plt.close(self.figure)
            self.figure = None
            self.axes = []
            self._lines = []
        if self._wasInteractive is False:
            plt.ioff()
        self._wasInteractive = None
        self._drawing = False
