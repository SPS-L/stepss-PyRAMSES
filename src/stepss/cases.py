#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Simulation case configuration for stepss.

Defines :class:`cfg`, which collects all input and output file paths required
by the RAMSES solver and serialises them into the RAMSES command-file format.
"""

import os
import warnings

from . import globals as _globals
from .globals import RAMSESError, CustomWarning

warnings.showwarning = CustomWarning


class cfg(object):
    """Simulation case configuration.

    Collects and validates all file paths needed to run a RAMSES simulation:
    data files, disturbance file, trajectory file, observables, trace outputs,
    and optional runtime observable definitions.  The assembled configuration
    can be serialised to a RAMSES command file via :meth:`writeCmdFile`, which
    is called automatically by :meth:`~stepss.simulator.sim.execSim`.

    A case can be built programmatically (by calling the ``add*`` methods) or
    loaded from an existing command file by passing its path to *cmd*.

    **Instance attributes (all private):**

    - ``_dataset`` (*list of str*) — data files (.dat) defining the network model and solver settings.
    - ``_dstset`` (*list of str*) — the single active disturbance file (.dst).
    - ``_init`` (*list of str*) — path for the initialisation trace output.
    - ``_cont`` (*list of str*) — path for the continuous convergence trace output.
    - ``_disc`` (*list of str*) — path for the discrete events trace output.
    - ``_obs`` (*list of str*) — observables definition file (.dat or .obs).
    - ``_trj`` (*list of str*) — Fortran binary trajectory output file (.trj).
    - ``_runobs`` (*list of str*): runtime observable descriptors.
    - ``_out`` (*list of str*) — execution log / output trace file.

    :Example:

    >>> import stepss
    >>> case = stepss.cfg()
    >>> case.addData('dyn.dat')
    >>> case.addData('volt_rat.dat')
    >>> case.addData('settings.dat')
    >>> case.addInit('init.trace')
    >>> case.addDst('disturbance.dst')
    >>> case.addTrj('output.trj')
    >>> case.addObs('obs.dat')
    """

    def __init__(self, cmd=None):
        """Initialise a case, optionally loading it from a command file.

        When *cmd* is ``None`` (the default) all file lists are empty and must
        be populated with the ``add*`` methods before the case can be used.

        When *cmd* is provided the command file is parsed line-by-line using a
        simple state machine (``typeread``) that moves through eight sections in
        fixed order:

        1. Data files  — one per line; ends at the first blank line.
        2. Init trace  — single optional line.
        3. Disturbance — single required line.
        4. Trajectory  — single optional line.
        5. Observables — required when a trajectory file is present.
        6. Continuous trace — single optional line.
        7. Discrete trace   — single optional line.
        8. Runtime observables — zero or more lines.

        :param cmd: path to an existing RAMSES command file to parse, or
                    ``None`` to start with an empty case.
        :type cmd: str or None
        :raises IOError: if *cmd* is given but cannot be read.
        :raises Exception: if the command file is missing required sections
                           (at least one data file, a disturbance file, or an
                           observables file when a trajectory is defined).
        """
        self._out = []  # output file
        self._dataset = []  # data files
        self._dstset = []  # disturbance files
        self._runobs = []  # runtime observables
        self._init = []  # initialization file
        self._disc = []  # discrete trace file
        self._cont = []  # continuous trace file
        self._obs = []  # observables file
        self._trj = []  # trajectory file
        if cmd:
            try:
                typeread = 1  # 1=data, 2=init, 3=dst, 4=trj, 5=obs,6=cont, 7=disc, 8=runtime obs
                with open(cmd) as data:
                    content = data.read().splitlines()
                    for line in content:
                        token = line.split()
                        if typeread == 1:
                            if len(token) > 0:
                                self.addData(line)
                            else:
                                if not self._dataset:
                                    raise Exception('RAMSES: At least one datafile is necessary in the command file.')
                                typeread += 1
                        elif typeread == 2:
                            if len(token) > 0:
                                self.addInit(line)
                                typeread += 1
                            else:
                                typeread += 1
                        elif typeread == 3:
                            if len(token) > 0:
                                self.addDst(line)
                                typeread += 1
                            else:
                                raise Exception('RAMSES: At least one dstfile is necessary in the command file.')
                        elif typeread == 4:
                            if len(token) > 0:
                                self.addTrj(line)
                                typeread += 1
                            else:
                                typeread += 2
                        elif typeread == 5:
                            if len(token) > 0:
                                self.addObs(line)
                                typeread += 1
                            else:
                                raise Exception(
                                    'RAMSES: Since a trajectory file was defined, an observable file should be given.')
                        elif typeread == 6:
                            if len(token) > 0:
                                self.addCont(line)
                                typeread += 1
                            else:
                                typeread += 1
                        elif typeread == 7:
                            if len(token) > 0:
                                self.addDisc(line)
                                typeread += 1
                            else:
                                typeread += 1
                        elif typeread == 8:
                            if len(token) > 0:
                                self.addRunObs(line)
                            else:
                                typeread += 1
            except IOError:
                raise

    def writeCmdFile(self, userFile=None):
        """Serialise the case to a RAMSES command file.

        The command file format is a fixed-section plain-text file consumed
        directly by the RAMSES solver.  Sections are separated by blank lines
        and appear in this order:

        1. Data files (one per line)
        2. Initialisation trace path (or blank)
        3. Disturbance file path
        4. Trajectory file path + observables file path (or blank)
        5. Continuous trace path (or blank)
        6. Discrete trace path (or blank)
        7. Runtime observable descriptors (zero or more lines)

        :param userFile: path where the command file should be written.  If
                         ``None`` the serialised text is returned as a string
                         without writing to disk.
        :type userFile: str or None
        :returns: ``0`` after writing to *userFile*, or the command-file text
                  as a string when *userFile* is ``None``.
        :rtype: int or str
        :raises RAMSESError: if ``_dataset`` or ``_dstset`` is empty.
        :raises IOError: if the file cannot be written.

        .. warning:: If *userFile* already exists it will be overwritten.
        """
        if not self._dataset or not self._dstset:
            raise RAMSESError('Dataset and disturbance set cannot be empty.')

        cmdFile = ""

        try:
            for i in self._dataset:
                cmdFile = cmdFile + i + '\n'
            cmdFile = cmdFile + '\n'
            if self._init:
                cmdFile = cmdFile + self._init[0] + '\n'
            else:
                cmdFile = cmdFile + '\n'
            if self._dstset:
                cmdFile = cmdFile + self._dstset[0] + '\n'
            if self._trj:
                cmdFile = cmdFile + self._trj[0] + '\n'
                cmdFile = cmdFile + self._obs[0] + '\n'
            else:
                cmdFile = cmdFile + '\n'
            if self._cont:
                cmdFile = cmdFile + self._cont[0] + '\n'
            else:
                cmdFile = cmdFile + '\n'
            if self._disc:
                cmdFile = cmdFile + self._disc[0] + '\n'
            else:
                cmdFile = cmdFile + '\n'
            for i in self._runobs:
                cmdFile = cmdFile + i + '\n'
            cmdFile = cmdFile + '\n'
            cmdFile = cmdFile + '\n'
        except IOError as e:
            raise IOError("RAMSES: I/O error({0}): {1}".format(e.errno, e.strerror))

        if userFile is None:
            return cmdFile
        else:
            if os.path.isfile(userFile):
                warnings.warn('The file %s already exists. It will be overwritten!' % (userFile))
            with open(userFile, "w") as text_file:
                text_file.write(cmdFile)
            return 0

    # def __del__(self):
    #     silentremove(self._cmdfile.name)

    def addInit(self, afile):
        """Set the file where the simulation initialisation trace will be saved.
        
        The initialisation trace records the output of RAMSES's power-flow
        initialisation step.  Only one initialisation file can be active at a
        time; calling this method again replaces any previously set path.

        :param str afile: the filename. The complete path can be given or a path
                          relative to the working directory (``os.getcwd()``).

        :Example:

        >>> import stepss
        >>> case1 = stepss.cfg()
        >>> case1.addInit("init.trace")

        .. warning:: If the file already exists, it will be overwritten without warning!
        """
        del self._init[:]
        if os.path.isfile(afile):
            warnings.warn('The file %s already exists. It will be overwritten!' % (afile))
        self._init.append(afile)

    def getInit(self):
        """Return the initialisation trace file path.

        :returns: path of the initialisation trace file, or an empty string if none is set.
        :rtype: str
        """
        if self._init:
            return self._init[0]
        else:
            return ''

    def addOut(self, afile):
        """Define the file where the simulation output will be saved.

        :param str afile: the filename. The complete path must be given.

        :Example:

        >>> import stepss
        >>> import os
        >>> case1 = stepss.cfg()
        >>> case1.addOut(os.path.join(os.getcwd(),'output.trace'))

        .. note:: If the file already exists, the output will be appended to that file.
        """
        del self._out[:]
        self._out.append(afile)

    def getOut(self):
        """Return the output trace file path.

        :returns: path of the output trace file, or an empty string if none is set.
        :rtype: str
        """
        if self._out:
            return self._out[0]
        else:
            return ''

    def addCont(self, afile):
        """Set the continuous trace output file.
        
        The continuous trace records convergence information from the numerical
        integration algorithm inside RAMSES.  It is mainly useful for debugging
        solver issues but can slow down the simulation significantly.

        :param str afile: the filename. The complete path can be given or a path
                          relative to the working directory (``os.getcwd()``).

        :Example:

        >>> import stepss
        >>> case1 = stepss.cfg()
        >>> case1.addCont("cont.trace")

        .. warning:: If the file already exists, it will be overwritten without warning!
        """
        del self._cont[:]
        if os.path.isfile(afile):
            warnings.warn('The file %s already exists. It will be overwritten!' % (afile))
        self._cont.append(afile)

    def getCont(self):
        """Return the continuous trace file path.
        
        :returns: path of the continuous trace file, or an empty string if none is set.
        :rtype: str
        
        """
        if self._cont:
            return self._cont[0]
        else:
            return ''

    def addTrj(self, afile):
        """Set the Fortran binary trajectory output file.

        The trajectory file is written by RAMSES during the simulation and later
        parsed by :class:`~stepss.extractor.extractor` to extract timeseries
        for individual components.

        :param str afile: the filename. The complete path can be given or a path
                          relative to the working directory (``os.getcwd()``).

        :Example:

        >>> import stepss
        >>> case1 = stepss.cfg()
        >>> case1.addTrj("output.trj")

        .. warning:: If the file already exists, it will be overwritten without warning!
        """
        del self._trj[:]
        if os.path.isfile(afile):
            warnings.warn('The file %s already exists. It will be overwritten!' % (afile))
        self._trj.append(afile)

    def getTrj(self):
        """Return the trajectory output file path.

        :returns: path of the trajectory file, or an empty string if none is set.
        :rtype: str
        """
        if self._trj:
            return self._trj[0]
        else:
            return ''

    def addDisc(self, afile):
        """Set the discrete events trace output file.

        The discrete trace records events that occur during the simulation, such
        as discrete controller transitions, disturbance-file events, and state
        changes inside injector, two-port, torque, or exciter models.

        :param str afile: the filename. The complete path can be given or a path
                          relative to the working directory (``os.getcwd()``).

        :Example:

        >>> import stepss
        >>> case1 = stepss.cfg()
        >>> case1.addDisc("disc.trace")

        .. warning:: If the file already exists, it will be overwritten without warning!
        """
        del self._disc[:]
        if os.path.isfile(afile):
            warnings.warn('The file %s already exists. It will be overwritten!' % (afile))
        self._disc.append(afile)

    def clearDisc(self):
        """Remove the discrete trace file path from the case."""
        del self._disc[:]

    def getDisc(self):
        """Return the discrete trace file path.

        :returns: path of the discrete trace file, or an empty string if none is set.
        :rtype: str
        """
        if self._disc:
            return self._disc[0]
        else:
            return ''

    def addRunObs(self, runobs):
        """Add runtime observable.
        
        This defines some states the engine records while the simulation runs.
        
        :param str runobs: Description of runtime observable as defined in the RAMSES userguide
        
        :Example:        
        
        - BV BUSNAME: Voltage magnitude of bus::
   
           >>> case.addRunObs('BV 1041') # observe the bus voltage of bus 1041
        
        - MS SYNHRONOUS_MACHINE: Synchronous speed of machine::
        
           >>> case.addRunObs('MS g1')
           
        - RT RT: Real-time vs simulated time plot::
        
           >>> case.addRunObs('RT RT')
           
        - BPE/BQE/BPO/BQO BRANCH_NAME: Branch active (P), reactive (Q) power at the origin (O) or extremity (E) of a branch::

           >>> case.addRunObs('BPO 1041-01') # active power at the origin of branch 1041-01
           >>> case.addRunObs('BPE 1041-01') # active power at the extremity of branch 1041-01

        - ON INJECTOR_NAME OBSERVABLE_NAME: Monitor a named observable from an injector ::

           >>> case.addRunObs('ON WT1a Pw') # observable Pw from injector WT1a

        - TO TWOP_NAME OBSERVABLE_NAME: Monitor a named observable from a two-port ::

           >>> case.addRunObs('TO hvdc1 P1') # observable P1 from two-port hvdc1


        """
        # Unconditional. This used to be gated on a gnuplot PATH probe, from
        # when RAMSES drew run-time observables itself by piping to gnuplot, and
        # the else branch made this method a silent no-op for anyone without
        # gnuplot installed. The engine writes the observable file and calls
        # nothing, so there is no longer a condition to test.
        if runobs not in self._runobs:
            self._runobs.append(runobs)

    def clearRunObs(self):
        """Remove all runtime observable descriptors from the case."""
        del self._runobs[:]

    def addObs(self, ofile):
        """Add observables file

        :param str ofile: the filename. The complete path can be given or a the path relative to the working directory (os.getcwd())

        :Example:

        >>> import stepss
        >>> case1 = stepss.cfg()
        >>> case1.addObs("obs.dat")

        """
        if os.path.isfile(ofile):
            del self._obs[:]
            self._obs.append(ofile)
        else:
            raise IOError('RAMSES: The observables file %s does not exist or is not valid.' % (ofile))

    def getObs(self):
        """Return the observables file path.

        :returns: path of the observables file, or an empty string if none is set.
        :rtype: str
        """
        if self._obs:
            return self._obs[0]
        else:
            return ''

    def addData(self, datafile):
        """Add a data file to the dataset.
        
        Data files provide the network model (dynamic models, power-flow solution)
        and solver parameters consumed by RAMSES.  Multiple data files can be
        added; they are passed to the solver in the order they were added.
        Duplicate paths are silently ignored.

        :param str datafile: path to an existing data file. The complete path
                             can be given or a path relative to the working
                             directory (``os.getcwd()``).

        :Example:

        >>> import stepss
        >>> case1 = stepss.cfg()
        >>> case1.addData("dyn_A.dat")

        .. warning:: At least one data file must be added before running a simulation.
        """
        if os.path.isfile(datafile):
            if datafile not in self._dataset:
                self._dataset.append(datafile)
        else:
            raise IOError('RAMSES: The datafile %s does not exist or is not valid.' % (datafile))

    def getData(self):
        """Get datafile list
        
        :returns: list of data file names
        :rtype: list
        
        """
        return self._dataset

    def delData(self, datafile):
        """Remove a specific data file from the dataset.

        :param str datafile: path of the data file to remove. No error is
                             raised if the file is not currently in the dataset.
        """
        if datafile in self._dataset:
            self._dataset.remove(datafile)

    def clearData(self):
        """Remove all data files from the dataset."""
        del self._dataset[:]

    def addDst(self, dstfile):
        """Set the disturbance file for the simulation.
        
        The disturbance file defines the fault or event sequence to be applied
        during the simulation.  Only one disturbance file is active at a time;
        calling this method again replaces the previous one.

        :param str dstfile: path to an existing ``.dst`` file. The complete
                            path can be given or a path relative to the working
                            directory (``os.getcwd()``).

        :Example:

        >>> import stepss
        >>> case1 = stepss.cfg()
        >>> case1.addDst("short.dst")

        .. warning:: A disturbance file must be provided before the simulation can start.
        """
        if os.path.isfile(dstfile):
            del self._dstset[:]
            self._dstset.append(dstfile)
        else:
            raise IOError('RAMSES: The dstfile %s does not exist or is not valid.' % (dstfile))

    def getDst(self):
        """Get disturbance
        
        :returns: name of disturbance file
        :rtype: str
        
        """
        if self._dstset:
            return self._dstset[0]
        else:
            return ''

    def clearDst(self):
        """Remove the disturbance file from the case."""
        del self._dstset[:]
