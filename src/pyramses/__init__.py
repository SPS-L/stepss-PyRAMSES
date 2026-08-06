#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pyramses — Python interface for the RAMSES dynamic power-system simulator.

Public API exported by this package:

- :class:`~pyramses.cases.cfg` — build and manage a simulation case (input/output files).
- :class:`~pyramses.simulator.sim` — load the RAMSES shared library and run simulations.
- :class:`~pyramses.extractor.extractor` — parse Fortran binary trajectory files post-simulation.
- :class:`~pyramses.extractor.cur` — lightweight NamedTuple holding a (time, value, msg) timeseries.
- :func:`~pyramses.extractor.curplot` — plot one or more :class:`cur` objects on a single axes.
- :class:`~pyramses.helios.HeliosSession` — run AC power flows with the Helios engine.
- :class:`~pyramses.globals.HeliosError` — exception raised by Helios calls.

Module-level flags set at import time:

- ``__runTimeObs__`` — ``True`` when gnuplot is available on the system PATH and runtime
  observable plots are therefore enabled; ``False`` otherwise.
"""

__package_name__ = "pyramses"
__version__ = '0.3.1'
__author__ = "Petros Aristidou"
__copyright__ = "Petros Aristidou"
__license__ = "Apache-2.0"
__maintainer__ = "Petros Aristidou"
__email__ = "apetros@pm.me"
__url__ = "https://stepss.sps-lab.org"
__status__ = "5 - Production/Stable"

import sys
from warnings import warn

from . import globals as _globals
from .cases import cfg
from .globals import __which, HeliosError
from .simulator import sim
from .extractor import extractor, curplot, cur
from . import helios
from .helios import HeliosSession
from ._bundled import RAMSES_VERSION as __ramses_version__
from ._bundled import HELIOS_VERSION as __helios_version__

__all__ = ["cfg", "sim", "extractor", "cur", "curplot", "helios",
           "HeliosSession", "HeliosError"]

# Detect gnuplot at import time; propagate result to globals so that cases.py
# (which reads __runTimeObs__ from globals at import time) also gets the correct value.
if sys.platform in ('win32', 'cygwin'):
    checkGnuplot = __which('gnuplot.exe')
else:
    checkGnuplot = __which('gnuplot')
if checkGnuplot is None:
    warn("RAMSES: Gnuplot executable could not be found in the system path, so the runtime observables are disabled.")
    _globals.__runTimeObs__ = False
else:
    _globals.__runTimeObs__ = True

# Re-export the (now-updated) flag under the expected public name.
__runTimeObs__ = _globals.__runTimeObs__
