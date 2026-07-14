/* SPDX-License-Identifier: LGPL-3.0-or-later
 * Copyright (c) 2026 Sustainable Power Systems Laboratory (https://sps-lab.org/)
 * Part of STEPSS-Helios: Modern C++ Power Flow Calculator
 */

#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#ifdef _WIN32
  #ifdef HELIOS_API_EXPORTS
    #define HELIOS_API __declspec(dllexport)
  #else
    #define HELIOS_API __declspec(dllimport)
  #endif
#else
  #define HELIOS_API __attribute__((visibility("default")))
#endif

typedef void* HeliosHandle;

/* Maximum buffer size (including NUL) sufficient for any element name
 * returned by the helios_get_*_name functions. */
#define HELIOS_NAME_MAX 64

/* Maximum buffer size (including NUL) sufficient for message-sized
 * strings such as contingency names and violation descriptions. */
#define HELIOS_TEXT_MAX 256

/* Status codes returned by the API. Success is HELIOS_OK (0) or, where
 * documented, a non-negative count. Any negative value is an error and
 * sets the per-handle error string (see helios_get_last_error). */
typedef enum HeliosStatus {
    HELIOS_OK                   =  0,
    HELIOS_NOT_CONVERGED        =  1,  /* solve ran but did not converge */
    HELIOS_ERROR                = -1,  /* unspecified error */
    HELIOS_ERR_NULL_ARG         = -2,  /* NULL handle or required pointer */
    HELIOS_ERR_NOT_FOUND        = -3,  /* name lookup failed */
    HELIOS_ERR_INDEX            = -4,  /* index or option id out of range */
    HELIOS_ERR_IO               = -5,  /* file could not be opened/written */
    HELIOS_ERR_PARSE            = -6,  /* input file parse error */
    HELIOS_ERR_NO_NETWORK       = -7,  /* called before helios_load_file */
    HELIOS_ERR_BUFFER_TOO_SMALL = -8   /* caller buffer/array too short */
} HeliosStatus;

/* ---- Lifecycle ---- */

HELIOS_API HeliosHandle helios_create(void);
HELIOS_API void         helios_destroy(HeliosHandle h);

/* ---- Library information ---- */

/* API version of the loaded library. Any output pointer may be NULL. */
HELIOS_API void         helios_get_api_version(int* major, int* minor, int* patch);
/* Static, never-freed description string: version, compiler, platform. */
HELIOS_API const char*  helios_get_build_info(void);

/* ---- Error reporting ----
 * Every failing call stores a human-readable message on the handle;
 * successful calls leave it untouched. The returned pointer is owned by
 * the handle and valid until the next API call on the same handle. */

HELIOS_API const char*  helios_get_last_error(HeliosHandle h);  /* "" if none */
HELIOS_API void         helios_clear_last_error(HeliosHandle h);

/* ---- Load and solve ---- */

HELIOS_API int          helios_load_file(HeliosHandle h, const char* filepath);
HELIOS_API int          helios_solve(HeliosHandle h);
HELIOS_API int          helios_get_convergence_status(HeliosHandle h);

/* ---- Solver options ----
 * Options map 1:1 onto the solver parameters read from $PARAM records.
 * helios_load_file overwrites them from the data file, so set options
 * AFTER load and BEFORE solve. Integer-valued options (MAX_ITER, PLIM)
 * are passed as double and truncated. There is no flat-start option:
 * the initial state comes from the data file; use helios_reset() to
 * return to it. */

typedef enum HeliosOption {
    HELIOS_OPT_SBASE = 0,   /* system base, MVA */
    HELIOS_OPT_TOLAC,       /* active power tolerance, MW ($TOLAC) */
    HELIOS_OPT_TOLREAC,     /* reactive power tolerance, Mvar ($TOLREAC) */
    HELIOS_OPT_MAX_ITER,    /* maximum iterations ($NBITMA) */
    HELIOS_OPT_TH_BLOCK,    /* tap-blocking mismatch threshold, MVA ($MISBLOC) */
    HELIOS_OPT_TH_ADJ,      /* tap-adjustment mismatch threshold, MVA ($MISADJ) */
    HELIOS_OPT_TH_QLIM,     /* Q-limit switching mismatch threshold, MVA ($MISQLIM) */
    HELIOS_OPT_PLIM,        /* 0/1 slack P-limit relaxation ($PLIM) */
    HELIOS_OPT_DIVDET       /* divergence detection threshold ($DIVDET) */
} HeliosOption;

HELIOS_API int          helios_set_option(HeliosHandle h, int option, double value);
HELIOS_API int          helios_get_option(HeliosHandle h, int option, double* value);

/* ---- Solve metadata (valid after helios_solve) ---- */

/* Iterations used by the last solve, or negative error code. */
HELIOS_API int          helios_get_iteration_count(HeliosHandle h);
/* Largest remaining mismatches of the last solve. NULL pointers skipped. */
HELIOS_API int          helios_get_max_mismatch(HeliosHandle h, double* mw, double* mvar);
/* Detailed solver status: 0=NOT_RUN 1=CONVERGED 2=DIVERGED 3=MAX_ITERATIONS
 * 4=SINGULAR, or negative error code. */
HELIOS_API int          helios_get_solver_status(HeliosHandle h);

/* ---- Element counts ---- */

HELIOS_API int          helios_get_bus_count(HeliosHandle h);
HELIOS_API int          helios_get_branch_count(HeliosHandle h);
HELIOS_API int          helios_get_generator_count(HeliosHandle h);
HELIOS_API int          helios_get_svc_count(HeliosHandle h);
HELIOS_API int          helios_get_zone_count(HeliosHandle h);
HELIOS_API int          helios_get_cut_count(HeliosHandle h);

/* ---- Names and lookup ----
 * Name getters copy a NUL-terminated string into the caller buffer
 * (HELIOS_NAME_MAX bytes always suffice). Find functions return the
 * element index (>= 0) or HELIOS_ERR_NOT_FOUND. Indices are stable
 * until the next helios_load_file. */

HELIOS_API int          helios_get_bus_name(HeliosHandle h, int index, char* buf, int buf_size);
HELIOS_API int          helios_get_branch_name(HeliosHandle h, int index, char* buf, int buf_size);
HELIOS_API int          helios_get_generator_name(HeliosHandle h, int index, char* buf, int buf_size);
HELIOS_API int          helios_get_svc_name(HeliosHandle h, int index, char* buf, int buf_size);
HELIOS_API int          helios_get_zone_name(HeliosHandle h, int index, char* buf, int buf_size);
HELIOS_API int          helios_get_cut_name(HeliosHandle h, int index, char* buf, int buf_size);

HELIOS_API int          helios_find_bus(HeliosHandle h, const char* name);
HELIOS_API int          helios_find_branch(HeliosHandle h, const char* name);
HELIOS_API int          helios_find_generator(HeliosHandle h, const char* name);
HELIOS_API int          helios_find_svc(HeliosHandle h, const char* name);
HELIOS_API int          helios_find_zone(HeliosHandle h, const char* name);
HELIOS_API int          helios_find_cut(HeliosHandle h, const char* name);

/* ---- Indexed getters ----
 * All output pointers may be NULL to skip that field. */

/* bus_type: 0=PQ 1=PV 2=SLACK 3=ISOLATED */
HELIOS_API int          helios_get_bus_info(HeliosHandle h, int index, double* v_pu,
                                            double* angle_rad, int* bus_type, double* vnom_kv);
HELIOS_API int          helios_get_bus_load(HeliosHandle h, int index, double* p_mw, double* q_mvar);
/* b_mvar: voltage-dependent shunt at 1 pu; q_mvar: fixed reactive shunt injection */
HELIOS_API int          helios_get_bus_shunt(HeliosHandle h, int index, double* b_mvar, double* q_mvar);
/* Zone index of a bus (>= 0), HELIOS_ERR_NOT_FOUND if the bus has no zone. */
HELIOS_API int          helios_get_bus_zone(HeliosHandle h, int bus_index);

/* branch type: 1=line -2=fixed trfo -3=LTC 2=switch 3=nrtp; status: 1=closed 0=open */
HELIOS_API int          helios_get_branch_info(HeliosHandle h, int index, int* from_bus,
                                               int* to_bus, int* status, int* is_transformer,
                                               double* snom_mva);
HELIOS_API int          helios_get_branch_flow_by_index(HeliosHandle h, int index,
                                               double* p_from_mw, double* q_from_mvar,
                                               double* p_to_mw, double* q_to_mvar);

HELIOS_API int          helios_get_generator_info(HeliosHandle h, int index, int* bus_index,
                                               int* status, double* p_mw, double* q_mvar,
                                               double* v_setpoint_pu);
HELIOS_API int          helios_get_generator_limits(HeliosHandle h, int index,
                                               double* p_min_mw, double* p_max_mw,
                                               double* q_min_mvar, double* q_max_mvar,
                                               int* has_p_limits);

/* control: -4=voltage control -1=fixed Q 4=at Bmax 5=at Bmin */
HELIOS_API int          helios_get_svc_info(HeliosHandle h, int index, int* bus_index,
                                               int* status, double* q_mvar,
                                               double* v_setpoint_pu, int* control);

/* Signed total P/Q flow through a cut (sum over member branches). */
HELIOS_API int          helios_get_cut_flow(HeliosHandle h, int index, double* p_mw, double* q_mvar);

/* ---- Bulk copy (vectorized access) ----
 * Fill caller-allocated arrays indexed like the element vectors: query
 * the matching *_count first and pass array_len >= count. Any array
 * pointer may be NULL to skip it. Returns HELIOS_ERR_BUFFER_TOO_SMALL
 * if array_len < count. */

HELIOS_API int          helios_copy_bus_voltages(HeliosHandle h, double* v_pu,
                                               double* angle_rad, int array_len);
HELIOS_API int          helios_copy_bus_loads(HeliosHandle h, double* p_mw,
                                               double* q_mvar, int array_len);
HELIOS_API int          helios_copy_branch_flows(HeliosHandle h, double* p_from_mw,
                                               double* q_from_mvar, double* p_to_mw,
                                               double* q_to_mvar, int array_len);
HELIOS_API int          helios_copy_branch_status(HeliosHandle h, int* status, int array_len);
HELIOS_API int          helios_copy_generator_outputs(HeliosHandle h, double* p_mw,
                                               double* q_mvar, int* status, int array_len);
HELIOS_API int          helios_copy_svc_outputs(HeliosHandle h, double* q_mvar,
                                               int* status, int array_len);

/* ---- Network modification ----
 * Modifications accumulate an active-power imbalance that is settled by
 * helios_apply_changes (connectivity check + redispatch onto remaining
 * generators + re-solve, matching the Fortran modify workflow). Calling
 * helios_solve directly instead re-solves WITHOUT redispatch.
 * change_* functions apply DELTAS (increments), not absolute values.
 * Some calls record informational warnings (e.g. "active power limited
 * to maximum") in the last-error string while still returning HELIOS_OK;
 * the return code is authoritative. */

HELIOS_API int          helios_trip_branch(HeliosHandle h, const char* name);
HELIOS_API int          helios_connect_branch(HeliosHandle h, const char* name);
HELIOS_API int          helios_trip_generator(HeliosHandle h, const char* name);
HELIOS_API int          helios_connect_generator(HeliosHandle h, const char* name);
HELIOS_API int          helios_trip_svc(HeliosHandle h, const char* name);
HELIOS_API int          helios_connect_svc(HeliosHandle h, const char* name);

HELIOS_API int          helios_set_generator_voltage(HeliosHandle h, const char* name, double v_pu);
/* Switch a generator to PQ mode with the given reactive output. */
HELIOS_API int          helios_set_generator_pq(HeliosHandle h, const char* name, double q_mvar);
HELIOS_API int          helios_change_generation(HeliosHandle h, const char* gen_name,
                                                 double delta_p_mw);
HELIOS_API int          helios_change_load(HeliosHandle h, const char* bus_name,
                                           double delta_p_mw, double delta_q_mvar);
HELIOS_API int          helios_change_shunt(HeliosHandle h, const char* bus_name,
                                            double delta_b_mvar);
HELIOS_API int          helios_change_zone_load(HeliosHandle h, const char* zone,
                                                double delta_p_mw, double delta_q_mvar);
HELIOS_API int          helios_change_zone_generation(HeliosHandle h, const char* zone,
                                                      double delta_p_mw);

/* Connectivity check + redispatch + re-solve. Returns HELIOS_OK,
 * HELIOS_NOT_CONVERGED, or a negative error. Solve metadata getters
 * reflect this solve afterwards; the redispatch summary (if any) is
 * placed in the last-error string as information. */
HELIOS_API int          helios_apply_changes(HeliosHandle h);

/* Restore the state saved right after helios_load_file and discard any
 * pending (un-applied) modification imbalance. */
HELIOS_API int          helios_reset(HeliosHandle h);

/* ---- File writers ----
 * All writers serialize the CURRENT network state (call after solve).
 * Existing files are overwritten. */

/* Re-serialize the network as a data file (DF command). */
HELIOS_API int          helios_write_dump(HeliosHandle h, const char* filepath);
/* Write the operating-point voltages / LTC data (VT command, LFRESV records). */
HELIOS_API int          helios_write_voltrat(HeliosHandle h, const char* filepath);
/* Write the operating point and Y-bus as a MATLAB script (S command). */
HELIOS_API int          helios_write_matlab(HeliosHandle h, const char* filepath);
/* Render an SVG one-line diagram by substituting %X placeholders in a template. */
HELIOS_API int          helios_write_diagram(HeliosHandle h, const char* template_svg,
                                             const char* output_svg);

/* ---- Contingency analysis ----
 * Runners execute each contingency (snapshot -> apply -> redispatch ->
 * solve -> check -> restore); the base network state is unchanged
 * afterwards. Results are stored on the handle until the next run or
 * load. Runners return the number of contingencies executed (>= 0) or
 * a negative error; parser/run warnings are placed in the last-error
 * string as information. Limits: v_min_pu/v_max_pu (voltage band),
 * overload_pct (branch loading threshold in % of Snom), dv_max_pu
 * (max allowed voltage change vs base case; pass 999 to disable). */

HELIOS_API int          helios_run_contingencies_file(HeliosHandle h, const char* contingency_file,
                                             double v_min_pu, double v_max_pu,
                                             double overload_pct, double dv_max_pu);
/* Auto N-1 over the selected equipment classes (non-zero = include). */
HELIOS_API int          helios_run_contingencies_n1(HeliosHandle h,
                                             int include_branches, int include_generators,
                                             int include_svcs,
                                             double v_min_pu, double v_max_pu,
                                             double overload_pct, double dv_max_pu);

HELIOS_API int          helios_get_contingency_count(HeliosHandle h);
/* Contingency names and violation strings are free text: pass buffers of
 * HELIOS_TEXT_MAX bytes. */
HELIOS_API int          helios_get_contingency_name(HeliosHandle h, int index,
                                             char* buf, int buf_size);
/* converged/accepted: 0/1. Any output pointer may be NULL. */
HELIOS_API int          helios_get_contingency_result(HeliosHandle h, int index,
                                             int* converged, int* accepted,
                                             double* min_v_pu, double* max_v_pu,
                                             double* max_loading_pct);
/* Buses/branch where the extremes occurred; each buffer receives up to
 * buf_size bytes (HELIOS_NAME_MAX suffices). NULL buffers are skipped. */
HELIOS_API int          helios_get_contingency_extremes(HeliosHandle h, int index,
                                             char* min_v_bus, char* max_v_bus,
                                             char* max_loading_branch, int buf_size);
HELIOS_API int          helios_get_contingency_violation_count(HeliosHandle h, int index);
HELIOS_API int          helios_get_contingency_violation(HeliosHandle h, int index,
                                             int viol_index, char* buf, int buf_size);

/* ---- Named queries ---- */

HELIOS_API int          helios_get_bus_voltage(HeliosHandle h, const char* bus_name,
                                               double* v_pu, double* angle_rad);
HELIOS_API int          helios_get_branch_flow(HeliosHandle h, const char* branch_name,
                                               double* p_mw, double* q_mvar);
/* Returns a newline-separated machine-readable summary of all buses.
 * Format: "bus <name> V=<v_pu> angle=<angle_rad> type=<PQ|PV|SLACK|ISOLATED> vnom_kv=<kv>"
 * For formatted display tables, use the TUI or PlainMenu interfaces. */
HELIOS_API const char*  helios_get_output_text(HeliosHandle h);

#ifdef __cplusplus
}
#endif
