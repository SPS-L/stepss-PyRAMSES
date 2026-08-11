#!/usr/bin/env bash
# Local test for tools/bump_version.sh.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/tools/bump_version.sh"
FAILURES=0
fail() { echo "FAIL: $*"; FAILURES=$((FAILURES + 1)); }
ok()   { echo "ok: $*"; }

TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT

g() { sed -n "s/^$2[[:space:]]*=[[:space:]]*[\"']\([^\"']*\)[\"'].*/\1/p" "$1" | head -n1; }

# make_tree <dir> <version> <ramses> <helios>
make_tree() {
    mkdir -p "$1/src/pyramses"
    cat > "$1/src/pyramses/__init__.py" <<EOF
__package_name__ = "pyramses"
__version__ = '$2'
__author__ = "Petros Aristidou"
EOF
    cat > "$1/src/pyramses/_bundled.py" <<EOF
RAMSES_VERSION = "$3"
HELIOS_VERSION = "$4"
EOF
}

# run <dir> <tags> <args...>
run() {
    local d="$1" tags="$2"; shift 2
    PYRAMSES_ROOT="$d" PYRAMSES_TAGS="$tags" "$SCRIPT" "$@"
}

# --- usage errors --------------------------------------------------------
"$SCRIPT" >/dev/null 2>&1
[ $? -eq 2 ] && ok "no args exits 2" || fail "no args should exit 2"
"$SCRIPT" ramses >/dev/null 2>&1
[ $? -eq 2 ] && ok "ramses without a tag exits 2" || fail "ramses without a tag should exit 2"
PYRAMSES_ROOT="$TMPD" "$SCRIPT" banana v1.0 >/dev/null 2>&1
[ $? -eq 2 ] && ok "unknown source exits 2" || fail "unknown source should exit 2"
PYRAMSES_ROOT="$TMPD" "$SCRIPT" manual v1.0 >/dev/null 2>&1
[ $? -eq 2 ] && ok "manual with a tag exits 2" || fail "manual takes no tag"

# --- the documented sequence, end to end ---------------------------------
# ramses publishes 3.57: first release on that base, so the bare version.
D="$TMPD/seq"; make_tree "$D" "0.3.5" "v3.56" "v1.4.1"
OUT="$(run "$D" "v0.3.4
v0.3.5" ramses v3.57)"
[ "$OUT" = "3.57" ] && ok "ramses bump takes the RAMSES version" || fail "printed '$OUT', want '3.57'"
[ "$(g "$D/src/pyramses/_bundled.py" RAMSES_VERSION)" = "v3.57" ] \
    && ok "RAMSES_VERSION updated" || fail "RAMSES_VERSION not updated"
[ "$(g "$D/src/pyramses/_bundled.py" HELIOS_VERSION)" = "v1.4.1" ] \
    && ok "HELIOS_VERSION carried forward" || fail "HELIOS_VERSION not carried forward"

# helios publishes next: same base, first counter.
OUT="$(run "$D" "v0.3.5
v3.57" helios v1.5.0)"
[ "$OUT" = "3.57.1" ] && ok "helios bump takes the first counter" || fail "printed '$OUT', want '3.57.1'"
[ "$(g "$D/src/pyramses/_bundled.py" RAMSES_VERSION)" = "v3.57" ] \
    && ok "helios bump keeps the RAMSES base" || fail "RAMSES_VERSION changed on a helios bump"

# a python-only release after that: next counter, neither upstream moves.
OUT="$(run "$D" "v3.57
v3.57.1" manual)"
[ "$OUT" = "3.57.2" ] && ok "manual release takes the next counter" || fail "printed '$OUT', want '3.57.2'"
[ "$(g "$D/src/pyramses/_bundled.py" RAMSES_VERSION)" = "v3.57" ] \
    && ok "manual keeps RAMSES_VERSION" || fail "manual changed RAMSES_VERSION"
[ "$(g "$D/src/pyramses/_bundled.py" HELIOS_VERSION)" = "v1.5.0" ] \
    && ok "manual keeps HELIOS_VERSION" || fail "manual changed HELIOS_VERSION"

# the next RAMSES restarts the sequence, because no tag on that base exists.
OUT="$(run "$D" "v3.57
v3.57.1
v3.57.2" ramses v3.58)"
[ "$OUT" = "3.58" ] && ok "a new RAMSES restarts the sequence" || fail "printed '$OUT', want '3.58'"

# --- counter selection ---------------------------------------------------
D2="$TMPD/max"; make_tree "$D2" "3.57.2" "v3.57" "v1.4.1"
OUT="$(run "$D2" "v3.57
v3.57.1
v3.57.5
v3.57.2" manual)"
[ "$OUT" = "3.57.6" ] && ok "counter follows the maximum, not the count" || fail "printed '$OUT', want '3.57.6'"

# A counter with no bare tag still works: the sequence continues from it.
D3="$TMPD/nobare"; make_tree "$D3" "3.57.3" "v3.57" "v1.4.1"
OUT="$(run "$D3" "v3.57.3" manual)"
[ "$OUT" = "3.57.4" ] && ok "a counter without the bare tag continues" || fail "printed '$OUT', want '3.57.4'"

# --- tags on other bases must not be counted -----------------------------
# 'v3.5.1' must not be read as base 3.5 + counter 1 when the base is 3.57,
# and 'v3.571' must not match base 3.57 either.
D4="$TMPD/other"; make_tree "$D4" "0.3.5" "v3.57" "v1.4.1"
OUT="$(run "$D4" "v0.3.5
v3.5.1
v3.56
v3.56.9
v3.571" manual)"
[ "$OUT" = "3.57" ] && ok "tags on other bases are ignored" || fail "printed '$OUT', want '3.57'"

# A dot in the base must be a literal, not a regex wildcard.
D5="$TMPD/dot"; make_tree "$D5" "0.1.0" "v3.5" "v1.4.1"
OUT="$(run "$D5" "v375.1" manual)"
[ "$OUT" = "3.5" ] && ok "the base dot is matched literally" || fail "printed '$OUT', want '3.5'"

# --- a two-component current version is now normal, not an error ---------
# Going 3.57 -> 3.57.1 means __version__ legitimately has two components.
D6="$TMPD/twocomp"; make_tree "$D6" "3.57" "v3.57" "v1.4.1"
OUT="$(run "$D6" "v3.57" manual)"
[ "$OUT" = "3.57.1" ] && ok "a two-component current version bumps cleanly" || fail "printed '$OUT', want '3.57.1'"
[ "$(g "$D6/src/pyramses/__init__.py" __version__)" = "3.57.1" ] \
    && ok "__version__ rewritten" || fail "__version__=$(g "$D6/src/pyramses/__init__.py" __version__)"

# --- a non-numeric RAMSES_VERSION must fail, not produce a junk version ---
D7="$TMPD/junk"; make_tree "$D7" "3.57" "not-a-version" "v1.4.1"
OUT="$(run "$D7" "" manual 2>/dev/null)"
RC=$?
[ "$RC" -ne 0 ] && ok "non-numeric RAMSES_VERSION exits non-zero" \
    || fail "non-numeric RAMSES_VERSION should exit non-zero, got $RC"
[ -z "$OUT" ] && ok "non-numeric RAMSES_VERSION prints nothing" \
    || fail "printed '$OUT'"

# --- the files must stay importable --------------------------------------
python3 -c "
import ast
ast.parse(open('$D/src/pyramses/_bundled.py').read())
ast.parse(open('$D/src/pyramses/__init__.py').read())
" && ok "both files still parse as Python" || fail "a rewritten file is not valid Python"

# --- regression: a failed __version__ rewrite must not still publish ------
# Two identical __version__ lines make the rewrite's "exactly one match"
# guard fire. The script must detect that failure and abort *before*
# touching _bundled.py, print nothing on stdout, and exit non-zero.
DUPD="$TMPD/dup"
mkdir -p "$DUPD/src/pyramses"
cat > "$DUPD/src/pyramses/__init__.py" <<'EOF'
__package_name__ = "pyramses"
__version__ = '3.57'
__version__ = '3.57'
__author__ = "Petros Aristidou"
EOF
cat > "$DUPD/src/pyramses/_bundled.py" <<'EOF'
RAMSES_VERSION = "v3.57"
HELIOS_VERSION = "v1.4.1"
EOF
BUNDLED_BEFORE="$(cat "$DUPD/src/pyramses/_bundled.py")"
OUT="$(run "$DUPD" "v3.57" ramses v3.60 2>/dev/null)"
RC=$?
[ "$RC" -ne 0 ] && ok "duplicated __version__ exits non-zero" \
    || fail "duplicated __version__ should exit non-zero, got $RC"
[ -z "$OUT" ] && ok "duplicated __version__ prints nothing on stdout" \
    || fail "duplicated __version__ printed '$OUT' on stdout"
BUNDLED_AFTER="$(cat "$DUPD/src/pyramses/_bundled.py")"
[ "$BUNDLED_AFTER" = "$BUNDLED_BEFORE" ] && ok "duplicated __version__ leaves _bundled.py untouched" \
    || fail "_bundled.py was modified despite a failed rewrite"

echo ""
if [ "$FAILURES" -eq 0 ]; then echo "PASS: all assertions held"; exit 0; fi
echo "$FAILURES failure(s)"; exit 1
