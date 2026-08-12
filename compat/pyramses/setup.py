#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build script for the retired `pyramses` distribution.

This is a tombstone, not a package. `pyramses` was renamed to `stepss`, and
installing this distribution fails on purpose with a message naming the
replacement, so that anyone who reaches for the old name is sent to the right
one rather than quietly receiving something that no longer tracks the engine.

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
"""

import os
import sys

from setuptools import setup

MESSAGE = """
***************************************************************************
pyramses is retired. Install stepss instead:

    pip install stepss

Then change `import pyramses` to `import stepss`. The API is unchanged:
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
    version='3.58.2',
    description='pyramses is retired: install stepss instead.',
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
