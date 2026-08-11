#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Python interface to the Helios AC power-flow engine.

Helios is the STEPSS power-flow calculator (successor of the Fortran PFC).
This module wraps the bundled ``libhelios_api`` C shared library with an
explicit ctypes binding and exposes :class:`HeliosSession`, a stateful
session object with a load → (modify) → solve → query lifecycle.

Unlike the rest of stepss (which follows the historical camelCase RAMSES
conventions), this module deliberately uses PEP 8 snake_case naming.

Quick start::

    from stepss.helios import HeliosSession

    with HeliosSession() as pf:
        pf.load_file("network.dat")
        pf.solve()
        v, angle = pf.get_bus_voltage("A")
        v_all, angle_all = pf.get_bus_voltages()

Each session owns an independent solver instance; sessions may be used
concurrently from different threads (do not share one session between
threads without locking).
"""

import ctypes
import enum
import os
import sys
from dataclasses import dataclass, field

import numpy

from .globals import HeliosError, __platlibdir__

_c_int_p = ctypes.POINTER(ctypes.c_int)
_c_double_p = ctypes.POINTER(ctypes.c_double)

#: Buffer size sufficient for any element name (mirrors HELIOS_NAME_MAX).
NAME_MAX = 64
#: Buffer size for free-text strings such as violations (HELIOS_TEXT_MAX).
TEXT_MAX = 256

#: Oldest / newest C API major.minor this wrapper is tested against.
_SUPPORTED_API = ((1, 1), (1, None))


class SolverStatus(enum.IntEnum):
    """Detailed solver status reported by :attr:`HeliosSession.solver_status`."""

    NOT_RUN = 0
    CONVERGED = 1
    DIVERGED = 2
    MAX_ITERATIONS = 3
    SINGULAR = 4


class Option(enum.IntEnum):
    """Solver options accepted by :meth:`HeliosSession.set_option` (HeliosOption enum)."""

    SBASE = 0        #: system base, MVA
    TOLAC = 1        #: active power tolerance, MW ($TOLAC)
    TOLREAC = 2      #: reactive power tolerance, Mvar ($TOLREAC)
    MAX_ITER = 3     #: maximum iterations ($NBITMA)
    TH_BLOCK = 4     #: tap-blocking mismatch threshold, MVA ($MISBLOC)
    TH_ADJ = 5       #: tap-adjustment mismatch threshold, MVA ($MISADJ)
    TH_QLIM = 6      #: Q-limit switching mismatch threshold, MVA ($MISQLIM)
    PLIM = 7         #: 0/1 slack P-limit relaxation ($PLIM)
    DIVDET = 8       #: divergence detection threshold ($DIVDET)


class BusType(enum.IntEnum):
    """Bus type reported by :meth:`HeliosSession.get_bus_info`."""

    PQ = 0
    PV = 1
    SLACK = 2
    ISOLATED = 3


@dataclass
class BusInfo:
    """Static and solved data of one bus."""

    name: str
    v_pu: float
    angle_rad: float
    bus_type: BusType
    vnom_kv: float
    p_load_mw: float
    q_load_mvar: float


@dataclass
class BranchInfo:
    """Static data and solved flows of one branch."""

    name: str
    from_bus: str
    to_bus: str
    closed: bool
    is_transformer: bool
    snom_mva: float
    p_from_mw: float
    q_from_mvar: float
    p_to_mw: float
    q_to_mvar: float


@dataclass
class GeneratorInfo:
    """Static data and solved outputs of one generator."""

    name: str
    bus: str
    in_service: bool
    p_mw: float
    q_mvar: float
    v_setpoint_pu: float
    p_min_mw: float
    p_max_mw: float
    q_min_mvar: float
    q_max_mvar: float
    has_p_limits: bool


@dataclass
class ContingencyResult:
    """Outcome of one contingency run."""

    name: str
    converged: bool
    accepted: bool
    min_v_pu: float
    max_v_pu: float
    min_v_bus: str
    max_v_bus: str
    max_loading_pct: float
    max_loading_branch: str
    violations: list = field(default_factory=list)


def _lib_name():
    """Return the platform-specific shared-library filename."""
    if sys.platform in ("win32", "cygwin"):
        return "helios_api.dll"
    if sys.platform == "darwin":
        return "libhelios_api.dylib"
    return "libhelios_api.so"


# Explicit binding table: {symbol: (restype, [argtypes])}. The bundled
# libs/helios_api.h is the authoritative reference for these signatures;
# an explicit table is used (instead of parsing the header, as the RAMSES
# wrapper does) because helios_api.h contains enums, typedefs, and
# multi-line prototypes that a line-based parser cannot handle.
_H = ctypes.c_void_p
_I = ctypes.c_int
_D = ctypes.c_double
_S = ctypes.c_char_p
_SIGNATURES = {
    "helios_create": (_H, []),
    "helios_destroy": (None, [_H]),
    "helios_get_api_version": (None, [_c_int_p, _c_int_p, _c_int_p]),
    "helios_get_build_info": (_S, []),
    "helios_get_last_error": (_S, [_H]),
    "helios_clear_last_error": (None, [_H]),
    "helios_load_file": (_I, [_H, _S]),
    "helios_solve": (_I, [_H]),
    "helios_get_convergence_status": (_I, [_H]),
    "helios_get_bus_voltage": (_I, [_H, _S, _c_double_p, _c_double_p]),
    "helios_get_branch_flow": (_I, [_H, _S, _c_double_p, _c_double_p]),
    "helios_get_output_text": (_S, [_H]),
    "helios_set_option": (_I, [_H, _I, _D]),
    "helios_get_option": (_I, [_H, _I, _c_double_p]),
    "helios_get_iteration_count": (_I, [_H]),
    "helios_get_max_mismatch": (_I, [_H, _c_double_p, _c_double_p]),
    "helios_get_solver_status": (_I, [_H]),
    "helios_get_bus_count": (_I, [_H]),
    "helios_get_branch_count": (_I, [_H]),
    "helios_get_generator_count": (_I, [_H]),
    "helios_get_svc_count": (_I, [_H]),
    "helios_get_zone_count": (_I, [_H]),
    "helios_get_cut_count": (_I, [_H]),
    "helios_get_bus_name": (_I, [_H, _I, _S, _I]),
    "helios_get_branch_name": (_I, [_H, _I, _S, _I]),
    "helios_get_generator_name": (_I, [_H, _I, _S, _I]),
    "helios_get_svc_name": (_I, [_H, _I, _S, _I]),
    "helios_get_zone_name": (_I, [_H, _I, _S, _I]),
    "helios_get_cut_name": (_I, [_H, _I, _S, _I]),
    "helios_find_bus": (_I, [_H, _S]),
    "helios_find_branch": (_I, [_H, _S]),
    "helios_find_generator": (_I, [_H, _S]),
    "helios_find_svc": (_I, [_H, _S]),
    "helios_find_zone": (_I, [_H, _S]),
    "helios_find_cut": (_I, [_H, _S]),
    "helios_get_bus_info": (_I, [_H, _I, _c_double_p, _c_double_p, _c_int_p, _c_double_p]),
    "helios_get_bus_load": (_I, [_H, _I, _c_double_p, _c_double_p]),
    "helios_get_bus_shunt": (_I, [_H, _I, _c_double_p, _c_double_p]),
    "helios_get_bus_zone": (_I, [_H, _I]),
    "helios_get_branch_info": (_I, [_H, _I, _c_int_p, _c_int_p, _c_int_p, _c_int_p, _c_double_p]),
    "helios_get_branch_flow_by_index": (_I, [_H, _I, _c_double_p, _c_double_p, _c_double_p, _c_double_p]),
    "helios_get_generator_info": (_I, [_H, _I, _c_int_p, _c_int_p, _c_double_p, _c_double_p, _c_double_p]),
    "helios_get_generator_limits": (_I, [_H, _I, _c_double_p, _c_double_p, _c_double_p, _c_double_p, _c_int_p]),
    "helios_get_svc_info": (_I, [_H, _I, _c_int_p, _c_int_p, _c_double_p, _c_double_p, _c_int_p]),
    "helios_get_cut_flow": (_I, [_H, _I, _c_double_p, _c_double_p]),
    "helios_copy_bus_voltages": (_I, [_H, _c_double_p, _c_double_p, _I]),
    "helios_copy_bus_loads": (_I, [_H, _c_double_p, _c_double_p, _I]),
    "helios_copy_branch_flows": (_I, [_H, _c_double_p, _c_double_p, _c_double_p, _c_double_p, _I]),
    "helios_copy_branch_status": (_I, [_H, _c_int_p, _I]),
    "helios_copy_generator_outputs": (_I, [_H, _c_double_p, _c_double_p, _c_int_p, _I]),
    "helios_copy_svc_outputs": (_I, [_H, _c_double_p, _c_int_p, _I]),
    "helios_trip_branch": (_I, [_H, _S]),
    "helios_connect_branch": (_I, [_H, _S]),
    "helios_trip_generator": (_I, [_H, _S]),
    "helios_connect_generator": (_I, [_H, _S]),
    "helios_trip_svc": (_I, [_H, _S]),
    "helios_connect_svc": (_I, [_H, _S]),
    "helios_set_generator_voltage": (_I, [_H, _S, _D]),
    "helios_set_generator_pq": (_I, [_H, _S, _D]),
    "helios_change_generation": (_I, [_H, _S, _D]),
    "helios_change_load": (_I, [_H, _S, _D, _D]),
    "helios_change_shunt": (_I, [_H, _S, _D]),
    "helios_change_zone_load": (_I, [_H, _S, _D, _D]),
    "helios_change_zone_generation": (_I, [_H, _S, _D]),
    "helios_apply_changes": (_I, [_H]),
    "helios_reset": (_I, [_H]),
    "helios_write_dump": (_I, [_H, _S]),
    "helios_write_voltrat": (_I, [_H, _S]),
    "helios_write_matlab": (_I, [_H, _S]),
    "helios_write_diagram": (_I, [_H, _S, _S]),
    "helios_run_contingencies_file": (_I, [_H, _S, _D, _D, _D, _D]),
    "helios_run_contingencies_n1": (_I, [_H, _I, _I, _I, _D, _D, _D, _D]),
    "helios_get_contingency_count": (_I, [_H]),
    "helios_get_contingency_name": (_I, [_H, _I, _S, _I]),
    "helios_get_contingency_result": (_I, [_H, _I, _c_int_p, _c_int_p, _c_double_p, _c_double_p, _c_double_p]),
    "helios_get_contingency_extremes": (_I, [_H, _I, _S, _S, _S, _I]),
    "helios_get_contingency_violation_count": (_I, [_H, _I]),
    "helios_get_contingency_violation": (_I, [_H, _I, _I, _S, _I]),
}

_lib_cache = {}


def _load_library(lib_dir=None):
    """Load (or return the cached) helios shared library and bind signatures.

    Without *lib_dir* the platform-specific bundled copy is used
    (``libs/win``, ``libs/lin`` or ``libs/mac``); a custom *lib_dir* must
    contain the library file directly (no platform subfolder).
    """
    directory = os.path.realpath(lib_dir) if lib_dir else __platlibdir__
    path = os.path.join(directory, _lib_name())
    if path in _lib_cache:
        return _lib_cache[path]
    try:
        lib = ctypes.CDLL(path)
    except OSError as exc:
        raise ImportError(
            "Could not load the helios shared library from %r: %s" % (path, exc)
        ) from exc
    for name, (restype, argtypes) in _SIGNATURES.items():
        try:
            fn = getattr(lib, name)
        except AttributeError as exc:
            raise ImportError(
                "Symbol %r missing from %r — library too old for this wrapper?" % (name, path)
            ) from exc
        fn.restype = restype
        fn.argtypes = argtypes

    major = ctypes.c_int()
    minor = ctypes.c_int()
    patch = ctypes.c_int()
    lib.helios_get_api_version(ctypes.byref(major), ctypes.byref(minor), ctypes.byref(patch))
    (min_major, min_minor), (max_major, _) = _SUPPORTED_API
    if not (min_major, min_minor) <= (major.value, minor.value) or major.value > max_major:
        raise ImportError(
            "helios library version %d.%d.%d is outside the supported range (>= %d.%d, major <= %d)"
            % (major.value, minor.value, patch.value, min_major, min_minor, max_major)
        )

    _lib_cache[path] = lib
    return lib


class HeliosSession:
    """A Helios power-flow session: load → (modify) → solve → query.

    :param str lib_dir: optional directory containing the helios shared
        library, overriding the copy bundled with stepss (useful for
        testing pre-release engine builds).

    The session is a context manager; on exit the native handle is
    destroyed. Explicit :meth:`close` is idempotent.
    """

    def __init__(self, lib_dir=None):
        self._lib = _load_library(lib_dir)
        self._handle = self._lib.helios_create()
        if not self._handle:
            raise HeliosError("helios_create failed (out of memory?)")

    # -- lifecycle ---------------------------------------------------------

    def close(self):
        """Destroy the native handle. Safe to call more than once."""
        if getattr(self, "_handle", None):
            self._lib.helios_destroy(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _check(self, ret, what):
        """Raise :class:`HeliosError` when *ret* is a negative status code."""
        if ret < 0:
            raise HeliosError("%s failed (%d): %s" % (what, ret, self.last_error))
        return ret

    @property
    def _h(self):
        if not self._handle:
            raise HeliosError("session is closed")
        return self._handle

    # -- library information ------------------------------------------------

    def api_version(self):
        """Return the C API version as a ``(major, minor, patch)`` tuple."""
        major = ctypes.c_int()
        minor = ctypes.c_int()
        patch = ctypes.c_int()
        self._lib.helios_get_api_version(
            ctypes.byref(major), ctypes.byref(minor), ctypes.byref(patch))
        return (major.value, minor.value, patch.value)

    def build_info(self):
        """Return the library build description string."""
        return self._lib.helios_get_build_info().decode()

    @property
    def last_error(self):
        """Diagnostic text of the most recent failing call (or warning)."""
        return self._lib.helios_get_last_error(self._h).decode()

    def clear_last_error(self):
        """Clear the per-session diagnostic text."""
        self._lib.helios_clear_last_error(self._h)

    # -- load and solve ------------------------------------------------------

    def load_file(self, path):
        """Load a STEPSS data file, replacing any previously loaded network."""
        self._check(self._lib.helios_load_file(self._h, str(path).encode("utf-8")),
                    "load_file(%s)" % path)

    def solve(self):
        """Run the power flow. Returns ``True`` if converged.

        Raises :class:`HeliosError` on hard errors (no network loaded,
        solver exception); mere non-convergence returns ``False``.
        """
        ret = self._check(self._lib.helios_solve(self._h), "solve")
        return ret == 0

    def reset(self):
        """Restore the state saved at load and drop pending modifications."""
        self._check(self._lib.helios_reset(self._h), "reset")

    @property
    def converged(self):
        """``True`` when the last solve converged."""
        return self._check(self._lib.helios_get_convergence_status(self._h),
                           "get_convergence_status") == 0

    @property
    def solver_status(self):
        """Detailed :class:`SolverStatus` of the last solve."""
        return SolverStatus(self._check(self._lib.helios_get_solver_status(self._h),
                                        "get_solver_status"))

    @property
    def iterations(self):
        """Iterations used by the last solve."""
        return self._check(self._lib.helios_get_iteration_count(self._h),
                           "get_iteration_count")

    @property
    def max_mismatch(self):
        """Largest remaining ``(mw, mvar)`` mismatches of the last solve."""
        mw = ctypes.c_double()
        mvar = ctypes.c_double()
        self._check(self._lib.helios_get_max_mismatch(
            self._h, ctypes.byref(mw), ctypes.byref(mvar)), "get_max_mismatch")
        return (mw.value, mvar.value)

    # -- solver options -------------------------------------------------------

    def set_option(self, option, value):
        """Set a solver :class:`Option`. Call after :meth:`load_file`
        (loading overwrites options with the file's ``$PARAM`` values)."""
        self._check(self._lib.helios_set_option(self._h, int(option), float(value)),
                    "set_option(%s)" % option)

    def get_option(self, option):
        """Return the current value of a solver :class:`Option`."""
        value = ctypes.c_double()
        self._check(self._lib.helios_get_option(self._h, int(option), ctypes.byref(value)),
                    "get_option(%s)" % option)
        return value.value

    # -- counts, names, lookup -------------------------------------------------

    @property
    def bus_count(self):
        return self._check(self._lib.helios_get_bus_count(self._h), "get_bus_count")

    @property
    def branch_count(self):
        return self._check(self._lib.helios_get_branch_count(self._h), "get_branch_count")

    @property
    def generator_count(self):
        return self._check(self._lib.helios_get_generator_count(self._h),
                           "get_generator_count")

    @property
    def svc_count(self):
        return self._check(self._lib.helios_get_svc_count(self._h), "get_svc_count")

    @property
    def zone_count(self):
        return self._check(self._lib.helios_get_zone_count(self._h), "get_zone_count")

    @property
    def cut_count(self):
        return self._check(self._lib.helios_get_cut_count(self._h), "get_cut_count")

    def _names(self, count, getter, what):
        buf = ctypes.create_string_buffer(NAME_MAX)
        names = []
        for i in range(count):
            self._check(getter(self._h, i, buf, NAME_MAX), what)
            names.append(buf.value.decode())
        return names

    def bus_names(self):
        """Names of all buses, in element-index order."""
        return self._names(self.bus_count, self._lib.helios_get_bus_name, "get_bus_name")

    def branch_names(self):
        """Names of all branches, in element-index order."""
        return self._names(self.branch_count, self._lib.helios_get_branch_name,
                           "get_branch_name")

    def generator_names(self):
        """Names of all generators, in element-index order."""
        return self._names(self.generator_count, self._lib.helios_get_generator_name,
                           "get_generator_name")

    def svc_names(self):
        """Names of all SVCs, in element-index order."""
        return self._names(self.svc_count, self._lib.helios_get_svc_name, "get_svc_name")

    def zone_names(self):
        """Names of all zones, in element-index order."""
        return self._names(self.zone_count, self._lib.helios_get_zone_name, "get_zone_name")

    def cut_names(self):
        """Names of all cuts, in element-index order."""
        return self._names(self.cut_count, self._lib.helios_get_cut_name, "get_cut_name")

    def find_bus(self, name):
        """Element index of the named bus (raises if unknown)."""
        return self._check(self._lib.helios_find_bus(self._h, name.encode("utf-8")),
                           "find_bus(%s)" % name)

    def find_branch(self, name):
        """Element index of the named branch (raises if unknown)."""
        return self._check(self._lib.helios_find_branch(self._h, name.encode("utf-8")),
                           "find_branch(%s)" % name)

    def find_generator(self, name):
        """Element index of the named generator (raises if unknown)."""
        return self._check(self._lib.helios_find_generator(self._h, name.encode("utf-8")),
                           "find_generator(%s)" % name)

    # -- per-element queries ------------------------------------------------------

    def get_bus_voltage(self, bus):
        """Solved voltage of the named bus as ``(v_pu, angle_rad)``."""
        v = ctypes.c_double()
        angle = ctypes.c_double()
        self._check(self._lib.helios_get_bus_voltage(
            self._h, bus.encode("utf-8"), ctypes.byref(v), ctypes.byref(angle)),
            "get_bus_voltage(%s)" % bus)
        return (v.value, angle.value)

    def get_branch_flow(self, branch):
        """From-end flow of the named branch as ``(p_mw, q_mvar)``."""
        p = ctypes.c_double()
        q = ctypes.c_double()
        self._check(self._lib.helios_get_branch_flow(
            self._h, branch.encode("utf-8"), ctypes.byref(p), ctypes.byref(q)),
            "get_branch_flow(%s)" % branch)
        return (p.value, q.value)

    def get_bus_info(self, bus):
        """Full :class:`BusInfo` of the named bus."""
        idx = self.find_bus(bus)
        v = ctypes.c_double()
        angle = ctypes.c_double()
        btype = ctypes.c_int()
        vnom = ctypes.c_double()
        self._check(self._lib.helios_get_bus_info(
            self._h, idx, ctypes.byref(v), ctypes.byref(angle),
            ctypes.byref(btype), ctypes.byref(vnom)), "get_bus_info(%s)" % bus)
        p = ctypes.c_double()
        q = ctypes.c_double()
        self._check(self._lib.helios_get_bus_load(
            self._h, idx, ctypes.byref(p), ctypes.byref(q)), "get_bus_load(%s)" % bus)
        return BusInfo(name=bus, v_pu=v.value, angle_rad=angle.value,
                       bus_type=BusType(btype.value), vnom_kv=vnom.value,
                       p_load_mw=p.value, q_load_mvar=q.value)

    def get_branch_info(self, branch):
        """Full :class:`BranchInfo` of the named branch."""
        idx = self.find_branch(branch)
        frm = ctypes.c_int()
        to = ctypes.c_int()
        status = ctypes.c_int()
        is_trfo = ctypes.c_int()
        snom = ctypes.c_double()
        self._check(self._lib.helios_get_branch_info(
            self._h, idx, ctypes.byref(frm), ctypes.byref(to), ctypes.byref(status),
            ctypes.byref(is_trfo), ctypes.byref(snom)), "get_branch_info(%s)" % branch)
        pf = ctypes.c_double()
        qf = ctypes.c_double()
        pt = ctypes.c_double()
        qt = ctypes.c_double()
        self._check(self._lib.helios_get_branch_flow_by_index(
            self._h, idx, ctypes.byref(pf), ctypes.byref(qf),
            ctypes.byref(pt), ctypes.byref(qt)), "get_branch_flow_by_index(%s)" % branch)
        buses = self.bus_names()
        return BranchInfo(name=branch,
                          from_bus=buses[frm.value] if frm.value >= 0 else "",
                          to_bus=buses[to.value] if to.value >= 0 else "",
                          closed=status.value == 1,
                          is_transformer=bool(is_trfo.value),
                          snom_mva=snom.value,
                          p_from_mw=pf.value, q_from_mvar=qf.value,
                          p_to_mw=pt.value, q_to_mvar=qt.value)

    def get_generator_info(self, generator):
        """Full :class:`GeneratorInfo` of the named generator."""
        idx = self.find_generator(generator)
        bus = ctypes.c_int()
        status = ctypes.c_int()
        p = ctypes.c_double()
        q = ctypes.c_double()
        v = ctypes.c_double()
        self._check(self._lib.helios_get_generator_info(
            self._h, idx, ctypes.byref(bus), ctypes.byref(status), ctypes.byref(p),
            ctypes.byref(q), ctypes.byref(v)), "get_generator_info(%s)" % generator)
        pmin = ctypes.c_double()
        pmax = ctypes.c_double()
        qmin = ctypes.c_double()
        qmax = ctypes.c_double()
        has_p = ctypes.c_int()
        self._check(self._lib.helios_get_generator_limits(
            self._h, idx, ctypes.byref(pmin), ctypes.byref(pmax), ctypes.byref(qmin),
            ctypes.byref(qmax), ctypes.byref(has_p)), "get_generator_limits(%s)" % generator)
        buses = self.bus_names()
        return GeneratorInfo(name=generator,
                             bus=buses[bus.value] if bus.value >= 0 else "",
                             in_service=status.value == 1,
                             p_mw=p.value, q_mvar=q.value, v_setpoint_pu=v.value,
                             p_min_mw=pmin.value, p_max_mw=pmax.value,
                             q_min_mvar=qmin.value, q_max_mvar=qmax.value,
                             has_p_limits=bool(has_p.value))

    def get_cut_flow(self, cut):
        """Signed total ``(p_mw, q_mvar)`` flow through the named cut."""
        idx = self._check(self._lib.helios_find_cut(self._h, cut.encode("utf-8")),
                          "find_cut(%s)" % cut)
        p = ctypes.c_double()
        q = ctypes.c_double()
        self._check(self._lib.helios_get_cut_flow(
            self._h, idx, ctypes.byref(p), ctypes.byref(q)), "get_cut_flow(%s)" % cut)
        return (p.value, q.value)

    # -- bulk NumPy getters ------------------------------------------------------

    def _copy(self, count, fn, arrays, what):
        """Call a bulk copy function, filling freshly allocated NumPy arrays."""
        out = []
        args = []
        for kind in arrays:
            arr = numpy.empty(count, dtype=numpy.float64 if kind == "d" else numpy.int32)
            out.append(arr)
            ptr_type = _c_double_p if kind == "d" else _c_int_p
            args.append(arr.ctypes.data_as(ptr_type))
        self._check(fn(self._h, *args, count), what)
        return tuple(out)

    def get_bus_voltages(self):
        """All bus voltages as ``(v_pu, angle_rad)`` NumPy arrays."""
        return self._copy(self.bus_count, self._lib.helios_copy_bus_voltages,
                          "dd", "copy_bus_voltages")

    def get_bus_loads(self):
        """All bus loads as ``(p_mw, q_mvar)`` NumPy arrays."""
        return self._copy(self.bus_count, self._lib.helios_copy_bus_loads,
                          "dd", "copy_bus_loads")

    def get_branch_flows(self):
        """All branch flows as ``(p_from_mw, q_from_mvar, p_to_mw, q_to_mvar)`` arrays."""
        return self._copy(self.branch_count, self._lib.helios_copy_branch_flows,
                          "dddd", "copy_branch_flows")

    def get_branch_status(self):
        """All branch statuses (1=closed, 0=open) as an int array."""
        return self._copy(self.branch_count, self._lib.helios_copy_branch_status,
                          "i", "copy_branch_status")[0]

    def get_generator_outputs(self):
        """All generator outputs as ``(p_mw, q_mvar, status)`` arrays."""
        return self._copy(self.generator_count, self._lib.helios_copy_generator_outputs,
                          "ddi", "copy_generator_outputs")

    def get_svc_outputs(self):
        """All SVC outputs as ``(q_mvar, status)`` arrays."""
        return self._copy(self.svc_count, self._lib.helios_copy_svc_outputs,
                          "di", "copy_svc_outputs")

    # -- network modification -------------------------------------------------

    def trip_branch(self, name):
        """Open the named branch (settle with :meth:`apply_changes`)."""
        self._check(self._lib.helios_trip_branch(self._h, name.encode("utf-8")),
                    "trip_branch(%s)" % name)

    def connect_branch(self, name):
        """Close the named branch."""
        self._check(self._lib.helios_connect_branch(self._h, name.encode("utf-8")),
                    "connect_branch(%s)" % name)

    def trip_generator(self, name):
        """Take the named generator out of service (slack refused)."""
        self._check(self._lib.helios_trip_generator(self._h, name.encode("utf-8")),
                    "trip_generator(%s)" % name)

    def connect_generator(self, name):
        """Return the named generator to service in PV mode."""
        self._check(self._lib.helios_connect_generator(self._h, name.encode("utf-8")),
                    "connect_generator(%s)" % name)

    def trip_svc(self, name):
        """Take the named SVC out of service."""
        self._check(self._lib.helios_trip_svc(self._h, name.encode("utf-8")),
                    "trip_svc(%s)" % name)

    def connect_svc(self, name):
        """Return the named SVC to service in voltage-control mode."""
        self._check(self._lib.helios_connect_svc(self._h, name.encode("utf-8")),
                    "connect_svc(%s)" % name)

    def set_generator_voltage(self, name, v_pu):
        """Set the voltage setpoint of the named generator."""
        self._check(self._lib.helios_set_generator_voltage(
            self._h, name.encode("utf-8"), float(v_pu)),
            "set_generator_voltage(%s)" % name)

    def set_generator_pq(self, name, q_mvar):
        """Switch the named generator to PQ mode with the given Q output."""
        self._check(self._lib.helios_set_generator_pq(
            self._h, name.encode("utf-8"), float(q_mvar)),
            "set_generator_pq(%s)" % name)

    def change_generation(self, generator, delta_p_mw):
        """Change the named generator's active output by *delta_p_mw* (a delta)."""
        self._check(self._lib.helios_change_generation(
            self._h, generator.encode("utf-8"), float(delta_p_mw)),
            "change_generation(%s)" % generator)

    def change_load(self, bus, delta_p_mw, delta_q_mvar=0.0):
        """Change the named bus load by the given deltas."""
        self._check(self._lib.helios_change_load(
            self._h, bus.encode("utf-8"), float(delta_p_mw), float(delta_q_mvar)),
            "change_load(%s)" % bus)

    def set_load(self, bus, p_mw, q_mvar):
        """Set the named bus load to absolute values (reads the current load
        and applies the difference)."""
        idx = self.find_bus(bus)
        p0 = ctypes.c_double()
        q0 = ctypes.c_double()
        self._check(self._lib.helios_get_bus_load(
            self._h, idx, ctypes.byref(p0), ctypes.byref(q0)), "get_bus_load(%s)" % bus)
        self.change_load(bus, float(p_mw) - p0.value, float(q_mvar) - q0.value)

    def change_shunt(self, bus, delta_b_mvar):
        """Change the named bus shunt susceptance by *delta_b_mvar* (at 1 pu)."""
        self._check(self._lib.helios_change_shunt(
            self._h, bus.encode("utf-8"), float(delta_b_mvar)),
            "change_shunt(%s)" % bus)

    def change_zone_load(self, zone, delta_p_mw, delta_q_mvar=0.0):
        """Distribute a load change over the named zone's buses by participation."""
        self._check(self._lib.helios_change_zone_load(
            self._h, zone.encode("utf-8"), float(delta_p_mw), float(delta_q_mvar)),
            "change_zone_load(%s)" % zone)

    def change_zone_generation(self, zone, delta_p_mw):
        """Distribute a generation change over the named zone by participation."""
        self._check(self._lib.helios_change_zone_generation(
            self._h, zone.encode("utf-8"), float(delta_p_mw)),
            "change_zone_generation(%s)" % zone)

    def apply_changes(self):
        """Settle pending modifications: connectivity check + redispatch +
        re-solve. Returns ``True`` if the re-solve converged. The redispatch
        summary (if any) is available via :attr:`last_error`."""
        ret = self._check(self._lib.helios_apply_changes(self._h), "apply_changes")
        return ret == 0

    # -- file writers ------------------------------------------------------------

    def write_dump(self, path):
        """Write the current network as a re-loadable data file (DF)."""
        self._check(self._lib.helios_write_dump(self._h, str(path).encode("utf-8")),
                    "write_dump(%s)" % path)

    def write_voltrat(self, path):
        """Write the operating-point voltages / LTC data (VT, LFRESV records)."""
        self._check(self._lib.helios_write_voltrat(self._h, str(path).encode("utf-8")),
                    "write_voltrat(%s)" % path)

    def write_matlab(self, path):
        """Write the operating point and Y-bus as a MATLAB script (S)."""
        self._check(self._lib.helios_write_matlab(self._h, str(path).encode("utf-8")),
                    "write_matlab(%s)" % path)

    def write_diagram(self, template_svg, output_svg):
        """Render an SVG one-line diagram from a placeholder template."""
        self._check(self._lib.helios_write_diagram(
            self._h, str(template_svg).encode("utf-8"), str(output_svg).encode("utf-8")),
            "write_diagram(%s)" % template_svg)

    # -- contingency analysis -------------------------------------------------------

    def run_contingencies(self, file=None, branches=False, generators=False,
                          svcs=False, v_min=0.9, v_max=1.1, overload=100.0,
                          dv_max=999.0):
        """Run contingency analysis and return a list of :class:`ContingencyResult`.

        Pass either ``file`` (a Fortran-format contingency file) or one or
        more of ``branches``/``generators``/``svcs`` for automatic N-1 over
        those equipment classes. The base network state is unchanged
        afterwards.

        :param file: contingency file path, or ``None`` for N-1 mode
        :param branches: N-1 mode — include in-service branches
        :param generators: N-1 mode — include in-service generators (except slack)
        :param svcs: N-1 mode — include in-service SVCs
        :param v_min: acceptance band lower voltage, pu
        :param v_max: acceptance band upper voltage, pu
        :param overload: branch loading threshold, % of Snom
        :param dv_max: max allowed voltage change vs base case, pu (999 = off)
        """
        if file is not None:
            count = self._check(self._lib.helios_run_contingencies_file(
                self._h, str(file).encode("utf-8"),
                float(v_min), float(v_max), float(overload), float(dv_max)),
                "run_contingencies_file(%s)" % file)
        else:
            if not (branches or generators or svcs):
                raise HeliosError(
                    "run_contingencies: pass file= or enable at least one of "
                    "branches/generators/svcs")
            count = self._check(self._lib.helios_run_contingencies_n1(
                self._h, int(branches), int(generators), int(svcs),
                float(v_min), float(v_max), float(overload), float(dv_max)),
                "run_contingencies_n1")

        results = []
        name = ctypes.create_string_buffer(TEXT_MAX)
        bmin = ctypes.create_string_buffer(NAME_MAX)
        bmax = ctypes.create_string_buffer(NAME_MAX)
        brload = ctypes.create_string_buffer(NAME_MAX)
        viol = ctypes.create_string_buffer(TEXT_MAX)
        for i in range(count):
            self._check(self._lib.helios_get_contingency_name(
                self._h, i, name, TEXT_MAX), "get_contingency_name")
            converged = ctypes.c_int()
            accepted = ctypes.c_int()
            vmin = ctypes.c_double()
            vmax = ctypes.c_double()
            loading = ctypes.c_double()
            self._check(self._lib.helios_get_contingency_result(
                self._h, i, ctypes.byref(converged), ctypes.byref(accepted),
                ctypes.byref(vmin), ctypes.byref(vmax), ctypes.byref(loading)),
                "get_contingency_result")
            self._check(self._lib.helios_get_contingency_extremes(
                self._h, i, bmin, bmax, brload, NAME_MAX), "get_contingency_extremes")
            violations = []
            nviol = self._check(self._lib.helios_get_contingency_violation_count(self._h, i),
                                "get_contingency_violation_count")
            for j in range(nviol):
                self._check(self._lib.helios_get_contingency_violation(
                    self._h, i, j, viol, TEXT_MAX), "get_contingency_violation")
                violations.append(viol.value.decode())
            results.append(ContingencyResult(
                name=name.value.decode(),
                converged=bool(converged.value),
                accepted=bool(accepted.value),
                min_v_pu=vmin.value, max_v_pu=vmax.value,
                min_v_bus=bmin.value.decode().strip(),
                max_v_bus=bmax.value.decode().strip(),
                max_loading_pct=loading.value,
                max_loading_branch=brload.value.decode().strip(),
                violations=violations))
        return results
