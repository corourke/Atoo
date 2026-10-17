"""The community files a visitor meets before the code:
CONTRIBUTING.md, SECURITY.md, CHANGELOG.md and the issue templates.

Nothing here runs at show time, so nothing else in the suite would notice
a template GitHub cannot parse, a link to a page that moved, or a label
the release checklist forgot to create. GitHub's own check of an issue
form only happens on the public repository, after it is too late.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TEMPLATES = REPO / ".github" / "ISSUE_TEMPLATE"
FORMS = ("bug.yml", "desk-test-report.yml", "war-story.yml")


def _local_links(markdown: str) -> list[str]:
    links = re.findall(r"\]\(([^)\s]+)\)", markdown)
    return [link.split("#", 1)[0] for link in links
            if not link.startswith(("http://", "https://", "../../", "#", "mailto:"))]


@pytest.mark.parametrize("name", ["CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md"])
def test_community_file_links_resolve(name):
    text = (REPO / name).read_text(encoding="utf-8")
    for link in _local_links(text):
        assert (REPO / link).exists(), f"{name} links to {link}, which is not in the repository"


def test_contributing_links_each_issue_form_by_its_file_name():
    """`../../issues/new?template=<file>` is how CONTRIBUTING reaches a
    form without naming the repository, so a rename leaves it alone."""
    text = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for form in FORMS:
        assert f"../../issues/new?template={form}" in text, form


def test_issue_forms_parse_and_their_labels_are_on_the_release_checklist():
    yaml = pytest.importorskip("yaml")
    # The checklist is the maintainer's own page; without it (the public
    # tree) the forms are still parsed, and only the label check stands down.
    checklist_path = REPO / "docs" / "product" / "release-checklist.md"
    checklist = checklist_path.read_text(encoding="utf-8") if checklist_path.is_file() else None
    for form in FORMS:
        data = yaml.safe_load((TEMPLATES / form).read_text(encoding="utf-8"))
        assert data["name"] and data["description"], form
        ids = [item["id"] for item in data["body"] if "id" in item]
        assert len(ids) == len(set(ids)), f"{form}: duplicate field ids {ids}"
        for item in data["body"]:
            assert item["type"] in {"markdown", "textarea", "input", "dropdown", "checkboxes"}
        for label in data.get("labels", []) if checklist is not None else []:
            assert f"`{label}`" in checklist, (
                f"{form} applies the label {label!r}, which the release checklist does not "
                "say to create -- GitHub drops a label that does not exist")
    config = yaml.safe_load((TEMPLATES / "config.yml").read_text(encoding="utf-8"))
    assert {link["url"].rsplit("/", 1)[-1] for link in config["contact_links"]} == {"discussions", "new"}


def test_the_issue_chooser_and_the_install_page_name_the_same_repository():
    """A rename has to change both; a half-done one sends a newcomer's
    questions to one repository and their install to another."""
    config = (TEMPLATES / "config.yml").read_text(encoding="utf-8")
    install = (REPO / "docs" / "user" / "install.md").read_text(encoding="utf-8")
    repos = set(re.findall(r"https://github\.com/([\w.-]+/[\w.-]+?)(?:\.git|/|\")", config + install))
    assert len(repos) == 1, repos


def test_the_licence_is_agpl_in_the_file_the_metadata_and_the_readme():
    """Decided 2026-10-11: AGPL-3.0, plus a commercial licence by
    agreement. corourke/Atoo carries the AGPL text, and a release copies
    this repository's LICENSE over it, so the two must not disagree."""
    import tomllib

    licence = (REPO / "LICENSE").read_text(encoding="utf-8")
    assert licence.lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE")
    assert "Version 3, 19 November 2007" in licence
    meta = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert meta["project"]["license"] == {"text": "AGPL-3.0-or-later"}
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    section = readme[readme.index("## Licence"):]
    assert "AGPL-3.0" in section and "commercial licence" in section
    assert "Apache" not in readme
