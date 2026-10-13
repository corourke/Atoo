"""`read_console_state(bulk=True)` fetches whole nodes with
the protocol's `,s *` node dump instead of one GET per leaf.

The speed is not the risk -- **agreement is**. A read that is fast and
subtly different from the slow one would make every report this tool
produces untrue in a way nobody could see. So the central test here
serves ONE table of values two ways, per-leaf and by dump, and requires
the two `ConsoleState`s to be identical.
"""

import pytest

from atoo.audit import (DUMP_UNSAFE_LEAVES, bulk_node_for,
                             console_read_plan, group_plan_by_node,
                             read_console_state, socket_groups_to_read)
from atoo import console_facts
from atoo.console import OscReply


# -- the plan is counted, not remembered -----------------------------------


def test_a_compact_reading_its_own_panel_asks_for_6143_addresses():
    # Counted, not pinned to a constant: this is the number
    # `cli.read_addresses` prints and `progress` divides by, and the
    # hand-maintained constant it replaced (5,928) had been stale for
    # two issues by the time anyone checked.
    #
    # 6,032. A11 read all 6,032 off real hardware and
    # got 5,712 values back; the 320 that never answered do not exist on
    # the console (`console_facts.SEND_LEAVES`), and 5,712 is exactly
    # what the desk answered.
    #
    # 5,808 once an earlier change added each of the 48 strips' alternate-patch
    # group and switch (`in/conn/altgrp`, `in/set/altsrc`), which A7 read
    # off the same desk.
    #
    # 6,112: every insert point's switch and slot (288 --
    # four leaves on a channel, bus, Main and Matrix, two on an aux) and
    # `/fx/{1..16}/mdl`.
    #
    # 6,113 since the comms half: `/cfg/talk/assign` (T001).
    # Where TALK A and B are routed is second-pass, and only when assigned.
    #
    # 6,114 since the global alternate switch, `/io/altsw` (C005).
    #
    # 6,143 since an earlier change (three AES50 link states, two monitor
    # sources); 6,138: each phantom-capable socket's width
    # (`/io/in/{grp}/{n}/mode`, 8 LCL + 16 A), so C001 can tell the even
    # socket of a stereo pair is taken. Same `/io/in` node as `vph`.
    inputs, outputs = socket_groups_to_read("wing-compact")
    plan = console_read_plan(input_sockets=inputs, output_sockets=outputs)
    assert len(plan) == 6143
    assert len(set(a for a, _ in plan)) == 6143, "no address is read twice"


def test_the_320_addresses_the_desk_never_answers_are_no_longer_asked_for():
    """An earlier change, and the arithmetic is the evidence: 16 busses x 8
    matrices x 2 leaves + 4 Mains x 8 x 2 = 320, which is exactly the
    number A11 measured as unanswered and exactly 6,032 - 5,712.

    Spelled in literals rather than derived from `SEND_LEAVES`: a table
    compared against itself passes whatever it says."""
    inputs, outputs = socket_groups_to_read("wing-compact")
    asked = {a for a, _ in console_read_plan(input_sockets=inputs,
                                             output_sockets=outputs)}
    phantom = {f"/{bank}/{n}/send/MX{m}/{leaf}"
               for bank, count in (("bus", 16), ("main", 4))
               for n in range(1, count + 1)
               for m in range(1, 9)
               for leaf in ("mode", "pon")}
    assert len(phantom) == 320
    assert not (asked & phantom)
    # ...and the ones beside them, which the desk does answer, are still read.
    assert "/bus/16/send/MX8/on" in asked
    assert "/bus/16/send/MX8/lvl" in asked
    assert "/main/4/send/MX8/on" in asked
    assert "/main/4/send/MX8/lvl" in asked
    # A strip's send is a different object and keeps all four.
    assert "/ch/40/send/MX8/mode" in asked
    assert "/ch/40/send/MX8/pon" in asked
    assert "/aux/8/send/MX8/mode" in asked
    assert "/aux/8/send/16/pon" in asked


def test_a_bank_nobody_measured_is_asked_for_everything():
    """The default posture, and it points the safe way: skipping an
    address we were wrong about loses a value silently, asking for one we
    were wrong about costs three seconds and an honest "unanswered"."""
    assert console_facts.send_has_leaf("nosuchbank", "mode") is True
    assert console_facts.send_has_leaf("ch", "mode") is True
    assert console_facts.send_has_leaf("aux", "pon") is True
    assert console_facts.send_has_leaf("bus", "mode") is False
    assert console_facts.send_has_leaf("bus", "pon") is False
    assert console_facts.send_has_leaf("main", "mode") is False
    assert console_facts.send_has_leaf("bus", "on") is True
    assert console_facts.send_has_leaf("bus", "lvl") is True


def test_the_plan_contacts_nothing():
    # It is called before the console is opened, by `cli.watch_cmd`, to
    # say how long the wait will be.
    assert console_read_plan(channels=1, aux=0, buses=1, mains=1, matrices=1,
                             dcas=0, mute_groups=0)[0] == ("/ch/1/name", "s")


def test_node_dumps_take_6143_addresses_down_to_323_requests():
    inputs, outputs = socket_groups_to_read("wing-compact")
    plan = console_read_plan(input_sockets=inputs, output_sockets=outputs)
    by_node, alone = group_plan_by_node(plan)
    assert len(by_node) == 164
    # The 154 left over are names and tags, never taken from a dump, the
    # sixteen FX slots' `mdl`, which have no node, and
    # `/cfg/talk/assign` (the comms half), which has none either,
    # and `/io/altsw` (C005), likewise.
    # The 288 insert leaves an earlier change added ride inside nodes already fetched.
    # 159 since an earlier change added the three AES50 ports' link status
    # and the two monitor sources, none of which has a node either.
    assert len(alone) == 159
    assert len([a for a, _ in alone if a.startswith("/fx/")]) == 16
    assert [a for a, _ in alone if a.startswith("/cfg/")] == [
        "/cfg/talk/assign", "/cfg/mon/1/src", "/cfg/mon/2/src"]
    assert [a for a, _ in alone if a.startswith("/$stat/")] == [
        "/$stat/A/stat", "/$stat/B/stat", "/$stat/C/stat"]
    assert len(by_node) + len(alone) == 323
    # 323 is now a watch's FIRST pass and every refresh pass.
    # 88 of the 159 left over are names (40 ch, 8 aux, 16 bus, 16 DCA,
    # 8 mute groups), which a pass between refreshes takes from the last
    # refresh -- so that pass is 235. `tests/test_watch_name_refresh.py`
    # counts both at a desk.
    assert len([a for a, _ in alone if a.endswith("/name")]) == 88
    assert len(by_node) + len(alone) - 88 == 235


def test_a_name_or_a_tag_is_never_covered_by_a_dump():
    assert DUMP_UNSAFE_LEAVES == ("name", "tags")
    assert bulk_node_for("/ch/1/name") is None
    assert bulk_node_for("/ch/1/tags") is None
    assert bulk_node_for("/dca/3/name") is None
    # ...but a leaf that merely ENDS with those letters is not one.
    assert bulk_node_for("/ch/1/in/conn/grp") == "/ch/1"
    assert bulk_node_for("/ch/1/send/3/lvl") == "/ch/1"
    assert bulk_node_for("/io/out/LCL/5/grp") == "/io/out/LCL/5"


def test_an_address_with_no_node_is_read_on_its_own():
    assert bulk_node_for("/nosuchroot/1/x") is None
    assert bulk_node_for("/ch") is None
    assert bulk_node_for("/ch/1") is None, "a node is not covered by its own dump"


# -- one desk, served two ways, must read the same -------------------------


class TwoWayConsole:
    """A fake desk holding one table of `address -> text value`, which
    answers a per-leaf GET and a node dump from the same table -- in the
    reply shapes the protocol PDF documents for each.

    `omit_from_dumps` leaves an address out of every dump without
    removing it from the desk: that is the case where a dump does not
    mention a leaf, and the read must go and ask rather than record a
    default.
    """

    console_model = "wing-compact"

    def __init__(self, values, *, omit_from_dumps=(), broken_nodes=(),
                 dump_says=None):
        self.values = values
        self.omit_from_dumps = set(omit_from_dumps)
        self.broken_nodes = set(broken_nodes)
        self.dump_says = dump_says or {}
        self.gets = []
        self.dumps = []

    # per-leaf: the `,sff` / `,sfi` / `,s` shapes of PDF p21
    def get(self, address):
        self.gets.append(address)
        if address not in self.values:
            return None
        text = self.values[address]
        try:
            number = -144.0 if text == "-oo" else float(text)
        except ValueError:
            return OscReply(address, "s", [text])
        if float(number).is_integer() and "." not in text and text != "-oo":
            # An earlier change, and the reason this fake is not simpler: for a
            # patch connector the desk's INT argument is one less than
            # the number it shows and than its own text argument
            # (hardware: 2026-09-21/A1-raw.log, `/ch/7/in/conn/in` ->
            # ['6', 0.0794, 5]). A fake that answered 6 in both would
            # hide exactly the bug this file is here to catch.
            offset = console_facts.readback_index_offset(address) or 0
            return OscReply(address, "sfi", [text, 0.0, int(number) - offset])
        return OscReply(address, "sff", [text, 0.0, number])

    # the node dump of PDF p24-25
    def node_dump(self, node):
        self.dumps.append(node)
        if node in self.broken_nodes:
            return None
        if node in self.dump_says:
            return self.dump_says[node]
        # Spelled the way the console spells it (PDF p25): leading dots
        # climb back out of wherever the last item left us, then names
        # descend. A fake that just wrote `send.1.on=0,send.1.lvl=-oo`
        # would be testing a grammar WING does not use.
        items, path = [], []
        for address, text in self.values.items():
            if not address.startswith(node + "/") or address in self.omit_from_dumps:
                continue
            segments = address[len(node) + 1:].split("/")
            items.append("." * len(path) + ".".join(segments) + f"={text}")
            path = segments[:-1]
        return ",".join(items) + ("," if items else "")


SMALL = dict(channels=1, aux=0, buses=1, mains=1, matrices=0, dcas=1,
             mute_groups=0, fx_slots=1)

# A desk that answers for EVERY address the plan asks for, so that a
# leaf read one at a time is a deliberate fallback rather than an
# accident of the fixture. Interesting values where they matter --
# `-oo`, a patched connector, a non-default send mode -- and plausible
# ones elsewhere.
INTERESTING = {
    "/ch/1/name": "Kick", "/ch/1/mute": "1", "/ch/1/fdr": "-2.0",
    "/ch/1/tags": "#D1", "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": "6",
    "/ch/1/send/1/lvl": "-oo", "/ch/1/send/1/mode": "POST",
    "/bus/1/name": "Mains", "/dca/1/name": "Drums",
}
DEFAULTS = {"s": "OFF", "i": "0", "f": "0.0"}
DESK = {address: INTERESTING.get(address, DEFAULTS[value_type])
        for address, value_type in console_read_plan(**SMALL)}


def read_both_ways(**kwargs):
    per_leaf = TwoWayConsole(DESK, **kwargs)
    bulk = TwoWayConsole(DESK, **kwargs)
    return (read_console_state(per_leaf, **SMALL),
            read_console_state(bulk, bulk=True, **SMALL),
            per_leaf, bulk)


def test_both_paths_read_the_same_desk_the_same_way():
    slow, fast, slow_console, fast_console = read_both_ways()
    assert fast.values == slow.values
    assert len(fast_console.gets) < len(slow_console.gets)


def test_the_fast_path_really_did_use_dumps():
    _, _, slow_console, fast_console = read_both_ways()
    assert fast_console.dumps == ["/ch/1", "/bus/1", "/main/1", "/dca/1"]
    assert slow_console.dumps == []
    # Only the free-text leaves were fetched one at a time -- plus the
    # second pass for the one patched strip: its source socket's name, which is a `name` and therefore `DUMP_UNSAFE_LEAVES`
    # anyway, and its `clink`. Neither could have been asked
    # of a node dump, because which socket to ask about is not knowable
    # until the patch has been read. And the FX slot's model,
    # which `BULK_NODE_DEPTH` deliberately has no node for, and the one
    # talkback address, which has no node either.
    assert sorted(fast_console.gets) == [
        "/bus/1/name", "/cfg/talk/assign", "/ch/1/clink", "/ch/1/name", "/ch/1/tags",
        "/dca/1/name", "/fx/1/mdl", "/io/altsw", "/io/in/LCL/6/name"]


def test_a_patch_index_from_a_dump_is_not_offset_corrected():
    # The per-leaf reply's INT argument is one less than the number the
    # desk shows, so every per-leaf call site applies
    # `console_facts.correct_readback_index`. A dump carries
    # the TEXT form, which is already the desk's number -- correcting it
    # again would report socket 7 for a channel patched to 6.
    slow, fast, _, _ = read_both_ways()
    assert slow.number("/ch/1/in/conn/in") == 6
    assert fast.number("/ch/1/in/conn/in") == 6


def test_a_level_at_minus_infinity_agrees_between_the_two_paths():
    slow, fast, _, _ = read_both_ways()
    assert slow.number("/ch/1/send/1/lvl") == fast.number("/ch/1/send/1/lvl") == -144.0


# -- what a dump does NOT carry ---------------------------------------------


def test_a_leaf_a_dump_omits_is_read_on_its_own_not_defaulted():
    # The failure this guards against is the quiet one: an absent leaf
    # recorded as 0/"" would make the audit report a send that is off
    # and a channel that is unpatched, from a desk where neither is true.
    omitted = "/ch/1/send/1/lvl"
    slow, fast, _, fast_console = read_both_ways(omit_from_dumps=[omitted])
    assert omitted in fast_console.gets
    assert fast.number(omitted) == -144.0
    assert fast.values == slow.values


def test_a_node_whose_dump_fails_falls_back_to_every_leaf_of_it():
    slow, fast, _, fast_console = read_both_ways(broken_nodes=["/ch/1"])
    assert fast.values == slow.values
    assert "/ch/1/send/1/mode" in fast_console.gets
    assert "/bus/1/mute" not in fast_console.gets, "only the broken node fell back"


def test_a_dump_this_parser_will_not_guess_at_falls_back_whole():
    # An unquoted comma in a free-text value is what this looks like from
    # here. Half a parsed dump is worse than none: the unparsed half
    # would read as "the console did not say".
    slow, fast, _, fast_console = read_both_ways(
        dump_says={"/ch/1": "mute=1,fdr=-2.0,in.conn.grp=LCL, oops,"})
    assert fast.values == slow.values
    assert "/ch/1/mute" in fast_console.gets


def test_a_dump_value_of_the_wrong_type_falls_back_for_that_leaf_only():
    slow, fast, _, fast_console = read_both_ways(
        dump_says={"/ch/1": "mute=NOTANUMBER,fdr=-2.0,"})
    assert "/ch/1/mute" in fast_console.gets
    assert "/ch/1/fdr" not in fast_console.gets
    assert fast.number("/ch/1/fdr") == -2.0


def test_a_name_in_a_dump_is_ignored_in_favour_of_the_leaf_read():
    # The dump is free to claim anything about a name; this path does not
    # listen. `a11-read-speed.sh` is what measures whether it could.
    _, fast, _, _ = read_both_ways(
        dump_says={"/ch/1": "name=WRONG,mute=1,fdr=-2.0,tags=WRONG,"
                            "in.conn.grp=LCL,in=6,send.1.on=1,lvl=-oo,"
                            "mode=POST,pon=0,..main.1.on=1,"})
    assert fast.text("/ch/1/name") == "Kick"
    assert fast.text("/ch/1/tags") == "#D1"


# -- progress reporting through the read ------------------------------------


class CountingProgress:
    def __init__(self):
        self.started, self.answered, self.unanswered = [], 0, 0
        self.total = 0

    def set_total(self, total):
        self.total = total

    def add_total(self, extra=1):
        self.total += extra

    def start_address(self, address):
        self.started.append(address)

    def finish_address(self, *, answered):
        if answered:
            self.answered += 1
        else:
            self.unanswered += 1


def test_the_address_is_reported_before_the_request_goes_out():
    # A stall has to be attributable. The whole value of naming the
    # address is that when the line stops moving, the address on it is
    # the one timing out -- which is only true if it is reported BEFORE
    # the request rather than after it.
    events = []

    class Ordered(TwoWayConsole):
        def get(self, address):
            events.append(("get", address))
            return super().get(address)

    class Watching(CountingProgress):
        def start_address(self, address):
            events.append(("start", address))
            super().start_address(address)

    read_console_state(Ordered(DESK), progress=Watching(), **SMALL)
    assert events[0] == ("start", "/ch/1/name")
    assert events[1] == ("get", "/ch/1/name")
    starts = [e for e in events if e[0] == "start"]
    gets = [e for e in events if e[0] == "get"]
    assert len(starts) == len(gets)
    assert all(events[i * 2][1] == events[i * 2 + 1][1] for i in range(len(gets)))


def test_the_read_reports_every_address_it_asks_for():
    progress = CountingProgress()
    read_console_state(TwoWayConsole(DESK), progress=progress, **SMALL)
    plan = console_read_plan(**SMALL)
    # The plan, and then the second pass the plan cannot contain: for
    # every patched strip, its source socket's name and its
    # `clink`. `/ch/1` is on LCL 6 in this fixture and it is
    # the only patched strip, so there are exactly two.
    assert progress.started == [a for a, _ in plan] + ["/io/in/LCL/6/name",
                                                       "/ch/1/clink"]
    # A per-leaf read never calls `set_total` -- the CLI sizes the bar
    # from `console_read_plan` before the read starts -- so this counter
    # holds exactly what the second pass ADDED to the denominator. Two,
    # rather than the bar going past 100%.
    assert progress.total == 2
    assert progress.answered == len(DESK)
    assert progress.unanswered == len(plan) + 2 - len(DESK)


def test_an_unpatched_desk_costs_nothing_extra_for_source_names():
    """The budget, stated as a test (and the lesson). The
    second pass asks about a SOCKET, so a strip patched to nothing has
    nothing to ask about and the read is the plan and no more."""
    unpatched = {a: v for a, v in DESK.items() if not a.endswith("in/conn/grp")}
    console = TwoWayConsole(unpatched)
    read_console_state(console, **SMALL)
    assert not [a for a in console.gets if a.startswith("/io/in/")]
    assert len(console.gets) == len(console_read_plan(**SMALL))


def test_the_read_reports_an_address_the_desk_never_answers():
    progress = CountingProgress()
    read_console_state(TwoWayConsole({}), progress=progress, **SMALL)
    assert progress.answered == 0
    assert progress.unanswered == len(console_read_plan(**SMALL))


def test_a_bulk_read_reports_its_nodes_and_grows_its_total_for_a_fallback():
    progress = CountingProgress()
    read_console_state(TwoWayConsole(DESK, omit_from_dumps=["/ch/1/send/1/lvl"]),
                       progress=progress, bulk=True, **SMALL)
    assert "/ch/1 (node)" in progress.started
    assert "/ch/1/send/1/lvl" in progress.started
    by_node, alone = group_plan_by_node(console_read_plan(**SMALL))
    assert progress.total == len(by_node) + len(alone) + 1 + 2, (
        "exactly one leaf was missing from a dump, so exactly one extra "
        "read -- plus the two the second pass adds for the one patched "
        "strip: its source socket's name and its clink")
    assert "/io/in/LCL/6/name" in progress.started
    assert "/ch/1/clink" in progress.started


def test_a_read_with_no_progress_object_still_works():
    assert read_console_state(TwoWayConsole(DESK), **SMALL).text("/ch/1/name") == "Kick"


@pytest.mark.parametrize("bulk", [False, True])
def test_the_console_model_still_rides_along(bulk):
    state = read_console_state(TwoWayConsole(DESK), bulk=bulk, **SMALL)
    assert state.console_model == "wing-compact"
