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
- :class:`~stepss.live.monitor` - plot chosen quantities while a simulation runs.
- :class:`~stepss.helios.HeliosSession` - run AC power flows with the Helios engine.
- :class:`~stepss.globals.HeliosError` - exception raised by Helios calls.

Module-level flags set at import time:

- ``__runTimeObs__`` - always ``True``. Run-time observables no longer depend on
  anything being installed, so this flag has nothing left to report. It is kept
  because it is public, and it is deprecated: do not branch on it.
"""

__package_name__ = "stepss"
__version__ = '3.80'
__author__ = "Petros Aristidou"
__copyright__ = "Petros Aristidou"
__license__ = "Apache-2.0"
__maintainer__ = "Petros Aristidou"
__email__ = "apetros@pm.me"
__url__ = "https://stepss.sps-lab.org"
__status__ = "5 - Production/Stable"

from . import globals as _globals
from .cases import cfg
from .globals import HeliosError
from .simulator import sim
from .extractor import extractor, curplot, cur
from .live import monitor
from . import helios
from .helios import HeliosSession
from ._bundled import RAMSES_VERSION as __ramses_version__
from ._bundled import HELIOS_VERSION as __helios_version__

__all__ = ["cfg", "sim", "extractor", "cur", "curplot", "monitor", "helios",
           "HeliosSession", "HeliosError"]

# No gnuplot probe. This package has always plotted with matplotlib, through
# curplot; the probe existed because RAMSES used to draw run-time observables
# itself by piping to gnuplot, so a machine without gnuplot could not produce
# them. RAMSES no longer does that: it writes the observable file and calls
# nothing, so gnuplot's presence has no bearing on anything here.
#
# Leaving the probe in place was not merely untidy. addRunObs() gated on this
# flag and became a silent no-op when the probe failed, so every user without
# gnuplot installed lost run-time observables for a reason that no longer
# existed. Kept as a name, always True, because it is documented public API.
__runTimeObs__ = _globals.__runTimeObs__
