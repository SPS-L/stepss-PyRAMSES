"""Fixed-column parsing of the three results files ssa.f90 writes.

The happy path is checked against genuine engine output committed under
tests/data/ssa/, because the parser reads by column offset and only real
output proves the offsets. The refusals are checked against text built here,
so that regenerating a fixture cannot turn a refusal into a pass.
"""

from pathlib import Path

import numpy as np
import pytest

from stepss import ssa
from stepss.globals import RAMSESError

FIXTURES = Path(__file__).resolve().parent / "data" / "ssa"


def en(value):
    """One number in the 24-column field ssa.f90's en24.15 edit descriptor fills."""
    return "%24s" % ("%.15E" % value)


def modes_line(index, re, im, zeta, freq, smp, dom=None):
    """One modes row at the offsets (i8,1x,4(en24.15,1x),i2) produces.

    Passing `dom` produces the v1 layout, which carried a dominance flag where
    v2 puts smp and pushed smp two columns further right.
    """
    row = "%8d %s %s %s %s " % (index, en(re), en(im), en(zeta), en(freq))
    if dom is None:
        return row + "%2d" % smp
    return row + "%2d %2d" % (dom, smp)


V2_HEADER = (
    "# STEPSS SSA modes v2\n"
    "# nstates 4 nalg 12 time %s pf_floor %s gap_tol %s\n"
) % (en(0.0), en(1e-3), en(1e-6))


def test_slice_keeps_leading_blank_and_drops_trailing():
    assert ssa._slice("  g1                ", 0, 20) == "  g1"


def test_slice_past_end_of_line_is_empty():
    assert ssa._slice("short", 40, 60) == ""


def test_num_names_the_columns_it_could_not_read():
    with pytest.raises(RAMSESError, match="columns 1-8"):
        ssa._num("not a number", 0, 8, 7)


def test_keyed_reads_a_header_value_by_name():
    header = "# nstates 70 nalg 250 time %s" % en(0.5)
    assert ssa._keyed(header, "nstates") == 70.0
    assert ssa._keyed(header, "time") == pytest.approx(0.5)
    assert ssa._keyed(header, "absent") is None


def test_read_modes_parses_the_engines_own_output():
    modes, header = ssa._read_modes((FIXTURES / "kundur_nopss_modes.dat").read_text())

    assert header["format_version"] == 2
    assert header["nstates"] == len(modes)
    assert header["nalg"] > 0
    assert header["pf_floor"] > 0.0
    assert modes["index"][0] == 1
    assert np.all(np.diff(modes["index"]) == 1)
    # Power system spectra are heavily degenerate; both flags occur here.
    assert modes["simple"].any()
    assert (~modes["simple"]).any()
    # One mode near 0.62 Hz with negative damping: the unstable inter-area mode.
    band = (modes["freq"] > 0.4) & (modes["freq"] < 0.9) & (modes["im"] > 0)
    assert band.sum() == 1
    assert modes["zeta"][band][0] < 0.0


def test_read_modes_reads_smp_from_the_v2_column():
    modes, _ = ssa._read_modes(
        V2_HEADER + modes_line(1, -0.5, 3.9, 0.13, 0.62, 1) + "\n")
    assert modes["simple"][0]
    assert modes["re"][0] == pytest.approx(-0.5)
    assert modes["freq"][0] == pytest.approx(0.62)


def test_read_modes_refuses_v1_naming_the_engine_version():
    text = ("# STEPSS SSA modes v1\n"
            + modes_line(1, -0.5, 3.9, 0.13, 0.62, smp=1, dom=0) + "\n")
    with pytest.raises(RAMSESError, match="older than 3.79"):
        ssa._read_modes(text)


def test_read_modes_refuses_a_newer_version():
    text = ("# STEPSS SSA modes v3\n"
            + modes_line(1, -0.5, 3.9, 0.13, 0.62, 1) + "\n")
    with pytest.raises(RAMSESError, match="version 3"):
        ssa._read_modes(text)


def test_read_modes_refuses_a_file_with_no_banner():
    with pytest.raises(RAMSESError, match="banner"):
        ssa._read_modes(modes_line(1, -0.5, 3.9, 0.13, 0.62, 1) + "\n")


def test_read_modes_refuses_a_banner_with_no_rows():
    with pytest.raises(RAMSESError, match="no mode rows"):
        ssa._read_modes(V2_HEADER)
