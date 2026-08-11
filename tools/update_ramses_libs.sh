#!/usr/bin/env bash
# Download the RAMSES shared libraries from a stepss-ramses GitHub release and
# copy them into src/stepss/libs/ for bundling.
#
# Usage: tools/update_ramses_libs.sh <tag>        e.g. tools/update_ramses_libs.sh v3.55
#
# Requires the GitHub CLI (gh) authenticated with access to SPS-L/stepss-ramses.
# Review and commit the updated binaries afterwards:
#   git add src/stepss/libs/ && git commit -m "Bundle RAMSES <tag> libraries"
#
# Companion to tools/update_helios_libs.sh; the release automation calls both.
#
# STEPSS_LIBS_DIR overrides the destination, for tests.
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "usage: $0 <ramses-release-tag> (e.g. v3.55)" >&2
    exit 2
fi
TAG="$1"
REPO="SPS-L/stepss-ramses"
LIBS_DIR="${STEPSS_LIBS_DIR:-$(cd "$(dirname "$0")/.." && pwd)/src/stepss/libs}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "Downloading RAMSES $TAG libraries from $REPO ..."
gh release download "$TAG" --repo "$REPO" \
    --pattern "pyramses-libs-*-$TAG.zip" --dir "$WORK_DIR"

# The Linux and macOS archives both contain a member named ramses.so, so each
# is unzipped into its own directory rather than a shared one. A flat
# extraction would silently leave one platform holding the other's library.
for plat in linux windows macos-arm64; do
    zip="$WORK_DIR/pyramses-libs-$plat-$TAG.zip"
    [ -f "$zip" ] || { echo "FAIL: RAMSES $TAG has no pyramses-libs-$plat-$TAG.zip" >&2; exit 1; }
    unzip -q "$zip" -d "$WORK_DIR/$plat"
done

install -m 644 "$WORK_DIR/linux/ramses.so"      "$LIBS_DIR/lin/ramses.so"
install -m 644 "$WORK_DIR/windows/ramses.dll"   "$LIBS_DIR/win/ramses.dll"
# macOS keeps the .so name: stepss separates platforms by directory.
install -m 644 "$WORK_DIR/macos-arm64/ramses.so" "$LIBS_DIR/mac/ramses.so"

echo
echo "Updated $LIBS_DIR:"
ls -l "$LIBS_DIR"/lin "$LIBS_DIR"/win "$LIBS_DIR"/mac | grep -i ramses || true
echo
echo "Done. Review the changes and commit, e.g.:"
echo "  git add src/stepss/libs && git commit -m \"Bundle RAMSES $TAG libraries\""
