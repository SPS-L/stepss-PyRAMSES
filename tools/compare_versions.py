#!/usr/bin/env python3
"""Compare this repository's version against the one published on PyPI.

Usage:
    compare_versions.py <master-version> <pypi-version>

Prints exactly one word describing master relative to PyPI: ``ahead``,
``level`` or ``behind``. Used by .github/workflows/bundled-drift-check.yml,
where only "master ahead" means a release was built but never uploaded.

Why this is a script rather than a heredoc in the workflow
----------------------------------------------------------
It used to be inlined, and it demanded exactly three numeric components with
the comment "bump_version.sh enforces exactly that shape". That stopped being
true when the version scheme changed to ``<ramses-version>[.<counter>]``: the
commit that made the change updated bump_version.sh, its tests, the sync
workflow and CLAUDE.md, but not the drift check. Nothing tested the drift
check, so the mismatch stayed invisible until the first bare release (3.58)
turned the scheduled run red.

Living in tools/ with tools/test_compare_versions.sh beside it, the same way
every other helper here does, is what makes that class of drift catchable.

The scheme
----------
A version is the bundled RAMSES version, optionally followed by a counter:

    3.58      first release on the 3.58 base
    3.58.1    a later release on the same base
    3.59      first release once RAMSES 3.59 is bundled

So two or three numeric components, never more. A missing counter compares as
zero, which is how PEP 440 orders these: ``3.58`` and ``3.58.0`` are the same
release, and ``3.58.1`` is greater than both.

Anything outside that shape is a hard failure rather than a best guess. This
check exists to catch a version that never reached PyPI, so a version it
cannot parse must go red rather than quietly report "no drift".
"""

import sys

_COMPONENTS = 3


def parse(label, value):
    """Return *value* as a 3-tuple of ints, or exit 1 if it is not a version.

    ``label`` names the source ('master' or 'PyPI') so a failure says which
    of the two was malformed.
    """
    parts = value.split('.')
    if len(parts) not in (2, _COMPONENTS) or not all(p.isdigit() for p in parts):
        sys.exit('FAIL: %s version %r is not <ramses-version>[.<counter>] '
                 'with numeric parts' % (label, value))
    numbers = [int(p) for p in parts]
    # Pad the absent counter with zero so a bare version compares against a
    # counter version correctly: 3.58 is 3.58.0, and 3.58.1 is above it.
    numbers += [0] * (_COMPONENTS - len(numbers))
    return tuple(numbers)


def main(argv):
    if len(argv) != 3:
        print('usage: compare_versions.py <master-version> <pypi-version>',
              file=sys.stderr)
        return 2
    repo = parse('master', argv[1])
    pypi = parse('PyPI', argv[2])
    print('ahead' if repo > pypi else 'level' if repo == pypi else 'behind')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
