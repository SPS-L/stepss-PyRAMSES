#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Python interface to the RAMSES dynamic power-system simulator.

Provides :class:`sim`, a ctypes-based wrapper around the RAMSES shared library
(``ramses.dll`` on Windows, ``ramses.so`` on Linux).  Function signatures are
read automatically from the bundled ``ramses.h`` C header at instantiation
time, so the wrapper is self-describing and does not hard-code argument types.
"""

import ctypes
import _ctypes
import os
import sys
import warnings
import datetime
import numpy as np
from scipy.sparse import coo_matrix

from .cases import cfg
from .globals import RAMSESError, CustomWarning, __libdir__, wrapToList

class sim(object):
    """Interface to a RAMSES solver instance.

    Each :class:`sim` object loads the RAMSES shared library into the current
    process and exposes the solver's C API through Python methods.  The library
    is unloaded (via :func:`ctypes.FreeLibrary` / :func:`ctypes._ctypes.dlclose`)
    when the instance is garbage-collected.

    **Thread safety:** RAMSES maintains internal global state; running multiple
    :class:`sim` instances concurrently in separate threads is not supported.
    Multiple sequential instances within the same process are safe.

    **Class attributes:**

    - ``ramsesCount`` (*int*) — number of :class:`sim` instances currently alive.
      Incremented in :meth:`__init__` and decremented in :meth:`__del__`.
    """

    warnings.showwarning = CustomWarning

    ramsesCount = 0  # number of active sim instances
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

    def __init__(self, custLibDir = None):
        """Load the RAMSES shared library and initialise C function signatures.

        On Windows the library is ``ramses.dll``; on all other platforms it is
        ``ramses.so``.  By default the library bundled with the package
        (``src/pyramses/libs/``) is used.  A custom directory can be supplied
        via *custLibDir* to override that library — useful for testing
        pre-release solver builds.

        After loading the library, :meth:`_setcalls` is invoked to parse
        ``ramses.h`` and configure the ctypes argument/return types for every
        exported function.

        :param custLibDir: path to a directory containing an alternative
                           ``ramses.dll`` / ``ramses.so``.  The directory must
                           exist.  When provided, the library file in that
                           location will be locked by the OS until this instance
                           is deleted.
        :type custLibDir: str or None
        :raises RAMSESError: if *custLibDir* is given but does not exist or is
                             not a directory.
        :raises ImportError: if the shared library cannot be loaded (e.g. missing
                             system runtime libraries such as OpenBLAS on Linux).
        """
        if custLibDir is None:
            ramLibDir = __libdir__
        else:
            try:
                if os.path.exists(custLibDir) and os.path.isdir(custLibDir):
                    ramLibDir = custLibDir
                    warnings.warn("Overwriting the internal DLL with the one at %s. The DLL in that location will be locked. To unlock it, you need to del() this instance of pyramses.sim() or restart the kernel." % ramLibDir)
                else:
                    raise RAMSESError('RAMSES: The path %s does not exist or it is not a directory.' % (custLibDir))
            except OSError as e:
                raise RAMSESError('RAMSES: The path %s gave an error.' % custLibDir) from e
            
        try:
            if sys.platform in ('win32', 'cygwin'):
                self._ramseslib = ctypes.CDLL(os.path.join(ramLibDir, "ramses.dll"))
            else:
                self._ramseslib = ctypes.CDLL(os.path.join(ramLibDir, "ramses.so"))
        except OSError as e:
            raise ImportError('RAMSES: Could not load shared library from %s.' % ramLibDir) from e

        sim.ramsesCount += 1
        self._ramsesNum = sim.ramsesCount  # This is the current instance of Ramses
        self._setcalls()

    def __del__(self):
        """Unload the RAMSES shared library and decrement the instance counter.

        Called automatically by the garbage collector.  Releases the OS-level
        handle to the DLL/SO so the file can be replaced or deleted afterwards.
        Guards against partially-initialised instances (e.g. if ``__init__``
        raised before the library was loaded).
        """
        if not hasattr(self, '_ramseslib'):
            return
        warnings.warn("Simulator with number %i was deleted." % getattr(self, '_ramsesNum', -1))
        if sys.platform in ('win32', 'cygwin'):
            _ctypes.FreeLibrary(self._ramseslib._handle)
        else:
            _ctypes.dlclose(self._ramseslib._handle)
        sim.ramsesCount -= 1

    def _c_func_wrapper(self, cdecl_text):
        """Parse a single C function declaration and configure its ctypes binding.

        Reads one line from ``ramses.h``, extracts the return type, function
        name, and parameter types, then sets ``restype`` and ``argtypes`` on the
        corresponding function object retrieved from ``self._ramseslib``.

        :param str cdecl_text: a single-line C function declaration in the form
                               ``<return_type> <name>(<param_type> <param_name>, ...)``
        :raises KeyError: (internally caught) if a C type has no ctypes mapping.

        .. note:: Pointer qualifiers (``*``) attached to the variable name are
                  moved to the type string before lookup, so both ``char* x``
                  and ``char *x`` are handled correctly.
        """

        def move_pointer_and_strip(type_def, name):
            """Move any trailing ``*`` from *name* onto *type_def* and strip whitespace."""
            if '*' in name:
                type_def += ' ' + name[:name.rindex('*') + 1]
                name = name.rsplit('*', 1)[1]
            return type_def.strip(), name.strip()

        def type_lookup(type_def):
            '''Supported C variable types and their ctypes equivalents.'''
            types = {
                'void': None,
                'char *': ctypes.c_char_p,
                'int': ctypes.c_int,
                'int *': ctypes.POINTER(ctypes.c_int),
                'void *': ctypes.c_void_p,
                'size_t': ctypes.c_size_t,
                'size_t *': ctypes.POINTER(ctypes.c_size_t),
                'double': ctypes.c_double,
                'double *': ctypes.POINTER(ctypes.c_double)
            }
            type_def_without_const = type_def.replace('const ', '')
            if type_def_without_const in types:
                return types[type_def_without_const]
            elif (type_def_without_const.endswith('*') and type_def_without_const[:-1] in types):
                return ctypes.POINTER(types[type_def_without_const[:-1]])
            else:
                raise KeyError(type_def)

        a, b = [i.strip() for i in cdecl_text.split('(', 1)]
        params, _ = b.rsplit(')', 1)
        rtn_type, name = move_pointer_and_strip(*a.rsplit(' ', 1))
        param_spec = []
        for param in params.split(','):
            if param != 'void':
                param_spec.append(move_pointer_and_strip(*param.rsplit(' ', 1)))

        try:
            func = getattr(self._ramseslib, name)  # get the function from the dll
            setattr(func, 'restype', type_lookup(rtn_type))  # set the return type
            setattr(func, 'argtypes', [type_lookup(type_def) for type_def, _ in param_spec])  # set the argument types
        except AttributeError as e:
            warnings.warn('RAMSES: Function %s is listed in ramses.h but cannot be found in the library.' % (name))
            warnings.warn(str(e))

    def _setcalls(self):
        """Parse ``ramses.h`` and configure ctypes bindings for all exported functions.

        Reads the C header file bundled with the package line by line, skipping
        blank lines and ``//`` comments, and delegates each declaration to
        :meth:`_c_func_wrapper`.

        :raises IOError: if ``ramses.h`` cannot be opened.
        """
        try:
            with open(os.path.join(__libdir__, "ramses.h"), 'r') as f:
                _C_HEADER = f.read()
                for cdecl_text in _C_HEADER.splitlines():
                    if cdecl_text.strip():
                        if not cdecl_text.startswith("//"):
                            self._c_func_wrapper(cdecl_text)
        except IOError as e:
            raise IOError("RAMSES: Cannot open ramses.h files", e)

    def getLastErr(self):
        """Return the last error message issued by RAMSES.

        :rtype: str

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 0) # start simulation paused
        >>> ram.getLastErr()
        'This is an error msg'

        """

        errMsg = ctypes.create_string_buffer(1024)

        try:
            retval = self._ramseslib.get_last_err_log(errMsg)
        except KeyError:
            retval = 1

        if (retval != 0):
            raise RAMSESError('RAMSES: Function getLastErr failed.')

        return errMsg.value.decode()

    def getJac(self):
        """Return the system Jacobian matrices written by RAMSES to temporary files.

        Triggers the RAMSES ``get_Jac`` routine, which writes two sparse matrix
        files to the current working directory (``py_eqs.dat`` for the structural
        incidence matrix *E* and ``py_val.dat`` for the Jacobian values *A*).
        Both files are then parsed and returned as SciPy CSC sparse matrices.

        The simulation must have been initialised (i.e. :meth:`execSim` called
        with ``pause=0.0``) before this method is called.

        :returns: tuple ``(A, E)`` where *A* is the Jacobian value matrix and
                  *E* is the structural incidence matrix, both as
                  :class:`scipy.sparse.csc_matrix` of shape ``(N, N)``.
        :rtype: tuple

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 0) # start simulation paused
        >>> ram.getJac()

        """
        try:
            retval = self._ramseslib.get_Jac()
        except KeyError:
            retval = 1

        if (retval != 0) and (retval != 112):
            raise RAMSESError('RAMSES: Function get_Jac failed.')
        
        Nmat = 0
        try:
            with open('py_eqs.dat', 'r') as f:
                lines = f.readlines()
            rowl = []
            coll = []
            datal = []
            for x in lines:
                xsplit = x.split()
                if int(xsplit[0]) > Nmat:
                    Nmat = int(xsplit[0])
                if int(xsplit[5]) > 0:
                    rowl.append(int(xsplit[0])-1)
                    coll.append(int(xsplit[5])-1)
                    datal.append(1)
            row = np.array( rowl, dtype=int )
            col = np.array( coll, dtype=int )
            data = np.array( datal, dtype=float )
            E = coo_matrix((data,(row,col)), shape=(Nmat,Nmat)).tocsc()
        except Exception:
            raise RAMSESError('RAMSES: Function get_Jac failed while reading E.')
            
        try:
            with open('py_val.dat', 'r') as f:
                lines = f.readlines()
            row = np.array( [ int(x.split()[0])-1 for x in lines ], dtype=int )
            col = np.array( [ int(x.split()[1])-1 for x in lines ], dtype=int )
            data = np.array( [ x.split()[2] for x in lines ], dtype=float )
            A = coo_matrix((data,(row,col)), shape=(Nmat,Nmat)).tocsc()
        except Exception:
            raise RAMSESError('RAMSES: Function get_Jac failed while reading A.')

        return A, E

    def getCompName(self, comp_type, num):
        """Return the name of the *num*-th component of the given type.

        :param str comp_type: component type string — one of ``'BUS'``,
                              ``'SYNC'``, ``'INJ'``, ``'DCTL'``, ``'BRANCH'``,
                              ``'TWOP'``, ``'SHUNT'``, ``'LOAD'``.
        :param int num: 1-based index of the component.
        :returns: component name as returned by RAMSES (trailing whitespace stripped).
        :rtype: str
        :raises RAMSESError: if the component does not exist or the call fails.

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 0) # start simulation paused
        >>> ram.getCompName("BUS",1)
        'B1'

        """
        get_name_func = {
            'BUS': self._ramseslib.get_bus_name,
            'SYNC': self._ramseslib.get_sync_name,
            'INJ': self._ramseslib.get_inj_name,
            'DCTL': self._ramseslib.get_dctl_name,
            'BRANCH': self._ramseslib.get_branch_name,
            'TWOP': self._ramseslib.get_twop_name,
            'SHUNT': self._ramseslib.get_shunt_name,
            'LOAD': self._ramseslib.get_load_name
        }

        name = ctypes.create_string_buffer(21)

        try:
            retval = get_name_func[comp_type](num, name)
        except KeyError:
            retval = 1

        if (retval != 0):
            raise RAMSESError(
                'RAMSES: Function getCompName(%s,%i) failed. Does this component exist?' % (comp_type, num))

        return name.value.decode()

    def getAllCompNames(self, comp_type):
        """Return the names of all components of the given type.

        :param str comp_type: component type string — one of ``'BUS'``,
                              ``'SYNC'``, ``'INJ'``, ``'DCTL'``, ``'BRANCH'``,
                              ``'TWOP'``, ``'SHUNT'``, ``'LOAD'``.
        :returns: list of component names (empty list if none exist).
        :rtype: list of str
        :raises RAMSESError: if *comp_type* is not recognised.

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 0) # start simulation paused
        >>> ram.getAllCompNames("BUS")
        ['B1',
        'B2',
        'B3']

        """
        get_nb_func = {
            'BUS': self._ramseslib.get_nbbus,
            'SYNC': self._ramseslib.get_nbsync,
            'INJ': self._ramseslib.get_nbinj,
            'DCTL': self._ramseslib.get_nbdctl,
            'BRANCH': self._ramseslib.get_nbbra,
            'TWOP': self._ramseslib.get_nbtwop,
            'SHUNT': self._ramseslib.get_nbshunt,
            'LOAD': self._ramseslib.get_nbload
        }

        try:
            Nb = get_nb_func[comp_type]()
        except KeyError:
            raise RAMSESError(
                'RAMSES: Function getAllCompName(%s) failed. Does this component type exists?' % (comp_type))

        names = []
        if Nb > 0:
            for comp in range(1, Nb + 1):
                names.append(self.getCompName(comp_type, comp))
        return names

    def execSim(self, cmd, pause=None):
        """Execute a RAMSES simulation.

        Serialises *cmd* to a RAMSES command file (via :meth:`~pyramses.cfg.writeCmdFile`),
        then calls the RAMSES solver.  If *pause* is supplied, the simulation is
        scheduled to stop at that simulated time and can be resumed later with
        :meth:`contSim`.  Pass ``pause=0.0`` to initialise only (power-flow
        solution) without running the dynamic simulation.

        :param cmd: case configuration describing all input and output files.
        :type cmd: :class:`pyramses.cfg`
        :param pause: simulated time (seconds) at which to pause, or ``None``
                      to run until the end of the disturbance scenario.
        :type pause: float or None
        :returns: ``0`` on success.
        :rtype: int
        :raises TypeError: if *cmd* is not a :class:`pyramses.cfg` instance.
        :raises RAMSESError: if the solver returns a non-zero, non-112 flag.

        .. note:: Return code ``112`` means the simulation paused normally; it
                  is treated as success by this method.

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case)               # run to end
        >>> ram.execSim(case, pause=0.0)    # initialise only, then pause

        .. note:: If you have an existing command file, you can load it with
                  ``pyramses.cfg("cmd.txt")`` before passing it here.
        """
        if not isinstance(cmd, cfg):
            raise TypeError('RAMSES: Function execSim failed because the command file is not of type pyramses.cfg()')
        if pause is not None:
            self.pauseSim(pause)
        cmdfilename = cmd.writeCmdFile()
        if not cmd._out:
            outfilename = os.path.join(os.getcwd(),'output '+datetime.datetime.now().strftime("%d.%m.%Y-%H.%M.%S")+'.trace')
        else:
            outfilename = cmd._out[0]
        retval = self._ramseslib.ramses(cmdfilename.encode('utf-8'), outfilename.encode('utf-8'))
        if (retval != 0) and (retval != 112):
            raise RAMSESError('RAMSES: Function execSim() failed with the flag %i. Last message was: %s' % (retval, self.getLastErr()))
        return 0

    def contSim(self, pause=None):
        """Continue a paused simulation until *pause* seconds of simulated time.

        If *pause* is given, :meth:`pauseSim` is called first to schedule the
        next stop.  Pass ``self.getInfTime()`` to run until the end of the
        disturbance scenario.

        :param pause: simulated time (in seconds) at which to pause again, or
                      ``None`` to keep the currently scheduled pause time.
        :type pause: float or None
        :returns: ``0`` on success.
        :rtype: int
        :raises RAMSESError: if the RAMSES call returns a non-zero, non-112 flag.

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 0.0)        # initialise and pause at t=0
        >>> ram.contSim(ram.getInfTime()) # run to end of scenario
        """
        if pause is not None:
            self.pauseSim(pause)
        retval = self._ramseslib.continue_simul()
        if (retval != 0) and (retval != 112):
            raise RAMSESError('RAMSES: Function contSim() failed with the flag %i. Last message was: %s' % (retval, self.getLastErr()))
        return 0

    def getBusVolt(self, busNames):
        """Return the voltage magnitude of a list of buses

        :param busNames: the names of buses
        :type busNames: list of str
        :returns: list of bus voltage magnitudes
        :rtype: list of floats

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 10.0) # simulate until 10 seconds and pause
        >>> buses = ['g1','g2','g3']
        >>> ram.getBusVolt(buses)
        [1.0736851673414456,
         1.0615442362180327,
         1.064702686997689]
        """
        volts = []
        bus_volt = ctypes.c_double()
        for bus in busNames:
            retval = self._ramseslib.get_volt_mag(bus.encode('utf-8'), bus_volt)
            if (retval != 0):
                raise RAMSESError(
                    'RAMSES: Function getBusVolt(%s) failed with the flag %i.  Does the bus exist? Last message was: %s' % (bus, retval, self.getLastErr()))
            volts.append(bus_volt.value)
        return volts

    def getBranchPow(self, branchName):
        """Return the active and reactive powers of a list of branches

        :param branchName: the names of branches
        :type branchName: list of str
        :returns: list of branch powers. These are active and reactive power at the origin and extremity respectively (p_orig, q_orig, p_extr, q_extr)
        :rtype: list of floats

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 10.0) # simulate until 10 seconds and pause
        >>> branchName = ['1011-1013','1012-1014','1021-1022']
        >>> ram.getBranchPow(branchName)
        """
        pows = []
        p_orig = ctypes.c_double()
        q_orig = ctypes.c_double()
        p_extr = ctypes.c_double()
        q_extr = ctypes.c_double()
        for branch in branchName:
            retval = self._ramseslib.get_line_pow(branch.encode('utf-8'), p_orig, q_orig, p_extr, q_extr)
            if (retval != 0):
                raise RAMSESError(
                    'RAMSES: Function get_line_pow(%s) failed with the flag %i.  Does the branch exist? Last message was: %s' % (branch, retval, self.getLastErr()))
            thisBranch = [p_orig.value, q_orig.value, p_extr.value, q_extr.value]
            pows.append(thisBranch)
        return pows

    def getBranchCur(self, branchName):
        """Return the currents of a list of branches

        :param branchName: the names of branches
        :type branchName: list of str
        :returns: list of branch currents. These are x-y components at the origin and extremity respectively (ix_orig, iy_orig, ix_extr, iy_extr)
        :rtype: list of floats

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 10.0) # simulate until 10 seconds and pause
        >>> branchName = ['1011-1013','1012-1014','1021-1022']
        >>> ram.getBranchCur(branchName)

        """
        curs = []
        ix_orig = ctypes.c_double()
        iy_orig = ctypes.c_double()
        ix_extr = ctypes.c_double()
        iy_extr = ctypes.c_double()
        for branch in branchName:
            retval = self._ramseslib.get_line_cur(branch.encode('utf-8'), ix_orig, iy_orig, ix_extr, iy_extr)
            if (retval != 0):
                raise RAMSESError(
                    'RAMSES: Function get_line_cur(%s) failed with the flag %i.  Does the branch exist? Last message was: %s' % (branch, retval, self.getLastErr()))
            thisBranch = [ix_orig.value, iy_orig.value, ix_extr.value, iy_extr.value]
            curs.append(thisBranch)
        return curs        

    def getBusPha(self, busNames):
        """Return the voltage phase of a list of buses

        :param busNames: the names of buses
        :type busNames: list of str
        :returns: list of bus voltage phase
        :rtype: list of floats

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 10.0) # simulate until 10 seconds and pause
        >>> buses = ['g1','g2','g3']
        >>> ram.getBusPha(buses)
        [0.0000000000000000,
         10.0615442362180327,
         11.064702686997689]

        """
        pha = []
        bus_pha = ctypes.c_double()
        for bus in busNames:
            retval = self._ramseslib.get_volt_pha(bus.encode('utf-8'), bus_pha)
            if (retval != 0):
                raise RAMSESError(
                    'RAMSES: Function getBusPha(%s) failed with the flag %i.  Does the bus exist? Last message was: %s' % (bus, retval, self.getLastErr()))
            pha.append(bus_pha.value)
        return pha

    def endSim(self):
        """Signal RAMSES to end the simulation and block until it terminates.

        Sets the internal RAMSES end-of-simulation flag and then calls
        :meth:`contSim` with an infinite time horizon so that the solver
        flushes its output and cleans up.

        :returns: return value of the underlying :meth:`contSim` call (``0`` on success).
        :rtype: int
        """

        self._ramseslib.set_end_simul()
        return self.contSim(self.getInfTime())
    
    def getEndSim(self):
        """Check whether the simulation has ended.

        :returns: ``0`` if the simulation is still running; ``1`` if it has ended.
        :rtype: int
        """

        return self._ramseslib.get_end_simul()

    def getSimTime(self):
        """Return the current simulated time reported by the RAMSES solver.

        Only meaningful while a simulation is paused (between :meth:`execSim`
        and :meth:`contSim` calls).

        :returns: current simulation time in seconds.
        :rtype: float
        """
        return self._ramseslib.get_sim_time()

    def getInfTime(self):
        """Return the largest representable double recognised by the RAMSES solver.

        Passing this value to :meth:`contSim` or :meth:`execSim` instructs
        RAMSES to run until the end of the disturbance scenario.

        :returns: maximum double value used internally by RAMSES as a sentinel
                  for "simulate to the end".
        :rtype: float
        """
        return self._ramseslib.get_huge_double()

    def initObserv(self, traj_filenm):
        """Initialise the runtime observable recording system.

        Must be called after :meth:`execSim` (with ``pause=0.0``) and before
        :meth:`addObserv` / :meth:`finalObserv`.  Sets the path of the output
        trajectory file and prepares the internal observable structures.

        :param str traj_filenm: path of the ``.trj`` file where recorded
                                timeseries will be written.
        :returns: return value from the underlying RAMSES call (non-zero on error).

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt") # command file without any observables
        >>> ram.execSim(case, 0.0) # start
        >>> traj_filenm = 'obs.trj'
        >>> ram.initObserv(traj_filenm)
        """

        return self._ramseslib.initObserv(traj_filenm.encode('utf-8'))

    def addObserv(self, string):
        """Register one observable element for runtime recording.

        Must be called after :meth:`initObserv` and before :meth:`finalObserv`.
        Accepts RAMSES observable selector strings such as ``'BUS *'`` (all
        buses) or ``'SYNC g1'`` (a specific generator).

        :param str string: observable selector in RAMSES format.
        :returns: return value from the underlying RAMSES call (non-zero on error).

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt") # command file without any observables
        >>> ram.execSim(case, 0.0) # start
        >>> traj_filenm = 'obs.trj'
        >>> ram.initObserv(traj_filenm)
        >>> string = 'BUS *' # monitor all buses
        >>> ram.addObserv(string)
        """

        return self._ramseslib.addObserv(string.encode('utf-8'))

    def finalObserv(self):
        """Finalise observable selection, allocate recording buffers, and write the trajectory file header.

        Must be called after all :meth:`addObserv` calls.  RAMSES will write
        timeseries data to the ``.trj`` file specified in :meth:`initObserv`
        as the simulation advances.

        :returns: return value from the underlying RAMSES call (non-zero on error).

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt") # command file without any observables
        >>> ram.execSim(case, 0.0) # start
        >>> traj_filenm = 'obs.trj'
        >>> ram.initObserv(traj_filenm)
        >>> string = 'BUS *' # monitor all buses
        >>> ram.addObserv(string)
        >>> ram.finalObserv()
        """

        return self._ramseslib.finalObserv()

    def getPrm(self, comp_type, comp_name, prm_name):
        """Get the value of a named parameter

        :param comp_type: the types of components (EXC, TOR, INJ, DCTL, TWOP)
        :type comp_type: list of str
        :param comp_name: the names of components
        :type comp_name: list of str
        :param prm_name: the names of parameters
        :type prm_name: list of str

        :returns: list of parameter values
        :rtype: list of floats

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 10.0) # simulate until 10 seconds and pause
        >>> comp_type = ['EXC','EXC','EXC']
        >>> comp_name = ['g1','g2','g3']
        >>> prm_name = ['V0','V0','V0']
        >>> ram.getPrm(comp_type,comp_name, prm_name)
        [1.0736851673414456,
         1.0615442362180327,
         1.064702686997689]

        """

        comp_type = wrapToList(comp_type)
        comp_name = wrapToList(comp_name)
        prm_name = wrapToList(prm_name)

        if not (len(comp_type) == len(comp_name) == len(prm_name)):
            raise ValueError('RAMSES: Function getPrm failed because the lists are not equal!')
        prm_values = []
        for a, b, c in zip(comp_type, comp_name, prm_name):
            prm_value = ctypes.c_double()
            retval = self._ramseslib.get_named_prm(a.encode('utf-8'), b.encode('utf-8'), c.encode('utf-8'),
                                                   prm_value)
            if retval != 0:
                raise RAMSESError(
                    'RAMSES: Function getPrm(%s,%s,%s) failed with the flag %i. Does the parameter or equipment exist? Last message was: %s'
                    % (a, b, c, retval, self.getLastErr()))
            prm_values.append(prm_value.value)
        if len(prm_values) == 1:
            return prm_values[0]
        else:
            return prm_values

    def defineSS(self, ssID, filter1, filter2, filter3):
        """Define a subsytem using three filters. The resulting list is an intersection of the filters.

        :param ssID: Number of the SS
        :type ssID: int
        :param filter1: Voltage levels to be included
        :type filter1: list of str or str
        :param filter2: Zones (which zone/zones will be included)
        :type filter2: list of str or str
        :param filter3: Bus names to be included
        :type filter3: list of str or str

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 0.0)
        >>> ram.defineSS(1, ['735'], [], []) # SS 1 with all buses at 735 kV, no zones, no list of buses

        :raises RAMSESError: if *ssID*, *location*, or *in_service* are not valid, or the RAMSES call fails.
        :returns: ``None``

        .. note:: An empty filter means it is deactivated and discarded.

        """
        filter1 = wrapToList(filter1)
        filter2 = wrapToList(filter2)
        filter3 = wrapToList(filter3)

        strF1 = ' '.join(filter1)
        strF2 = ' '.join(filter2)
        strF3 = ' '.join(filter3)

        retval = self._ramseslib.define_SS(ctypes.c_int(ssID), strF1.encode('utf-8'), ctypes.c_int(len(filter1)),
                                           strF2.encode('utf-8'), ctypes.c_int(len(filter2)), strF3.encode('utf-8'),
                                           ctypes.c_int(len(filter3)))
        if retval != 0:
            raise RAMSESError('RAMSES: Function define_SS(%i,...) failed with the flag %i. Last message was: %s' % (ssID, retval, self.getLastErr()))

    def getSS(self, ssID):
        """Retrieve the buses of a subsytem.

        :param ssID: Number of the SS
        :type ssID: int

        :returns: list of buses
        :rtype: list of str

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 0.0)
        >>> ram.defineSS(1, ['735'], [], []) # SS 1 with all buses at 735 kV
        >>> ram.getSS(1) # get list of buses in SS 1

        """

        mxreclen = self._ramseslib.get_nbbus()
        string_buffer = ctypes.create_string_buffer(19 * mxreclen)

        retval = self._ramseslib.get_SS(ctypes.c_int(ssID), ctypes.c_int(mxreclen), string_buffer)
        if retval != 0:
            raise RAMSESError('RAMSES: Function getSS(%i) failed with the flag %i. Last message was: %s' % (ssID, retval, self.getLastErr()))

        return string_buffer.value.split()

    def getTrfoSS(self, ssID, location, in_service, rettype):
        """Retrieve transformer information of subsystem after applying some filters

        :param ssID: Number of the SS
        :type ssID: int
        :param location: 1 – both buses inside SS, 2 - tie transformers, 3 – 1 & 2
        :type location: int
        :param in_service: 1 – transformers in service, 2 - all transformers
        :type in_service: int
        :param rettype: Type of response (NAME, From, To, Status, Tap, Currentf, Currentt, Pf, Qf, Pt, Qt).
        :type rettype: str

        :returns: list of transformer names
        :rtype: list of str

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 0.0)
        >>> ram.defineSS(1, ['735'], [], []) # SS 1 with all buses at 735 kV
        >>> ram.getTrfoSS(1,3,2,'Status')

        .. note:: Tap is not implemented yet.

        .. todo:: Implement Taps after discussing with Lester.
        """

        if rettype not in ['NAME', 'From', 'To', 'Status', 'Tap', 'Currentf', 'Currentt', 'Pf', 'Qf', 'Pt', 'Qt']:
            raise RAMSESError('RAMSES: Function getTrfoSS(%i,%i,%i,%s): rettype is not valid!' % (
                ssID, location, in_service, rettype))
        elif location not in [1, 2, 3]:
            raise RAMSESError('RAMSES: Function getTrfoSS(%i,%i,%i,%s): location is not valid!' % (
                ssID, location, in_service, rettype))
        elif in_service not in [1, 2]:
            raise RAMSESError('RAMSES: Function getTrfoSS(%i,%i,%i,%s): in_service is not valid!' % (
                ssID, location, in_service, rettype))

        mxreclen = self._ramseslib.get_nbbra()
        string_buffer = ctypes.create_string_buffer(21 * mxreclen)
        dp_vec = (ctypes.c_double * mxreclen)()
        dp_int = (ctypes.c_int * mxreclen)()
        elem = ctypes.c_int()

        retval = self._ramseslib.get_transformer_in_SS(ctypes.c_int(ssID), ctypes.c_int(location),
                                                       ctypes.c_int(in_service), rettype.encode('utf-8'),
                                                       ctypes.c_int(mxreclen), string_buffer, dp_vec, dp_int, elem)
        if retval != 0:
            raise RAMSESError('RAMSES: Function getTrfoSS(%i,%i,%i,%s) failed with the flag %i.' % (
                ssID, location, in_service, rettype, retval))

        if elem == 0:
            return []
        elif rettype in ['Tap', 'Status']:
            return [dp_int[i] for i in range(0, elem.value)]
        elif rettype in ['Currentf', 'Currentt', 'Pf', 'Qf', 'Pt', 'Qt']:
            return [dp_vec[i] for i in range(0, elem.value)]
        else:
            return string_buffer.value.split()

    def getPrmNames(self, comp_type, comp_name):
        """Get the named parameters of a model

        :param comp_type: the types of components (EXC, TOR, INJ, DCTL, TWOP)
        :type comp_type: list of str or str
        :param comp_name: the names of component instances
        :type comp_name: list of str or str

        :returns: list of parameter names
        :rtype: list of lists of strings

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 0.0) # initialize and wait
        >>> comp_type = ['EXC','EXC','EXC']
        >>> comp_name = ['g1','g2','g3'] # name of synchronous machines
        >>> ram.getPrmNames(comp_type,comp_name)

        """
        comp_type = wrapToList(comp_type)
        comp_name = wrapToList(comp_name)

        if not (len(comp_type) == len(comp_name)):
            raise ValueError('RAMSES: Function getPrmNames failed because the lists are not equal!')
        prm_names = []
        mxprm = self._ramseslib.get_mxprm()  # get maximum number of parameters in any model
        for a, b in zip(comp_type, comp_name):
            string_buffer = ctypes.create_string_buffer(11 * mxprm)
            retval = self._ramseslib.get_comp_prm_names(a.encode('utf-8'), b.encode('utf-8'), ctypes.c_int(mxprm),
                                                        string_buffer)
            if retval != 0:
                raise RAMSESError(
                    'RAMSES: Function getPrm(%s,%s) failed with the flag %i. Does the parameter or equipment exist?'
                    % (a, b, retval))
            decodedstring = string_buffer.value.decode()
            prm_names.append(decodedstring.split())
        if len(prm_names) == 1:
            return prm_names[0]
        else:
            return prm_names

    def getObs(self, comp_type, comp_name, obs_name):
        """Get the value of a named observable. 

        :param comp_type: the types of components ('EXC','TOR','INJ','TWOP','DCTL','SYN')
        :type comp_type: list of str
        :param comp_name: the names of components
        :type comp_name: list of str
        :param obs_name: the names of observables
        :type obs_name: list of str

        :returns: list of observable values
        :rtype: list of floats

        .. note:: 
          
          For the synchronous generator ('SYN') the accepted obs_name values are 
          - 'P': Active power (MW)
          - 'Q': Reactive power (MVAr)
          - ``'Omega'``: Machine speed (pu)
          - 'S': Apparent power (MVA)
          - 'SNOM': Nominal apparent power (MVA)
          - 'PNOM': Nominal active power (MW)

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 10.0) # simulate until 10 seconds and pause
        >>> comp_type = ['INJ','EXC','TOR']
        >>> comp_name = ['L_11','g2','g3']
        >>> obs_name = ['P','vf','Pm']
        >>> ram.getObs(comp_type,comp_name, obs_name)
        [199.73704732259995,
        1.3372945282585218,
        0.816671075203357]

        """
        comp_type = wrapToList(comp_type)
        comp_name = wrapToList(comp_name)
        obs_name = wrapToList(obs_name)

        if not (len(comp_type) == len(comp_name) == len(obs_name)):
            raise ValueError('RAMSES: Function getObs failed because the lists are not equal!')
        obs_values = []
        for a, b, c in zip(comp_type, comp_name, obs_name):
            obs_value = ctypes.c_double()
            retval = self._ramseslib.get_named_obs(a.encode('utf-8'), b.encode('utf-8'), c.encode('utf-8'),
                                                   obs_value)
            if retval != 0:
                raise RAMSESError(
                    'RAMSES: Function getObs(%s,%s,%s) failed with the flag %i. Does the observable or equipment exist?'
                    % (a, b, c, retval))
            obs_values.append(obs_value.value)
        return obs_values

    def pauseSim(self, t_pause):
        """Schedule a pause at *t_pause* seconds of simulated time.

        The pause is registered in the solver's internal state and takes effect
        during the next :meth:`execSim` or :meth:`contSim` call.

        :param float t_pause: simulated time (seconds) at which to pause.
        :returns: return value from the underlying RAMSES call (non-zero on error).
        :rtype: int

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.pauseSim(10.0)
        >>> ram.execSim(case)  # will pause at t=10 s
        """
        return self._ramseslib.set_pause_time(t_pause)

    def addDisturb(self, t_dist, disturb):
        """Add a new disturbance at a specific time. Follows the same structure as the disturbances in the dst files.

        :param t_dist: time of the disturbance
        :type t_dist: float
        :param disturb: description of disturbance
        :type disturb: str

        :Example:

        >>> import pyramses
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case, 80.0) # simulate until 80 seconds and pause
        >>> ram.addDisturb(100.000, 'CHGPRM DCTL 1-1041  Vsetpt -0.05 0') # Decrease the setpoint of the DCTL by 0.015 pu, at t=100 s
        >>> ram.addDisturb(100.000, 'CHGPRM DCTL 2-1042  Vsetpt -0.05 0')
        >>> ram.addDisturb(100.000, 'CHGPRM DCTL 3-1043  Vsetpt -0.05 0')
        >>> ram.addDisturb(100.000, 'CHGPRM DCTL 4-1044  Vsetpt -0.05 0')
        >>> ram.addDisturb(100.000, 'CHGPRM DCTL 5-1045  Vsetpt -0.05 0')
        >>> ram.contSim(ram.getInfTime()) # continue the simulation
        """
        return self._ramseslib.add_disturb(t_dist, disturb.encode('utf-8'))

    def load_MDL(self, MDLName):
        """Load an external shared library containing user-defined RAMSES models.

        The library must expose the standard RAMSES user-model interface.  Once
        loaded, the models it defines become available to the solver for the
        lifetime of this :class:`sim` instance.

        :param str MDLName: path to the model library (``*.dll`` on Windows,
                            ``*.so`` on Linux).  Use the current directory or
                            an absolute path.
        :returns: return value from the underlying RAMSES call (non-zero on error).

        :Example:

        >>> import pyramses
        >>> pyramses.sim.load_MDL("MDLs.dll")
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case)
        """
        return self._ramseslib.c_load_MDL(MDLName.encode('utf-8'))

    def unload_MDL(self, MDLName):
        """Unload a previously loaded user-model shared library.

        :param str MDLName: path to the model library that was passed to
                            :meth:`load_MDL`.
        :returns: return value from the underlying RAMSES call (non-zero on error).

        :Example:

        >>> import pyramses
        >>> pyramses.sim.load_MDL("MDLs.dll")
        >>> ram = pyramses.sim()
        >>> case = pyramses.cfg("cmd.txt")
        >>> ram.execSim(case)
        >>> pyramses.sim.unload_MDL("MDLs.dll")
        """
        return self._ramseslib.c_unload_MDL(MDLName.encode('utf-8'))


    def get_MDL_no(self):
        """Return the number of user-model libraries currently loaded.

        :returns: count of loaded user-model libraries.
        :rtype: int

        :Example:

        >>> import pyramses
        >>> pyramses.sim.load_MDL("MDLs.dll")
        >>> pyramses.sim.get_MDL_no()
        1
        """
        return self._ramseslib.c_get_MDL_no()
