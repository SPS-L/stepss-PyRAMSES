#!/usr/bin/env bash
# Download the helios C API shared libraries from a stepss-helios GitHub
# release and copy them into src/stepss/libs/ for bundling.
#
# Usage: tools/update_helios_libs.sh <tag>        e.g. tools/update_helios_libs.sh v1.1.0
#
# Requires the GitHub CLI (gh) authenticated with access to SPS-L/stepss-helios.
# Review and commit the updated binaries afterwards:
#   git add src/stepss/libs/ && git commit -m "Bundle helios <tag> libraries"
#
# Note for macOS users downloading libraries manually through a browser
# instead of this script: strip the quarantine attribute before use
# (xattr -d com.apple.quarantine libhelios_api.dylib). Files installed by
# pip from the wheel do not carry the attribute.

set -euo pipefail

TAG="${1:?usage: $0 <helios-release-tag> (e.g. v1.1.0)}"
REPO="SPS-L/stepss-helios"
LIBS_DIR="$(cd "$(dirname "$0")/.." && pwd)/src/stepss/libs"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "Downloading helios $TAG API archives from $REPO ..."
gh release download "$TAG" --repo "$REPO" --pattern 'helios-api-*' --dir "$WORK_DIR"

cd "$WORK_DIR"
for archive in helios-api-*.tar.gz; do
    tar xzf "$archive"
done
if [ -f helios-api-windows-x64.zip ]; then
    unzip -q helios-api-windows-x64.zip -d helios-api-windows-x64
fi

# Shared libraries go into per-platform subfolders (the Linux and macOS
# RAMSES builds share the filename ramses.so); the header is platform-
# independent and stays at the libs/ root.
install -m 644 helios-api-linux-x86_64/libhelios_api.so      "$LIBS_DIR/lin/"
install -m 644 helios-api-macos-arm64/libhelios_api.dylib     "$LIBS_DIR/mac/"
install -m 644 helios-api-windows-x64/helios_api.dll          "$LIBS_DIR/win/"
install -m 644 helios-api-linux-x86_64/helios_api.h           "$LIBS_DIR/"

echo
echo "Updated $LIBS_DIR:"
ls -l "$LIBS_DIR" "$LIBS_DIR"/lin "$LIBS_DIR"/mac "$LIBS_DIR"/win | grep -i helios
echo
echo "Done. Review the changes and commit, e.g.:"
echo "  git add src/stepss/libs && git commit -m \"Bundle helios $TAG C API libraries\""
