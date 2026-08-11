#!/usr/bin/env bash
# Compute the next pyramses version and record the bundled upstream versions.
#
#   bump_version.sh ramses <upstream-tag>
#   bump_version.sh helios <upstream-tag>
#   bump_version.sh manual
#
# The version is <ramses-version>[.<counter>], so the leading components always
# name the RAMSES shared library bundled in the wheel:
#
#   ramses v3.57 published        -> 3.57      (first release on this base)
#   helios released after it      -> 3.57.1
#   python-only release after that-> 3.57.2
#   ramses v3.58 published        -> 3.58      (sequence restarts)
#
# Like stepss-java-ui's tools/ci next_version, the counter is derived from the
# tags that already exist rather than from a stored number, so there is nothing
# to drift out of step: a RAMSES bump restarts the sequence on its own, because
# no tag for the new base exists yet. Re-running a failed release recomputes the
# same value, and a tag created by hand is taken into account for free.
#
# Rewrites src/pyramses/_bundled.py so the named upstream carries <upstream-tag>
# and the other keeps whatever it had; `manual` changes neither. Prints the new
# pyramses version (no 'v' prefix) on stdout; the release workflow reads that.
#
# PYRAMSES_ROOT overrides the repository root, and PYRAMSES_TAGS overrides the
# tag list (newline-separated), both for tests.
set -u

usage() {
    echo "usage: $0 <ramses|helios> <upstream-tag>" >&2
    echo "       $0 manual" >&2
    exit 2
}

[ $# -ge 1 ] || usage
SOURCE="$1"
case "$SOURCE" in
    ramses|helios) [ $# -eq 2 ] || usage; TAG="$2" ;;
    manual)        [ $# -eq 1 ] || usage; TAG="" ;;
    *)             usage ;;
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

RAMSES_VER="$(read_assign "$BUNDLED" RAMSES_VERSION)"
HELIOS_VER="$(read_assign "$BUNDLED" HELIOS_VERSION)"
if [ "$SOURCE" = "ramses" ]; then
    RAMSES_VER="$TAG"
elif [ "$SOURCE" = "helios" ]; then
    HELIOS_VER="$TAG"
fi
[ -n "$RAMSES_VER" ] || { echo "FAIL: no RAMSES_VERSION to carry forward" >&2; exit 1; }
[ -n "$HELIOS_VER" ] || { echo "FAIL: no HELIOS_VERSION to carry forward" >&2; exit 1; }

# The base is whatever RAMSES this wheel will bundle, after the update above.
if [ -n "${PYRAMSES_TAGS+x}" ]; then
    TAGS="$PYRAMSES_TAGS"
else
    TAGS="$(git -C "$ROOT" tag --list 2>/dev/null)" || TAGS=""
fi

NEW="$(RAMSES_VER="$RAMSES_VER" TAGS="$TAGS" python3 - <<'PYEOF'
import os, re, sys

base = os.environ["RAMSES_VER"].lstrip("vV").strip()
if not re.fullmatch(r"[0-9]+(\.[0-9]+)*", base):
    sys.exit("FAIL: RAMSES_VERSION %r is not a numeric version" % base)

tags = set(os.environ["TAGS"].split())
counters = [
    int(m.group(1))
    for m in (re.fullmatch(r"v%s\.([0-9]+)" % re.escape(base), t) for t in tags)
    if m
]

# The bare version is simply the first pyramses release on this RAMSES base,
# whatever triggered it; every later one on the same base takes a counter.
if ("v" + base) not in tags and not counters:
    print(base)
else:
    print("%s.%d" % (base, max(counters) + 1 if counters else 1))
PYEOF
)" || exit 1
[ -n "$NEW" ] || { echo "FAIL: could not compute the next version" >&2; exit 1; }

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
REWRITE_RC=$?
# Must abort here, before _bundled.py is touched: a failed rewrite must
# leave no partial mutation, or CI would tag/publish a version that was
# never actually written to the package.
[ "$REWRITE_RC" -eq 0 ] || exit 1

cat > "$BUNDLED" <<EOF
"""Upstream component versions bundled in this pyramses release.

Written by tools/bump_version.sh, which the release automation invokes when
stepss-ramses or stepss-helios publishes, and on a manual python-only release.
Do not edit by hand: a manual edit is silently overwritten by the next sync.

Only the upstream that triggered a sync changes; the other is carried forward.
RAMSES_VERSION is also what the pyramses version number is built from, so the
leading components of __version__ always name the library bundled here.
"""

RAMSES_VERSION = "$RAMSES_VER"
HELIOS_VERSION = "$HELIOS_VER"
EOF

echo "$NEW"
