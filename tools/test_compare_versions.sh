#!/usr/bin/env bash
# Local test for tools/compare_versions.py.
#
# The regression this exists to prevent: the comparison used to demand exactly
# three numeric components, which rejected every bare release the version
# scheme produces (3.58, 3.59, ...) and turned bundled-drift-check.yml red on
# a schedule. See the header of compare_versions.py.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/tools/compare_versions.py"
FAILURES=0
fail() { echo "FAIL: $*"; FAILURES=$((FAILURES + 1)); }
ok()   { echo "ok: $*"; }

# expect <master> <pypi> <expected-word>
expect() {
    local out
    out="$(python3 "$SCRIPT" "$1" "$2" 2>/dev/null)"
    if [ "$out" = "$3" ]; then
        ok "$1 vs $2 -> $3"
    else
        fail "$1 vs $2 gave '$out', expected '$3'"
    fi
}

# rejects <bad-version>
rejects() {
    python3 "$SCRIPT" "$1" 3.58.1 >/dev/null 2>&1
    if [ $? -eq 1 ]; then
        ok "rejects '$1'"
    else
        fail "should have rejected '$1'"
    fi
}

# --- the reported regression ---------------------------------------------
# A bare release is two components. Every one of these was rejected outright
# before this script existed, which is what failed run 31567918181.
expect 3.58   3.58   level
expect 3.59   3.58   ahead
expect 3.60   3.59   ahead

# --- counter releases, which always worked -------------------------------
expect 3.58.1 3.58   ahead
expect 3.58   3.58.1 behind
expect 3.58.2 3.58.1 ahead

# --- two and three components mixed --------------------------------------
# PEP 440 orders 3.58 and 3.58.0 as the same release, so the comparison pads
# the missing counter with zero rather than treating shorter as smaller.
expect 3.58   3.58.0 level
expect 3.58.0 3.58   level
expect 3.59   3.58.9 ahead

# --- the pre-scheme versions still compare -------------------------------
expect 0.3.5  0.3.5  level
expect 3.58   0.3.5  ahead
expect 0.3.5  3.58   behind

# --- shapes that must stay hard failures ---------------------------------
# A corrupted version must never be guessed at: the whole point of this check
# is that it fails loudly rather than quietly reporting "no drift".
rejects 3
rejects 3.58.1.2
rejects 3.x
rejects v3.58
rejects 3..1
rejects ""
rejects " 3.58"
rejects 3.58-rc1

# --- usage ---------------------------------------------------------------
python3 "$SCRIPT" >/dev/null 2>&1
[ $? -eq 2 ] && ok "no args exits 2" || fail "no args should exit 2"
python3 "$SCRIPT" 3.58 >/dev/null 2>&1
[ $? -eq 2 ] && ok "one arg exits 2" || fail "one arg should exit 2"
python3 "$SCRIPT" 3.58 3.58 extra >/dev/null 2>&1
[ $? -eq 2 ] && ok "three args exits 2" || fail "three args should exit 2"

# --- result --------------------------------------------------------------
if [ "$FAILURES" -eq 0 ]; then
    echo
    echo "PASS: all assertions held"
    exit 0
fi
echo
echo "FAIL: $FAILURES assertion(s) failed"
exit 1
