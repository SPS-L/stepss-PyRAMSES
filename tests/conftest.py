"""Shared fixtures for the pyramses helios test suite.

The tests exercise the bundled helios shared library through the
:class:`pyramses.helios.HeliosSession` wrapper, using the 6-bus microgrid
example committed under ``tests/data/``.

Set the ``PYRAMSES_HELIOS_LIB_DIR`` environment variable to test against a
locally built library instead of the bundled one.
"""

import os
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent / "data"
LIB_DIR = os.environ.get("PYRAMSES_HELIOS_LIB_DIR") or None


@pytest.fixture
def data_dir():
    """Path to the committed test-data directory."""
    return DATA_DIR


@pytest.fixture
def case_6bus(data_dir):
    """Path to the 6-bus microgrid data file."""
    return data_dir / "6bus_mg.dat"


@pytest.fixture
def session():
    """A fresh, empty HeliosSession (closed after the test)."""
    from pyramses.helios import HeliosSession

    with HeliosSession(lib_dir=LIB_DIR) as pf:
        yield pf


@pytest.fixture
def solved(session, case_6bus):
    """A HeliosSession with the 6-bus case loaded and solved."""
    session.load_file(case_6bus)
    assert session.solve()
    return session
