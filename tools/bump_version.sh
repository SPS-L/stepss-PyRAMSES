#!/usr/bin/env bash
# Bump the pyramses patch version and record the bundled upstream versions.
#
#   bump_version.sh <ramses|helios> <upstream-tag>
#
# Bumps the patch component of __version__ in src/pyramses/__init__.py, then
# rewrites src/pyramses/_bundled.py so the named upstream carries <upstream-tag>
# and the other keeps whatever it already had. Prints the new pyramses version
# (no 'v' prefix) on stdout; the release workflow reads that.
#
# PYRAMSES_ROOT overrides the repository root, for tests.
set -u

if [ $# -ne 2 ]; then
    echo "usage: $0 <ramses|helios> <upstream-tag>" >&2
    exit 2
fi
SOURCE="$1"
TAG="$2"
case "$SOURCE" in
    ramses|helios) ;;
    *) echo "usage: $0 <ramses|helios> <upstream-tag>" >&2; exit 2 ;;
esac

ROOT="${PYRAMSES_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
INIT="$ROOT/src/pyramses/__init__.py"
BUNDLED="$ROOT/src/pyramses/_bundled.py"

[ -f "$INIT" ] || { echo "FAIL: not found: $INIT" >&2; exit 1; }

read_assign() {  # read_assign <file> <name>
    [ -f "$1" ] || return 0
    sed -n "s/^$2[[:space:]]*=[[:space:]]*[\"']\([^\"']*\)[\"'].*/\1/p" "$1" | head -n1
}

CUR="$(read_assign "$INIT" __version__)"
[ -n "$CUR" ] || { echo "FAIL: __version__ not found in $INIT" >&2; exit 1; }

# Split on dots and bump the last component numerically. Guard against a
# non-numeric patch so a malformed version fails loudly instead of producing
# a nonsense tag that then gets published.
MAJOR="${CUR%%.*}"
REST="${CUR#*.}"
MINOR="${REST%%.*}"
PATCH="${REST#*.}"
case "$MAJOR$MINOR$PATCH" in
    *[!0-9]*) echo "FAIL: __version__ '$CUR' is not major.minor.patch with numeric parts" >&2; exit 1 ;;
esac
NEW="$MAJOR.$MINOR.$((PATCH + 1))"

RAMSES_VER="$(read_assign "$BUNDLED" RAMSES_VERSION)"
HELIOS_VER="$(read_assign "$BUNDLED" HELIOS_VERSION)"
if [ "$SOURCE" = "ramses" ]; then
    RAMSES_VER="$TAG"
else
    HELIOS_VER="$TAG"
fi
[ -n "$RAMSES_VER" ] || { echo "FAIL: no RAMSES_VERSION to carry forward" >&2; exit 1; }
[ -n "$HELIOS_VER" ] || { echo "FAIL: no HELIOS_VERSION to carry forward" >&2; exit 1; }

# Rewrite __version__ in place. Anchored to the start of the line so a
# docstring mentioning __version__ cannot be hit.
python3 - "$INIT" "$CUR" "$NEW" <<'PYEOF'
import re, sys
path, cur, new = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(path, encoding='utf-8').read()
out, n = re.subn(r"(?m)^__version__\s*=\s*['\"]%s['\"]" % re.escape(cur),
                 "__version__ = '%s'" % new, src)
if n != 1:
    sys.exit("FAIL: expected exactly one __version__ assignment, found %d" % n)
open(path, 'w', encoding='utf-8').write(out)
PYEOF

cat > "$BUNDLED" <<EOF
"""Upstream component versions bundled in this pyramses release.

Written by tools/bump_version.sh, which the release automation invokes when
stepss-ramses or stepss-helios publishes. Do not edit by hand: a manual edit
is silently overwritten by the next sync.

Only the upstream that triggered a sync changes; the other is carried forward.
"""

RAMSES_VERSION = "$RAMSES_VER"
HELIOS_VERSION = "$HELIOS_VER"
EOF

echo "$NEW"
