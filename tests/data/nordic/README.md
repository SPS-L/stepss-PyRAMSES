# Nordic voltage-collapse regression case

Vendored from `SPS-L/stepss-ramses`, `examples/Nordic/`. Apache-2.0; the
licence travels with the files as `LICENSE`.

This is the **CI variant**: `dyn_A.dat` + `volt_rat_A.dat` +
`short_trip_branch.dst`. It is deliberately the same variant, with the same
`settings1.dat` and `obs.dat`, that the stepss-ramses release gate runs, so a
single baseline serves both repositories.

Do not edit these files. Changing them changes the observable count and
invalidates `tests/baselines/nordic_baseline.npz`; refresh both together and
say why in the commit message.

The case is also published as stepss teaching material for the EEN452
course at Cyprus University of Technology.
