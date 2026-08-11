#!/usr/bin/env bash
# Verify the pyramses compatibility shim forwards to stepss.
#
# Builds a throwaway venv, installs the real package and then the shim, and
# asserts that the three import shapes real user code uses still work:
#   import pyramses
#   pyramses.cfg / pyramses.sim
#   from pyramses.globals import RAMSESError   <- needs sys.modules aliasing
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT

python -m venv "$TMPD/venv"
VPY="$TMPD/venv/bin/python"
[ -x "$VPY" ] || VPY="$TMPD/venv/Scripts/python.exe"

"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet "$ROOT/src"
# --no-deps: the shim's stepss>=3.58.1 pin cannot resolve until stepss is on
# PyPI, and the local build installed above is the thing under test anyway.
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
print("PASS: shim forwards to stepss")
PY

echo "PASS: all compat shim checks"
