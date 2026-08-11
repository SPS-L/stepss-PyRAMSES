"""Run every helios example script and require a clean exit."""

import os
import runpy
from pathlib import Path

import pytest

import stepss.helios
from conftest import LIB_DIR

EXAMPLES = sorted((Path(__file__).resolve().parents[1] / "examples" / "helios").glob("*.py"))


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.name)
def test_example_runs(example, monkeypatch, tmp_path, capsys):
    if LIB_DIR:
        # Redirect the bundled-library lookup to the override directory.
        monkeypatch.setattr(stepss.helios, "__platlibdir__", os.path.realpath(LIB_DIR))
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(example), run_name="__main__")
    assert capsys.readouterr().out  # every example prints something


def test_examples_exist():
    assert len(EXAMPLES) == 5


def test_console_script_target_is_importable():
    """The `ramses` console script entry point must be shipped in the wheel.

    Regression guard: `stepss/scripts/` had no __init__.py, so find_packages()
    skipped it and the installed entry point pointed at a missing module.
    """
    from stepss.scripts.exec import run

    assert callable(run)
