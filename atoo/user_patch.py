"""A stereo pair the desk cannot form from the sockets it is cabled to (LCL 4 and 5, B 2 and 3,
A 16 and 17, or two groups), patched through two USER PATCH slots.

A WING forms a stereo pair from an odd socket and the next. Its USER PATCH slots (`USR`
25-56) each take one socket of any group, and a pair of slots, odd first, is a pair the desk
forms; so a channel patched to `USR n, n+1` hears the two sockets as one stereo source. The plan
says what each slot takes in `user_sources`.

Both Build paths use this one module, so they cannot choose differently: the compact reply
(`reply_expand.expand_mechanical`) and the intent (`intent_compile`).
"""

from __future__ import annotations

from atoo import console_facts as facts


def pair_problem(stated: tuple[str, int], pair_stated: tuple[str, int]) -> str | None:
    """Why two rows' stated sockets cannot be one stereo pair on the desk as cabled, or None when
    they can."""
    if stated[0] != pair_stated[0]:
        return "they are in two socket groups"
    return facts.stereo_pair_problem([stated[1], pair_stated[1]])


def cannot_take(stated: tuple[str, int], pair_stated: tuple[str, int]) -> list[tuple[str, int]]:
    """The sockets of the two a user patch cannot take (a group it has no source for)."""
    return [s for s in (stated, pair_stated) if s[0] not in facts.USER_PATCH_SOURCE_GROUPS]


def taken_slots(plan: dict | None, reserved=(), used=()) -> set[int]:
    """The USR slots already spoken for: `reserved` (the show's `user.csv`), `used` (slots the
    caller has taken), every slot the plan's `user_sources` defines and every one a channel is
    patched to."""
    taken = {int(n) for n in reserved or ()} | {int(n) for n in used or ()}
    for entry in (plan or {}).get("user_sources") or []:
        if isinstance(entry, dict) and isinstance(entry.get("slot"), int):
            taken.add(entry["slot"])
    for channel in (plan or {}).get("channels") or []:
        patch = channel.get("patch") if isinstance(channel, dict) else None
        if isinstance(patch, dict) and patch.get("group") == "USR":
            taken.update(n for n in patch.get("sockets") or [] if isinstance(n, int))
    return taken


def free_pair(taken) -> int | None:
    """The first odd USER PATCH slot n with n and n+1 both free, or None when every pair is
    taken."""
    low, high = facts.USER_PATCH_SLOTS
    for n in range(low + (low % 2 == 0), high, 2):
        if n not in taken and n + 1 not in taken:
            return n
    return None


def entries(slot: int, name: str, stated: tuple[str, int], pair_stated: tuple[str, int]) -> list[dict]:
    """The plan's two `user_sources` entries for a pair routed through `slot` and `slot + 1`. Each
    slot is named as the channel is, the name Apply writes on a channel's source either way."""
    return [{"slot": n, "name": name, "source": {"group": group, "index": index}, "stated": False}
            for n, (group, index) in ((slot, stated), (slot + 1, pair_stated))]


def routed_info(left: str, stated, right: str, pair_stated, name: str, slot: int) -> str:
    """The INFO for a pair patched through user patch `slot`, `slot + 1`."""
    from atoo.input_list import format_socket

    a, b = format_socket(*stated), format_socket(*pair_stated)
    return (f"{left!r} ({a}) and {right!r} ({b}) can't be one stereo pair as cabled -- "
            f"{pair_problem(stated, pair_stated)} -- so {name!r} is patched through user patch USR "
            f"{slot}-{slot + 1}, which take {a} and {b}")


def split_info(left: str, stated, right: str, pair_stated) -> str:
    """The INFO for a pair that cannot be routed either: two mono channels."""
    from atoo.input_list import format_socket

    a, b = format_socket(*stated), format_socket(*pair_stated)
    cannot = [format_socket(*s) for s in cannot_take(stated, pair_stated)]
    reason = (f"a user patch cannot take {' or '.join(cannot)}" if cannot else
              f"no pair of user patch slots (USR {facts.USER_PATCH_SLOTS[0]}-"
              f"{facts.USER_PATCH_SLOTS[1]}) is free to pair them through")
    return (f"{left!r} ({a}) and {right!r} ({b}) can't be one stereo pair as cabled -- "
            f"{pair_problem(stated, pair_stated)} -- and {reason}; they are built as two mono channels")
