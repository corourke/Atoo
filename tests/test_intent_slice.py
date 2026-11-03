"""The desk graph and the slice of it a request needs (`atoo/intent_desk.py`),
offline. Frozen inputs only (`tests/fixtures/intent/`); nothing here reads
`examples/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "intent"
CONSOLES = ("wing-compact", "wing-rack", "wing-full")


from atoo import intent_compile as ic  # noqa: E402
from atoo import intent_desk as dg  # noqa: E402

BASE = json.loads((FIXTURES / "demo_base.plan.json").read_text())
RIG = {"A": "S16"}


def graph(model="wing-compact"):
    return dg.index_desk(BASE, aes50_devices=RIG, console_model=model)


def slice_of(text, model="wing-compact", **kw):
    g = graph(model)
    return dg.slice_for(dg.hints_from_request(text, g), g, **kw), g


def test_every_link_resolves_to_a_node_and_runs_both_ways():
    g = graph()
    assert len(g["nodes"]) == 55
    for link in g["links"]:
        assert link["from"] in g["nodes"] and link["to"] in g["nodes"], link
    kick = g["by_name"]["ch"]["Kick"]
    assert {n["name"] for _l, n in dg.neighbours(g, "bus:5", kinds={"send"}, direction="in")} >= {"Kick"}
    assert [n["name"] for _l, n in dg.neighbours(g, kick, kinds={"member"}, direction="out")] == [
        "Drums", "Band"]
    assert [o["name"] for o in dg.occupant_of_socket(g, "A", 5)] == ["OH"]
    assert [o["name"] for o in dg.occupant_of_socket(g, "A", 6)] == ["OH"]  # a stereo pair


@pytest.mark.parametrize("model", CONSOLES)
def test_the_free_map_comes_from_the_console_and_the_stage_box(model):
    free = slice_of("x", model)[0]["free"]
    assert free["in"]["A"] == "10,16"           # the S16 ends at 16
    assert free["in"]["LCL"] == ("5-8" if model == "wing-full" else "5-24")
    assert free["out"]["LCL"] == "3-8" and free["out"]["A"] == "4-6"
    assert free["strip"]["ch"] == "14-40" and free["index"]["bus"] == "8-16"


def test_requests_pick_out_what_they_name():
    g = graph()
    h = dg.hints_from_request("Clear bus 5 and 6. Add a stereo IEM bus on LCL 3-4.", g)
    assert h["numbered"] == ["bus:5", "bus:6"] and h["sockets"] == [("LCL", 3), ("LCL", 4)]
    assert {"drop", "bus", "stereo"} <= h["ops"]
    h = dg.hints_from_request("trumpet, sax and trombone on A 10, A 16 and LCL 3", g)
    assert h["sockets"] == [("A", 10), ("A", 16), ("LCL", 3)]
    # an article is not an AES50 port
    assert dg.hints_from_request("Add a 16 channel snake", g)["sockets"] == []
    assert dg.hints_from_request("Get rid of the FX DCA", g)["names"] == ["dca:5", "mgrp:3"]
    assert dg.hints_from_request("Add a HiHat after the Snare", g)["numbered"] == ["ch:3"]


def test_the_slice_always_has_the_index_and_what_is_free():
    sl, _g = slice_of("HPF 100 on the Lead Vox")
    assert sl["index"]["ch"]["Lead Vox"] == "10" and sl["index"]["dca"]["FX"] == "5"
    assert set(sl["free"]) == {"in", "out", "strip", "index"}
    assert [c["name"] for c in sl["cards"]] == ["Lead Vox"]
    assert ": " not in dg.slice_json(sl) and ", " not in dg.slice_json(sl).replace(
        "Rack Tom", "")  # compact JSON


def test_a_drop_shows_whoever_it_moves_and_a_landing_shows_its_occupant():
    sl, _g = slice_of("Clear bus 5 and 6")
    drums = next(c for c in sl["cards"] if c["name"] == "Drums" and "senders" in c)
    assert "Kick" in drums["senders"]
    sl, _g = slice_of("Add a mic on A 3")
    assert [c["name"] for c in sl["cards"]] == ["Rack Tom", "Floor Tom"]  # and its pair neighbour, A 4
    sl, _g = slice_of("Add a HiHat after the Snare")
    assert [c["name"] for c in sl["cards"]] == ["Snare", "Rack Tom"]
    sl, _g = slice_of("Insert a HiHat after the Snare")
    assert [c["name"] for c in sl["cards"]][0] == "Snare" and len(sl["cards"]) == 12


def touched(base: dict, merged: dict, graph: dict) -> dict:
    """Existing objects a result removes, changes or lands on (cards needed), and
    the existing ones it only refers to (names needed)."""
    need_card, need_name = {}, {}

    def by_name(plan, key):
        items = plan.get(key) or {}
        return items if key != "channels" else {c["name"]: c for c in items}

    for key, kind in (("channels", None), ("busses", "bus"), ("dcas", "dca"),
                      ("mute_groups", "mgrp"), ("outputs", "out")):
        before, after = by_name(base, key), by_name(merged, key)
        for name, obj in before.items():
            node = graph["by_name"].get(kind or obj.get("bank", "ch"), {}).get(name)
            if node is None and kind is None:
                node = graph["by_name"]["ch"].get(name) or graph["by_name"]["aux"].get(name)
            if name not in after or after[name] != obj:
                need_card[node] = name
        for name, obj in after.items():
            if key != "channels" or (name in before and before[name] == obj):
                continue
            strip = f"{obj.get('bank', 'ch')}:{obj.get('channel')}"
            if strip in graph["nodes"] and graph["nodes"][strip]["name"] != name:
                need_card[strip] = name
            p = obj.get("patch") or {}
            for socket in p.get("sockets") or []:
                for owner in dg.occupant_of_socket(graph, p.get("group"), socket):
                    if owner["name"] != name:
                        need_card[owner["id"]] = name
            for ref_key, kind2 in (("dca", "dca"), ("mute_group", "mgrp")):
                for ref in obj.get(ref_key) or []:
                    if ref in graph["by_name"][kind2]:
                        need_name[graph["by_name"][kind2][ref]] = name
    return {"card": {k: v for k, v in need_card.items() if k}, "name": need_name}


def test_the_slice_holds_what_every_corpus_case_touches():
    """For each case, the slice built from the REQUEST ALONE has a card (or lists, in
    a neighbour's card) every object the result removes, changes or lands on."""
    cases = json.loads((FIXTURES / "cases.json").read_text())
    graph_ = graph()
    for case in cases["cases"]:
        merge, _ = ic.apply_intent(case["intent"], json.loads(json.dumps(BASE)), "wing-compact",
                                   text=case["request"], aes50_devices=RIG)
        need = touched(BASE, merge.plan, graph_)
        sl = dg.slice_for(dg.hints_from_request(case["request"], graph_), graph_)
        missing = [(case["id"], i, who) for i, who in need["card"].items()
                   if dg.covered(sl, graph_, i) not in ("card", "listed")]
        assert not missing, missing


def test_a_paraphrase_names_nothing_but_the_index_names_everything_and_widening_closes_it():
    """"the whole kit" selects no card; every object is still in the index, and a
    second slice built from the model's own answer has them."""
    graph_ = graph()
    intent = {"name": "n", "notes": [], "ops": [
        {"op": "set", "object": "channel", "name": n, "field": "processing.hpf_hz", "value": 120}
        for n in ("Kick", "Snare", "Rack Tom", "Floor Tom", "OH")]}
    first = dg.slice_for(dg.hints_from_request("HPF 120 on the whole kit", graph_), graph_)
    assert first["cards"] == [] and "Kick" in first["index"]["ch"]
    wide = dg.slice_for(dg.hints_from_intent(intent, graph_), graph_)
    assert {c["name"] for c in wide["cards"]} == {"Kick", "Snare", "Rack Tom", "Floor Tom", "OH"}
    sl, _g = slice_of("x", members=True)
    assert "Kick" in sl["index"]["members"]["dca:Drums"]
