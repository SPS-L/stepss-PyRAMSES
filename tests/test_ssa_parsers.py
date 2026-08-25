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


def pf_line(mode, state, pf, family, device, variable):
    """One row at the offsets (i8,1x,i8,1x,en24.15,1x,a8,1x,a20,1x,a20) produces."""
    return "%8d %8d %s %-8s %-20s %-20s" % (mode, state, en(pf), family, device,
                                            variable)


def ms_line(mode, state, magnitude, angle_deg, device):
    """One row at the offsets (i8,1x,i8,1x,2(en24.15,1x),a20) produces."""
    return "%8d %8d %s %s %-20s" % (mode, state, en(magnitude), en(angle_deg),
                                    device)


def test_read_pf_parses_the_engines_own_output():
    rows = ssa._read_pf((FIXTURES / "kundur_nopss_pf.dat").read_text())
    assert rows
    # Normalisation puts one entry at exactly 1 in every mode, so no mode can
    # be emptied by the floor: a mode missing from a v2 file means the file is
    # incomplete.
    for entries in rows.values():
        assert max(e.pf for e in entries) == pytest.approx(1.0)
        assert [e.pf for e in entries] == sorted((e.pf for e in entries),
                                                 reverse=True)
    assert any(e.variable == "omega" for entries in rows.values() for e in entries)


def test_read_pf_keeps_a_device_name_with_an_embedded_blank():
    """Splitting on whitespace shifts every field after such a name."""
    text = ("# STEPSS SSA participation factors v2\n"
            + pf_line(3, 7, 0.5, "SYN", "g 1", "omega") + "\n")
    rows = ssa._read_pf(text)
    assert rows[3][0].device == "g 1"
    assert rows[3][0].variable == "omega"
    assert rows[3][0].family == "SYN"


def test_read_pf_keeps_a_leading_blank_in_a_device_name():
    text = ("# STEPSS SSA participation factors v2\n"
            + pf_line(3, 7, 0.5, "SYN", " g1", "omega") + "\n")
    assert ssa._read_pf(text)[3][0].device == " g1"


def test_read_pf_of_an_empty_file_is_empty():
    assert ssa._read_pf("") == {}


def test_read_ms_parses_the_engines_own_output():
    rows = ssa._read_ms((FIXTURES / "kundur_nopss_ms.dat").read_text())
    assert rows
    for entries in rows.values():
        assert max(e.magnitude for e in entries) == pytest.approx(1.0)
        # Angles are relative to the largest entry, which therefore sits at 0.
        reference = max(entries, key=lambda e: e.magnitude)
        assert reference.angle_deg == pytest.approx(0.0, abs=1e-9)


def test_read_ms_keeps_file_order():
    """File order is state order, and the phase reference is a row in it."""
    text = ("# STEPSS SSA mode shapes v2\n"
            + ms_line(1, 9, 0.4, -178.0, "g4") + "\n"
            + ms_line(1, 3, 1.0, 0.0, "g1") + "\n")
    assert [e.device for e in ssa._read_ms(text)[1]] == ["g4", "g1"]
