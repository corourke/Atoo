"""C003: a channel patched from, or an output routed to,
an expansion bay the desk reports empty.

The deferred half of #115. `apply` refuses to *create* this; the audit
has to find one that is *already there* -- a show applied before that
refusal existed, a patch made by hand, a card pulled after load-in. The
WING accepts a patch from `MOD` with no module fitted and reads it back
unchanged (`console_facts.UNFITTED_BAY_PATCH_IS_ACCEPTED`, measured in
A8), so nothing else reports it.

Four properties matter, and each has a test:

1. It fires, at ERROR, on both directions `apply` checks.
2. **Silent, not clean**, whenever the bay was not read or did not say
   `NONE` in as many letters -- a capture made before this rule carries
   no bay reading at all.
3. The read asks for a bay only when something uses it, so a factory desk
   pays nothing and its 5,738-address read does not move.
4. When the rule is silent for want of a reading, the coverage line says
   so (FR-4.2: a partial read is permitted only if it is declared).
"""

from __future__ import annotations

from atoo.audit import (
    ConsoleState,
    DEFAULT_RULES,
    expansion_bay_addresses,
    read_console_state,
    render_coverage,
    run_audit,
)
from atoo.console import OscReply
from atoo.diagnostics import Severity

MODULE = "/$syscfg/opt_mod"
CARD = "/cards/$type"


def _c003(state: ConsoleState, **kwargs):
    return [f for f in run_audit(state, **kwargs) if f.rule_id == "C003"]


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------


def test_a_channel_patched_from_an_empty_module_bay_is_an_error():
    state = ConsoleState({
        "/ch/40/name": "Podium",
        "/ch/40/in/conn/grp": "MOD", "/ch/40/in/conn/in": 1,
        MODULE: "NONE",
    })
    [finding] = _c003(state)
    assert finding.severity is Severity.ERROR
    assert 'CH 40 "Podium" is patched from MOD 1' in finding.detail
    assert MODULE in finding.detail
    assert finding.addresses == ("/ch/40/in/conn/grp", MODULE)


def test_an_output_routed_to_an_empty_card_bay_is_an_error():
    state = ConsoleState({
        "/io/out/CRD/3/grp": "MAIN", "/io/out/CRD/3/in": 1,
        CARD: "NONE",
    })
    [finding] = _c003(state)
    assert finding.severity is Severity.ERROR
    assert finding.addresses == ("/io/out/CRD/3/grp", CARD)


def test_an_unpatched_output_socket_on_an_empty_bay_is_not_a_fault():
    state = ConsoleState({
        "/io/out/CRD/3/grp": "OFF", "/io/out/CRD/3/in": 0,
        CARD: "NONE",
    })
    assert _c003(state) == []


def test_one_finding_per_dependent_so_each_can_be_fixed():
    state = ConsoleState({
        "/ch/1/in/conn/grp": "MOD", "/ch/1/in/conn/in": 1,
        "/aux/2/in/conn/grp": "MOD", "/aux/2/in/conn/in": 3,
        MODULE: "NONE",
    })
    cited = sorted(f.addresses[0] for f in _c003(state))
    assert cited == ["/aux/2/in/conn/grp", "/ch/1/in/conn/grp"]


def test_a_fitted_bay_is_not_a_finding():
    state = ConsoleState({
        "/ch/1/in/conn/grp": "CRD", "/ch/1/in/conn/in": 1,
        CARD: "WLIVE",
    })
    assert _c003(state) == []


def test_silent_not_clean_when_the_bay_was_never_read():
    """A capture made before this rule carries no bay reading. That is
    "unknown", and the rule says nothing rather than calling it fine --
    and, equally, rather than calling it empty."""
    state = ConsoleState({"/ch/1/in/conn/grp": "MOD", "/ch/1/in/conn/in": 1})
    assert _c003(state) == []


def test_a_bay_reading_it_does_not_recognise_is_not_empty():
    """`bay_is_empty` says "empty" only on the literal NONE. A card from a
    firmware newer than our table must not become a false ERROR."""
    state = ConsoleState({
        "/ch/1/in/conn/grp": "MOD", "/ch/1/in/conn/in": 1,
        MODULE: "SOMETHING-NEW",
    })
    assert _c003(state) == []


def test_the_other_bay_being_empty_says_nothing_about_this_one():
    state = ConsoleState({
        "/ch/1/in/conn/grp": "CRD", "/ch/1/in/conn/in": 1,
        CARD: "WLIVE", MODULE: "NONE",
    })
    assert _c003(state) == []


def test_a_plan_stating_the_patch_does_not_stand_it_down():
    """The mechanism 2 withholds a structural finding when the
    plan states the parameter it judged. The plan asking for MOD 1 does
    not put a module in the bay -- so this one must survive."""
    state = ConsoleState({
        "/ch/1/in/conn/grp": "MOD", "/ch/1/in/conn/in": 1,
        MODULE: "NONE",
    })
    plan = {"channels": [{"bank": "ch", "channel": 1, "name": "Kick",
                          "patch": {"group": "MOD", "sockets": [1]}}]}
    assert len(_c003(state, plan=plan)) == 1


def test_sp_c003_is_in_the_default_catalogue():
    assert "C003" in {rule.id for rule in DEFAULT_RULES}


# --------------------------------------------------------------------------
# The read
# --------------------------------------------------------------------------


def test_no_bay_is_asked_about_when_nothing_uses_one():
    state = ConsoleState({"/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1})
    assert expansion_bay_addresses(state) == []


def test_only_the_bay_in_use_is_asked_about_and_only_once():
    state = ConsoleState({
        "/ch/1/in/conn/grp": "MOD", "/ch/1/in/conn/in": 1,
        "/ch/2/in/conn/grp": "MOD", "/ch/2/in/conn/in": 2,
    })
    assert expansion_bay_addresses(state) == [(MODULE, "s")]


class _Desk:
    """Answers strings and ints from a dict; remembers what it was asked."""

    console_model = "wing-compact"

    def __init__(self, values):
        self.values = values
        self.asked = []

    def get(self, address):
        self.asked.append(address)
        if address not in self.values:
            return None
        value = self.values[address]
        if isinstance(value, str):
            return OscReply(address=address, typetag="s", args=[value])
        # `in/conn/in` reads back one low on the wire.
        wire = value - 1 if address.endswith("/in/conn/in") else value
        return OscReply(address=address, typetag="sfi", args=[str(value), 0.0, wire])


_ONE_STRIP = dict(channels=1, aux=0, buses=0, mains=0, matrices=0,
                  dcas=0, mute_groups=0)


def test_a_live_read_fetches_the_bay_a_strip_is_patched_from():
    desk = _Desk({"/ch/1/in/conn/grp": "MOD", "/ch/1/in/conn/in": 1,
                  MODULE: "NONE"})
    state = read_console_state(desk, **_ONE_STRIP)
    assert desk.asked.count(MODULE) == 1
    assert CARD not in desk.asked
    assert state.get(MODULE) == "NONE"
    assert [f.rule_id for f in run_audit(state)].count("C003") == 1


def test_a_live_read_of_a_desk_using_no_bay_asks_nothing_extra():
    desk = _Desk({"/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1})
    read_console_state(desk, **_ONE_STRIP)
    assert MODULE not in desk.asked
    assert CARD not in desk.asked


# --------------------------------------------------------------------------
# Silence is declared, not implied (FR-4.2)
# --------------------------------------------------------------------------


def test_coverage_says_when_a_bay_in_use_was_not_read():
    state = ConsoleState({"/ch/1/in/conn/grp": "MOD", "/ch/1/in/conn/in": 1})
    text = render_coverage(state, from_capture=True)
    assert "Expansion bay MOD (/ch/1/in/conn/grp) is in use" in text
    assert MODULE in text
    assert "C003" in text


def test_coverage_says_nothing_about_a_bay_that_was_read():
    state = ConsoleState({"/ch/1/in/conn/grp": "MOD", "/ch/1/in/conn/in": 1,
                          MODULE: "DANTE"})
    assert "C003" not in render_coverage(state)
