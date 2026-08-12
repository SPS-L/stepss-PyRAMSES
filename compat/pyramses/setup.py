#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build script for the decommissioned `pyramses` distribution.

This is a tombstone, not a package. `pyramses` was renamed to `stepss`, and
installing this distribution fails on purpose with a message naming the
replacement, so that anyone who reaches for the old name is sent to the right
one rather than quietly receiving something that no longer tracks the engine.

It also holds the name. PyPI releases a deleted project's name for anyone to
register, and `pyramses` has real installs behind it in notebooks and papers,
so leaving the name unclaimed would let a third party publish anything under
it to those users.

How the refusal works, and why it is shaped this way:

- The raise below runs when pip prepares metadata, so `pip install pyramses`
  stops with the message. That only holds for an **sdist**: a wheel installs
  by unpacking, without executing this file. Publish the sdist alone. The
  workflow enforces it, and a wheel slipping onto PyPI would silently restore
  a working install of the retired name.
- Building the sdist has to run this file too, so the raise is gated on
  PYRAMSES_BUILD_TOMBSTONE. Only the publish workflow sets it. An env var, not
  a `sys.argv` check, because pip drives modern builds through
  `prepare_metadata_for_build_wheel` rather than a recognisable command.

This is the same mechanism the `sklearn` tombstone uses to redirect to
`scikit-learn`.

There is exactly one release, and there must never be another. PyPI cannot
host a project with no files: one with none behaves like a deleted project, so
`pip install pyramses` would fail with a bare resolver error and say nothing.
This single release exists only to carry the notice.

The version is 3.58.3 for reach, not for continuity. It sits above the last
real release, 3.58, so a range pin such as `pyramses>=3.5` still resolves here
and the installer reads the notice, where a low version would be reached only
by a bare `pip install pyramses`. 3.58.1 and 3.58.2 can never be reused: the
project was deleted from PyPI, and a deleted filename is permanently burned
even after the project is recreated. Exact pins on withdrawn releases cannot
resolve at all, for the same reason.

Archive the project on PyPI once this is published. Archiving keeps it
installable and resolvable while blocking further releases, which is what
holds the name and keeps the notice from being replaced.
"""

import os
import sys

from setuptools import setup

MESSAGE = """
***************************************************************************
This package has been decommissioned. Install stepss instead:

    pip install stepss

stepss is this package under its current name, and the only one that tracks
the RAMSES and Helios engines. Change `import pyramses` to `import stepss`:
cfg, sim, extractor, curplot and HeliosSession keep their names, and
`from pyramses.globals import X` becomes `from stepss.globals import X`.

Documentation: https://stepss.sps-lab.org/python/
***************************************************************************
"""

if not os.environ.get('PYRAMSES_BUILD_TOMBSTONE'):
    sys.stderr.write(MESSAGE)
    raise SystemExit(1)


def read(name):
    with open(os.path.join(os.path.dirname(__file__), name), encoding='utf-8') as f:
        return f.read()


setup(
    name='pyramses',
    version='3.58.3',
    description='This package has been decommissioned: install stepss instead.',
    long_description=read('README.rst'),
    long_description_content_type='text/x-rst',
    author='Petros Aristidou',
    author_email='apetros@pm.me',
    url='https://stepss.sps-lab.org/python/',
    license='Apache-2.0',
    packages=['pyramses'],
    classifiers=[
        "Development Status :: 7 - Inactive",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
    ],
)
