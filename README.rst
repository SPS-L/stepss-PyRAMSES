|PyPI version| |PyPI status| |Docs status|

.. |PyPI version| image:: https://img.shields.io/pypi/v/pyramses
   :target: https://pypi.org/project/pyramses/
   :alt: PyPI version

.. |PyPI status| image:: https://img.shields.io/pypi/status/pyramses
   :target: https://pypi.org/project/pyramses/
   :alt: PyPI status

.. |Docs status| image:: https://img.shields.io/github/actions/workflow/status/SPS-L/stepss-docs/deploy.yml?branch=main&label=docs
   :target: https://github.com/SPS-L/stepss-docs/
   :alt: Docs deploy status

PyRAMSES: Python Interface to RAMSES
=====================================

PyRAMSES is a Python interface to the `RAMSES <https://stepss.sps-lab.org/getting-started/overview/>`_ dynamic simulator — part of the `STEPSS <https://stepss.sps-lab.org/>`_ power system simulation suite. It covers the full simulation workflow: defining test cases, launching simulations, querying system state at runtime, and extracting and plotting results.

STEPSS has been developed by `Dr. Petros Aristidou <https://sps-lab.org/>`_ (Cyprus University of Technology) and Dr. Thierry Van Cutsem (Emeritus, University of Liège).

Overview
--------

PyRAMSES enables scripted power system dynamic simulations from Python or Jupyter notebooks. It exposes the full capability of the RAMSES solver through a clean Python API, with pre-compiled binaries bundled for Windows and Linux — no separate solver installation required.

RAMSES (RApid Multithreaded Simulation of Electric power Systems) simulates the dynamic evolution of power systems under the phasor approximation, using Backward Euler, Trapezoidal, or BDF2 integration with OpenMP parallelism.

Key Features
------------

- **Complete simulation workflow** — define cases, run simulations, pause/continue, and extract results, all from Python
- **Runtime interaction** — query bus voltages, branch flows, and component observables while paused; inject disturbances on-the-fly
- **Trajectory post-processing** — extract and plot time-series results from Fortran binary trajectory files
- **Parameter sweeps** — script multiple simulations with varying parameters or disturbances
- **Eigenanalysis support** — export system Jacobian matrices for small-signal stability analysis
- **Bundled binaries** — pre-compiled RAMSES shared libraries (``ramses.dll`` / ``ramses.so``) for Windows and Linux
- **Scientific Python integration** — works natively with NumPy, SciPy, Matplotlib, and Jupyter

Installation
------------

Install PyRAMSES and all recommended dependencies via pip::

   pip install matplotlib scipy numpy mkl jupyter ipython pyramses

Minimal installation (no plotting or notebook support)::

   pip install pyramses

**Optional:** Install `Gnuplot <http://www.gnuplot.info/>`_ to enable real-time observable plots during simulation. PyRAMSES will still work without it, but runtime plots will be disabled.

Linux System Prerequisites
~~~~~~~~~~~~~~~~~~~~~~~~~~

On Linux, the following system libraries must be installed before running PyRAMSES::

   sudo apt install libopenblas0 libgfortran5 libgomp1

These packages provide:

- **libopenblas0** — OpenBLAS BLAS/LAPACK routines used by the solver
- **libgfortran5** — GNU Fortran runtime required by the Fortran components of RAMSES
- **libgomp1** — OpenMP runtime for multi-core parallel execution

On most desktop Linux distributions these are already present. If ``pyramses`` fails to import with a shared-library error, install the packages above and retry.

Platform Support
~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 20 20 60
   :header-rows: 1

   * - Platform
     - Binary
     - Notes
   * - Windows
     - ``ramses.dll``
     - Primary platform, full support
   * - Linux
     - ``ramses.so``
     - Full support

The free version is limited to 1000 buses and 2 OpenMP cores. See the `License <https://stepss.sps-lab.org/getting-started/license/>`_ page for full terms.

Quick Start
-----------

.. code-block:: python

   import pyramses

   # 1. Define the test case
   case = pyramses.cfg()
   case.addData('dyn.dat')        # dynamic model data
   case.addData('volt_rat.dat')   # power-flow initialisation
   case.addData('settings.dat')   # solver settings
   case.addDst('fault.dst')       # disturbance sequence
   case.addObs('obs.dat')         # define observables to record
   case.addTrj('output.trj')      # trajectory output file

   # 2. Run simulation
   ram = pyramses.sim()
   ram.execSim(case)              # run to completion

   # 3. Extract and plot results
   ext = pyramses.extractor(case.getTrj())
   ext.getBus('1041').mag.plot()  # bus voltage magnitude
   ext.getSync('g1').S.plot()     # generator rotor speed

For interactive usage, pause/continue and on-the-fly disturbance injection is supported:

.. code-block:: python

   ram = pyramses.sim()
   ram.execSim(case, 0.0)                        # initialise, paused at t=0
   ram.addDisturb(10.0, 'BREAKER SYNC_MACH g7 0')  # schedule generator trip
   ram.contSim(ram.getInfTime())                 # run to end of time horizon
   ram.endSim()

Helios Power-Flow Interface
---------------------------

PyRAMSES also bundles `Helios <https://stepss.sps-lab.org/user-guide/pfc/>`_, the STEPSS AC power-flow engine (successor of the Fortran PFC), exposed through the ``pyramses.helios`` module. Unlike the RAMSES classes, this interface uses PEP 8 snake_case naming. Pre-compiled libraries are bundled for Linux, Windows, and macOS.

.. code-block:: python

   from pyramses.helios import HeliosSession

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
   * - ``pyramses.cfg``
     - Defines a test case: data files, disturbance file, output files, observables, and runtime options.
   * - ``pyramses.sim``
     - Runs simulations. Supports start/pause/continue, runtime queries, and on-the-fly disturbance injection.
   * - ``pyramses.extractor``
     - Extracts and visualises time-series results from trajectory (``.trj``) files produced by a simulation.
   * - ``pyramses.helios.HeliosSession``
     - Runs AC power flows with the Helios engine: load, modify, solve, contingency screening, and file exports.

Documentation
-------------

Full documentation is available at `https://stepss.sps-lab.org/pyramses/ <https://stepss.sps-lab.org/pyramses/>`_.

- `Overview <https://stepss.sps-lab.org/pyramses/overview/>`_
- `Installation <https://stepss.sps-lab.org/pyramses/installation/>`_
- `API Reference <https://stepss.sps-lab.org/pyramses/api-reference/>`_
- `Examples <https://stepss.sps-lab.org/pyramses/examples/>`_

License
-------

PyRAMSES (the Python wrapper) is distributed under the `Apache License 2.0 <LICENSE.rst>`_.

The RAMSES solver (the dynamic library bundled in this package) is proprietary software owned by the University of Liège and is free for non-commercial use (teaching, academic research, personal purposes), with a limit of 1000 buses and 2 CPU cores. For commercial use or larger models, contact the authors. See the `STEPSS License page <https://stepss.sps-lab.org/getting-started/license/>`_ for full terms.

Authors
-------

- `Dr. Petros Aristidou <https://sps-lab.org/>`_ — Cyprus University of Technology
- Dr. Thierry Van Cutsem — Emeritus, University of Liège

Support
-------

- Documentation: `https://stepss.sps-lab.org/pyramses/ <https://stepss.sps-lab.org/pyramses/overview/>`_
- Issues: `https://github.com/SPS-L/stepss-pyramses/issues <https://github.com/SPS-L/stepss-pyramses/issues>`_
- Project page: `https://sps-lab.org/project/pyramses/ <https://sps-lab.org/project/pyramses/>`_

