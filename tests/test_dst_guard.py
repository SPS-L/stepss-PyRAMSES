"""The disturbance-file guard: a run needs a .dst, and it must carry a STOP.

RAMSES refuses both cases itself, deep inside get_disturb and after the whole
network has been read. These checks are the front-end half, so the message
arrives before anything is launched and names the file.
"""

import pytest

import stepss
from stepss.cases import _dstProblem
from stepss.globals import RAMSESError

GOOD = """  0.000 CONTINUE SOLVER BD 0.020 0.001 0. ABL
  1.000 FAULT BUS 4032 0. 0.8
  1.100 CLEAR BUS 4032
240.000 STOP
"""


def write(tmp_path, name, text):
    target = tmp_path / name
    target.write_text(text)
    return str(target)


# -- the checker ----------------------------------------------------------

def test_a_complete_file_passes(tmp_path):
    assert _dstProblem(write(tmp_path, "good.dst", GOOD)) is None


def test_stop_may_carry_trailing_text(tmp_path):
    assert _dstProblem(write(tmp_path, "t.dst", "240.000 STOP ;\n")) is None


def test_stop_need_not_be_the_last_line(tmp_path):
    # The engine stops reading at the first STOP, so what follows is ignored.
    text = "240.000 STOP\n300.000 FAULT BUS 4032 0. 0.8\n"
    assert _dstProblem(write(tmp_path, "t.dst", text)) is None


def test_comments_and_blank_lines_are_skipped(tmp_path):
    text = "# a comment\n\n! another\n  1.0 FAULT BUS 4032 0. 0.8\n  9.0 STOP\n"
    assert _dstProblem(write(tmp_path, "t.dst", text)) is None


def test_a_stop_inside_a_comment_does_not_count(tmp_path):
    text = "# 240.000 STOP\n  1.0 FAULT BUS 4032 0. 0.8\n"
    assert "no STOP record" in _dstProblem(write(tmp_path, "t.dst", text))


def test_a_file_without_stop_is_named(tmp_path):
    path = write(tmp_path, "nostop.dst", "  1.000 FAULT BUS 4032 0. 0.8\n")
    problem = _dstProblem(path)
    assert "nostop.dst" in problem
    assert "no STOP record" in problem
    assert "240.0 STOP" in problem  # says what to add


def test_an_empty_file_reports_no_records(tmp_path):
    assert "no disturbance records" in _dstProblem(write(tmp_path, "t.dst", ""))


def test_a_file_of_only_comments_reports_no_records(tmp_path):
    assert "no disturbance records" in _dstProblem(write(tmp_path, "t.dst", "# nothing\n"))


def test_a_stop_without_a_time_says_so(tmp_path):
    problem = _dstProblem(write(tmp_path, "t.dst", "  1.0 FAULT BUS 4032 0. 0.8\nSTOP\n"))
    assert "STOP without a time" in problem


def test_an_unreadable_path_is_reported(tmp_path):
    problem = _dstProblem(str(tmp_path))  # a directory, not a file
    assert "could not be read" in problem


# -- addDst ---------------------------------------------------------------

def test_addDst_accepts_a_complete_file(tmp_path):
    case = stepss.cfg()
    path = write(tmp_path, "good.dst", GOOD)
    case.addDst(path)
    assert case.getDst() == path


def test_addDst_refuses_a_file_without_stop(tmp_path):
    case = stepss.cfg()
    with pytest.raises(RAMSESError, match="no STOP record"):
        case.addDst(write(tmp_path, "nostop.dst", "  1.0 FAULT BUS 4032 0. 0.8\n"))


def test_a_rejected_file_does_not_replace_the_attached_one(tmp_path):
    case = stepss.cfg()
    good = write(tmp_path, "good.dst", GOOD)
    case.addDst(good)
    with pytest.raises(RAMSESError):
        case.addDst(write(tmp_path, "nostop.dst", "  1.0 FAULT BUS 4032 0. 0.8\n"))
    assert case.getDst() == good


def test_addDst_still_refuses_a_missing_file(tmp_path):
    case = stepss.cfg()
    with pytest.raises(IOError):
        case.addDst(str(tmp_path / "absent.dst"))


# -- writeCmdFile ---------------------------------------------------------

def built(tmp_path, dst=None):
    case = stepss.cfg()
    case.addData(write(tmp_path, "dyn.dat", "# data\n"))
    if dst is not None:
        case.addDst(dst)
    return case


def test_a_case_without_a_disturbance_file_will_not_serialise(tmp_path):
    with pytest.raises(RAMSESError, match="No disturbance file is set"):
        built(tmp_path).writeCmdFile()


def test_a_case_without_data_files_says_which_is_missing(tmp_path):
    case = stepss.cfg()
    with pytest.raises(RAMSESError, match="No data file is set"):
        case.writeCmdFile()


def test_a_complete_case_serialises(tmp_path):
    text = built(tmp_path, write(tmp_path, "good.dst", GOOD)).writeCmdFile()
    assert "good.dst" in text


def test_the_stop_is_rechecked_at_serialisation(tmp_path):
    """The file can be edited between being attached and being run."""
    path = write(tmp_path, "good.dst", GOOD)
    case = built(tmp_path, path)
    (tmp_path / "good.dst").write_text("  1.0 FAULT BUS 4032 0. 0.8\n")
    with pytest.raises(RAMSESError, match="no STOP record"):
        case.writeCmdFile()


# -- loading a command file -----------------------------------------------

def test_loading_a_command_file_checks_its_disturbance_file(tmp_path):
    good = built(tmp_path, write(tmp_path, "good.dst", GOOD))
    cmd = str(tmp_path / "cmd.txt")
    good.writeCmdFile(cmd)
    stepss.cfg(cmd)  # round-trips

    (tmp_path / "good.dst").write_text("  1.0 FAULT BUS 4032 0. 0.8\n")
    with pytest.raises(RAMSESError, match="no STOP record"):
        stepss.cfg(cmd)
