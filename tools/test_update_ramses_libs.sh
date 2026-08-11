#!/usr/bin/env bash
# Local test for tools/update_ramses_libs.sh, with a fake `gh` so no network
# or credentials are needed.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/tools/update_ramses_libs.sh"
FAILURES=0
fail() { echo "FAIL: $*"; FAILURES=$((FAILURES + 1)); }
ok()   { echo "ok: $*"; }

TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT

mkdir -p "$TMPD/libs"/{lin,win,mac}

# Build the three archives the real release carries, each holding one
# recognisable payload file.
STAGE="$TMPD/stage"; mkdir -p "$STAGE"
printf 'LINUX-SO-PAYLOAD\n'  > "$STAGE/ramses.so"
( cd "$STAGE" && zip -q "$TMPD/pyramses-libs-linux-v9.99.zip" ramses.so )
printf 'WINDOWS-DLL-PAYLOAD\n' > "$STAGE/ramses.dll"
( cd "$STAGE" && zip -q "$TMPD/pyramses-libs-windows-v9.99.zip" ramses.dll )
printf 'MACOS-SO-PAYLOAD\n'  > "$STAGE/ramses_mac.so"
( cd "$STAGE" && cp ramses_mac.so ramses.so && zip -q "$TMPD/pyramses-libs-macos-arm64-v9.99.zip" ramses.so )

FAKEBIN="$TMPD/fakebin"; mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/gh" <<EOF
#!/usr/bin/env bash
# Fake "gh": serve the prepared archives for 'release download --pattern P --dir D'.
DIR=""; PATTERN=""
while [ \$# -gt 0 ]; do
  case "\$1" in
    --dir) DIR="\$2"; shift 2 ;;
    --pattern) PATTERN="\$2"; shift 2 ;;
    *) shift ;;
  esac
done
[ -n "\$DIR" ] || exit 1
shopt -s nullglob
matched=0
for f in "$TMPD"/\$PATTERN; do cp "\$f" "\$DIR/"; matched=1; done
[ "\$matched" = 1 ] || { echo "fake gh: no asset matching \$PATTERN" >&2; exit 1; }
EOF
chmod +x "$FAKEBIN/gh"

# --- usage ---------------------------------------------------------------
"$SCRIPT" >/dev/null 2>&1
[ $? -eq 2 ] && ok "no args exits 2" || fail "no args should exit 2"

# --- happy path ----------------------------------------------------------
PATH="$FAKEBIN:$PATH" STEPSS_LIBS_DIR="$TMPD/libs" "$SCRIPT" v9.99 >"$TMPD/out.log" 2>&1
rc=$?
[ $rc -eq 0 ] && ok "happy path exits 0" || { fail "happy path exited $rc"; cat "$TMPD/out.log"; }

grep -q 'LINUX-SO-PAYLOAD'   "$TMPD/libs/lin/ramses.so"  && ok "lin/ramses.so installed"  || fail "lin/ramses.so wrong or missing"
grep -q 'WINDOWS-DLL-PAYLOAD' "$TMPD/libs/win/ramses.dll" && ok "win/ramses.dll installed" || fail "win/ramses.dll wrong or missing"
grep -q 'MACOS-SO-PAYLOAD'   "$TMPD/libs/mac/ramses.so"  && ok "mac/ramses.so installed"  || fail "mac/ramses.so wrong or missing"

# macOS must be a .so, never a .dylib: stepss splits platforms by directory.
[ ! -e "$TMPD/libs/mac/ramses.dylib" ] && ok "no stray mac/ramses.dylib" || fail "mac kit wrote a .dylib"

# The Linux and macOS archives share the member name ramses.so; a flat
# extraction would let one clobber the other.
if ! cmp -s "$TMPD/libs/lin/ramses.so" "$TMPD/libs/mac/ramses.so"; then
    ok "lin and mac .so are distinct (no cross-platform clobber)"
else
    fail "lin/ramses.so and mac/ramses.so are identical -- extraction clobbered one"
fi

# --- a missing asset must fail loudly ------------------------------------
rm -f "$TMPD/pyramses-libs-windows-v9.99.zip"
PATH="$FAKEBIN:$PATH" STEPSS_LIBS_DIR="$TMPD/libs" "$SCRIPT" v9.99 >/dev/null 2>&1
[ $? -ne 0 ] && ok "missing asset exits non-zero" || fail "missing asset should fail"

echo ""
if [ "$FAILURES" -eq 0 ]; then echo "PASS: all assertions held"; exit 0; fi
echo "$FAILURES failure(s)"; exit 1
