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
from collections import namedtuple

import numpy as np

from .globals import RAMSESError

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
ModeShapeEntry.__doc__ = """One row of ``<base>_ms.dat``: a machine's rotor-speed phasor in one mode.

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

        :rtype: ModeView
        """
        return ModeView(self, self.modes)

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

        :param mode: a 1-based mode index, or a row of :attr:`modes`
        :returns: the index
        :rtype: int
        :raises RAMSESError: if *mode* is neither
        """
        if isinstance(mode, (int, np.integer)):
            return int(mode)
        try:
            return int(mode['index'])
        except (TypeError, ValueError, IndexError, KeyError):
            raise RAMSESError('RAMSES: %r is neither a mode index nor a row of '
                              '.modes' % (mode,))

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
