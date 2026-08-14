"""Upstream component versions bundled in this stepss release.

Written by tools/bump_version.sh, which the release automation invokes when
stepss-ramses or stepss-helios publishes, and on a manual python-only release.
Do not edit by hand: a manual edit is silently overwritten by the next sync.

Only the upstream that triggered a sync changes; the other is carried forward.
RAMSES_VERSION is also what the stepss version number is built from, so the
leading components of __version__ always name the library bundled here.
"""

RAMSES_VERSION = "v3.74"
HELIOS_VERSION = "v1.4.1"
