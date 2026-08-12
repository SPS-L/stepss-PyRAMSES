|PyPI version| |PyPI status| |Docs status|

.. |PyPI version| image:: https://img.shields.io/pypi/v/stepss
   :target: https://pypi.org/project/stepss/
   :alt: PyPI version

.. |PyPI status| image:: https://img.shields.io/pypi/status/stepss
   :target: https://pypi.org/project/stepss/
   :alt: PyPI status

.. |Docs status| image:: https://img.shields.io/github/actions/workflow/status/SPS-L/stepss-docs/deploy.yml?branch=main&label=docs
   :target: https://github.com/SPS-L/stepss-docs/
   :alt: Docs deploy status

STEPSS for Python
=================

Scripted power system dynamic simulation and AC power-flow analysis.

**STEPSS** (*Static and Transient Electric Power Systems Simulation*) is a power system simulation platform for dynamic studies of electrical grids, developed by `Dr. Petros Aristidou <https://sps-lab.org>`_ (Cyprus University of Technology) and Dr. Thierry Van Cutsem (University of Liège).

STEPSS is delivered in two editions, which drive the same simulation engines and read the same data files:

- **STEPSS for Python**, this package. ``pip install stepss``, then script simulations from Python or a Jupyter notebook.
- **STEPSS for Java**, a desktop application. A single ``stepss.jar`` with a graphical interface, published on the `releases page <https://github.com/SPS-L/stepss-java-ui/releases>`_.

Neither is a wrapper around the other: they are two front ends onto the same Fortran engines, and a case built in one runs unchanged in the other. Pick this one to automate, sweep parameters, or work inside the scientific Python stack; pick the Java edition for interactive work, or for the model-building and curve-viewing tools it carries that this edition does not (see `Choosing an edition`_).

What this edition bundles
-------------------------

``pip install stepss`` is self-contained: no separate solver installation, no compiler, no licence server.

- `RAMSES <https://stepss.sps-lab.org/getting-started/overview/>`_ (RApid Multithreaded Simulation of Electric power Systems), the dynamic simulator. It simulates the evolution of a power system under the phasor approximation, using Backward Euler, Trapezoidal or BDF2 integration with OpenMP parallelism.
- `Helios <https://stepss.sps-lab.org/user-guide/power-flow/>`_, the AC power-flow engine, solving by Newton-Raphson in polar coordinates. Exposed through the ``stepss.helios`` module (see `Helios Power-Flow Interface`_ below).

Pre-compiled shared libraries for Linux, Windows and macOS ship inside the wheel.

Choosing an edition
-------------------

Two capabilities live only in the Java edition, because they are separate executables rather than libraries:

- **CODEGEN**, which translates user-written model descriptions into Fortran 2003 and compiles them into a custom simulator. Writing your own exciter, governor or injector needs the Java edition or the `CODEGEN toolchain <https://stepss.sps-lab.org/developer/user-models/>`_ directly.
- **DYNGRAPH**, the interactive trajectory viewer. This edition reads trajectories into NumPy instead, which is usually what you want from Python.

Everything else, running dynamic simulations and power flows against the same engines and data files, is available here.

Key Features
------------

- **Complete simulation workflow** - define cases, run simulations, pause/continue, and extract results, all from Python
- **Runtime interaction** - query bus voltages, branch flows, and component observables while paused; inject disturbances on-the-fly
- **Trajectory post-processing** - extract and plot time-series results from Fortran binary trajectory files
- **Parameter sweeps** - script multiple simulations with varying parameters or disturbances
- **Eigenanalysis support** - export system Jacobian matrices for small-signal stability analysis
- **AC power flow** - the ``stepss.helios`` module runs Helios power flows: solve, modify with redispatch, N-1 contingency screening, and file exports
- **Shared data files** - the same ``.dat``, ``.dst`` and ``.obs`` files run in the Java edition, so a case can move between the two
- **Scientific Python integration** - works natively with NumPy, SciPy, Matplotlib, and Jupyter

Installation
------------

Install stepss and all recommended dependencies via pip::

   pip install jupyter ipython stepss

Required dependencies (matplotlib, scipy, and numpy) are installed automatically.

Minimal installation (no plotting or notebook support)::

   pip install stepss

**Optional:** Install `Gnuplot <http://www.gnuplot.info/>`_ to enable real-time observable plots during simulation. stepss will still work without it, but runtime plots will be disabled.

Renamed from PyRAMSES
~~~~~~~~~~~~~~~~~~~~~

This package was published as ``pyramses`` up to version 3.58. Existing code
keeps working: ``pip install pyramses`` now installs a shim that forwards to
this package. New code should use ``import stepss``.

Linux System Prerequisites
~~~~~~~~~~~~~~~~~~~~~~~~~~

On Linux, the following system libraries must be installed before running stepss::

   sudo apt install libopenblas0 libgfortran5 libgomp1

These packages provide:

- **libopenblas0** - OpenBLAS BLAS/LAPACK routines used by the solver
- **libgfortran5** - GNU Fortran runtime required by the Fortran components of RAMSES
- **libgomp1** - OpenMP runtime for multi-core parallel execution

On most desktop Linux distributions these are already present. If ``stepss`` fails to import with a shared-library error, install the packages above and retry.

macOS System Prerequisites
~~~~~~~~~~~~~~~~~~~~~~~~~~

On macOS, the following system libraries must be installed before running stepss::

   brew install openblas gcc

These packages provide:

- **openblas** - OpenBLAS BLAS/LAPACK routines used by the solver
- **gcc** - GNU Fortran (``libgfortran``) and OpenMP (``libgomp``) runtimes required by the Fortran components of RAMSES

macOS is supported on Apple Silicon (arm64) only: both the bundled RAMSES and Helios binaries are arm64. If ``stepss`` fails to import with a shared-library error, install the packages above and retry.

Platform Support
~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 20 20 60
   :header-rows: 1

   * - Platform
     - Binaries
     - Notes
   * - Windows
     - ``ramses.dll``, ``helios_api.dll``
     - Primary platform, full support
   * - Linux
     - ``ramses.so``, ``libhelios_api.so``
     - Full support
   * - macOS
     - ``ramses.so``, ``libhelios_api.dylib``
     - Apple Silicon (arm64) only; RAMSES additionally needs Homebrew ``openblas``/``gcc`` (see `macOS System Prerequisites`_)

The free version is limited to 1000 buses and 2 OpenMP cores. See the `License <https://stepss.sps-lab.org/getting-started/license/>`_ page for full terms.

Quick Start
-----------

.. code-block:: python

   import stepss

   # 1. Define the test case
   case = stepss.cfg()
   case.addData('dyn.dat')        # dynamic model data
   case.addData('volt_rat.dat')   # power-flow initialisation
   case.addData('settings.dat')   # solver settings
   case.addDst('fault.dst')       # disturbance sequence
   case.addObs('obs.dat')         # define observables to record
   case.addTrj('output.trj')      # trajectory output file

   # 2. Run simulation
   ram = stepss.sim()
   ram.execSim(case)              # run to completion

   # 3. Extract and plot results
   ext = stepss.extractor(case.getTrj())
   ext.getBus('1041').mag.plot()  # bus voltage magnitude
   ext.getSync('g1').S.plot()     # generator rotor speed

For interactive usage, pause/continue and on-the-fly disturbance injection is supported:

.. code-block:: python

   ram = stepss.sim()
   ram.execSim(case, 0.0)                        # initialise, paused at t=0
   ram.addDisturb(10.0, 'BREAKER SYNC_MACH g7 0')  # schedule generator trip
   ram.contSim(ram.getInfTime())                 # run to end of time horizon
   ram.endSim()

Helios Power-Flow Interface
---------------------------

`Helios <https://stepss.sps-lab.org/user-guide/power-flow/>`_ is the AC power-flow engine both editions use, exposed here through the ``stepss.helios`` module. Unlike the RAMSES classes, this interface uses PEP 8 snake_case naming.

.. code-block:: python

   from stepss.helios import HeliosSession

   with HeliosSession() as pf:
       pf.load_file('network.dat')
       pf.solve()

       v, angle = pf.get_bus_voltage('1041')      # one bus
       v_all, angle_all = pf.get_bus_voltages()   # all buses (NumPy arrays)

       # modify the system and re-solve with redispatch
       pf.trip_branch('1042-1044')
       pf.change_load('1041', 50.0, 10.0)         # +50 MW, +10 Mvar
       pf.apply_changes()

       # N-1 contingency screening
       for result in pf.run_contingencies(branches=True, generators=True):
           print(result.name, result.accepted, result.violations)

       # export the operating point (e.g. as RAMSES initial conditions)
       pf.write_voltrat('volt_rat.dat')

Runnable examples live in ``examples/helios/``.

Main Classes
------------

.. list-table::
   :widths: 25 75
   :header-rows: 1

   * - Class
     - Description
   * - ``stepss.cfg``
     - Defines a test case: data files, disturbance file, output files, observables, and runtime options.
   * - ``stepss.sim``
     - Runs simulations. Supports start/pause/continue, runtime queries, and on-the-fly disturbance injection.
   * - ``stepss.extractor``
     - Extracts and visualises time-series results from trajectory (``.trj``) files produced by a simulation.
   * - ``stepss.helios.HeliosSession``
     - Runs AC power flows with the Helios engine: load, modify, solve, contingency screening, and file exports.

Bundled Binaries Are CI-Managed
-------------------------------

The native libraries under ``src/stepss/libs/`` and the version record in
``src/stepss/_bundled.py`` are written by automation, not by hand. When
RAMSES or Helios publishes a release, a workflow refreshes the affected
libraries, bumps the patch version, and publishes a new stepss release only
after the full test suite (including the Nordic voltage-collapse regression)
passes on Linux, Windows and macOS.

Check what a given release bundles with::

   python -c "import stepss; print(stepss.__ramses_version__, stepss.__helios_version__)"

Contributors should not edit those paths directly; a manual change is
overwritten by the next sync.

Documentation
-------------

Full documentation is available at `https://stepss.sps-lab.org/python/ <https://stepss.sps-lab.org/python/>`_.

- `Overview <https://stepss.sps-lab.org/python/overview/>`_
- `Installation <https://stepss.sps-lab.org/python/installation/>`_
- `Power Flow with Helios <https://stepss.sps-lab.org/python/helios/>`_
- `API Reference <https://stepss.sps-lab.org/python/api-reference/>`_
- `Examples <https://stepss.sps-lab.org/python/examples/>`_

Support:

- Issues: `https://github.com/SPS-L/stepss-python-ui/issues <https://github.com/SPS-L/stepss-python-ui/issues>`_
- Project page: `https://sps-lab.org/project/stepss/ <https://sps-lab.org/project/stepss/>`_

License
-------

stepss (the Python wrapper) is distributed under the **Apache License 2.0** - see ``LICENSE.rst``. Copyright © Petros Aristidou.

The RAMSES solver (the dynamic library bundled in this package) is proprietary software owned by the University of Liège and is distributed under the Academic Public License for the use of STEPSS: free for non-commercial use (teaching, academic research, personal purposes), with a limit of 1000 buses and 2 CPU cores. For commercial use or larger models, contact the authors. See the `STEPSS License page <https://stepss.sps-lab.org/getting-started/license/>`_ for full terms.

The STEPSS-Helios power-flow library (``libhelios_api``, also bundled in this package and used by ``stepss.helios``) is the property of Dr. Petros Aristidou, distributed under the STEPSS-Helios Academic Public License: free for non-commercial use; commercial use requires a license (info@sps-lab.org). See the ``NOTICE`` file for details.

Authors
-------

Developed and maintained by the `Sustainable Power Systems Laboratory (SPS-L) <https://sps-lab.org/>`_ at the Cyprus University of Technology, under the direction of Dr. Petros Aristidou.

- `Dr. Petros Aristidou <https://sps-lab.org/>`_ - Cyprus University of Technology
- Dr. Thierry Van Cutsem - Emeritus, University of Liège
