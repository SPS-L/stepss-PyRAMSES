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
    payload = tmp_path / "payload"
    payload.write_text("x")
    target = tmp_path / "run.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(payload, arcname="../escaped.dat")
    with pytest.raises(RAMSESError, match="outside"):
        ssa.load_archive(target)


def test_load_archive_refuses_a_zip_entry_that_escapes_the_destination(tmp_path):
    """The zip branch is the one where _safe_child is the only protection.

    tarfile's filter='data' would refuse this on its own, so the tar test above
    passes even with the guard removed. zipfile has no equivalent: a bare
    extractall writes ../escaped.dat outside the destination and reports
    nothing. This test is therefore the only thing standing behind _safe_child
    on the branch where it matters most.
    """
    target = tmp_path / "run.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("../escaped.dat", "x")
    with pytest.raises(RAMSESError, match="outside"):
        ssa.load_archive(target)
    assert not (tmp_path.parent / "escaped.dat").exists()


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
