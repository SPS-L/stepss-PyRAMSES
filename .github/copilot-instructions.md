# Copilot Instructions for stepss-PyRAMSES

## What This Project Is

PyRAMSES is a Python wrapper around the proprietary RAMSES C/Fortran solver for power system dynamics simulation. The Python code (~2000 lines) acts as a thin ctypes bridge to compiled `ramses.dll` (Windows) or `ramses.so` (Linux) binaries located in `src/pyramses/libs/`. The solver itself is a black box; this repo provides the API layer only.

## Build & Install

```bash
# Install in editable mode (development)
cd src && pip install -e .

# Build for PyPI
cd src && python setup.py sdist bdist_wheel
```

A pytest suite covers the helios power-flow module (`tests/`, run with `pytest tests/` after `pip install ./src pytest`; CI runs it on Linux/Windows/macOS via `.github/workflows/tests.yml`). The RAMSES side has **no test suite or linter configured** — validate RAMSES changes against one of the example repositories:

- Nordic test system: `git@github.com:SPS-L/stepss-IEEE-Nordic-Test-system.git`
- 5-bus test system: `git@github.com:SPS-L/stepss-5-bus-test-system.git`

The `ramses` console entry point (defined in `src/setup.py`) runs simulations from a command file:

```bash
ramses -t cmd.txt
```

## Architecture

Three public classes form the entire API, exposed via `src/pyramses/__init__.py`:

| Class | Module | Role |
|---|---|---|
| `cfg` | `cases.py` | Builds a case: collects input/output file paths, writes RAMSES command file |
| `sim` | `simulator.py` | Loads the RAMSES shared library via ctypes, executes and controls a simulation |
| `extractor` | `extractor.py` | Parses Fortran binary `.trj` trajectory files into Python objects |

Supporting pieces:
- `cur(NamedTuple)` — holds a `(time, value, msg)` timeseries; has a `.plot()` method
- `RAMSESError` / `CustomWarning` — in `globals.py`
- `scripts/exec.py` — thin CLI wrapper used by the `ramses` entry point

### Typical Workflow

```python
import pyramses

# 1. Configure case
case = pyramses.cfg()
case.addData('dyn.dat')          # dynamic model data
case.addData('volt_rat.dat')     # power flow solution (initial conditions)
case.addData('settings.dat')     # solver settings
case.addInit('init.trace')
case.addDst('disturbance.dst')
case.addCont('cont.trace')
case.addDisc('disc.trace')
case.addObs('obs.dat')
case.addTrj('output.trj')

# 2. Run simulation (pause=0.0 means initialize only)
ram = pyramses.sim()
ram.execSim(case, 0.0)

# 3. Add runtime disturbance and continue
ram.addDisturb(10.0, 'TM g7 -0.3 0')
ram.contSim(ram.getInfTime())

# 4. Extract and plot results
ext = pyramses.extractor(case.getTrj())
ext.getSync('g1').S.plot()    # 'S' = rotor speed (pu); attribute names match RAMSES obs keys
```

## Key Conventions

### Component Type Strings
RAMSES components are addressed by ALL_CAPS type strings throughout the API:
`'BUS'`, `'SYNC'`, `'INJ'`, `'BRANCH'`, `'TWOP'`, `'SHUNT'`, `'LOAD'`, `'DCTL'`, `'EXC'`

### File Types
- `.dat` — input data (dynamic models, power flow solution, solver settings)
- `.dst` — disturbance definitions
- `.obs` — observable variable definitions
- `.trj` — Fortran binary trajectory output (parsed by `extractor`)
- `.trace` — text log output (init, continuous, discrete)
- command file (e.g. `cmd.txt`) — ordered list of the above, consumed by RAMSES

### Extractor Attribute Names
Each `get*` method on `extractor` returns an inner object whose attributes are the RAMSES observable short codes — not descriptive Python names. For example:
- `ext.getBus('B1').mag` — voltage magnitude
- `ext.getSync('g1').P` / `.Q` / `.S` / `.A` / `.FW` etc.
- `ext.getBranch('1041-4041').PF` / `.QF` / `.PT` / `.QT` / `.RM` / `.RA`

For model-specific observables (exciters, governors, injectors, two-ports, DCTLs) the attribute names come directly from the user model definition and vary per model type.

### Private vs Public Members
Private attributes use a leading underscore (`_dataset`, `_ramseslib`). All public methods use camelCase (`addData`, `getBusVolt`, `execSim`). The class names themselves are lowercase (`sim`, `cfg`, `extractor`).

Exception: the `pyramses.helios` module (Helios power-flow interface) **deliberately** uses PEP 8 snake_case (`HeliosSession`, `load_file`, `get_bus_voltage`). Do not "fix" it to camelCase, and do not convert the RAMSES classes to snake_case.

### ctypes Interop
`simulator.py` parses `src/pyramses/libs/ramses.h` at import time to set C function signatures. String arguments must be encoded to bytes before passing to ctypes; return strings are decoded from bytes. See existing `sim` methods for the pattern.

### Fortran Binary Parsing
`extractor.py` uses `scipy.io.FortranFile` to read `.trj` files. The file structure is: metadata records (component counts and names), then variable-size timeseries chunks terminated by a 64-bit zero. Results are reshaped into a `(n_timesteps, n_observables + 1)` NumPy array; column 0 is always time. Inner classes (e.g., `_getBusClass`, `_getSyncClass`) compute column offsets into this array via pre-computed `_adexc`/`_adtor`/`_adinj` index lists.

### Multi-instance Simulation
`sim.ramsesCount` is a class-level counter. Multiple `sim` instances can coexist; each gets a unique `_ramsesNum`. Cleanup happens in `__del__`. Do not share a single `sim` instance across threads.

### cfg Initialization from File
`cfg(cmd='path/to/cmd.txt')` can parse an existing RAMSES command file instead of building one programmatically. `cfg.writeCmdFile()` serialises the object back to disk. When called without a filename argument it returns the command text as a string (used internally by `sim.execSim`).

## Dependencies

Core runtime: `numpy`, `scipy`, `matplotlib`, `mkl` (Intel MKL, linked by the RAMSES binary).  
Optional: `gnuplot` system binary for runtime observable plots during simulation.

## License Note

The Python wrapper is Apache 2.0. The RAMSES, PFC, and CODEGEN binaries in `libs/` are **proprietary** (check https://stepss.sps-lab.org/getting-started/license/) and free only for non-commercial use with a cap of 1000 buses and 2 CPU cores. Do not redistribute or modify those binaries.
