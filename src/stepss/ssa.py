#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Small-signal stability analysis: run it, read it, filter it, plot it.

RAMSES performs the analysis itself. It linearises about the operating point
the run is paused at, reduces the differential-algebraic Jacobian to the state
matrix, solves the dense eigenproblem, and writes three files named from a
basename: ``<base>_modes.dat``, ``<base>_pf.dat`` and ``<base>_ms.dat``.

This module drives that run, reads the three files and presents them, so that a
caller writes no parser. It also reads and writes the ``.ssa`` archive the
graphical interface exchanges, so a run made in either interface opens in the
other.

Every mode is in all three files, and the filtering happens here, against
results already in hand: :meth:`Results.electromechanical` selects the rotor
band and :meth:`Results.dominant` the modes above a real part limit, both with
the semantics the graphical interface uses.

:Example:

>>> import stepss
>>> from stepss import ssa
>>> case = stepss.cfg('cmd.txt')
>>> res = ssa.run(case, basename='ssa')
>>> em = res.electromechanical()
>>> em.table()
>>> em.splane()

.. note:: The engine retains one analysis at a time in a process, and the
          working directory is process-wide, so two analyses must not run
          concurrently from threads. :class:`stepss.simulator.sim` carries the
          same restriction.
"""

import os
import io
import tarfile
import tempfile
import zipfile
from collections import namedtuple
from copy import deepcopy

import numpy as np

from .globals import RAMSESError

__all__ = [
    'Results', 'ModeView', 'Participation', 'ModeShapeEntry', 'Manifest',
    'run', 'load', 'basenames', 'save', 'load_archive',
    'valid_basename', 'check_time', 'settings_text', 'settings_name',
    'disturbance_text', 'disturbance_name', 'members', 'clear_previous_run',
    'FORMAT_VERSION', 'ARCHIVE_FORMAT_VERSION', 'MANIFEST_NAME', 'MODE_DTYPE',
    'RESULT_SUFFIXES', 'JACOBIAN_SUFFIXES', 'SETTINGS_SUFFIX',
    'DISTURBANCE_SUFFIX', 'MIN_TIME', 'DEFAULT_REAL_LIMIT',
    'DEFAULT_PF_FLOOR', 'DEFAULT_DAMPING_ZETA',
]

#: The one ``_modes.dat`` format version this module reads. RAMSES has written
#: it since 3.79. v1 put a dominance flag exactly where v2 puts ``smp``, at the
#: same width with the same two legal values, so a positional reader that
#: skipped the banner would report one as the other and then read simplicity
#: off the end of the line. Hence the banner check before any row is parsed.
FORMAT_VERSION = 2

_MODES_BANNER = '# STEPSS SSA modes v'

#: What the analysis writes, in the order an archive carries them.
RESULT_SUFFIXES = ('_modes.dat', '_pf.dat', '_ms.dat')

#: What a JAC record writes beside them, under the same basename.
JACOBIAN_SUFFIXES = ('_eqs.dat', '_var.dat', '_val.dat', '_struc.dat')

#: Earliest analysis time offered, and the default. The engine needs at least
#: one step before it can apply an event.
MIN_TIME = 0.001

#: The real part limit the retired ``real_limit`` parameter defaulted to, so
#: that this default selects exactly what that default used to select.
DEFAULT_REAL_LIMIT = -1.0

#: The participation floor the retired ``pf_threshold`` parameter defaulted to.
#: The engine's own floor, ``pf_floor`` from ``$PF_THRES``, is lower, so this
#: trims a file that already holds more.
DEFAULT_PF_FLOOR = 0.05

#: Damping ratio of the s-plane's dashed ray, the usual planning criterion.
DEFAULT_DAMPING_ZETA = 0.05

#: One mode: the columns of ``<base>_modes.dat``, with lambda split into its
#: real and imaginary parts. ``simple`` false means the eigenvalue is
#: degenerate, its eigenvectors are not unique, and its participation factors
#: and mode shape are basis-dependent.
MODE_DTYPE = np.dtype([('index', 'i4'), ('re', 'f8'), ('im', 'f8'),
                       ('zeta', 'f8'), ('freq', 'f8'), ('simple', '?')])

# Field offsets, zero-based and half-open, as ssa.f90's edit descriptors
# produce them and as Columns.java in stepss-java-ui reads them. Splitting
# these lines on whitespace is wrong and fails silently: the a8 and a20 name
# fields are written as stored, so a leading blank is part of a name while
# trailing blanks are padding, and a device name may contain an embedded blank.
_MODES_FIELDS = ((0, 8), (9, 33), (34, 58), (59, 83), (84, 108), (109, 111))


def _slice(line, start, stop):
    """The field at ``[start, stop)``, trailing blanks removed.

    A leading blank is kept, because it is part of the name the engine stored.
    The end is clamped to the line length, since an all-blank trailing field is
    routinely stripped by editors and by CRLF normalisation.

    :param str line: one line of a results file, without its line ending
    :param int start: first column, zero-based
    :param int stop: one past the last column
    :returns: the field text
    :rtype: str
    """
    if start >= len(line):
        return ''
    return line[start:min(stop, len(line))].rstrip(' ')


def _num(line, start, stop, lineno):
    """The field at ``[start, stop)`` read as a float.

    :param str line: one line of a results file
    :param int start: first column, zero-based
    :param int stop: one past the last column
    :param int lineno: 1-based line number, used in the error message
    :returns: the value
    :rtype: float
    :raises RAMSESError: if the field does not parse, naming the columns
    """
    text = _slice(line, start, stop).strip()
    try:
        return float(text)
    except ValueError:
        raise RAMSESError('RAMSES: line %d: cannot read a number from <%s> at '
                          'columns %d-%d' % (lineno, text, start + 1, stop))


def _int(line, start, stop, lineno):
    """The field at ``[start, stop)`` read as an int.

    :param str line: one line of a results file
    :param int start: first column, zero-based
    :param int stop: one past the last column
    :param int lineno: 1-based line number, used in the error message
    :returns: the value
    :rtype: int
    :raises RAMSESError: if the field does not parse, naming the columns
    """
    text = _slice(line, start, stop).strip()
    try:
        return int(text)
    except ValueError:
        raise RAMSESError('RAMSES: line %d: cannot read an integer from <%s> at '
                          'columns %d-%d' % (lineno, text, start + 1, stop))


def _keyed(header, key):
    """One value out of a header comment, read by name rather than position.

    Reading by name is what lets a later engine add a field without breaking
    this, and lets an absent key stay None rather than failing the load.

    :param str header: the header line, including its leading ``#``
    :param str key: the key to look for
    :returns: the value, or None when the key is absent or does not parse
    :rtype: float or None
    """
    at = header.find(' ' + key + ' ')
    if at < 0:
        return None
    rest = header[at + len(key) + 2:].strip()
    token = rest.split(' ', 1)[0] if ' ' in rest else rest
    try:
        return float(token)
    except ValueError:
        return None


def _read_modes(text):
    """Parse ``<base>_modes.dat``.

    :param str text: the file's contents
    :returns: ``(modes, header)``, the modes as a :data:`MODE_DTYPE` array in
              file order, and the header as a dict with keys ``nstates``,
              ``nalg``, ``time``, ``pf_floor``, ``gap_tol`` and
              ``format_version``. An absent header key is None.
    :rtype: tuple
    :raises RAMSESError: if the banner is absent, names a version this module
                         does not read, or no mode rows follow it
    """
    version = 0
    header = {'nstates': None, 'nalg': None, 'time': None,
              'pf_floor': None, 'gap_tol': None}
    rows = []
    for i, line in enumerate(text.splitlines()):
        lineno = i + 1
        if not line.strip():
            continue
        if line[0] == '#':
            if line.startswith(_MODES_BANNER):
                tail = line[len(_MODES_BANNER):].strip()
                if tail.isdigit():
                    version = int(tail)
            if ' nstates ' in line:
                for key in header:
                    header[key] = _keyed(line, key)
            continue
        # Refused before the first row rather than after the last: a version
        # read as though it were v2 produces numbers, and numbers that parsed
        # are the hardest kind of wrong to notice.
        if version != FORMAT_VERSION:
            if version == 0:
                raise RAMSESError('RAMSES: no "%sN" banner; is this a '
                                  '_modes.dat file?' % _MODES_BANNER)
            raise RAMSESError(
                'RAMSES: unsupported _modes.dat format version %d; stepss reads '
                'v%d only%s' % (
                    version, FORMAT_VERSION,
                    '. It was written by a RAMSES older than 3.79.'
                    if version < FORMAT_VERSION else '.'))
        cols = _MODES_FIELDS
        rows.append((_int(line, cols[0][0], cols[0][1], lineno),
                     _num(line, cols[1][0], cols[1][1], lineno),
                     _num(line, cols[2][0], cols[2][1], lineno),
                     _num(line, cols[3][0], cols[3][1], lineno),
                     _num(line, cols[4][0], cols[4][1], lineno),
                     _int(line, cols[5][0], cols[5][1], lineno) == 1))
    if not rows:
        raise RAMSESError('RAMSES: no mode rows found; is this a _modes.dat file?')
    header['nstates'] = None if header['nstates'] is None else int(header['nstates'])
    header['nalg'] = None if header['nalg'] is None else int(header['nalg'])
    header['format_version'] = version
    return np.array(rows, dtype=MODE_DTYPE), header


_PF_FIELDS = ((0, 8), (9, 17), (18, 42), (43, 51), (52, 72), (73, 93))
_MS_FIELDS = ((0, 8), (9, 17), (18, 42), (43, 67), (68, 88))

Participation = namedtuple('Participation',
                           'mode state pf family device variable')
Participation.__doc__ = """One row of ``<base>_pf.dat``.

``pf`` is the participation factor, normalised so that the largest in each mode
is exactly 1. ``family`` is one of SYN, TOR, EXC, INJ, DCTL. A device absent
from a mode is below the run's ``pf_floor``, never zero.
"""

ModeShapeEntry = namedtuple('ModeShapeEntry',
                            'mode state magnitude angle_deg device')
ModeShapeEntry.__doc__ = """One row of ``<base>_ms.dat``: a machine's rotor-speed
phasor in one mode.

``magnitude`` is normalised so the largest in the mode is 1, and ``angle_deg``
is relative to that largest entry, because an eigenvector's absolute phase is
arbitrary and would otherwise vary from run to run.
"""


def _read_pf(text):
    """Parse ``<base>_pf.dat``, indexed by mode.

    Rows within a mode are sorted by participation factor, largest first.

    :param str text: the file's contents, or '' when the file is absent
    :returns: mode index to list of :class:`Participation`
    :rtype: dict
    :raises RAMSESError: if a field does not parse
    """
    by_mode = {}
    for i, line in enumerate(text.splitlines()):
        if not line.strip() or line[0] == '#':
            continue
        lineno = i + 1
        row = Participation(
            _int(line, _PF_FIELDS[0][0], _PF_FIELDS[0][1], lineno),
            _int(line, _PF_FIELDS[1][0], _PF_FIELDS[1][1], lineno),
            _num(line, _PF_FIELDS[2][0], _PF_FIELDS[2][1], lineno),
            _slice(line, _PF_FIELDS[3][0], _PF_FIELDS[3][1]).strip(),
            _slice(line, _PF_FIELDS[4][0], _PF_FIELDS[4][1]),
            _slice(line, _PF_FIELDS[5][0], _PF_FIELDS[5][1]).strip())
        by_mode.setdefault(row.mode, []).append(row)
    for rows in by_mode.values():
        rows.sort(key=lambda r: r.pf, reverse=True)
    return by_mode


def _read_ms(text):
    """Parse ``<base>_ms.dat``, indexed by mode.

    File order is kept, which is state order, because the phase reference is
    the largest-magnitude entry and reordering would obscure which machine that
    was.

    :param str text: the file's contents, or '' when the file is absent
    :returns: mode index to list of :class:`ModeShapeEntry`
    :rtype: dict
    :raises RAMSESError: if a field does not parse
    """
    by_mode = {}
    for i, line in enumerate(text.splitlines()):
        if not line.strip() or line[0] == '#':
            continue
        lineno = i + 1
        row = ModeShapeEntry(
            _int(line, _MS_FIELDS[0][0], _MS_FIELDS[0][1], lineno),
            _int(line, _MS_FIELDS[1][0], _MS_FIELDS[1][1], lineno),
            _num(line, _MS_FIELDS[2][0], _MS_FIELDS[2][1], lineno),
            _num(line, _MS_FIELDS[3][0], _MS_FIELDS[3][1], lineno),
            _slice(line, _MS_FIELDS[4][0], _MS_FIELDS[4][1]))
        by_mode.setdefault(row.mode, []).append(row)
    return by_mode


class ModeView(object):
    """A selection of modes, still attached to the run they came from.

    Filters return one of these rather than a bare array so that they compose,
    and so that the run's participation factors and mode shapes stay reachable
    through the selection.
    """

    def __init__(self, results, rows):
        """:param Results results: the run these modes came from
        :param numpy.ndarray rows: a :data:`MODE_DTYPE` array
        """
        self.results = results
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, item):
        return self.rows[item]

    def __iter__(self):
        return iter(self.rows)

    @property
    def lam(self):
        """The eigenvalues as a complex array.

        :rtype: numpy.ndarray
        """
        return self.rows['re'] + 1j * self.rows['im']

    def electromechanical(self, lo=0.1, hi=2.5):
        """The rotor band, one member of each conjugate pair, sorted by frequency.

        Rotor oscillations sit roughly between 0.1 and 2.5 Hz; below that are
        slow controller modes and above it exciter and network dynamics. The
        ``Im > 0`` test is what collapses each conjugate pair to a single row,
        since the two members are one physical oscillation.

        :param float lo: lower frequency bound in Hz, exclusive
        :param float hi: upper frequency bound in Hz, exclusive
        :returns: the selection
        :rtype: ModeView
        """
        sel = ((self.rows['freq'] > lo) & (self.rows['freq'] < hi)
               & (self.rows['im'] > 0.0))
        kept = self.rows[sel]
        return ModeView(self.results, kept[np.argsort(kept['freq'], kind='stable')])

    def dominant(self, real_limit=DEFAULT_REAL_LIMIT):
        """The modes whose real part is above ``real_limit``.

        Strictly greater than, which is what the engine's retired
        ``real_limit`` was, so a given limit selects exactly the modes it would
        have selected before. Input order is preserved, so composing this after
        :meth:`electromechanical` keeps that method's sort.

        :param float real_limit: the limit, in 1/s
        :returns: the selection
        :rtype: ModeView
        """
        return ModeView(self.results, self.rows[self.rows['re'] > real_limit])

    def participation(self, mode, floor=DEFAULT_PF_FLOOR, allow_degenerate=False):
        """See :meth:`Results.participation`. Resolves against this view's run.

        :rtype: list of Participation
        """
        return self.results.participation(mode, floor, allow_degenerate)

    def mode_shape(self, mode, allow_degenerate=False):
        """See :meth:`Results.mode_shape`. Resolves against this view's run.

        :rtype: list of ModeShapeEntry
        """
        return self.results.mode_shape(mode, allow_degenerate)

    def table(self):
        """Print one line per mode: index, frequency, damping ratio, lambda, simplicity.

        .. note:: This prints and returns None. Use :meth:`to_frame` or
                  :attr:`rows` to work with the values.
        """
        print('  %-6s %-9s %-11s %-26s %s'
              % ('mode', 'f [Hz]', 'zeta', 'lambda', 'simple'))
        for row in self.rows:
            print('  %-6d %-9.4f %-+11.4f %-26s %s'
                  % (row['index'], row['freq'], row['zeta'],
                     '%+.4f %+.4fj' % (row['re'], row['im']),
                     'yes' if row['simple'] else 'NO'))

    def to_frame(self):
        """The same rows as a pandas DataFrame.

        :rtype: pandas.DataFrame
        :raises RAMSESError: if pandas is not installed. It is not a dependency
                             of this package, which is why this is the only
                             place that imports it.
        """
        try:
            import pandas
        except ImportError:
            raise RAMSESError('RAMSES: to_frame() needs pandas, which stepss does '
                              'not depend on. Install it, or use .rows.')
        return pandas.DataFrame(self.rows)

    def splane(self, ax=None, zeta=DEFAULT_DAMPING_ZETA, annotate=True,
               interactive=None):
        """Draw the modes on the complex plane.

        The vertical axis is oscillation frequency and the horizontal axis the
        decay rate. Everything strictly left of the crimson line at ``Re = 0``
        is stable. The dashed ray marks constant damping ratio, the usual
        planning criterion being 0.05.

        One dashed ray rather than two, because a ray of constant zeta leaves
        the origin at ``asin(zeta)`` from the imaginary axis, so 0.05 and 0.10
        sit 2.87 and 5.74 degrees off vertical and arrive as a single smudge
        beside the boundary. The one that remains is adjustable, which is the
        more useful of the two answers.

        The window is fitted to the modes on screen rather than fixed, so this
        works on any system and so that filtering actually zooms. The fitted
        window always contains ``Re = 0``, because a view that has scrolled off
        the boundary shows damping with nothing to measure it from.

        :param ax: the axes to draw into, or None to make a figure
        :type ax: matplotlib.axes.Axes or None
        :param float zeta: damping ratio of the dashed ray; no ray is drawn
                           when it is outside (0, 1)
        :param bool annotate: label each mode with its frequency
        :param interactive: enable click-to-select and drag-to-zoom; None means
                            whenever the backend can update a window
        :type interactive: bool or None
        :returns: the axes drawn into
        :rtype: matplotlib.axes.Axes
        """
        import matplotlib.pyplot as plt

        from .live import _canDraw

        if ax is None:
            _, ax = plt.subplots(figsize=(6, 5))

        re = self.rows['re']
        im = self.rows['im']
        ax.axvline(0.0, color='crimson', lw=1.5, zorder=1)

        lo_re, hi_re, lo_im, hi_im = _fit_window(re, im)
        if 0.0 < zeta < 1.0:
            # The ray reaches the top of the window, or the far left of it,
            # whichever is further, and is then clipped to the axes.
            root = (1.0 - zeta ** 2) ** 0.5
            reach = max(hi_im, abs(lo_re) * root / zeta)
            ax.plot([0.0, -reach * zeta / root], [0.0, reach], '--',
                    color='0.6', lw=1, zorder=1)

        unstable = self.rows['zeta'] < 0.0
        ax.scatter(re, im, s=90, facecolors='none',
                   edgecolors=np.where(unstable, 'crimson', 'tab:blue'),
                   linewidths=np.where(unstable, 1.8, 1.2), zorder=3, picker=6)
        if annotate:
            for row in self.rows:
                ax.annotate(' %.2f Hz' % row['freq'], (row['re'], row['im']),
                            fontsize=8)
        if unstable.any():
            # An empty scatter carrying the marker itself, so the key and the
            # plot cannot come to disagree about what an unstable mode is.
            ax.scatter([], [], s=90, facecolors='none', edgecolors='crimson',
                       linewidths=1.8, label='unstable')
            ax.legend(loc='lower left')

        ax.set_xlim(lo_re, hi_re)
        ax.set_ylim(lo_im, hi_im)
        ax.set_xlabel(r'Re$(\lambda)$  [1/s]')
        ax.set_ylabel(r'Im$(\lambda)$  [rad/s]')
        ax.grid(alpha=0.3)

        live = _canDraw() if interactive is None else bool(interactive)
        ax._stepss_splane_interactive = live
        if live:
            _attach_splane_interaction(ax, self, (lo_re, hi_re, lo_im, hi_im))
        elif interactive is None:
            print('s-plane drawn without interaction: this backend has no '
                  'window to update. In a script, switch to an interactive '
                  'backend before plotting; in a notebook, run %matplotlib '
                  'widget first. Either gives click-to-select and '
                  'drag-to-zoom.')
        return ax


class Results(object):
    """One small-signal run: the three files the engine wrote, and its header.

    ``_pf.dat`` and ``_ms.dat`` are optional and load as empty when absent,
    because their absence is not a reason to refuse the run that is present.
    """

    def __init__(self, modes, header, participation, shapes, directory,
                 basename, ram=None, generation=None):
        """:param numpy.ndarray modes: a :data:`MODE_DTYPE` array
        :param dict header: as :func:`_read_modes` returns
        :param dict participation: as :func:`_read_pf` returns
        :param dict shapes: as :func:`_read_ms` returns
        :param str directory: where the files were read from
        :param str basename: the run's basename
        :param ram: the simulator this run was made with, for the state matrix
        :type ram: stepss.simulator.sim or None
        :param generation: the value of the simulator's analysis counter when
                           this run was produced
        :type generation: int or None
        """
        self.modes = modes
        self.nstates = header['nstates']
        self.nalg = header['nalg']
        self.time = header['time']
        self.pf_floor = header['pf_floor']
        self.gap_tol = header['gap_tol']
        self.format_version = header['format_version']
        self.directory = str(directory)
        self.basename = basename
        self._participation = participation
        self._shapes = shapes
        self._ram = ram
        self._generation = generation

    def view(self):
        """Every mode, as a selection.

        A copy of :attr:`modes`, so mutating the returned view's ``rows``
        cannot corrupt this run's own copy, the same protection
        :meth:`electromechanical` and :meth:`dominant` already have by
        filtering into a new array.

        :rtype: ModeView
        """
        return ModeView(self, self.modes.copy())

    def electromechanical(self, lo=0.1, hi=2.5):
        """See :meth:`ModeView.electromechanical`.

        :rtype: ModeView
        """
        return self.view().electromechanical(lo, hi)

    def dominant(self, real_limit=DEFAULT_REAL_LIMIT):
        """See :meth:`ModeView.dominant`.

        :rtype: ModeView
        """
        return self.view().dominant(real_limit)

    def _index_of(self, mode):
        """The mode index named by an int or by a row of :attr:`modes`.

        Checked against :attr:`modes` before it is handed back, so that a
        stale or made-up index is refused here rather than silently producing
        an empty plot or an empty list that reads as a real mode with nothing
        to show.

        :param mode: a 1-based mode index, or a row of :attr:`modes`
        :returns: the index
        :rtype: int
        :raises RAMSESError: if *mode* is neither, or names no mode in this run
        """
        if isinstance(mode, (int, np.integer)):
            index = int(mode)
        else:
            try:
                index = int(mode['index'])
            except (TypeError, ValueError, IndexError, KeyError):
                raise RAMSESError('RAMSES: %r is neither a mode index nor a '
                                  'row of .modes' % (mode,))
        if index not in self.modes['index']:
            raise RAMSESError(
                'RAMSES: mode %d is not in this run; valid indices are %d to '
                '%d.' % (index, int(self.modes['index'].min()),
                         int(self.modes['index'].max())))
        return index

    def _check_simple(self, index, allow_degenerate):
        """Refuse a degenerate mode unless the caller insists.

        In a degenerate eigenspace the individual eigenvectors are not unique,
        so participation factors and mode shapes are basis-dependent: they are
        real numbers that mean nothing physically and would come out
        differently on another LAPACK build. The graphical interface declines
        to show either, and so does this by default.

        :param int index: the mode index
        :param bool allow_degenerate: return the rows anyway
        :raises RAMSESError: if the mode is degenerate and *allow_degenerate*
                             is False
        """
        if allow_degenerate:
            return
        row = self.modes[self.modes['index'] == index]
        if len(row) and not row['simple'][0]:
            raise RAMSESError(
                'RAMSES: mode %d is degenerate (simple = 0). Its eigenvectors '
                'are not unique, so its participation factors and mode shape '
                'are basis-dependent and would come out differently on another '
                'machine. Pass allow_degenerate=True to read them anyway.'
                % index)

    def participation(self, mode, floor=DEFAULT_PF_FLOOR, allow_degenerate=False):
        """Participation factors for one mode, largest first.

        ``floor`` is applied here and not by the engine. The file carries every
        entry above the run's own :attr:`pf_floor`, so lowering this shows more
        without re-running anything, down to that floor. Only below it is an
        entry genuinely absent from the file rather than merely filtered here.

        :param mode: a mode index, or a row of :attr:`modes`
        :param float floor: smallest participation factor to return
        :param bool allow_degenerate: read a degenerate mode anyway
        :returns: the rows
        :rtype: list of Participation
        :raises RAMSESError: if the mode is degenerate and not allowed
        """
        index = self._index_of(mode)
        self._check_simple(index, allow_degenerate)
        return [row for row in self._participation.get(index, [])
                if row.pf >= floor]

    def mode_shape(self, mode, allow_degenerate=False):
        """The rotor-speed phasor of each machine in one mode, in state order.

        :param mode: a mode index, or a row of :attr:`modes`
        :param bool allow_degenerate: read a degenerate mode anyway
        :returns: the rows
        :rtype: list of ModeShapeEntry
        :raises RAMSESError: if the mode is degenerate and not allowed
        """
        index = self._index_of(mode)
        self._check_simple(index, allow_degenerate)
        return list(self._shapes.get(index, []))

    @property
    def ram(self):
        """The simulator this run was made with.

        None for a run read from disk, such as one returned by :func:`load` or
        :func:`load_archive`. For a run made by :func:`run` with
        ``keep_open=True``, this is the live simulator, left paused rather
        than finalised, and it is the caller's to finalise with
        :meth:`~stepss.simulator.sim.endSim` when they are done with it.

        :rtype: stepss.simulator.sim or None
        """
        return self._ram

    @property
    def state_matrix(self):
        """The state matrix the engine reduced for this run.

        Lazy rather than captured, because ``nstates`` can reach the engine's
        ceiling of 5000, at which the dense matrix is 200 MB, and most runs
        never read it.

        The engine retains one matrix at a time and ``get_state_matrix``
        refuses only an order mismatch, so a later analysis of a case with the
        same state count would otherwise be handed back silently. This checks
        the simulator's analysis counter instead.

        :rtype: numpy.ndarray
        :raises RAMSESError: if this run was read from disk rather than made
                             here, or a later analysis has replaced the matrix
        """
        if self._ram is None:
            raise RAMSESError(
                'RAMSES: the state matrix lives in the engine and is in none of '
                'the results files, so it is available on a live run made with '
                'ssa.run() only.')
        if self._ram._ssaGeneration != self._generation:
            raise RAMSESError(
                'RAMSES: a later analysis has replaced the retained state '
                'matrix; this run was analysis %d and the engine now holds %d. '
                'Read the state matrix before starting the next analysis.'
                % (self._generation, self._ram._ssaGeneration))
        return self._ram.getStateMatrix()

    def summary(self):
        """Print the run's header and its mode counts.

        .. note:: This prints and returns None.
        """
        print('%s in %s' % (self.basename, self.directory))
        print('  %d states, %d algebraic variables, modes file v%d'
              % (self.nstates or 0, self.nalg or 0, self.format_version))
        if self.time is not None:
            print('  linearised at t = %g s' % self.time)
        print('  %d modes, %d simple, %d degenerate'
              % (len(self.modes), int(self.modes['simple'].sum()),
                 int((~self.modes['simple']).sum())))
        if self.pf_floor is not None:
            print('  participation written down to %g ($PF_THRES)' % self.pf_floor)

    def save(self, path, saved_by=None):
        """Write this run to a ``.ssa`` archive. See :func:`save`.

        :param path: where to write it
        :type path: str or pathlib.Path
        :param saved_by: what to record as the writer
        :type saved_by: str or None
        :returns: the member names that were not on disk
        :rtype: list of str
        """
        return save(self, path, saved_by)

    def splane(self, **kwargs):
        """Draw every mode. See :meth:`ModeView.splane`.

        :rtype: matplotlib.axes.Axes
        """
        return self.view().splane(**kwargs)

    def mode_shape_plot(self, mode, ax=None, allow_degenerate=False):
        """Draw one mode's rotor-speed phasors on a polar dial.

        For an inter-area mode the expected picture is two groups roughly 180
        degrees apart: the areas swinging against each other.

        :param mode: a mode index, or a row of :attr:`modes`
        :param ax: a polar axes to draw into, or None to make one
        :type ax: matplotlib.axes.Axes or None
        :param bool allow_degenerate: draw a degenerate mode anyway. The
                                      picture would be basis-dependent and
                                      would look exactly as authoritative,
                                      which is why this is off by default.
        :returns: the axes drawn into
        :rtype: matplotlib.axes.Axes
        :raises RAMSESError: if the mode is degenerate and not allowed
        """
        import matplotlib.pyplot as plt

        entries = self.mode_shape(mode, allow_degenerate)
        index = self._index_of(mode)
        if ax is None:
            _, ax = plt.subplots(figsize=(5, 5),
                                 subplot_kw={'projection': 'polar'})
        for entry in entries:
            theta = np.deg2rad(entry.angle_deg)
            ax.annotate('', xy=(theta, entry.magnitude), xytext=(0, 0),
                        arrowprops=dict(arrowstyle='->', lw=2))
            ax.text(theta, entry.magnitude * 1.12, entry.device.strip(),
                    ha='center', va='center')
        ax.set_rmax(1.3)
        ax.set_title('Mode %d shape (rotor speeds)' % index, pad=18)
        return ax

    def participation_plot(self, mode, floor=DEFAULT_PF_FLOOR, ax=None,
                           allow_degenerate=False):
        """Draw one mode's participation factors as a horizontal bar chart.

        :param mode: a mode index, or a row of :attr:`modes`
        :param float floor: smallest participation factor to draw
        :param ax: the axes to draw into, or None to make a figure
        :type ax: matplotlib.axes.Axes or None
        :param bool allow_degenerate: draw a degenerate mode anyway
        :returns: the axes drawn into
        :rtype: matplotlib.axes.Axes
        :raises RAMSESError: if the mode is degenerate and not allowed
        """
        import matplotlib.pyplot as plt

        rows = self.participation(mode, floor, allow_degenerate)
        index = self._index_of(mode)
        if ax is None:
            _, ax = plt.subplots(figsize=(6, max(2.0, 0.3 * len(rows) + 1.0)))
        positions = np.arange(len(rows))
        ax.barh(positions, [row.pf for row in rows], color='tab:blue')
        ax.set_yticks(positions)
        ax.set_yticklabels(['%s %s' % (row.device.strip(), row.variable)
                            for row in rows])
        ax.invert_yaxis()
        ax.set_xlabel('participation factor')
        ax.set_title('Mode %d, entries at or above %g' % (index, floor))
        return ax


#: Margin around the fitted extent, as a fraction of it.
_FIT_PAD = 0.06

#: Smallest margin in data units, which is what keeps a window around a single
#: mode, or around a set sharing one real part, from collapsing to zero width.
#: A zero span maps every coordinate to the same pixel.
_MIN_PAD = 0.5


def _fit_window(re, im):
    """The axis window that holds these modes, with a margin and ``Re = 0``.

    :param numpy.ndarray re: real parts
    :param numpy.ndarray im: imaginary parts
    :returns: ``(lo_re, hi_re, lo_im, hi_im)``
    :rtype: tuple
    """
    if len(re) == 0:
        return -3.0, 0.5, 0.0, 9.0
    lo_re, hi_re = min(float(re.min()), 0.0), max(float(re.max()), 0.0)
    lo_im, hi_im = min(float(im.min()), 0.0), max(float(im.max()), 0.0)
    pad_re = max((hi_re - lo_re) * _FIT_PAD, _MIN_PAD)
    pad_im = max((hi_im - lo_im) * _FIT_PAD, _MIN_PAD)
    return lo_re - pad_re, hi_re + pad_re, lo_im - pad_im, hi_im + pad_im


def _attach_splane_interaction(ax, view, home):
    """Wire click-to-select and drag-to-zoom onto an s-plane.

    Both use matplotlib's own event machinery, so no other library is needed.
    The selector is stashed on the axes because matplotlib holds only a weak
    reference to a widget and would otherwise garbage-collect it, leaving a
    plot that looks interactive and is not.

    :param matplotlib.axes.Axes ax: the axes drawn by :meth:`ModeView.splane`
    :param ModeView view: the modes it is showing
    :param tuple home: the fitted window, restored on a double click
    """
    from matplotlib.widgets import RectangleSelector

    def on_pick(event):
        if event.artist.axes is not ax or not len(event.ind):
            return
        row = view.rows[event.ind[0]]
        print('mode %d: f = %.4f Hz, zeta = %+.4f, lambda = %+.4f %+.4fj, %s'
              % (row['index'], row['freq'], row['zeta'], row['re'], row['im'],
                 'simple' if row['simple'] else 'DEGENERATE'))

    def on_zoom(press, release):
        if press.xdata is None or release.xdata is None:
            return
        ax.set_xlim(min(press.xdata, release.xdata),
                    max(press.xdata, release.xdata))
        ax.set_ylim(min(press.ydata, release.ydata),
                    max(press.ydata, release.ydata))
        ax.figure.canvas.draw_idle()

    def on_click(event):
        if event.inaxes is ax and event.dblclick:
            ax.set_xlim(home[0], home[1])
            ax.set_ylim(home[2], home[3])
            ax.figure.canvas.draw_idle()

    ax._stepss_splane_selector = RectangleSelector(
        ax, on_zoom, useblit=False, button=[1], interactive=False)
    ax.figure.canvas.mpl_connect('pick_event', on_pick)
    ax.figure.canvas.mpl_connect('button_press_event', on_click)


def load(directory, basename):
    """Read one run from disk, whatever produced it.

    :param directory: the directory holding the run
    :type directory: str or pathlib.Path
    :param str basename: the run's basename
    :returns: the run
    :rtype: Results
    :raises RAMSESError: if the modes file is absent or does not parse
    """
    directory = str(directory)
    modes_path = os.path.join(directory, basename + RESULT_SUFFIXES[0])
    if not os.path.isfile(modes_path):
        raise RAMSESError('RAMSES: no %s%s in %s'
                          % (basename, RESULT_SUFFIXES[0], directory))
    modes, header = _read_modes(_read_text(modes_path))
    return Results(modes, header,
                   _read_pf(_optional_text(directory, basename, '_pf.dat')),
                   _read_ms(_optional_text(directory, basename, '_ms.dat')),
                   directory, basename)


def basenames(directory):
    """Every basename in *directory* for which a modes file exists, sorted.

    A directory named ``<x>_modes.dat`` is not offered, because it would then
    be refused by :func:`load` about a name that plainly exists.

    :param directory: the directory to look in
    :type directory: str or pathlib.Path
    :returns: the basenames
    :rtype: list of str
    """
    directory = str(directory)
    suffix = RESULT_SUFFIXES[0]
    found = []
    try:
        names = os.listdir(directory)
    except OSError:
        return found
    for name in names:
        if (name.endswith(suffix) and len(name) > len(suffix)
                and os.path.isfile(os.path.join(directory, name))):
            found.append(name[:-len(suffix)])
    return sorted(found)


def _read_text(path):
    """The whole of a text file, decoded as UTF-8.

    :param str path: the file
    :returns: its contents
    :rtype: str
    """
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        return handle.read()


def _optional_text(directory, basename, suffix):
    """The contents of an optional results file, or '' when it is absent.

    :param str directory: the run's directory
    :param str basename: the run's basename
    :param str suffix: the file suffix, including its leading underscore
    :returns: the contents, or ''
    :rtype: str
    """
    path = os.path.join(str(directory), basename + suffix)
    return _read_text(path) if os.path.isfile(path) else ''


#: What is appended to a run's basename to name the generated settings file.
#: It mirrors the disturbance file the same run generates, and cannot collide
#: with a results file or a Jacobian table, all of which begin with an
#: underscore.
SETTINGS_SUFFIX = 'Eig.dat'

#: What is appended to a run's basename to name the generated disturbance file.
DISTURBANCE_SUFFIX = 'Eig.dst'

#: Gap between the analysis and the STOP record. The analysis is complete when
#: it returns, so this only has to be positive.
_STOP_MARGIN = 0.010

_BASENAME_OK = frozenset(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-')


def valid_basename(basename):
    """Whether *basename* is safe as both a file name stem and a quoted record.

    An apostrophe would terminate the analysis record's quoted argument early
    and the engine would write nothing, and a path separator would put the
    results where the loader does not look.

    :param basename: the candidate
    :returns: True when it may be used
    :rtype: bool
    """
    if not basename or not isinstance(basename, str):
        return False
    return all(char in _BASENAME_OK for char in basename)


def check_time(t):
    """Validate an analysis time.

    :param t: the time in seconds
    :returns: the time as a float
    :rtype: float
    :raises RAMSESError: if it is not a finite number, or is earlier than
                         :data:`MIN_TIME`
    """
    try:
        value = float(t)
    except (TypeError, ValueError):
        raise RAMSESError('RAMSES: the analysis time must be a number, not %r'
                          % (t,))
    if value != value or value in (float('inf'), float('-inf')):
        raise RAMSESError('RAMSES: the analysis time must be a finite number.')
    if value < MIN_TIME:
        raise RAMSESError('RAMSES: the analysis time must be at least %g s; the '
                          'engine needs at least one step before it can apply '
                          'an event.' % MIN_TIME)
    return value


def settings_text():
    """The solver settings a small-signal run is given, read after the case's own.

    Two records and nothing else. Every record here overrides whatever the case
    set, so anything beyond what the analysis requires would silently change
    the run for no reason. ``$EIG_MAX_STATES`` in particular is deliberately
    absent: it is a memory guard rather than a correctness one, and the
    eigensolve holds nine times the square of the state count in doubles at its
    peak, so raising it on the caller's behalf would trade a clear refusal for
    an out-of-memory kill.

    :returns: the file text, newline terminated
    :rtype: str
    """
    return ('# Written by stepss for the small-signal run, and read after the\n'
            "# case's own data files. The engine keeps the last record of each\n"
            '# kind it reads, so these two are the ones the analysis runs under\n'
            '# whatever the case set. Nothing else here is changed.\n'
            '\n'
            '$SCHEME DE                         ;\n'
            '$OMEGA_REF SYN                     ;\n')


def settings_name(basename):
    """What the generated settings file is called for a given run.

    :param str basename: the run's basename
    :returns: the file name, with no directory part
    :rtype: str
    :raises RAMSESError: if the basename is rejected
    """
    if not valid_basename(basename):
        raise RAMSESError('RAMSES: invalid results basename %r' % (basename,))
    return basename + SETTINGS_SUFFIX


def disturbance_name(basename):
    """What the generated disturbance file is called for a given run.

    :param str basename: the run's basename
    :returns: the file name, with no directory part
    :rtype: str
    :raises RAMSESError: if the basename is rejected
    """
    if not valid_basename(basename):
        raise RAMSESError('RAMSES: invalid results basename %r' % (basename,))
    return basename + DISTURBANCE_SUFFIX


def disturbance_text(t):
    """A disturbance file carrying no events, ending just after *t*.

    A disturbance file is mandatory because the case format requires one,
    regardless of how the analysis is run; :func:`run` generates this one when
    the case it is given carries none of its own. It deliberately carries no
    events: the engine linearises about whatever state the system is in when
    the analysis fires, so an event before then would describe that instant
    rather than an operating point. Running to a later time with no events
    lets the initialisation settle and linearises about the same operating
    point.

    :param float t: the analysis time in seconds
    :returns: the file text, newline terminated
    :rtype: str
    :raises RAMSESError: if the time is rejected
    """
    stop = check_time(t) + _STOP_MARGIN
    # Fixed point rather than repr, which emits scientific notation for small
    # values: the engine reads these records list-directed and would accept
    # 1.0E-3, but a plain decimal is what every other disturbance file in this
    # project uses and is what a reader comparing the two will expect.
    return ('0.000 CONTINUE SOLVER TR 0.010 0.001 0. ALL\n'
            '%.6f STOP\n' % stop)


def members(basename):
    """Every file a run of *basename* writes, results first.

    This is also exactly what an archive of the run carries besides its
    manifest, and exactly what :func:`clear_previous_run` deletes: the files a
    run writes and the files an archive of it holds are the same files.

    :param str basename: the run's basename
    :returns: the file names, with no directory part
    :rtype: tuple of str
    """
    return tuple(basename + suffix
                 for suffix in RESULT_SUFFIXES + JACOBIAN_SUFFIXES)


def clear_previous_run(directory, basename):
    """Delete what a previous run of *basename* left, and report what would not go.

    Why a run has to start by doing this. The engine writes its results itself
    and reports nothing on the way out about whether it managed to, so the only
    evidence a caller has is whether the modes file is on disk afterwards. A
    run whose initialisation failed writes nothing at all, and in a directory
    already holding an earlier run under the same basename that test passes on
    the earlier run's file. Clearing first is what makes "the modes file is
    there" mean "this run wrote it".

    Nothing else in the directory is touched: the basename exists so that
    several runs can share one directory, and the case's own data files usually
    live there too.

    :param directory: where the run will write, which need not exist
    :type directory: str or pathlib.Path
    :param str basename: the run's basename
    :returns: the names still present, in :func:`members` order; empty when the
              directory is clear
    :rtype: list of str
    """
    stuck = []
    for name in members(basename):
        path = os.path.join(str(directory), name)
        # exists() first, so that "was never there" and "is there and will not
        # go" stay distinguishable: only the second is a reason to refuse a run.
        if not os.path.exists(path):
            continue
        try:
            os.remove(path)
        except OSError:
            stuck.append(name)
    return stuck


# Which of a case's file lists name inputs. These are resolved to absolute
# paths before the working directory changes, so that a case built with
# relative names keeps working. The output lists are deliberately left alone,
# so that the trajectory and the traces land in the run's own directory.
#
# The test of an input is which way the cfg method fails: addObs and addData
# refuse a file that does not exist, while addInit warns that an existing one
# will be overwritten. The initialisation trace is therefore an output and is
# not in this tuple, however much its name suggests otherwise.
_INPUT_LISTS = ('_dataset', '_dstset', '_obs')


def _absolutise(case):
    """A copy of *case* whose input paths are absolute.

    The lists are rewritten directly rather than through the ``add`` methods,
    because those resolve against the current directory and validate on the
    way in, and this runs before the directory changes.

    :param stepss.cases.cfg case: the caller's case, which is not modified
    :returns: the copy
    :rtype: stepss.cases.cfg
    :raises AttributeError: if a name in :data:`_INPUT_LISTS` is not a list on
        the case. Deliberate: a default here would turn a wrong or renamed
        attribute into a silent no-op, and an input left relative fails much
        later and somewhere else.
    """
    copy = deepcopy(case)
    for name in _INPUT_LISTS:
        entries = getattr(copy, name)
        if entries:
            entries[:] = [os.path.abspath(entry) for entry in entries]
    return copy


def _same_file(left, right):
    """Whether two paths name the same file, whether or not it exists.

    :param str left: one path
    :param str right: the other
    :returns: True when the two name one file
    :rtype: bool
    """
    try:
        if os.path.exists(left) and os.path.exists(right):
            return os.path.samefile(left, right)
    except OSError:
        pass
    # realpath rather than abspath: abspath normalises ".." but not a
    # symlinked directory component, so a caller reaching their data file
    # through a symlink while workdir names the real directory would slip past
    # the collision refusal and have that file overwritten.
    return (os.path.normcase(os.path.realpath(left))
            == os.path.normcase(os.path.realpath(right)))


def run(case, basename='ssa', t=None, workdir=None, jacobian=False,
        ram=None, keep_open=False):
    """Run one small-signal analysis and return its results.

    The case is copied, never modified: it stays usable for an ordinary
    time-domain run afterwards. The copy is given one extra data file carrying
    ``$SCHEME DE`` and ``$OMEGA_REF SYN``, read last so that it wins whatever
    the case set, because the engine refuses the analysis under either of the
    values a case that says nothing about them lands on.

    Anything already on disk under *basename* is deleted before the run starts,
    since the only evidence an analysis produced results is that its modes file
    is there afterwards.

    :param stepss.cases.cfg case: the case to analyse
    :param str basename: names the three results files
    :param t: when to linearise, in seconds; defaults to :data:`MIN_TIME`
    :type t: float or None
    :param workdir: where to run and where the results land; the current
                    directory when None. It is created if it does not exist,
                    and the previous working directory is restored afterwards.
    :type workdir: str or pathlib.Path or None
    :param bool jacobian: also write the four Jacobian tables, at the instant
                          of the reduction. This uses paired disturbance
                          records rather than the direct entry, because
                          ``dumpjac`` and ``dumpeig`` are independent flags and
                          the two direct entries each advance the clock by a
                          millisecond, so calling them in turn would dump a
                          Jacobian taken after the reduction rather than at it.
    :param ram: an existing simulator to run in, or None to make one
    :type ram: stepss.simulator.sim or None
    :param bool keep_open: leave the simulation paused instead of finalising
                           it. A paused simulation is not finished, and loading
                           another case without finalising silently resumes it,
                           so this is for a caller who means to go on
                           interrogating this run. It applies only to a
                           simulator this call created: one passed as *ram* is
                           never finalised here whatever this is set to, on the
                           principle of not closing what you did not open, and
                           is the caller's to :meth:`~stepss.simulator.sim.endSim`.
                           Either way, the simulator is reachable afterwards as
                           :attr:`Results.ram`, which is where that call goes.
    :returns: the run
    :rtype: Results

    .. note:: When the case carries a disturbance file of its own, *t* must
              fall before that file's STOP record, because a run that has
              already stopped cannot be advanced to *t*, and before
              ``t + 0.010`` under ``jacobian=True``, which runs that much
              further to let the paired records fire. That cannot be checked
              here without parsing the caller's file, so it is stated rather
              than enforced; the failure is loud, since :meth:`runSsa` refuses
              a *t* earlier than the simulated time already reached. The
              generated file used when the case has none stops just after *t*.

    .. note:: The working directory is process-wide, so two of these must not
              run concurrently from threads: their ``chdir`` calls interleave
              and one analysis writes its results into the other's directory,
              which no check here can detect, because file existence is the
              only evidence a run produced anything and both runs find files.
              :class:`stepss.simulator.sim` carries the same restriction for
              its own reasons.
    :raises RAMSESError: if the basename or time is rejected, the generated
                         settings file would overwrite one of the case's own
                         data files, a previous run cannot be cleared, or the
                         analysis produced no modes file

    :Example:

    >>> import stepss
    >>> from stepss import ssa
    >>> case = stepss.cfg('cmd.txt')
    >>> res = ssa.run(case, basename='ssa', workdir='run1')
    >>> res.electromechanical().table()
    """
    if not valid_basename(basename):
        raise RAMSESError(
            'RAMSES: the results basename %r cannot be used. It names the three '
            'results files and is written into the analysis record, so it may '
            'contain only letters, digits, dot, underscore and hyphen.'
            % (basename,))
    when = check_time(MIN_TIME if t is None else t)

    prepared = _absolutise(case)
    here = os.getcwd()
    target = here if workdir is None else os.path.abspath(str(workdir))
    if not os.path.isdir(target):
        os.makedirs(target)

    settings_path = os.path.join(target, settings_name(basename))
    # Refused rather than written or deleted: a loaded data file bearing one
    # of these names is the caller's, and this run would either write over it
    # (the settings file) or, for a name from members(), have
    # clear_previous_run delete it before the engine writes its replacement.
    # Either way the caller's file is destroyed silently.
    guarded_paths = [settings_path] + [os.path.join(target, name)
                                       for name in members(basename)]
    for data_file in prepared.getData():
        for guarded_path in guarded_paths:
            if _same_file(data_file, guarded_path):
                raise RAMSESError(
                    'RAMSES: the run needs to write %s, which is one of the '
                    'loaded data files. Choose a different results basename, '
                    'or move that file, so the analysis does not overwrite it.'
                    % os.path.basename(guarded_path))

    owns_sim = ram is None
    os.chdir(target)
    try:
        with open(settings_name(basename), 'w') as handle:
            handle.write(settings_text())
        prepared.addData(os.path.abspath(settings_name(basename)))

        if not prepared.getDst():
            with open(disturbance_name(basename), 'w') as handle:
                handle.write(disturbance_text(when))
            prepared.addDst(os.path.abspath(disturbance_name(basename)))

        # Last, after every refusal above, because it destroys the previous run
        # under this basename: a run that never starts must leave that run
        # intact.
        stuck = clear_previous_run(target, basename)
        if stuck:
            raise RAMSESError(
                'RAMSES: a previous "%s" run is still in %s and could not be '
                'removed: %s. It would be read as this run\'s, so the analysis '
                'was not started.' % (basename, target, ', '.join(stuck)))

        if ram is None:
            from .simulator import sim
            ram = sim()
        ram.execSim(prepared, 0.0)
        if jacobian:
            # JAC and EIG fire at the same t and the engine acts on them in
            # that order within one step (simul_decomp: dump_jacobian then
            # dump_eig), so the dumped Jacobian is necessarily the one the
            # analysis reduced rather than one taken a moment later.
            #
            # This route carries no equivalent of runSsa's "time already
            # passed" refusal, and it cannot be reached here: execSim(prepared,
            # 0.0) just above always resets the clock to 0, and when is at
            # least MIN_TIME, so when > ram.getSimTime() always holds and
            # contSim() always runs. The two routes are not disagreeing; the
            # check is simply moot on this one.
            if when > ram.getSimTime():
                ram.contSim(when)
            ram.addDisturb(when, "JAC '%s'" % basename)
            ram.addDisturb(when, "EIG '%s'" % basename)
            ram.contSim(when + _STOP_MARGIN)
            ram._noteSsaAnalysis()
        else:
            ram.runSsa(basename, when)
        generation = ram._ssaGeneration

        modes_path = os.path.join(target, basename + RESULT_SUFFIXES[0])
        if not os.path.isfile(modes_path):
            raise RAMSESError(
                'RAMSES: no results were produced. The run was given $SCHEME DE '
                'and $OMEGA_REF SYN, so the reason is elsewhere: usually a '
                'system with more states than $EIG_MAX_STATES allows, or one '
                'with no differential states at all. The engine says which: %s'
                % ram.getLastErr())

        modes, header = _read_modes(_read_text(modes_path))
        return Results(modes, header,
                       _read_pf(_optional_text(target, basename, '_pf.dat')),
                       _read_ms(_optional_text(target, basename, '_ms.dat')),
                       target, basename, ram=ram, generation=generation)
    finally:
        # Nested, so the working directory comes back on every path. endSim
        # reaches the engine through ctypes and can raise something other than
        # RAMSESError; unnested, that would propagate out of this finally and
        # leave the process sitting in target, silently relocating every
        # relative path the caller uses afterwards.
        try:
            if ram is not None and owns_sim and not keep_open:
                try:
                    ram.endSim()
                except RAMSESError:
                    # A run that already stopped, or one that failed before it
                    # started, has nothing to finalise. The failure worth
                    # reporting is the one on the way out of the try block,
                    # not this one.
                    pass
        finally:
            os.chdir(here)


#: The archive format this module writes, and the newest it reads.
ARCHIVE_FORMAT_VERSION = 1

#: Names the manifest inside an archive.
MANIFEST_NAME = 'stepss-ssa.txt'

_MANIFEST_MAGIC = '# STEPSS small-signal archive v'


class Manifest(namedtuple('Manifest', 'basename engine_version time saved_by')):
    """What an archive records about the run inside it.

    Every field but the basename may be None, and None means "not recorded"
    rather than zero. There are no threshold fields: the analysis record has no
    thresholds to record, and the one floor the engine applies is written into
    the modes file itself as ``pf_floor``.
    """

    __slots__ = ()

    def text(self):
        """The manifest file's contents.

        A key per line, absent keys omitted rather than written as zero, read
        back by name so that a later format can add one without breaking this.
        The prose at the top is for whoever opens the archive in a file manager
        and wants to know what they have without installing anything.

        :returns: the file text, newline terminated
        :rtype: str
        """
        lines = [
            _MANIFEST_MAGIC + str(ARCHIVE_FORMAT_VERSION),
            '#',
            '# One small-signal run, as it was analysed: the dynamic Jacobian the',
            '# engine reduced, the modes, participation factors and mode shapes',
            '# it produced, and this file. The data files, solver settings and',
            '# disturbance that produced them are NOT here, so this records a',
            '# result rather than reproducing it.',
            '#',
            '# Open it with Load dynamic Jacobian on the STEPSS Analysis tab, or',
            '# with stepss.ssa.load_archive() in Python.',
            '#',
            'basename ' + self.basename,
        ]
        if self.engine_version is not None:
            lines.append('engine_version %.2f' % self.engine_version)
        if self.time is not None:
            lines.append('t %.6f' % self.time)
        if self.saved_by:
            lines.append('saved_by ' + self.saved_by)
        return '\n'.join(lines) + '\n'

    @classmethod
    def parse(cls, text):
        """Read a manifest back.

        :param str text: the manifest file's contents
        :returns: the run it describes
        :rtype: Manifest
        :raises RAMSESError: if the text is not a manifest, was written by a
                             newer STEPSS, or names a basename this module
                             would refuse to write
        """
        version = -1
        fields = {'basename': None, 'engine_version': None, 't': None,
                  'saved_by': None}
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith(_MANIFEST_MAGIC):
                tail = line[len(_MANIFEST_MAGIC):].strip()
                version = int(tail) if tail.isdigit() else -1
                continue
            if line[0] == '#':
                continue
            key, _, value = line.partition(' ')
            if key in fields:
                fields[key] = value.strip()
        if version < 0:
            raise RAMSESError('RAMSES: its %s does not start with "%s".'
                              % (MANIFEST_NAME, _MANIFEST_MAGIC))
        if version > ARCHIVE_FORMAT_VERSION:
            raise RAMSESError('RAMSES: it is in archive format v%d and stepss '
                              'reads v%d. Update stepss to open it.'
                              % (version, ARCHIVE_FORMAT_VERSION))
        # The basename becomes a file name the moment it is used, and it
        # arrives from a file someone else wrote, so it is held to exactly the
        # rule this module holds its own basenames to rather than trusted.
        if not valid_basename(fields['basename']):
            raise RAMSESError('RAMSES: its %s names an unusable basename %r.'
                              % (MANIFEST_NAME, fields['basename']))
        return cls(fields['basename'],
                   _float_or_none(fields['engine_version']),
                   _float_or_none(fields['t']),
                   fields['saved_by'])


def _float_or_none(token):
    """*token* as a float, or None when it is absent or does not parse.

    :param token: the text
    :type token: str or None
    :rtype: float or None
    """
    if token is None:
        return None
    try:
        return float(token)
    except ValueError:
        return None


def save(results, path, saved_by=None):
    """Write one run to a ``.ssa`` archive the graphical interface can open.

    The format is chosen from the file name: ``.tar.gz`` or ``.tgz`` for a
    gzipped tar, anything else for a zip. Everything goes under one directory
    named for the run, so unpacking by hand produces a folder rather than eight
    loose files, and the manifest is written first so that a listing puts what
    the archive is at the top.

    :param Results results: the run to archive
    :param path: where to write it
    :type path: str or pathlib.Path
    :param saved_by: what to record as the writer; defaults to this package and
                     its version
    :type saved_by: str or None
    :returns: the member names that were not on disk, in :func:`members` order.
              The three results files are optional in the sense that
              ``_pf.dat`` and ``_ms.dat`` may legitimately be absent, and the
              four Jacobian tables are absent from every run made without
              ``jacobian=True``.
    :rtype: list of str
    :raises RAMSESError: if the run has no modes file to archive
    """
    from . import __version__

    directory = getattr(results, 'directory', None)
    basename = getattr(results, 'basename', None)
    if not directory or not basename:
        raise RAMSESError('RAMSES: this Results names no directory to archive.')
    modes_path = os.path.join(directory, basename + RESULT_SUFFIXES[0])
    if not os.path.isfile(modes_path):
        raise RAMSESError('RAMSES: there is no %s in %s, so there is no analysis '
                          'to archive.'
                          % (os.path.basename(modes_path), directory))

    present, absent = [], []
    for name in members(basename):
        (present if os.path.isfile(os.path.join(directory, name))
         else absent).append(name)

    manifest = Manifest(basename, None, results.time,
                        saved_by or ('stepss %s' % __version__)).text()
    target = str(path)
    prefix = basename + '/'
    if _is_tar_name(target):
        # Refused before anything is written, on the tar path only: the Java
        # writer (SsaArchive.java) refuses the same way for the same reason.
        _check_tar_names(prefix, [MANIFEST_NAME] + present)
    # Written to a .part file and moved into place, as the Java side does.
    # A failure partway through, a full disk or a permission error, would
    # otherwise leave a truncated file at the requested path that looks like
    # an archive until someone tries to open it.
    part = target + '.part'
    try:
        if _is_tar_name(target):
            with tarfile.open(part, 'w:gz') as archive:
                _tar_add_bytes(archive, prefix + MANIFEST_NAME,
                               manifest.encode('utf-8'))
                for name in present:
                    archive.add(os.path.join(directory, name),
                                arcname=prefix + name)
        else:
            with zipfile.ZipFile(part, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(prefix + MANIFEST_NAME, manifest)
                for name in present:
                    archive.write(os.path.join(directory, name),
                                  arcname=prefix + name)
        os.replace(part, target)
    except BaseException:
        # Nothing survives a failure, so a retry starts from a clean slate.
        # BaseException rather than Exception: an interrupt partway through a
        # write leaves the same debris as an error does.
        if os.path.exists(part):
            os.remove(part)
        raise
    return absent


def load_archive(path, into=None):
    """Unpack a ``.ssa`` archive and read the run in it.

    :param path: the archive, in ``.zip`` or gzipped tar
    :type path: str or pathlib.Path
    :param into: where to unpack; a temporary directory when None. The results
                 files are read from there and the returned :class:`Results`
                 keeps naming that directory, which is why the default one is
                 not cleaned up here.
    :type into: str or pathlib.Path or None
    :returns: ``(results, manifest)``
    :rtype: tuple
    :raises RAMSESError: if the file is neither a zip nor a gzipped tar, holds
                         no manifest, is in a newer format, names an unusable
                         basename, or carries an entry that would be written
                         outside the destination
    """
    target = str(path)
    into = tempfile.mkdtemp(prefix='stepss-ssa-') if into is None else str(into)
    if zipfile.is_zipfile(target):
        with zipfile.ZipFile(target) as archive:
            for name in archive.namelist():
                _safe_child(into, name)
            archive.extractall(into)
    elif tarfile.is_tarfile(target):
        with tarfile.open(target, 'r:*') as archive:
            for member in archive.getmembers():
                _safe_child(into, member.name)
            # filter='data' explicitly, rather than relying on the default.
            # Python 3.14 changes that default to filter and warns until it
            # does, so naming it keeps the behaviour identical either side of
            # that release instead of changing under the package silently. It
            # is also the right filter: an archive of this format holds
            # regular files and one directory, and 'data' strips the device
            # nodes, links and setuid bits none of them should carry.
            # _safe_child above still does the path check, which the filter
            # does not replace, because the filter reports its refusals as
            # exceptions from inside extraction rather than before it.
            archive.extractall(into, filter='data')
    else:
        raise RAMSESError('RAMSES: could not open %s: it is neither a zip nor a '
                          'gzipped tar, so it is not a small-signal archive.'
                          % os.path.basename(target))

    manifest_path = _find_manifest(into)
    if manifest_path is None:
        raise RAMSESError('RAMSES: could not open %s: it carries no %s, so it '
                          'was not written by STEPSS.'
                          % (os.path.basename(target), MANIFEST_NAME))
    manifest = Manifest.parse(_read_text(manifest_path))
    return load(os.path.dirname(manifest_path), manifest.basename), manifest


def _is_tar_name(name):
    """Whether *name* spells a gzipped tar.

    ``.tgz`` is accepted on the way in because many tools produce it, and never
    written: one spelling per format keeps the writer honest about what it made.

    :param str name: the file name
    :rtype: bool
    """
    lower = name.lower()
    return lower.endswith('.tar.gz') or lower.endswith('.tgz')


def _check_tar_names(prefix, names):
    """Refuse a member name a ustar header cannot hold.

    A ustar name field is 100 bytes. Past that, CPython's ``tarfile`` does not
    refuse: it falls back to a PAX extended header, which the graphical
    interface's own unpacker does not read, since it skips PAX headers and
    extracts every later member's truncated ustar name over the one before it.
    A long basename would therefore write an archive that looks fine here and
    loses data there. Checked before anything is written, so both writers
    refuse the same basenames.

    :param str prefix: the archive's top-level directory, with trailing slash
    :param names: the member names about to be written, with no directory part
    :type names: iterable of str
    :raises RAMSESError: if a resulting member name would exceed 100 bytes
    """
    for name in names:
        full = prefix + name
        length = len(full.encode('utf-8'))
        if length > 100:
            raise RAMSESError(
                'RAMSES: the name "%s" is %d bytes, past the 100-byte limit a '
                'tar archive member name can hold. Save as .zip, or use a '
                'shorter basename.' % (full, length))


def _tar_add_bytes(archive, name, payload):
    """Add an in-memory member to an open tar archive.

    :param tarfile.TarFile archive: the archive
    :param str name: the member name
    :param bytes payload: its contents
    """
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def _safe_child(into, entry_name):
    """Refuse an archive entry that would be written outside *into*.

    :param str into: the destination directory
    :param str entry_name: the entry's name as the archive spells it
    :returns: the resolved path
    :rtype: str
    :raises RAMSESError: if the entry escapes the destination
    """
    root = os.path.realpath(into)
    resolved = os.path.realpath(os.path.join(root, entry_name))
    if resolved != root and not resolved.startswith(root + os.sep):
        raise RAMSESError('RAMSES: the archive entry %r would be written outside '
                          'the destination directory.' % (entry_name,))
    return resolved


def _find_manifest(root):
    """The manifest inside an unpacked archive, at the root or one level down.

    :param str root: the unpacked directory
    :returns: the path, or None when there is none
    :rtype: str or None
    """
    direct = os.path.join(root, MANIFEST_NAME)
    if os.path.isfile(direct):
        return direct
    for name in sorted(os.listdir(root)):
        nested = os.path.join(root, name, MANIFEST_NAME)
        if os.path.isfile(nested):
            return nested
    return None
