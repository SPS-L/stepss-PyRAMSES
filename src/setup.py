#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Package build script for pyramses.

Reads version metadata from the installed :mod:`pyramses` package and uses
:func:`setuptools.setup` to define the distribution.  Run via
``python setup.py install`` (legacy) or, preferably, with ``pip install .``.
"""

try:
    from setuptools import setup, find_packages
except ImportError:
    from distutils.core import setup, find_packages
import os
import re

def read_first_existing(*paths):
    base = os.path.dirname(__file__)
    for path in paths:
        full_path = os.path.join(base, path)
        if os.path.exists(full_path):
            with open(full_path, encoding='utf-8') as f:
                return f.read()
    raise FileNotFoundError("None of the candidate files exist: {}".format(paths))

# Metadata is parsed (not imported) from the package so that setup.py works
# in pip's isolated build environment, where the package's runtime
# dependencies (numpy, scipy, ...) are not installed.
def read_metadata():
    init_path = os.path.join(os.path.dirname(__file__), 'pyramses', '__init__.py')
    with open(init_path, encoding='utf-8') as f:
        content = f.read()
    def grab(name):
        match = re.search(r"^__%s__\s*=\s*['\"]([^'\"]+)['\"]" % name, content, re.M)
        if not match:
            raise RuntimeError("__%s__ not found in %s" % (name, init_path))
        return match.group(1)
    return {name: grab(name) for name in
            ('version', 'author', 'email', 'status', 'url', 'package_name')}

# Since RAMSES v3.50 the bundled binaries are gfortran builds: they link only
# system libraries (OpenBLAS/gfortran/OpenMP runtimes on Linux, none on
# Windows), so no MKL dependency is needed.
install_requires = ['matplotlib','scipy','numpy']

_meta = read_metadata()
__version__ = _meta['version']
__author__ = _meta['author']
__email__ = _meta['email']
__status__ = _meta['status']
__url__ = _meta['url']
__name__ = _meta['package_name']

setup(
    name=__name__,
    version=__version__,
    description='Python library for RAMSES dynamic simulator of STEPSS package.',
    author=__author__,
    author_email=__email__,
    url=__url__,
    keywords=['RAMSES', 'Power Systems', 'Simulator','STEPSS'],
    license='Apache-2.0',
    # Prefer the repository-level README as the single source of truth.
    # Keep a local fallback for legacy build contexts that only copy ./src.
    long_description=read_first_existing('../README.rst', 'README.rst'),
    long_description_content_type='text/x-rst',
    packages=find_packages(),
    install_requires=install_requires, 
    package_data={
        # Headers are platform-independent and live at the libs/ root; the
        # shared libraries are split per platform because the Linux and macOS
        # RAMSES builds share the filename ramses.so.
        'pyramses': ['libs/*.h',
                     'libs/win/*.dll',
                     'libs/lin/*.so',
                     'libs/mac/*.so', 'libs/mac/*.dylib'],
    },
    classifiers=[
        "Development Status :: " + __status__,
        "Intended Audience :: Developers",
        "Environment :: Console",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3"
    ],
    entry_points={
        'console_scripts' : [
            'ramses = pyramses.scripts.exec:run',
        ]
    }

)
