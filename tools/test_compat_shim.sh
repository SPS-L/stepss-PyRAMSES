#!/usr/bin/env bash
# Verify the pyramses compatibility shim forwards to stepss.
#
# Builds a throwaway venv, installs the real package and then the shim, and
# asserts that the import shapes real user code uses still work:
#   import pyramses
#   pyramses.cfg / pyramses.sim
#   pyramses.__ramses_version__ and the other documented attributes
#   from pyramses.globals import RAMSESError   <- needs sys.modules aliasing
#
# The attribute check is not decoration. Shim 3.58.1 shipped forwarding only
# `stepss.__all__`, so every documented package-level attribute raised
# AttributeError, and nothing here caught it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT

python -m venv "$TMPD/venv"
VPY="$TMPD/venv/bin/python"
[ -x "$VPY" ] || VPY="$TMPD/venv/Scripts/python.exe"

"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet "$ROOT/src"
# --no-deps: resolving the shim's stepss pin would pull the published wheel
# from PyPI, and the local build installed above is the thing under test.
"$VPY" -m pip install --quiet --no-deps "$ROOT/compat/pyramses"

"$VPY" - <<'PY'
import warnings

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    import pyramses

assert any(issubclass(w.category, DeprecationWarning) for w in caught), \
    "FAIL: importing pyramses raised no DeprecationWarning"

assert callable(pyramses.cfg), "FAIL: pyramses.cfg missing"
assert callable(pyramses.sim), "FAIL: pyramses.sim missing"

from pyramses.globals import RAMSESError
from pyramses.helios import HeliosSession
assert issubclass(RAMSESError, Exception)
assert HeliosSession is not None

import stepss
assert pyramses.cfg is stepss.cfg, "FAIL: shim is not forwarding to stepss"

# The package-level attributes documented at
# https://stepss.sps-lab.org/python/overview/ . `from stepss import *` binds
# none of these, so they only exist if the shim mirrors the module.
for _attr in ('__version__', '__ramses_version__', '__helios_version__',
              '__url__', '__runTimeObs__'):
    assert hasattr(pyramses, _attr), f"FAIL: pyramses.{_attr} missing"
    assert getattr(pyramses, _attr) == getattr(stepss, _attr), \
        f"FAIL: pyramses.{_attr} does not match stepss.{_attr}"

# `ramses = pyramses.scripts.exec:run` was the old console script.
from pyramses.scripts.exec import run
assert callable(run), "FAIL: pyramses.scripts.exec.run missing"

print("PASS: shim forwards to stepss")
PY

echo "PASS: all compat shim checks"
