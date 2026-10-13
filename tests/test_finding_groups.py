"""FR-X.15c: repeated findings are grouped in what a person reads, and kept
one per item in the data.

The maintainer, 2026-09-30, after a 24-channel build printed about sixty notes:
*"The notes noise is way too much."* Every finding here is built in the
test (CLAUDE.md: a test never reads `examples/`), shaped like the ones
that build printed.
"""

from __future__ import annotations

from atoo import finding_groups as fg
from atoo.diagnostics import Diagnostic, Severity, render
from atoo.verify_plan import VerifyResult


def _override(n: int, name: str, preset: str, was: float, now: float) -> Diagnostic:
    """`preset_expand`'s preset.overridden, as a real build writes it."""
    return Diagnostic(
        Severity.INFO, "preset.overridden",
        f"ch {n} ({name!r}): the plan's own processing wins at 2 address(es) the preset "
        f"{preset!r} also sets -- flt/lcf preset {was} -> plan {now}; flt/lc 1 (both agree)",
        where=f"channels[{n}]", source="build")


def _unstated(n: int, name: str) -> str:
    """`apply`'s per-strip warning, as a journal holds it."""
    return (f"ch {n} ({name!r}): patch socket was not stated in the input list and was "
            "assigned during generation -- verify before trusting this write")


def _unused(section: str, line: str, message: str) -> Diagnostic:
    """`conventions_audit.findings_from_plan`'s conventions.unused."""
    return Diagnostic(
        Severity.INFO, "conventions.unused", f'{message} -- quoting "{line}"',
        where=f"conventions § {section}", category=section, line=line,
        fix="drop it for shows like this one, or give it members", source="build")


def _empty(kind: str, label: str, name: str) -> Diagnostic:
    return Diagnostic(Severity.INFO, "group.empty",
                      f"{label} {name!r} is declared but no channel or bus joins it -- "
                      "it does nothing", where=f"plan.{kind}[{name}]", source="verify")


# ---- the default rule --------------------------------------------------

def test_one_entry_for_the_same_note_on_many_channels():
    found = [_override(1, "Kick", "Kick In", 37.9, 40.0),
             _override(2, "Snare", "Snare", 89.9, 40.0),
             _override(3, "Hi-hat", "Hi Hat", 200.0, 40.0),
             _override(16, "DSR Vox", "Vocal Beta58", 100.2, 120.0)]
    entries = fg.groups(found)
    assert len(entries) == 1
    entry = entries[0].entry
    # The items, compactly -- not one name per line.
    assert entry.where == "ch 1-3, 16 (4 channels)"
    # A numeric slot that differs shows its range; a name that differs
    # shows "…"; what every member shares is shown as it is.
    assert entry.message == ("the plan's own processing wins at 2 address(es) the preset … "
                             "also sets -- flt/lcf preset 37.9..200.0 -> plan 40.0..120.0; "
                             "flt/lc 1 (both agree)")
    assert entry.severity == Severity.INFO and entry.code == "preset.overridden"
    assert entries[0].members == found


def test_the_apostrophe_in_plans_is_not_a_quote():
    """"the plan's own ... the preset 'Synth'" -- read as one quoted slot
    from the apostrophe on, every preset name made its own template and
    nothing grouped."""
    tmpl, values = fg.template("the plan's own processing: the preset 'Synth' also sets")
    assert values == ("'Synth'",)
    assert "plan's" in tmpl


def test_grouping_never_changes_the_list_it_is_given():
    found = [_override(n, f"ch{n}", "P", 10.0, 40.0) for n in range(1, 6)]
    before = list(found)
    fg.group(found)
    render(found)
    assert found == before


def test_a_warning_groups_only_when_it_says_exactly_the_same_thing():
    """Something to act on never has a value hidden behind a summary."""
    same = [Diagnostic(Severity.WARNING, "x.w", f"ch {n} ('C{n}'): socket not stated")
            for n in (1, 2, 3)]
    assert len(fg.group(same)) == 1
    differing = [Diagnostic(Severity.WARNING, "x.w", f"ch {n} ('C{n}'): gain {g} dB out of range")
                 for n, g in ((1, 90), (2, 95))]
    assert fg.group(differing) == differing


def test_severity_is_part_of_the_key():
    """A WARNING group stays a WARNING, and an ERROR shares an entry with
    nothing but ERRORs."""
    mixed = [Diagnostic(Severity.ERROR, "x.y", "ch 1 ('A'): broken"),
             Diagnostic(Severity.INFO, "x.y", "ch 2 ('B'): broken"),
             Diagnostic(Severity.WARNING, "x.y", "ch 3 ('C'): broken"),
             Diagnostic(Severity.WARNING, "x.y", "ch 4 ('D'): broken")]
    entries = fg.group(mixed)
    assert [e.severity for e in entries] == [Severity.ERROR, Severity.INFO, Severity.WARNING]
    assert entries[2].where == "ch 3-4 (2 channels)"
    errors = [Diagnostic(Severity.ERROR, "x.y", f"ch {n} ('C'): broken") for n in (5, 6)]
    [grouped] = fg.group(errors)
    assert grouped.severity == Severity.ERROR


def test_a_finding_about_no_nameable_item_is_never_grouped():
    """A critic's free-text `where`, a model's own note: nothing to list,
    so nothing to group them under."""
    notes = [Diagnostic(Severity.WARNING, "critic.intent", "Trim left null", where="Kick"),
             Diagnostic(Severity.WARNING, "critic.intent", "Trim left null", where="Snare")]
    assert fg.group(notes) == notes


def test_different_codes_never_share_an_entry():
    a = Diagnostic(Severity.INFO, "a.b", "x", where="busses[Drums]")
    b = Diagnostic(Severity.INFO, "a.c", "x", where="busses[Keys]")
    assert fg.group([a, b]) == [a, b]


def test_where_items_keep_the_where_syntax():
    found = [Diagnostic(Severity.INFO, "a.b", "left as it was", where=f"busses[{b}].processing")
             for b in ("Drums", "Keys", "VOX Reverb")]
    [entry] = fg.group(found)
    assert entry.where == "busses[Drums, Keys, VOX Reverb].processing (3 busses)"


def test_a_long_list_of_names_is_capped():
    found = [Diagnostic(Severity.INFO, "a.b", "same", where=f"busses[B{i:02}]")
             for i in range(fg.MAX_NAMES + 4)]
    [entry] = fg.group(found)
    assert entry.where.endswith(f"and 4 more] ({fg.MAX_NAMES + 4} busses)")


# ---- per-code summaries ------------------------------------------------

def test_unused_conventions_become_one_list_with_one_fix():
    found = [_unused("DCAs", "Tracks: all tracks- or trax- category channels", "no tracks"),
             _unused("DCAs", "Strings: all strings-category channels", "no strings"),
             _unused("DCAs", "Horns: all horns-category channels", "no horns"),
             _unused("Mute Groups", "Speech: All speech channels", "no speech"),
             _unused("Busses", 'If there are multiple keyboards, create a "Keys" bus.', "one kb")]
    [entry] = fg.group(found)
    assert entry.message == ("declared but unused in this show (5): DCAs Horns, Strings, "
                             "Tracks; Mute Groups Speech; Busses Keys")
    assert entry.fix == "drop it for shows like this one, or give it members"
    assert entry.where == "conventions"
    text = render(found)
    assert text.count("Fix:") == 1
    assert text.count("(conventions.unused)") == 1


def test_an_unused_note_quoting_several_lines_stands_on_its_own():
    """Its first quote's section is all the finding records -- listing its
    other names there could put a mute group among the DCAs."""
    several = Diagnostic(
        Severity.INFO, "conventions.unused",
        'no speech -- quoting "Speech: Hosts, MCs"; "Speech: All speech channels"',
        where="conventions § DCAs", category="DCAs", line="Speech: Hosts, MCs",
        fix="drop it for shows like this one, or give it members", source="build")
    one = _unused("DCAs", "Tracks: all tracks", "no tracks")
    other = _unused("DCAs", "Horns: all horns", "no horns")
    entries = fg.group([several, one, other])
    assert entries[0] is several
    assert entries[1].message == "declared but unused in this show (2): DCAs Horns, Tracks"


def test_empty_dcas_and_mute_groups_become_one_list():
    found = [_empty("dcas", "DCA", n) for n in ("Tracks", "Strings", "Horns", "Speech")]
    found.append(_empty("mute_groups", "mute group", "Speech"))
    [entry] = fg.group(found)
    assert entry.where == "DCAs Horns, Speech, Strings, Tracks; mute group Speech"
    assert entry.message == "declared, but no channel or bus joins them -- they do nothing"
    assert str(entry).startswith("[info] DCAs Horns")


def test_an_inferred_value_stays_exact_and_its_reasons_are_listed_once():
    """CLAUDE.md: an inferred value must announce itself. Grouped, every
    bus is still named and the value decided is still stated exactly --
    only the repetition goes."""
    def width(bus, value, basis):
        return Diagnostic(Severity.INFO, "inferred.bus-width",
                          f"width set to {value} -- the conventions did not state it; "
                          f"decided by the generator: {basis}", where=f"busses[{bus}]")
    mix = "Mix Busses heading: 'These are stereo busses'"
    fx = "FX Busses heading: 'These are stereo busses'"
    found = [width("Drums", "stereo", mix), width("Vocals", "stereo", mix),
             width("VOX Reverb", "stereo", fx), width("MON1", "mono", "a wedge")]
    entries = fg.group(found)
    assert len(entries) == 2
    assert entries[0].where == "busses[Drums, Vocals, VOX Reverb] (3 busses)"
    assert entries[0].message == ("width set to stereo -- the conventions did not state it; "
                                  f"decided by the generator: {mix} / {fx}")
    assert entries[1] is found[3]


def test_send_levels_on_many_busses_are_one_entry():
    def level(bus, n, channels):
        return Diagnostic(
            Severity.INFO, "inferred.send-level",
            f"sends into {bus} set to 0 dB on {n} channel(s) ({channels}) -- the plan states "
            f"no level for them; decided by Atoo's fallback rule: a post-fader send "
            f"starts at unity; left unset, a fresh desk's -144 would leave {bus} silent",
            where=f"busses[{bus}]", source="verify")
    found = [level("Drums", 3, "Kick, Snare, Hat"), level("Keys", 2, "Keys 1, Keys 2")]
    [entry] = fg.group(found)
    assert entry.where == "busses[Drums, Keys] (2 busses)"
    assert entry.message.startswith("sends set to 0 dB on 5 channel send(s) in all -- ")
    assert entry.message.endswith("would leave the bus silent")


# ---- where it is used --------------------------------------------------

def test_render_prints_one_block_and_can_still_print_each():
    found = [_override(n, f"C{n}", "P", 20.0, 40.0) for n in range(1, 23)]
    grouped = render(found)
    assert grouped.count("(preset.overridden)") == 1
    assert "ch 1-22 (22 channels)" in grouped
    assert render(found, group=False).count("(preset.overridden)") == 22


def test_verify_report_groups_lines_and_keeps_the_counts():
    r = VerifyResult()
    for f in [_empty("dcas", "DCA", n) for n in ("A", "B", "C")]:
        r.findings.append(f)
    text = r.report()
    assert text.startswith("0 error(s), 0 warning(s), 3 note(s)")
    assert text.count("(group.empty)") == 1
    assert len(r.findings) == 3


def test_apply_warning_lines_group_and_infos_stay_apart():
    lines = [_unstated(n, f"C{n}") for n in range(1, 24)]
    lines.append("INFO 24 strip(s) set to their main input")
    lines.append("channel 30 ('X'): unrecognized bank 'zz' -- treated as 'ch'")
    assert fg.group_lines(lines) == [
        "ch 1-23 (23 channels): patch socket was not stated in the input list and was "
        "assigned during generation -- verify before trusting this write",
        "INFO 24 strip(s) set to their main input",
        "channel 30 ('X'): unrecognized bank 'zz' -- treated as 'ch'",
    ]
    # A single line is printed exactly as it was.
    assert fg.group_lines([_unstated(4, "Tom")]) == [_unstated(4, "Tom")]


def test_group_dicts_passes_singles_through_and_lists_members():
    found = [_override(n, f"C{n}", "P", 20.0, 40.0).to_dict() for n in (1, 2)]
    single = {"severity": "warning", "code": "critic.intent", "message": "m",
              "where": "Kick", "_ui_only": True}
    out = fg.group_dicts(found + [single])
    assert out[1] is single
    assert out[0]["where"] == "ch 1-2 (2 channels)"
    assert out[0]["members"] == found
    # Not a finding this build would write: shown as it is.
    odd = {"message": "no severity at all"}
    assert fg.group_dicts([odd]) == [odd]


def test_output_indexes_decided_alike_share_an_entry():
    """Main 1 and Matrix 1 both filled with 1 by the fallback rule: one
    line, both outputs named, the index exact, both reasons given."""
    def index(name, strip, basis):
        return Diagnostic(Severity.INFO, "inferred.output-index",
                          f"{strip} index set to 1 -- the plan left it out; decided by "
                          f"Atoo's fallback rule: {basis}", where=f"outputs[{name}]")
    found = [index("Main", "Main", "the plan has one Main, so it is Main 1"),
             index("Matrix 1", "Matrix", "its name, 'Matrix 1', states slot 1"),
             Diagnostic(Severity.INFO, "inferred.output-index",
                        "Matrix index set to 2 -- the plan left it out; decided by "
                        "Atoo's fallback rule: next free", where="outputs[Mx]")]
    entries = fg.group(found)
    assert len(entries) == 2
    assert entries[0].where == "outputs[Main, Matrix 1] (2 outputs)"
    assert entries[0].message == (
        "index set to 1 -- the plan left it out; decided by Atoo's fallback rule: "
        "the plan has one Main, so it is Main 1 / its name, 'Matrix 1', states slot 1")
    assert entries[1] is found[2]
