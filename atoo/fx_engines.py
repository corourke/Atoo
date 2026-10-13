"""FX engines: what each engine can hold, how a plan's effects are given
engines, and how an effect's parameters are typed -- an earlier change.

The maintainer, 2026-10-12: *"It's important to me that we are able to set up
buses with effects."* The effects come from bus presets saved on the desk
(`presets.BusPreset`): a `.bus` file carries the effect model and every
one of its parameters (`preins_data`), and the engine it was saved from
(`target_fx`).

## What the WING offers

Sixteen engines, `/fx/1`..`/fx/16`. An engine is heard only when a strip
inserts it (`docs/reference/wing-console-model.md`, "Effects are inserts,
not sends"). **Which models an engine offers is not the same for all
sixteen**: the walk of a real Compact (firmware 3.1) lists 65 models on
engines 1-8 and 39 on 9-16 -- every reverb, every delay and the
modulation effects (chorus, flanger, pitch) are offered by 1-8 only.
That table is frozen in `initialized/fx_models.json` by
`tools/freeze_initialized_capture.py fx`, from the walk itself, so this
module never carries a hand-typed list of "reverbs";
`tests/test_fx_engines.py` re-derives it and fails if they drift.

## Allocation (code, not the model)

`allocate` gives each effect an engine, in the plan's bus order:

1. **The preset's own engine** (`target_fx`), when it can hold the model
   and nothing earlier in the plan claimed it. That is the engine the
   engineer saved it from, and the one he will look for.
2. Otherwise **the first free engine that can hold it**, trying the
   engines that offer the FEWEST models first -- so an EQ or compressor
   effect goes to 9-16 and leaves 1-8 for the reverbs and delays only
   they can hold.
3. No engine left: none, and verify says so at ERROR (`fx.no-engine`):
   more effects than the desk has engines for is a desk that cannot be
   set.

Every choice is announced at INFO (`fx.engine-allocated`), with what it
was chosen from.

## Parameter types

An OSC write needs a type tag, and a `.bus`'s JSON cannot always give
one. The parameter map is the console describing itself, so a parameter
the map types the same way under every model it saw takes the map's type
(`initialized/leaf_types.json`, `/fx/{n}/<param>`). Two kinds of
parameter have no such entry, and take the type of the value as saved
(a whole number `i`, a fractional one `f`, a boolean `i`, text `s`):

* one whose type differs between models (`att` is an int under GATED and
  a knob under others) -- the saved value is GATED's own;
* one the map does not have at all, because no engine held that model
  when the desk was walked (V-REV's `mod`, `out`, `trans`).

Both are said at INFO (`fx.parameter-typed-from-value`), and every write
is read back, so a wrong tag is a readback mismatch in the journal, never
a silently mis-set desk. **None of this is confirmed on a desk until
the maintainer's desk tests**.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from atoo import console_facts

FX_MODELS_FILE = "fx_models.json"

#: The engine leaf holding the model, and the parameter keys of a
#: `preins_data`/`postins_data` block that are not parameters.
MODEL_LEAF = "mdl"


@lru_cache(maxsize=1)
def _table() -> dict:
    from atoo.initialize import CAPTURE_DIR

    return json.loads((CAPTURE_DIR / FX_MODELS_FILE).read_text(encoding="utf-8"))


def engines() -> range:
    return range(1, console_facts.FX_SLOTS + 1)


def engine_models(engine: int) -> tuple[str, ...]:
    """The models engine `engine` offers, as the desk spells them."""
    for group in _table()["engines"]:
        if engine in group["engines"]:
            return tuple(group["models"])
    return ()


def all_models() -> tuple[str, ...]:
    """Every model any engine offers, in the desk's own order."""
    seen: dict[str, None] = {}
    for group in _table()["engines"]:
        seen.update(dict.fromkeys(group["models"]))
    return tuple(seen)


def engines_for(model: str) -> list[int]:
    """The engines that can hold `model`."""
    return [e for e in engines() if model in engine_models(e)]


def is_known_model(model: object) -> bool:
    return isinstance(model, str) and model in all_models() and model != console_facts.FX_EMPTY


def engine_range_text(engine_list: list[int]) -> str:
    """`[1..8]` as "1-8"; anything not contiguous as a list."""
    if not engine_list:
        return "none"
    if engine_list == list(range(engine_list[0], engine_list[-1] + 1)):
        return f"{engine_list[0]}-{engine_list[-1]}" if len(engine_list) > 1 else str(engine_list[0])
    return ", ".join(str(e) for e in engine_list)


def mapped_parameters() -> frozenset[str]:
    return frozenset(_table()["parameters"])


@dataclass(frozen=True)
class EngineRequest:
    """One effect a plan wants an engine for. `owner` names the strip and
    insert point it is for ("bus 'Vox Verb' pre-insert"); `key` is what the
    caller files the answer under."""

    key: object
    owner: str
    model: str
    saved_engine: int | None


@dataclass(frozen=True)
class Allocation:
    engine: int | None
    reason: str


def allocate(requests: list[EngineRequest],
             taken: dict[int, str] | None = None) -> dict[object, Allocation]:
    """An engine for each request -- see the module docstring. `taken` is
    engines already spoken for (engine -> who holds it), which no request
    is given. A request whose model no engine offers gets None; verify
    reports it as `fx.unknown-model`."""
    claimed: dict[int, str] = dict(taken or {})
    out: dict[object, Allocation] = {}
    # Pass 1: every effect whose own engine is free and can hold it keeps
    # it -- before any other is placed, so a later bus's saved engine is
    # not taken by an earlier bus that had no preference.
    for req in requests:
        e = req.saved_engine
        if isinstance(e, int) and e in engines_for(req.model) and e not in claimed:
            claimed[e] = req.owner
            out[req.key] = Allocation(e, f"the engine the preset was saved from")
    for req in requests:
        if req.key in out:
            continue
        legal = engines_for(req.model)
        if not legal:
            out[req.key] = Allocation(None, f"no engine offers the model {req.model!r}")
            continue
        e = req.saved_engine
        if isinstance(e, int) and 1 <= e <= console_facts.FX_SLOTS:
            if e not in legal:
                why = (f"the preset was saved from FX{e}, which cannot hold {req.model} "
                       f"(only engines {engine_range_text(legal)} can)")
            else:
                why = f"the preset was saved from FX{e}, which {claimed[e]} already uses"
        else:
            why = "the preset names no engine"
        # Fewest-models first: keep 1-8 for what only 1-8 can hold.
        free = sorted((x for x in legal if x not in claimed),
                      key=lambda x: (len(engine_models(x)), x))
        if not free:
            out[req.key] = Allocation(
                None, f"{why}, and every engine that can hold {req.model} "
                      f"({engine_range_text(legal)}) is already in use")
            continue
        claimed[free[0]] = req.owner
        out[req.key] = Allocation(free[0], f"{why}; FX{free[0]} is the first free engine "
                                           f"that can hold it")
    return out


# -- parameters ---------------------------------------------------------------

def _template(param: str) -> dict | None:
    from atoo.initialize import leaf_types

    return leaf_types().get(f"/fx/{{n}}/{param}")


def param_type(param: str, value: object) -> tuple[str | None, bool]:
    """`(osc, from_map)`: the OSC type tag `param` is written with, and
    whether the map said so (False: taken from the saved value). None
    when the value has no type an OSC write can carry."""
    spec = _template(param)
    if spec is not None:
        return spec["osc"], True
    if isinstance(value, bool):
        return "i", False
    if isinstance(value, int):
        return "i", False
    if isinstance(value, float):
        return "f", False
    if isinstance(value, str):
        return "s", False
    return None, False


def coerce_param(param: str, value: object) -> tuple[object, str | None, bool]:
    """`(value, refusal, from_map)` -- the value in the type the desk
    takes, or a refusal saying why it cannot be written."""
    from atoo.initialize import coerce

    osc, from_map = param_type(param, value)
    if osc is None:
        return None, f"{value!r} is not a value an engine parameter can hold", False
    spec = _template(param) or {"osc": osc}
    if osc in ("i", "f") and (isinstance(value, str) or value is None):
        return None, f"{value!r} is not a number", from_map
    out = coerce(value, spec)
    if osc == "s":
        tokens = spec.get("tokens")
        if tokens and out not in tokens:
            return None, (f"{value!r} is not a choice the desk offers for {param} "
                          f"({', '.join(tokens)})"), from_map
    return out, None, from_map


def is_engine_parameter(param: str) -> bool:
    """A key of `preins_data` that is a parameter to write: not the model,
    and not a read-only `$` mirror."""
    return param != MODEL_LEAF and not param.startswith("$")


def engine_address(engine: int, leaf: str = MODEL_LEAF) -> str:
    return f"/fx/{engine}/{leaf}"


def insert_value(engine: int) -> str:
    """What a strip's `preins/ins` names for an engine: `FX5`."""
    return f"FX{engine}"


def parse_insert(value: object) -> int | None:
    """`FX5` -> 5; anything else (NONE, unknown) -> None."""
    if isinstance(value, str) and value.upper().startswith("FX"):
        try:
            n = int(value[2:])
        except ValueError:
            return None
        return n if 1 <= n <= console_facts.FX_SLOTS else None
    return None
