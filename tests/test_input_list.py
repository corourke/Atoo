from pathlib import Path

import pytest

from atoo.input_list import (
    _GROUP_ALIASES,
    CANONICAL_COLUMNS, InputListError, InputRow, format_socket, load_input_list, parse_input_list,
    parse_socket_spec,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_smallband_fixture():
    rows = load_input_list(str(FIXTURES / "smallband.csv"))
    assert len(rows) == 9
    assert rows[0] == InputRow(
        name="Kick", category="drums", type="Mic", phantom=False,
        model="Beta 52", notes="", patch="",
    )
    overheads = next(r for r in rows if r.name == "Overheads")
    assert overheads.phantom is True
    elec_gtr = next(r for r in rows if r.name == "Elec Gtr")
    assert elec_gtr.model == ""
    bass = next(r for r in rows if r.name == "Bass")
    assert bass.patch == "LCL 9"


def test_patch_column_is_optional():
    # No patch column at all -- every row's patch defaults to "", not
    # an error. Auto-assignment (compiler.py) is what makes this usable.
    text = "name,category,type,phantom\nKick,drums,Mic,FALSE\n"
    rows = parse_input_list(text)
    assert rows[0].patch == ""


@pytest.mark.parametrize("header", ["patch", "socket"])
def test_the_patch_column_is_read_under_either_name(header):
    """The column is `patch` now; a list written before then
    heads it `socket`, and must read exactly the same."""
    text = f"{header},name,category,type,phantom\nAES50-A 3,Kick,drums,Mic,FALSE\n,Snare,drums,Mic,FALSE\n"
    rows = parse_input_list(text)
    assert [r.patch for r in rows] == ["AES50-A 3", ""]


def test_a_header_with_both_names_reads_patch():
    """Both columns present: `patch` is the one the format names now."""
    text = "socket,patch,name,category,type,phantom\nLCL 1,LCL 2,Kick,drums,Mic,FALSE\n"
    assert parse_input_list(text)[0].patch == "LCL 2"


def test_a_newly_written_list_is_headed_patch():
    assert CANONICAL_COLUMNS[:2] == ("order", "patch")
    assert "socket" not in CANONICAL_COLUMNS


def test_rejects_missing_required_column():
    text = "name,category,type\nKick,drums,Mic\n"
    with pytest.raises(InputListError, match="missing required column"):
        parse_input_list(text)


def test_the_desk_sheet_columns_are_read():
    """`channel`, `dca` and `mute_group`: the desk sheets'
    optional columns, which `atoo capture` writes."""
    text = ("name,category,type,phantom,channel,dca,mute_group\n"
            "Kick,drums,Mic,FALSE,9,Drum LEVELS,BAND; ALL\n"
            "Phone,playback,Line,FALSE,Aux 3,,\n"
            "Spare,other,Mic,FALSE,,,\n")
    kick, phone, spare = parse_input_list(text)
    assert (kick.channel, kick.dca, kick.mute_group) == (("ch", 9), ("Drum LEVELS",), ("BAND", "ALL"))
    assert phone.channel == ("aux", 3)
    assert (spare.channel, spare.dca, spare.mute_group) == (None, (), ())


@pytest.mark.parametrize("cell", ["41", "0", "Aux 9", "Bus 1", "nine"])
def test_a_channel_the_desk_does_not_have_is_refused(cell):
    text = f"name,category,type,phantom,channel\nKick,drums,Mic,FALSE,{cell}\n"
    with pytest.raises(InputListError, match="column 'channel' must be a desk channel"):
        parse_input_list(text)


def test_rejects_ch_column_and_says_where_the_channel_goes():
    text = "name,category,type,phantom,ch\nKick,drums,Mic,FALSE,1\n"
    with pytest.raises(InputListError, match="goes in the 'channel' column"):
        parse_input_list(text)


def test_rejects_stereo_column():
    """Every input socket on a WING is mono, so no ROW is
    stereo -- linking two sources into one channel is a decision made from
    the conventions and the names, not a property of an input.

    Refused rather than ignored, on purpose. A sheet whose 'Keys L' row
    says stereo=TRUE would load fine, have no effect whatsoever, and
    produce a plan that silently contradicts the sheet someone is reading
    off at the stage box."""
    text = "name,category,type,stereo,phantom\nKeys,band,Line,TRUE,FALSE\n"
    with pytest.raises(InputListError) as exc:
        parse_input_list(text)
    assert "'stereo'" in str(exc.value)
    assert "every input socket on a WING is mono" in str(exc.value)
    assert "conventions" in str(exc.value)        # says where it belongs instead


def test_the_forbidden_column_message_covers_all_of_them_at_once():
    text = "name,category,type,phantom,stereo,ch\nKick,drums,Mic,FALSE,TRUE,1\n"
    with pytest.raises(InputListError) as exc:
        parse_input_list(text)
    assert "'ch'" in str(exc.value) and "'stereo'" in str(exc.value)


def test_rejects_blank_name():
    text = "name,category,type,phantom\n,drums,Mic,FALSE\n"
    with pytest.raises(InputListError, match="'name' is required"):
        parse_input_list(text)


def test_every_blank_required_column_is_named_at_once():
    """One message for the row, not one per Save -- a row
    with a name and nothing else used to take two more round trips."""
    text = "name,category,type,phantom\nKick,drums,Mic,FALSE\nClick Track,,,FALSE\n"
    with pytest.raises(InputListError) as exc:
        parse_input_list(text)
    assert str(exc.value) == "row 3: 'category' and 'type' are required and cannot be blank"
    with pytest.raises(InputListError) as exc:
        parse_input_list("name,category,type,phantom\n,,,FALSE\n")
    assert str(exc.value) == "row 2: 'name', 'category' and 'type' are required and cannot be blank"


def test_rejects_duplicate_name():
    text = (
        "name,category,type,phantom\n"
        "Kick,drums,Mic,FALSE\n"
        "Kick,drums,Mic,FALSE\n"
    )
    with pytest.raises(InputListError, match="duplicate input name"):
        parse_input_list(text)


def test_rejects_bad_boolean():
    text = "name,category,type,phantom\nKick,drums,Mic,maybe\n"
    with pytest.raises(InputListError, match="must be TRUE or FALSE"):
        parse_input_list(text)


def test_rejects_empty_file():
    with pytest.raises(InputListError, match="no header row"):
        parse_input_list("")


def test_rejects_header_only():
    with pytest.raises(InputListError, match="no data rows"):
        parse_input_list("name,category,type,phantom\n")


def test_accepts_lowercase_booleans():
    text = "name,category,type,phantom\nKick,drums,Mic,false\n"
    rows = parse_input_list(text)
    assert rows[0].phantom is False


# --- Every group the console names must be spellable --------


@pytest.mark.parametrize("token", ["LCL", "SC", "USB", "CRD", "MOD", "AES", "PLAY", "AUX", "USR"])
def test_every_socket_group_parses_by_its_own_token(token):
    # Found: the alias table held only FRIENDLY names, so CRD,
    # MOD, AUX and USR -- the tokens the hardware, console_facts and the
    # engineer all use -- were silently refused by the socket column.
    # "CRD 64" has to mean CRD socket 64.
    assert parse_socket_spec(f"{token} 7") == (token, 7)


@pytest.mark.parametrize("written,expected", [
    ("AES50-A 12", ("A", 12)),
    ("AES50-B 33", ("B", 33)),
    ("AES50-C 1", ("C", 1)),
])
def test_aes50_networks_are_written_out(written, expected):
    assert parse_socket_spec(written) == expected


@pytest.mark.parametrize("written", ["A 1", "B 12", "C 3"])
def test_a_bare_aes50_letter_is_refused(written):
    # Deliberate: "A 1" is ambiguous, and "AES 1" (AES/EBU) vs
    # "AES50-A 1" is the substitution this project has already watched a
    # model make 19 times in a row. The network is spelled out or it is
    # not accepted.
    assert parse_socket_spec(written) is None


def test_format_socket_round_trips_through_parse_socket_spec():
    for written in ("AES50-A 12", "LCL 3", "AES 1", "CRD 64", "SC 24", "USB 30"):
        assert format_socket(*parse_socket_spec(written)) == written


# --- A friendly name that names the wrong hardware ----------


def test_sd_card_does_not_parse_as_the_expansion_card():
    # The bug this pins, found reviewing an earlier change: `"sdcard": "CRD"` meant
    # an input list reading "SD card 3" was patched to socket 3 of the
    # EXPANSION card. "CRD is the expansion
    # card, not the SD card. The SD card is used by WING LIVE." An earlier change
    # corrected `console_facts` and the reference doc and left this table
    # alone, so the wrong patch survived the fix to its own root cause.
    #
    # Refusing is the right answer, not re-pointing: the SD card is not
    # an input group at all. An unparsable socket is already
    # reported by `verify_plan`'s `patch.unparsable-stated-socket`.
    for written in ("SD card 3", "sdcard 3", "SD-CARD 3", "sd_card 3"):
        assert parse_socket_spec(written) is None, f"{written!r} must not resolve"


def test_the_expansion_card_still_parses_both_ways():
    # The other half: "card" IS the expansion card now, so it stays.
    assert parse_socket_spec("card 3") == ("CRD", 3)
    assert parse_socket_spec("CRD 3") == ("CRD", 3)


def test_dante_does_not_parse_as_either_bay():
    # An earlier change, settled 2026-09-21. Dante is sold BOTH ways: as the W-DANTE
    # extension card, which is `CRD`, and as an internal Dante module,
    # which is `MOD` (PDF p.256; `/cards.$type` has WDANTE, and
    # `/$syscfg.opt_mod` has DANTE). So "Dante 3" names a signal on one
    # of two different pieces of hardware and does not say which -- the
    # "SD card 3" failure one slot over, and the next alias somebody
    # would helpfully add. It must keep failing to parse, which
    # `verify_plan` already reports as `patch.unparsable-stated-socket`.
    # WSG is both a card (WDWSG) and a module too; same answer.
    for written in ("Dante 3", "dante 3", "W-DANTE 3", "WSG 3", "AoIP 3"):
        assert parse_socket_spec(written) is None, f"{written!r} must not resolve"
    # What an engineer who knows which bay theirs is in writes instead:
    assert parse_socket_spec("CRD 3") == ("CRD", 3)
    assert parse_socket_spec("MOD 3") == ("MOD", 3)
    assert parse_socket_spec("module 3") == ("MOD", 3)


def test_every_alias_targets_a_group_the_console_actually_has():
    # The structural half of the same lesson. Two alias tables describe
    # the socket vocabulary -- `console_facts.GROUP_ALIASES` (a label
    # rendered INTO the generate prompt) and this module's
    # `_GROUP_ALIASES` (a word read FROM what the user wrote) -- and an earlier change
    # is what it looks like when one is corrected and the other is not.
    # This can't check that a friendly name names the right hardware (no
    # table in this repo knows that), but it can check that every alias
    # lands on a group the console is documented to have.
    from atoo import console_facts

    for spelling, group in _GROUP_ALIASES.items():
        assert group in console_facts.INPUT_SOCKETS, (
            f"input-list alias {spelling!r} points at {group!r}, which is not an "
            f"input group in console_facts.INPUT_SOCKETS"
        )
