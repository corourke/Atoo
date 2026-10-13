"""A WING node data dump (`,s *`) hands over a whole node's
values in one round trip, which takes a live audit read from 6,032
requests to about 300.

The reply is a flat `key=value,` string -- none of the OSC type
information a per-leaf reply carries -- so **parsing it is the risk**,
and the parser's job is to refuse anything it cannot read rather than
guess. A guessed value in this project is worse than a slow read: the
tool's whole claim is that the values it reports are the ones on the
desk.

The fixture below is the protocol PDF's OWN worked example, page 25,
transcribed byte for byte (its line breaks are the PDF's 98-column text
wrap, not part of the reply). Nothing here is invented.
"""

import pytest

from atoo.console import (MINUS_INFINITY_DB, NodeDumpError, OscReply,
                               parse_node_dump, value_from_dump_text)


# Behringer's WING_Remote-Protocols-3.1-03.pdf p25, "/ch/1 ,s *", the
# reply to a channel loaded with default values after init (2156 B).
PDF_CH1_DUMP = (
    "in.set.srcauto=0,altsrc=0,inv=0,trim=0.0,bal=0.0,dlymode=M,dly=0.1,dlyon=0,"
    ".conn.grp=LCL,in=1,altgrp=OFF,altin=1,"
    "..flt.lc=0,lcf=100.2,lcs=24,hc=0,hcf=10k02,hcs=12,tf=0,mdl=TILT,tilt=0.00,"
    ".clink=1,col=1,name=,icon=0,led=1,mute=0,fdr=-oo,pan=0,wid=100,solosafe=0,"
    "mon=A,proc=GEDI,ptap=5,"
    "peq.on=0,1g=0.0,1f=100,1q=1.00,2g=0.0,2f=999,2q=1.00,3g=0.0,3f=10k0,3q=1.00,"
    ".gate.on=0,mdl=GATE,thr=-40.0,range=40.0,att=10,hld=10,rel=199,acc=0,ratio='1:3',"
    ".gatesc.type=OFF,f=1k0,q=2.00,src=SELF,tap=IN,"
    ".eq.on=0,mdl=STD,mix=100,lg=0.0,lf=80.2,lq=1.00,leq=SHV,1g=0.0,1f=200.0,1q=1.00,"
    "2g=0.0,2f=601.4,2q=1.00,3g=0.0,3f=1k50,3q=1.00,4g=0.0,4f=3k99,4q=1.00,hg=0.0,"
    "hf=12k00,hq=1.00,heq=SHV,"
    ".dyn.on=0,mdl=COMP,mix=100,gain=0.0,thr=-10.0,ratio=3.0,knee=3,det=RMS,att=50,"
    "hld=20,rel=153,env=LOG,auto=1,"
    ".dynxo.depth=6.0,type=OFF,f=1k0,"
    ".dynsc.type=OFF,f=1k0,q=2.00,src=SELF,tap=IN,"
    ".preins.on=0,ins=NONE,"
    ".main.1.on=1,lvl=0.0,pre=0,.2.on=0,lvl=0.0,pre=0,.3.on=0,lvl=0.0,pre=0,"
    ".4.on=0,lvl=0.0,pre=0,"
    "..send.1.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".2.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".3.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".4.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".5.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".6.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".7.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".8.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".9.on=0,lvl=-oo,pon=0,mode=GRP,plink=1,pan=0,"
    ".10.on=0,lvl=-oo,pon=0,mode=GRP,plink=1,pan=0,"
    ".11.on=0,lvl=-oo,pon=0,mode=POST,plink=1,pan=0,"
    ".12.on=0,lvl=-oo,pon=0,mode=POST,plink=1,pan=0,"
    ".13.on=0,lvl=-oo,pon=0,mode=POST,plink=1,pan=0,"
    ".14.on=0,lvl=-oo,pon=0,mode=POST,plink=1,pan=0,"
    ".15.on=0,lvl=-oo,pon=0,mode=POST,plink=1,pan=0,"
    ".16.on=0,lvl=-oo,pon=0,mode=POST,plink=1,pan=0,"
    ".MX1.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".MX2.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".MX3.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".MX4.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".MX5.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".MX6.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".MX7.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    ".MX8.on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,"
    "..tapwid=100,postins.on=0,mode=FX,ins=NONE,w=0.0,.tags=,"
)


@pytest.fixture(scope="module")
def ch1():
    return parse_node_dump("/ch/1", PDF_CH1_DUMP)


# -- the depth question: how much of the subtree does one dump carry? ------


def test_one_channel_dump_carries_the_whole_channel_subtree(ch1):
    # This is the fact the whole speed argument turns on. `/ch/1 ,s *` is
    # not a listing of `/ch/1`'s immediate leaves -- it reaches all the
    # way down through `send/16` and `in/conn`, four levels deep.
    assert ch1["/ch/1/fdr"] == "-oo"
    assert ch1["/ch/1/mute"] == "0"
    assert ch1["/ch/1/in/conn/grp"] == "LCL"
    assert ch1["/ch/1/in/conn/in"] == "1"
    assert ch1["/ch/1/in/set/altsrc"] == "0"
    assert ch1["/ch/1/main/1/on"] == "1"
    assert ch1["/ch/1/main/4/on"] == "0"
    assert ch1["/ch/1/send/1/mode"] == "PRE"
    assert ch1["/ch/1/send/16/mode"] == "POST"
    assert ch1["/ch/1/send/16/lvl"] == "-oo"
    assert ch1["/ch/1/send/MX8/pon"] == "0"
    assert ch1["/ch/1/tags"] == ""
    assert ch1["/ch/1/name"] == ""


def test_the_dump_covers_every_leaf_a_live_read_asks_for_on_a_channel():
    # The point of the exercise: one request instead of 112 -- including
    # both insert points, which the PDF's dump carries. If a future
    # firmware drops a leaf from the dump this fails, which is the
    # warning worth having -- the read falls back per-leaf and gets
    # slower rather than wrong, but we should know.
    from atoo.audit import console_read_plan

    plan = [a for a, _ in console_read_plan(channels=1, aux=0, buses=16, mains=4,
                                            matrices=8, dcas=0, mute_groups=0)
            if a.startswith("/ch/1/")]
    parsed = parse_node_dump("/ch/1", PDF_CH1_DUMP)
    assert [a for a in plan if a not in parsed] == []
    assert len(plan) == 112


def test_the_climb_and_descend_grammar_matches_the_pdfs_own_example(ch1):
    # `..flt.lc=0` climbs two levels out of /ch/1/in/conn and descends
    # into flt; `.clink=1` climbs one out of /ch/1/flt back to /ch/1.
    assert ch1["/ch/1/flt/lc"] == "0"
    assert ch1["/ch/1/clink"] == "1"
    # `..tapwid=100` climbs two out of /ch/1/send/MX8.
    assert ch1["/ch/1/tapwid"] == "100"
    assert ch1["/ch/1/postins/ins"] == "NONE"


def test_a_quoted_value_survives_its_punctuation(ch1):
    # The PDF's own channel dump carries `ratio='1:3'`.
    assert ch1["/ch/1/gate/ratio"] == "1:3"


def test_the_fx_slot_example_from_the_same_page():
    assert parse_node_dump("/fx/1", "mdl=NONE,fxmix=100,") == {
        "/fx/1/mdl": "NONE", "/fx/1/fxmix": "100"}


# -- what the parser refuses ------------------------------------------------


def test_an_item_with_no_equals_is_refused():
    # This is what an UNQUOTED comma inside a free-text value looks like
    # from here: `name=Vox, Lead` splits into `name=Vox` and ` Lead`.
    # Refusing costs one node's worth of per-leaf reads. Accepting would
    # silently report a channel called "Vox".
    with pytest.raises(NodeDumpError) as exc:
        parse_node_dump("/ch/1", "name=Vox, Lead,mute=0,")
    assert "no '='" in str(exc.value)


def test_climbing_above_the_node_that_was_dumped_is_refused():
    with pytest.raises(NodeDumpError) as exc:
        parse_node_dump("/ch/1", "mute=0,...fdr=0,")
    assert "climbs" in str(exc.value)


def test_an_unterminated_quote_is_refused():
    with pytest.raises(NodeDumpError) as exc:
        parse_node_dump("/ch/1", "name='Vox,mute=0,")
    assert "unterminated quote" in str(exc.value)


def test_a_name_that_is_not_an_identifier_is_refused():
    with pytest.raises(NodeDumpError) as exc:
        parse_node_dump("/ch/1", "na me=Vox,")
    assert "unreadable name" in str(exc.value)


def test_an_empty_name_is_refused():
    with pytest.raises(NodeDumpError):
        parse_node_dump("/ch/1", "send..on=0,")


def test_a_trailing_comma_is_not_an_item():
    assert parse_node_dump("/dca/1", "mute=0,") == {"/dca/1/mute": "0"}


# -- the trailing climb an INTERMEDIATE node ends with ---------------------
#
# A11 found `/ch/1/send` unparseable -- `item '.' has no '='` -- and A12
# captured the bytes that explain it. Both strings below are transcribed
# from `archive/examples/console-runs/2026-09-22-2119/A12-protocol-probes.txt`
# section 3, hardware, WING Compact firmware 3.1-0-g9f314617. A dump of a
# node whose children are themselves nodes ends by climbing back out of
# the last one, and that climb is an item of its own with nothing after
# it.

# `/bus/1/send`, 568 bytes, the whole reply. Note the closing `,.`.
A12_BUS1_SEND_DUMP = (
    "1.on=0,lvl=-oo,pre=0,.2.on=0,lvl=-oo,pre=0,.3.on=0,lvl=-oo,pre=0,"
    ".4.on=0,lvl=-oo,pre=0,.5.on=0,lvl=-oo,pre=0,.6.on=0,lvl=-oo,pre=0,"
    ".7.on=0,lvl=-oo,pre=0,.8.on=0,lvl=-oo,pre=0,.9.on=0,lvl=-oo,pre=0,"
    ".10.on=0,lvl=-oo,pre=0,.11.on=0,lvl=-oo,pre=0,.12.on=0,lvl=-oo,pre=0,"
    ".13.on=0,lvl=-oo,pre=0,.14.on=0,lvl=-oo,pre=0,.15.on=0,lvl=-oo,pre=0,"
    ".16.on=0,lvl=-oo,pre=0,.MX1.on=0,lvl=-oo,pre=0,.MX2.on=0,lvl=-oo,pre=0,"
    ".MX3.on=0,lvl=-oo,pre=0,.MX4.on=0,lvl=-oo,pre=0,.MX5.on=0,lvl=-oo,pre=0,"
    ".MX6.on=0,lvl=-oo,pre=0,.MX7.on=0,lvl=-oo,pre=0,.MX8.on=0,lvl=-oo,pre=0,."
)

# `/ch/1/main`, 108 bytes, the whole reply. (In the capture this sits
# under the `/io/in/USR/1` heading: that probe does not match replies to
# requests, so from its fourth request on the headings are shifted by
# one. The address inside each datagram is the one to trust, and this
# one says `/ch/1/main`.)
A12_CH1_MAIN_DUMP = (
    "1.on=1,lvl=0.0,pre=0,.2.on=0,lvl=0.0,pre=0,"
    ".3.on=0,lvl=0.0,pre=0,.4.on=0,lvl=0.0,pre=0,."
)


def test_an_intermediate_node_dump_parses_despite_its_trailing_climb():
    parsed = parse_node_dump("/bus/1/send", A12_BUS1_SEND_DUMP)
    assert len(parsed) == 72          # 16 bus sends + 8 matrix sends, x3 leaves
    assert parsed["/bus/1/send/1/on"] == "0"
    assert parsed["/bus/1/send/1/lvl"] == "-oo"
    assert parsed["/bus/1/send/1/pre"] == "0"
    assert parsed["/bus/1/send/MX8/pre"] == "0"
    # and nothing landed outside the node, which is what a mishandled
    # climb would produce
    assert all(a.startswith("/bus/1/send/") for a in parsed)


def test_the_same_dump_says_a_bus_send_has_no_mode_and_no_pon():
    """The desk's own listing of what a bus send carries -- the
    first finding, from the console rather than from a count of
    timeouts."""
    parsed = parse_node_dump("/bus/1/send", A12_BUS1_SEND_DUMP)
    assert {a.rsplit("/", 1)[-1] for a in parsed} == {"on", "lvl", "pre"}
    assert "/bus/1/send/MX1/mode" not in parsed
    assert "/bus/1/send/MX1/pon" not in parsed
    assert "/bus/1/send/1/mode" not in parsed, "bus-to-bus sends are the same shape"


def test_a_strips_own_send_dump_does_carry_mode_and_pon():
    """The control, from the same capture: `/ch/1/send/1`, 64 bytes."""
    parsed = parse_node_dump(
        "/ch/1/send/1", "on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,")
    assert parsed["/ch/1/send/1/mode"] == "PRE"
    assert parsed["/ch/1/send/1/pon"] == "0"


def test_a_direct_to_main_route_dump_parses_too():
    parsed = parse_node_dump("/ch/1/main", A12_CH1_MAIN_DUMP)
    assert len(parsed) == 12
    assert parsed["/ch/1/main/1/on"] == "1"
    assert parsed["/ch/1/main/4/pre"] == "0"


def test_a_dots_only_item_in_the_MIDDLE_is_still_refused():
    """Only the trailing one is ignored, and the reason is narrow: there
    is nothing after it to mis-address. A climb in the middle decides
    where every later leaf lands, and no dump has ever shown a bare one,
    so it still falls back to per-leaf reads."""
    with pytest.raises(NodeDumpError) as exc:
        parse_node_dump("/bus/1/send", "1.on=0,lvl=-oo,.,2.on=0,")
    assert "no '='" in str(exc.value)


def test_a_bare_dot_that_climbs_too_far_is_still_refused():
    with pytest.raises(NodeDumpError) as exc:
        parse_node_dump("/dca/1", "mute=0,..")
    assert "climbs" in str(exc.value)


# -- turning dump text into the same value a per-leaf read would give ------


def test_minus_infinity_becomes_the_number_a_per_leaf_read_gives():
    # A per-leaf `/ch/1/fdr` answers `,sff  '-oo' 0.0 -144.0` and
    # `OscReply.value('f')` takes the last float. A dump carries only the
    # text, so it has to land on the same number or the two read paths
    # would disagree about a muted channel.
    per_leaf, error = OscReply("/ch/1/fdr", "sff", ["-oo", 0.0, -144.0]).value("f")
    assert error is None
    from_dump, error = value_from_dump_text("-oo", "f")
    assert error is None
    assert from_dump == per_leaf == MINUS_INFINITY_DB


def test_ordinary_values_convert_by_type():
    assert value_from_dump_text("-2.0", "f") == (-2.0, None)
    assert value_from_dump_text("1", "i") == (1, None)
    assert value_from_dump_text("LCL", "s") == ("LCL", None)


def test_a_value_that_will_not_convert_reports_an_error_rather_than_guessing():
    value, error = value_from_dump_text("10k02", "f")
    assert value is None and "not_a_float" in error
    value, error = value_from_dump_text("PRE", "i")
    assert value is None and "not_an_int" in error
    value, error = value_from_dump_text("1", "q")
    assert value is None and "unknown_value_type" in error


# -- WingConsole.node_dump: every failure looks the same to the caller -----


class OneReply:
    def __init__(self, reply):
        self.reply = reply
        self.asked = []

    def query(self, address, mode):
        self.asked.append((address, mode))
        return self.reply

    _log = staticmethod(lambda *a, **k: None)


def _node_dump(reply):
    from atoo.console import WingConsole
    console = OneReply(reply)
    return WingConsole.node_dump(console, "/ch/1")


def test_a_dump_comes_back_as_the_consoles_own_text():
    assert _node_dump(OscReply("/ch/1", "s", ["mute=0,"])) == "mute=0,"


@pytest.mark.parametrize("reply", [
    None,
    OscReply("/ch/1", "s", ["NODE NOT FOUND"]),
    OscReply("/ch/1", "SOCKET_ERROR", ["OSError"]),
    OscReply("/ch/1", "sfi", ["0", 0.0, 0]),   # a leaf value, not a dump
    OscReply("/ch/1", "s", []),
])
def test_anything_that_is_not_a_dump_comes_back_as_none(reply):
    # One answer for every failure, because every caller's response to it
    # is the same: read the leaves individually, the way it always has.
    assert _node_dump(reply) is None


def test_the_query_asks_for_the_values_only_mode():
    from atoo.console import NODE_DUMP_MODE, WingConsole
    console = OneReply(OscReply("/ch/1", "s", ["mute=0,"]))
    WingConsole.node_dump(console, "/ch/1")
    assert console.asked == [("/ch/1", NODE_DUMP_MODE)]
    assert NODE_DUMP_MODE == "*"
