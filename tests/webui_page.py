"""What the shell page sends with a confirmed write, for tests that drive
the write endpoints the way the page does.

A confirmed `POST /api/apply/run`, `/api/amend/run`, `/api/patch/run` or
`/api/undo/run`
must say what the page it came from was showing -- the bundle, and the
plan / review / journal-stack entry it reviewed -- or it is refused as a
stale page (webui.py's `_stale_bundle` and the checks beside it). A test
that is about something else still has to send them, and it reads them
from exactly the endpoints the page itself reads them from: `GET
/api/bundle`, `GET /api/apply/preflight`'s `plan_sha256`, `GET
/api/apply/status`'s `review.review_id`, and `GET /api/journals`' row
marked `is_top`. That makes these tests a page that is NOT stale; the
tests of the guard itself (`tests/test_webui_stale_page.py`) build the
stale ones by hand.

Not collected by pytest (no `test_` prefix).
"""

from __future__ import annotations


def page_fields(client, url: str) -> dict:
    fields: dict = {}
    bundle = client.get("/api/bundle")
    if bundle.status_code == 200:
        fields["expected_bundle"] = bundle.json()["directory"]
    if url == "/api/apply/run":
        preflight = client.get("/api/apply/preflight")
        if preflight.status_code == 200 and preflight.json().get("plan_sha256"):
            fields["expected_plan_sha256"] = preflight.json()["plan_sha256"]
    elif url in ("/api/amend/run", "/api/patch/run"):
        review = client.get("/api/apply/status").json().get("review") or {}
        if review.get("review_id"):
            fields["expected_review_id"] = review["review_id"]
    elif url == "/api/undo/run":
        journals = client.get("/api/journals").json()
        top = next((e for e in journals.get("entries") or [] if e.get("is_top")), None)
        if top is not None:
            fields["expected_undo_id"] = top["id"]
    return fields


def armed(client, url: str, **body) -> dict:
    """A confirmed, armed request body for `url`, from a page that is not
    stale: `confirm` and `arm`, what `page_fields` reads, and `body`."""
    return {"confirm": True, "arm": True, **page_fields(client, url), **body}
