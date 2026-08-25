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
