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

# A miniature package tree: the script must only ever touch these two files.
mkdir -p "$TMPD/src/pyramses"
cat > "$TMPD/src/pyramses/__init__.py" <<'EOF'
__package_name__ = "pyramses"
__version__ = '0.3.0'
__author__ = "Petros Aristidou"
EOF
cat > "$TMPD/src/pyramses/_bundled.py" <<'EOF'
RAMSES_VERSION = "v3.51"
HELIOS_VERSION = "v1.2.0"
EOF

g() { sed -n "s/^$2[[:space:]]*=[[:space:]]*[\"']\([^\"']*\)[\"'].*/\1/p" "$1" | head -n1; }

# --- usage errors --------------------------------------------------------
"$SCRIPT" >/dev/null 2>&1
[ $? -eq 2 ] && ok "no args exits 2" || fail "no args should exit 2"
"$SCRIPT" ramses >/dev/null 2>&1
[ $? -eq 2 ] && ok "one arg exits 2" || fail "one arg should exit 2"
PYRAMSES_ROOT="$TMPD" "$SCRIPT" banana v1.0 >/dev/null 2>&1
[ $? -eq 2 ] && ok "unknown source exits 2" || fail "unknown source should exit 2"

# --- ramses bump ---------------------------------------------------------
OUT="$(PYRAMSES_ROOT="$TMPD" "$SCRIPT" ramses v3.55)"
[ "$OUT" = "0.3.1" ] && ok "prints the new version" || fail "printed '$OUT', want '0.3.1'"
[ "$(g "$TMPD/src/pyramses/__init__.py" __version__)" = "0.3.1" ] \
    && ok "__version__ bumped" || fail "__version__=$(g "$TMPD/src/pyramses/__init__.py" __version__)"
[ "$(g "$TMPD/src/pyramses/_bundled.py" RAMSES_VERSION)" = "v3.55" ] \
    && ok "RAMSES_VERSION updated" || fail "RAMSES_VERSION=$(g "$TMPD/src/pyramses/_bundled.py" RAMSES_VERSION)"
# The whole point: the untouched upstream must survive.
[ "$(g "$TMPD/src/pyramses/_bundled.py" HELIOS_VERSION)" = "v1.2.0" ] \
    && ok "HELIOS_VERSION carried forward" || fail "HELIOS_VERSION=$(g "$TMPD/src/pyramses/_bundled.py" HELIOS_VERSION)"

# --- helios bump, from the already-bumped state --------------------------
OUT="$(PYRAMSES_ROOT="$TMPD" "$SCRIPT" helios v1.3.0)"
[ "$OUT" = "0.3.2" ] && ok "second bump increments again" || fail "printed '$OUT', want '0.3.2'"
[ "$(g "$TMPD/src/pyramses/_bundled.py" HELIOS_VERSION)" = "v1.3.0" ] \
    && ok "HELIOS_VERSION updated" || fail "HELIOS_VERSION=$(g "$TMPD/src/pyramses/_bundled.py" HELIOS_VERSION)"
[ "$(g "$TMPD/src/pyramses/_bundled.py" RAMSES_VERSION)" = "v3.55" ] \
    && ok "RAMSES_VERSION carried forward" || fail "RAMSES_VERSION=$(g "$TMPD/src/pyramses/_bundled.py" RAMSES_VERSION)"

# --- rollover across a two-digit patch -----------------------------------
sed -i "s/__version__ = '0.3.2'/__version__ = '0.3.9'/" "$TMPD/src/pyramses/__init__.py"
OUT="$(PYRAMSES_ROOT="$TMPD" "$SCRIPT" ramses v3.56)"
[ "$OUT" = "0.3.10" ] && ok "0.3.9 -> 0.3.10 (numeric, not lexical)" || fail "printed '$OUT', want '0.3.10'"

# --- the file must stay importable ---------------------------------------
python3 -c "
import ast, sys
ast.parse(open('$TMPD/src/pyramses/_bundled.py').read())
ast.parse(open('$TMPD/src/pyramses/__init__.py').read())
" && ok "both files still parse as Python" || fail "a rewritten file is not valid Python"

echo ""
if [ "$FAILURES" -eq 0 ]; then echo "PASS: all assertions held"; exit 0; fi
echo "$FAILURES failure(s)"; exit 1
