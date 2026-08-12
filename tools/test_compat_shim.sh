#!/usr/bin/env bash
# Verify the retired `pyramses` distribution refuses to install and says why.
#
# The tombstone works only as an sdist: pip runs setup.py to prepare metadata,
# setup.py raises, and the install stops with a message naming stepss. A wheel
# would install by unpacking and never run that code, so this script also
# asserts the build produces no wheel. That assertion is the important one:
# a wheel on PyPI would silently restore a working install of the retired name.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT

python -m venv "$TMPD/venv"
VPY="$TMPD/venv/bin/python"
[ -x "$VPY" ] || VPY="$TMPD/venv/Scripts/python.exe"

"$VPY" -m pip install --quiet --upgrade pip build

# Build exactly what the publish workflow builds.
PYRAMSES_BUILD_TOMBSTONE=1 "$VPY" -m build --sdist --outdir "$TMPD/dist" "$ROOT/compat/pyramses"

if compgen -G "$TMPD/dist/*.whl" >/dev/null; then
    echo "FAIL: a wheel was built; a wheel installs without running setup.py" >&2
    exit 1
fi
echo "ok: sdist only, no wheel"

SDIST="$(echo "$TMPD"/dist/pyramses-*.tar.gz)"
[ -f "$SDIST" ] || { echo "FAIL: no sdist built" >&2; exit 1; }

# The refusal. Without the env var, installing must fail and name stepss.
# Build isolation stays ON: that is the path a real `pip install pyramses`
# takes, and it is what runs setup.py to prepare metadata.
set +e
OUT="$("$VPY" -m pip install --no-cache-dir "$SDIST" 2>&1)"
RC=$?
set -e

[ "$RC" -ne 0 ] || { echo "FAIL: installing the tombstone succeeded" >&2; exit 1; }
echo "ok: install refused (exit $RC)"

grep -q "has been decommissioned" <<<"$OUT" || {
    echo "FAIL: refusal did not explain itself" >&2; echo "$OUT" >&2; exit 1; }
grep -q "pip install stepss" <<<"$OUT" || {
    echo "FAIL: refusal did not name the replacement" >&2; echo "$OUT" >&2; exit 1; }
echo "ok: refusal names stepss"

"$VPY" -c "import pyramses" 2>/dev/null && {
    echo "FAIL: pyramses is importable in the test venv" >&2; exit 1; }
echo "ok: pyramses not importable"

echo "PASS: all pyramses tombstone checks"
