"""The .ssa archive, which both interfaces read and write."""

import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

from stepss import ssa
from stepss.globals import RAMSESError

FIXTURES = Path(__file__).resolve().parent / "data" / "ssa"


@pytest.fixture
def res(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    for suffix in ("modes", "pf", "ms"):
        shutil.copy(FIXTURES / ("kundur_nopss_%s.dat" % suffix),
                    run / ("ssa_%s.dat" % suffix))
    return ssa.load(run, "ssa")


@pytest.mark.parametrize("name", ["run.zip", "run.tar.gz"])
def test_round_trip(res, tmp_path, name):
    target = tmp_path / name
    absent = ssa.save(res, target)
    assert set(absent) == set(ssa.members("ssa")[3:]), "no Jacobian was written"

    loaded, manifest = ssa.load_archive(target)
    assert manifest.basename == "ssa"
    assert manifest.saved_by.startswith("stepss ")
    assert len(loaded.modes) == len(res.modes)
    assert loaded.participation(res.electromechanical().rows[0])


def test_results_save_is_the_same_call(res, tmp_path):
    target = tmp_path / "run.zip"
    res.save(target)
    assert zipfile.is_zipfile(target)


def test_zip_puts_the_manifest_first_under_a_directory_named_for_the_run(res, tmp_path):
    target = tmp_path / "run.zip"
    ssa.save(res, target)
    with zipfile.ZipFile(target) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
    assert names[0] == "ssa/" + ssa.MANIFEST_NAME
    assert all(n.startswith("ssa/") for n in names)


def test_save_refuses_a_run_whose_modes_file_is_gone(res, tmp_path):
    Path(res.directory, "ssa_modes.dat").unlink()
    with pytest.raises(RAMSESError, match="no analysis to archive"):
        ssa.save(res, tmp_path / "run.zip")


def test_load_archive_refuses_a_file_that_is_neither_format(tmp_path):
    plain = tmp_path / "run.zip"
    plain.write_text("not an archive")
    with pytest.raises(RAMSESError, match="neither a zip nor a gzipped tar"):
        ssa.load_archive(plain)


def test_load_archive_refuses_an_archive_with_no_manifest(tmp_path):
    target = tmp_path / "run.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("ssa/ssa_modes.dat",
                         (FIXTURES / "kundur_nopss_modes.dat").read_text())
    with pytest.raises(RAMSESError, match=ssa.MANIFEST_NAME):
        ssa.load_archive(target)


def test_load_archive_refuses_a_newer_format_version(tmp_path):
    target = tmp_path / "run.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("ssa/" + ssa.MANIFEST_NAME,
                         "# STEPSS small-signal archive v2\nbasename ssa\n")
        archive.writestr("ssa/ssa_modes.dat",
                         (FIXTURES / "kundur_nopss_modes.dat").read_text())
    with pytest.raises(RAMSESError, match="archive format v2"):
        ssa.load_archive(target)


def test_load_archive_refuses_an_unusable_basename(tmp_path):
    target = tmp_path / "run.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("ssa/" + ssa.MANIFEST_NAME,
                         "# STEPSS small-signal archive v1\nbasename ../evil\n")
    with pytest.raises(RAMSESError, match="unusable basename"):
        ssa.load_archive(target)


def test_load_archive_refuses_a_tar_entry_that_escapes_the_destination(tmp_path):
    """Refused up front, and refused before anything is unpacked."""
    payload = tmp_path / "payload"
    payload.write_text("x")
    target = tmp_path / "run.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(payload, arcname="../escaped.dat")
    into = tmp_path / "unpacked_tar"
    into.mkdir()
    with pytest.raises(RAMSESError, match="outside"):
        ssa.load_archive(target, into=into)
    assert list(into.iterdir()) == []


def test_load_archive_refuses_a_zip_entry_that_escapes_the_destination(tmp_path):
    """The two branches are refused for different reasons, so both are tested.

    On the tar branch `filter='data'` would refuse this entry by itself, so
    that test passes even with _safe_child removed. zipfile does not refuse it
    and does not honour it either: CPython strips the "..", so "../escaped.dat"
    would unpack as "escaped.dat" inside the destination and nothing would be
    reported. Neither branch leaks a file, and this test does not pretend
    otherwise.

    What it pins is the module's own contract, which is stronger than either:
    an archive naming a path outside the destination is refused, and refused
    before anything is unpacked. The empty directory below is what says so.
    With _safe_child gone, this archive would unpack and that assertion would
    fail.
    """
    target = tmp_path / "run.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("../escaped.dat", "x")
    into = tmp_path / "unpacked_zip"
    into.mkdir()
    with pytest.raises(RAMSESError, match="outside"):
        ssa.load_archive(target, into=into)
    assert list(into.iterdir()) == []


def test_manifest_omits_absent_keys():
    text = ssa.Manifest("ssa", None, None, None).text()
    assert "basename ssa" in text
    assert "engine_version" not in text
    assert "\nt " not in text


def test_manifest_round_trips_every_key():
    original = ssa.Manifest("ssa", 3.81, 0.001, "stepss 3.81")
    back = ssa.Manifest.parse(original.text())
    assert back.basename == "ssa"
    assert back.engine_version == pytest.approx(3.81)
    assert back.time == pytest.approx(0.001)
    assert back.saved_by == "stepss 3.81"


def test_manifest_ignores_a_key_it_does_not_know():
    """A field added on one side is ignored on the other; that is the format's rule."""
    text = ("# STEPSS small-signal archive v1\nbasename ssa\n"
            "real_limit -1.0\nsaved_by STEPSS 3.74\n")
    assert ssa.Manifest.parse(text).saved_by == "STEPSS 3.74"
