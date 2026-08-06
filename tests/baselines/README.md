# CI baselines

`nordic_baseline.npz` — the Nordic voltage-collapse trajectory, all 1417
columns interpolated onto a 0 : 0.2 : 150 s grid, plus the final simulated
time (163.14 s, the `sim_minmaxvolt` trip instant). Consumed by
`tests/test_nordic.py` via `tools/compare_trj.py compare`.

This file is byte-identical to `stepss-ramses/tests/baselines/nordic_baseline.npz`.
The RAMSES standalone executable and the shared library reach the same
trajectory bit-exactly, so one baseline serves both repositories. Keep them in
step.

## Refresh policy

Regenerate ONLY when a change legitimately alters trajectories — a model or
solver change in RAMSES. In exactly that situation the gate is *supposed* to
fail against the old baseline, and the fix is a deliberate baseline update in
a reviewed pull request, never an automatic pass.

A failing gate blocks the release and files an issue. That is working as
designed.

## Regeneration

    python -m venv /tmp/rebase && /tmp/rebase/bin/pip install ./src
    D=$(mktemp -d); cp tests/data/nordic/* "$D/"
    ( cd "$D" && /tmp/rebase/bin/python - <<'EOF'
    import pyramses
    from pyramses.globals import RAMSESError
    case = pyramses.cfg()
    for f in ('dyn_A.dat', 'volt_rat_A.dat', 'settings1.dat'):
        case.addData(f)
    case.addObs('obs.dat'); case.addDst('short_trip_branch.dst')
    case.addTrj('obs.trj'); case.addOut('output.trace')
    case.addInit('init.trace'); case.addCont('cont.trace'); case.addDisc('disc.trace')
    ram = pyramses.sim()
    try:
        ram.execSim(case)
    except RAMSESError as exc:
        print('expected trip:', exc)
    EOF
    )
    python tools/compare_trj.py make-baseline "$D/obs.trj" \
      -o tests/baselines/nordic_baseline.npz --meta "$(git rev-parse --short HEAD)"

If `obs.dat` or the case files change, the observable count changes: pass the
new `--ncols` (the tool aborts with a time-axis error when it is wrong;
current value 1417).
