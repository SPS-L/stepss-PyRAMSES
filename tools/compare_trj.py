#!/usr/bin/env python3
"""Baseline/compare tool for RAMSES .trj trajectory files (CI regression gate).

A .trj written by src/observ.f90 is a sequence of Fortran unformatted
sequential records (4-byte length markers). The bulk of the file is one
large float64 record: a row-major (nsteps x ncols) matrix whose first
column is simulation time in seconds; the other columns are the
observables selected in obs.dat. Small header records (names/counts) and
the 8-byte footer are ignored: this tool always operates on the largest
record in the file.

make-baseline  sample every column onto a fixed time grid (linear
               interpolation) and save as compressed .npz together with
               the final simulated time (the protection-trip instant).
compare        interpolate a candidate .trj onto the stored grid and
               check |a-b| <= atol + rtol*|b| elementwise, plus the
               final-time window.

Exit codes: 0 pass, 1 fail (tolerance or structure).
"""
import argparse
import sys

import numpy as np

DEFAULT_RTOL = 1e-4
DEFAULT_ATOL = 1e-6
DEFAULT_TRIP_TOL = 1.0  # s


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def read_data_record(path):
    """Return the largest Fortran record in the file as a float64 array."""
    with open(path, "rb") as fh:
        buf = fh.read()
    off, n = 0, len(buf)
    best_off, best_len = -1, -1
    while off + 4 <= n:
        m = int(np.frombuffer(buf, np.uint32, 1, off)[0])
        off += 4
        if off + m + 4 > n:
            fail(f"{path}: truncated record at offset {off - 4}")
        tail = int(np.frombuffer(buf, np.uint32, 1, off + m)[0])
        if tail != m:
            fail(f"{path}: corrupt record markers at offset {off - 4}")
        if m > best_len:
            best_off, best_len = off, m
        off += m + 4
    if best_len <= 0 or best_len % 8:
        fail(f"{path}: no float64 data record found")
    return np.frombuffer(buf, np.float64, best_len // 8, best_off)


def to_grid(vals, ncols, tmax, dt, path):
    """Reshape to (nsteps, ncols), validate the time column, drop repeated
    time instants (discrete events), and interpolate onto 0:dt:tmax."""
    if vals.size % ncols:
        fail(f"{path}: {vals.size} values not divisible by ncols={ncols}")
    M = vals.reshape(-1, ncols)
    t = M[:, 0]
    if t[0] != 0.0 or np.max(np.abs(np.diff(t))) > 1.0:
        fail(f"{path}: column 0 does not look like a time axis (wrong --ncols?)")
    keep = np.concatenate(([True], np.diff(t) > 0))
    M, t = M[keep], t[keep]
    final_time = float(t[-1])
    if final_time < tmax:
        fail(f"{path}: trajectory ends at {final_time:.3f} s, before tmax={tmax:g} s")
    grid = np.arange(0.0, tmax + dt / 2, dt)
    out = np.empty((grid.size, ncols))
    out[:, 0] = grid
    for j in range(1, ncols):
        out[:, j] = np.interp(grid, t, M[:, j])
    return out, final_time


def cmd_make_baseline(args):
    vals = read_data_record(args.trj)
    M, final_time = to_grid(vals, args.ncols, args.tmax, args.dt, args.trj)
    np.savez_compressed(args.out, M=M, ncols=args.ncols, tmax=args.tmax,
                        dt=args.dt, final_time=final_time, meta=args.meta)
    print(f"baseline: {M.shape[0]} samples x {args.ncols} cols, "
          f"final time {final_time:.4f} s -> {args.out}")


def cmd_compare(args):
    b = np.load(args.baseline)
    ncols, tmax, dt = int(b["ncols"]), float(b["tmax"]), float(b["dt"])
    base, base_final = b["M"], float(b["final_time"])
    vals = read_data_record(args.trj)
    M, final_time = to_grid(vals, ncols, tmax, dt, args.trj)
    diff = np.abs(M[:, 1:] - base[:, 1:])
    excess = diff - (args.atol + args.rtol * np.abs(base[:, 1:]))
    max_abs = float(diff.max())
    i, j = np.unravel_index(np.argmax(excess), excess.shape)
    print(f"samples: {M.shape[0]}  cols: {ncols}  max |diff|: {max_abs:.6e}  "
          f"(worst margin at t={base[i, 0]:.2f} s, col {j + 1})")
    print(f"final time: {final_time:.4f} s  (baseline {base_final:.4f} s)")
    ok = True
    if float(excess.max()) > 0.0:
        print(f"FAIL: trajectory outside tolerance (rtol={args.rtol:g}, atol={args.atol:g})")
        ok = False
    if abs(final_time - base_final) > args.trip_tol:
        print(f"FAIL: trip time deviates more than {args.trip_tol:g} s from baseline")
        ok = False
    if ok:
        print(f"PASS (rtol={args.rtol:g}, atol={args.atol:g}, trip-tol={args.trip_tol:g} s)")
    sys.exit(0 if ok else 1)


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    mb = sub.add_parser("make-baseline", help="sample a .trj onto a grid, save .npz")
    mb.add_argument("trj")
    mb.add_argument("-o", "--out", required=True)
    mb.add_argument("--ncols", type=int, default=1417,
                    help="columns incl. time (Nordic CI case: 1417)")
    mb.add_argument("--tmax", type=float, default=150.0)
    mb.add_argument("--dt", type=float, default=0.2)
    mb.add_argument("--meta", default="")
    mb.set_defaults(func=cmd_make_baseline)

    cp = sub.add_parser("compare", help="compare a .trj against a baseline .npz")
    cp.add_argument("trj")
    cp.add_argument("baseline")
    cp.add_argument("--rtol", type=float, default=DEFAULT_RTOL)
    cp.add_argument("--atol", type=float, default=DEFAULT_ATOL)
    cp.add_argument("--trip-tol", type=float, default=DEFAULT_TRIP_TOL)
    cp.set_defaults(func=cmd_compare)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
