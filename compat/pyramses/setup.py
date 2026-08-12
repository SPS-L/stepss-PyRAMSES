#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build script for the pyramses compatibility shim.

Deliberately standalone: it shares no code with src/setup.py, because this
distribution is published on its own schedule and must not drift with the
real one.

Version history: 3.58.1 was the first shim; 3.58.2 corrects its forwarding,
which reached only the names in ``stepss.__all__`` and so lost the documented
package-level attributes. PyPI files are immutable, so any fix to the shim is
a new version, never a re-upload.
"""

import os

from setuptools import setup


def read(name):
    with open(os.path.join(os.path.dirname(__file__), name), encoding='utf-8') as f:
        return f.read()


setup(
    name='pyramses',
    version='3.58.2',
    description='Compatibility shim: pyramses is now stepss.',
    long_description=read('README.rst'),
    long_description_content_type='text/x-rst',
    author='Petros Aristidou',
    author_email='apetros@pm.me',
    url='https://stepss.sps-lab.org',
    license='Apache-2.0',
    packages=['pyramses'],
    install_requires=['stepss>=3.59'],
    classifiers=[
        "Development Status :: 7 - Inactive",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
    ],
)
