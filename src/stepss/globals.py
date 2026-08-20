#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Global module variables and utilities shared across stepss.

Provides:
- Module-level configuration flags (``__runTimeObs__``) and the resolved
  paths to the bundled native libraries: ``__libdir__`` (the ``libs/`` root,
  holding the platform-independent C headers) and ``__platlibdir__`` (the
  platform subdirectory ``libs/win``, ``libs/lin`` or ``libs/mac`` holding
  the shared libraries for the current platform).
- ``RAMSESError`` — custom exception for RAMSES solver failures.
- Helper functions used by :mod:`stepss.cases` and :mod:`stepss.simulator`.
"""

import errno
import inspect
import os
import sys

__runTimeObs__ = True
__libdir__ = os.path.realpath(
    os.path.abspath(os.path.join(os.path.split(inspect.getfile(inspect.currentframe()))[0], "libs")))


def _platform_subdir():
    """Return the ``libs/`` subdirectory name for the current platform.

    The macOS and Linux RAMSES builds share the filename ``ramses.so``, so
    the bundled libraries are kept in per-platform subdirectories:
    ``win`` (Windows), ``mac`` (macOS), ``lin`` (Linux and everything else).

    :returns: platform folder name, one of ``'win'``, ``'mac'``, ``'lin'``
    :rtype: str
    """
    if sys.platform in ('win32', 'cygwin'):
        return 'win'
    if sys.platform == 'darwin':
        return 'mac'
    return 'lin'


__platlibdir__ = os.path.join(__libdir__, _platform_subdir())


def CustomWarning(message, category, filename, lineno, file=None, line=None):
    """Format and print a RAMSES warning to stdout.

    Replaces the default :func:`warnings.showwarning` handler so that all
    warnings issued by stepss carry the ``RAMSESWarning:`` prefix.

    :param message: warning message object
    :param category: warning category class (unused; included for API compatibility)
    :param filename: source file that triggered the warning (unused; included for API compatibility)
    :param lineno: line number that triggered the warning (unused; included for API compatibility)
    :param file: output file object (unused; always writes to stdout)
    :param line: source line text (unused; included for API compatibility)

    .. note:: This function writes directly to stdout and has no return value.
    """
    print("RAMSESWarning: %s" % message)


def read_file(fname):
    """Read and return the text content of a file bundled with the package.

    The path is resolved relative to the directory containing this module,
    making it suitable for reading package data files (e.g. ``README.rst``).

    :param str fname: filename relative to the stepss package directory
    :returns: full text content of the file
    :rtype: str
    :raises IOError: if the file cannot be opened
    """
    with open(os.path.join(os.path.dirname(__file__), fname)) as f:
        return f.read()


class RAMSESError(Exception):
    """Exception raised for errors returned by the RAMSES solver.

    Raised when a RAMSES C library call returns a non-zero status code that
    cannot be recovered from, or when arguments supplied to a stepss function
    are inconsistent with the current solver state.
    """
    pass


class HeliosError(Exception):
    """Exception raised for errors returned by the Helios power-flow engine.

    Raised when a helios C library call returns a negative status code; the
    message includes the diagnostic text retrieved from the library's
    per-handle error channel (``helios_get_last_error``).
    """
    pass


def silentremove(filename):
    """Delete a file, silently ignoring the case where it does not exist.

    Any other OS-level error (e.g. permission denied) is re-raised unchanged.

    :param str filename: path of the file to remove
    :raises OSError: if deletion fails for any reason other than the file not existing
    """

    try:
        os.remove(filename)
    except OSError as e:
        if e.errno != errno.ENOENT:  # errno.ENOENT = no such file or directory
            raise  # re-raise exception if a different error occured

def wrapToList(item):
    """Wrap *item* in a list if it is not already a list.

    Used to normalise arguments that may be passed as a single scalar or as a
    list, so that the rest of the calling code can always iterate uniformly.

    :param item: value to wrap
    :returns: *item* unchanged if it is already a list, otherwise ``[item]``
    :rtype: list
    """
    if not isinstance(item, list):
        return [item]
    else:
        return item

    