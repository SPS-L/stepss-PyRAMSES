#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""stepss - Python interface to the STEPSS power-system simulation platform.

Drives RAMSES, the time-domain dynamic simulator, and Helios, the AC
power-flow engine, both of which ship as bundled shared libraries.

Public API exported by this package:

- :class:`~stepss.cases.cfg` - build and manage a simulation case (input/output files).
- :class:`~stepss.simulator.sim` - load the RAMSES shared library and run simulations.
- :class:`~stepss.extractor.extractor` - parse Fortran binary trajectory files post-simulation.
- :class:`~stepss.extractor.cur` - lightweight NamedTuple holding a (time, value, msg) timeseries.
- :func:`~stepss.extractor.curplot` - plot one or more :class:`cur` objects on a single axes.
- :class:`~stepss.helios.HeliosSession` - run AC power flows with the Helios engine.
- :class:`~stepss.globals.HeliosError` - exception raised by Helios calls.

Module-level flags set at import time:

- ``__runTimeObs__`` - ``True`` when gnuplot is available on the system PATH and runtime
  observable plots are therefore enabled; ``False`` otherwise.
"""

__package_name__ = "stepss"
__version__ = '3.60'
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
