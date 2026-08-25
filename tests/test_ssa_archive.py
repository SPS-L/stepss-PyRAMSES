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
    absent = ssa.save_archive(res, target)
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
    ssa.save_archive(res, target)
    with zipfile.ZipFile(target) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
    assert names[0] == "ssa/" + ssa.MANIFEST_NAME
    assert all(n.startswith("ssa/") for n in names)


def test_save_refuses_a_run_whose_modes_file_is_gone(res, tmp_path):
    Path(res.directory, "ssa_modes.dat").unlink()
    with pytest.raises(RAMSESError, match="no analysis to archive"):
        ssa.save_archive(res, tmp_path / "run.zip")


def test_save_refuses_a_tar_whose_member_name_is_too_long(tmp_path):
    """A basename this long pushes ``<basename>/<basename>_modes.dat`` past the
    100-byte ustar name field; Java's SsaArchive refuses the same way."""
    long_name = "n" * 45
    run = tmp_path / "run"
    run.mkdir()
    for suffix in ("modes", "pf", "ms"):
        shutil.copy(FIXTURES / ("kundur_nopss_%s.dat" % suffix),
                    run / ("%s_%s.dat" % (long_name, suffix)))
    long_res = ssa.load(run, long_name)
    with pytest.raises(RAMSESError, match="100-byte"):
        ssa.save_archive(long_res, tmp_path / "run.tar.gz")
    assert not (tmp_path / "run.tar.gz").exists()
    # The zip path has no such limit, so the same run must still save that way.
    ssa.save_archive(long_res, tmp_path / "run.zip")
    assert zipfile.is_zipfile(tmp_path / "run.zip")


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


def assert_refused_before_unpacking(target, into):
    """Assert that *target* is refused by this module, before it unpacks.

    Three assertions in this order, because the order is what makes each one
    discriminating rather than incidental. `pytest.raises(Exception)` rather
    than `raises(RAMSESError)` so that an error from the archive library
    reaches the assertions instead of escaping the test uncaught.

    Both were checked by neutralising `_safe_child` and running this: on the
    zip branch the first assertion fails, because CPython strips the ".." and
    unpacks the entry into the destination; on the tar branch the second
    fails, with `tarfile.OutsideDestinationError`, because `filter='data'`
    refuses from inside extraction rather than before it.
    """
    with pytest.raises(Exception) as caught:
        ssa.load_archive(target, into=into)
    assert list(into.iterdir()) == [], "the destination was written to"
    assert isinstance(caught.value, RAMSESError), type(caught.value).__name__
    assert "outside" in str(caught.value)


def test_load_archive_refuses_a_tar_entry_that_escapes_the_destination(tmp_path):
    payload = tmp_path / "payload"
    payload.write_text("x")
    target = tmp_path / "run.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(payload, arcname="../escaped.dat")
    into = tmp_path / "unpacked_tar"
    into.mkdir()
    assert_refused_before_unpacking(target, into)


def test_load_archive_refuses_a_zip_entry_that_escapes_the_destination(tmp_path):
    """Both containers are tested, because neither library refuses the same way.

    Refusing before unpacking is this module's own contract and is stronger
    than what either library provides on its own. See
    :func:`assert_refused_before_unpacking` for which assertion catches which.
    """
    target = tmp_path / "run.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("../escaped.dat", "x")
    into = tmp_path / "unpacked_zip"
    into.mkdir()
    assert_refused_before_unpacking(target, into)


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


# Forcing the old path on a modern interpreter trips the very
# DeprecationWarning the filter exists to avoid. A real 3.10 user takes
# this branch on a tarfile that has no such warning to give, so the
# noise is an artefact of the test rather than of the code.
@pytest.mark.filterwarnings("ignore:Python 3.14 will:DeprecationWarning")
def test_tar_round_trip_without_the_extraction_filter(res, tmp_path, monkeypatch):
    """The branch taken on a Python older than 3.11.4, 3.10.12 or 3.9.17.

    Those interpreters have no `filter` parameter on `TarFile.extractall`, and
    passing one is a TypeError rather than anything gentler. This package
    supports 3.10 and the runners' 3.10 is 3.10.11, so the branch is reached in
    practice. Version 3.81.1 shipped without it and raised that TypeError on
    every tar archive it was asked to open there.

    `hasattr(tarfile, 'data_filter')` is the check, so removing the attribute
    is what puts this test on the older path.
    """
    monkeypatch.delattr(tarfile, "data_filter", raising=False)
    target = tmp_path / "run.tar.gz"
    ssa.save_archive(res, target)
    loaded, manifest = ssa.load_archive(target)
    assert manifest.basename == "ssa"
    assert len(loaded.modes) == len(res.modes)


# Forcing the old path on a modern interpreter trips the very
# DeprecationWarning the filter exists to avoid. A real 3.10 user takes
# this branch on a tarfile that has no such warning to give, so the
# noise is an artefact of the test rather than of the code.
@pytest.mark.filterwarnings("ignore:Python 3.14 will:DeprecationWarning")
def test_the_escape_guard_still_holds_without_the_extraction_filter(
        res, tmp_path, monkeypatch):
    """The unfiltered path leans entirely on _safe_child, so pin that it holds.

    With the filter available, tarfile refuses an escaping entry itself. On an
    older interpreter nothing does but _safe_child, which is why it was kept
    when the filter was added rather than replaced by it.
    """
    monkeypatch.delattr(tarfile, "data_filter", raising=False)
    payload = tmp_path / "payload"
    payload.write_text("x")
    target = tmp_path / "escape.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(payload, arcname="../escaped.dat")
    into = tmp_path / "unpacked"
    into.mkdir()
    with pytest.raises(RAMSESError, match="outside"):
        ssa.load_archive(target, into=into)
    assert list(into.iterdir()) == []


def test_save_is_kept_as_an_alias_for_save_archive(res, tmp_path):
    """v3.81.1 and v3.81.2 shipped the writer as `save`, so the name stays.

    Not merely the same behaviour: the same object, so anything holding a
    reference to one is holding the other and the two can never drift.
    """
    assert ssa.save is ssa.save_archive
    target = tmp_path / "run.zip"
    ssa.save(res, target)
    assert zipfile.is_zipfile(target)


def test_results_save_keeps_its_short_name(res, tmp_path):
    """On a run object there is only one thing saving can mean.

    The method deliberately does not follow the module function's rename, and
    it must go on delegating to it rather than growing a second implementation.
    """
    target = tmp_path / "run.tar.gz"
    absent = res.save(target)
    assert tarfile.is_tarfile(target)
    assert set(absent) == set(ssa.members("ssa")[3:])
