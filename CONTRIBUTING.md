# Contributing

Thank you for looking. The most useful things you can send are not code,
so they come first.

## What helps most, in order

1. **A desk test report.** Run Atoo against your own WING and tell
   us what happened, good or bad. A WING Rack or full-size WING report
   is worth the most: the tool has been run on one WING Compact. Start
   read-only (`ping`, `audit`, `watch` never write), and write to a desk
   only when it is not doing a show and your show is saved.
   [Open a desk test report](../../issues/new?template=desk-test-report.yml).
2. **A war story.** Something that went silently wrong on a show: a
   wrong patch, a muted send, a phantom-power surprise. Each one can
   become an audit rule or a watch condition.
   [Tell us one](../../issues/new?template=war-story.yml).
3. **A conventions file** for a kind of show (worship, corporate,
   theatre, a festival changeover). Post it in Discussions, with the
   kind of show it is for. Shared conventions files are under
   [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), so others
   can adopt and adapt them with credit.
4. **A bug report**, with the journal file for a write that went wrong
   (`journals/` in the show's folder) or the `verify` output for a plan.
   [Report a bug](../../issues/new?template=bug.yml).
5. **Code.** Welcome, under the rules below.

Questions, ideas and "how do I" go in
[Discussions](../../discussions), so the issue list stays a list of
things to fix.

## Code

Start with [`atoo/README.md`](atoo/README.md): setting up a
working copy, where things are, and the test suite. Then:

- **The tests pass.** `python3 -m pytest -q`, with nothing failing.
  Add tests for what you change. A test never reads `examples/`: those
  are working show files, and `tests/conftest.py` refuses the read.
  Freeze what a test needs into `tests/fixtures/`.
- **The docs change in the same pull request.** A change to what the
  tool does updates the page that describes it: `docs/user/` for users,
  `docs/developer/requirements.md` if a requirement changes. Every
  command shown in a page under `docs/user/` is run before it is
  committed, and [`docs/user/STYLE.md`](docs/user/STYLE.md) says how
  those pages are written.
- **The CLI reference is generated.** After touching a command-line
  flag, run `python3 tools/gen_cli_reference.py`; a test fails while
  `docs/user/cli-reference.md` is out of date.
- **A change to the browser pages is opened in a browser.** The Python
  tests cannot see `atoo/web/static/`, so a renamed field shows as
  a blank, not a failure.
- **The engine stays dependency-free.** Only `atoo ui` may need
  third-party packages, behind the `ui` extra.
- **A choice the tool makes for the user is announced at INFO**, saying
  what was chosen and what it was inferred from. A setting the desk
  cannot hold is an error; a matter of taste is not.

Keep a pull request to one change, and say in its description what you
ran and what you could not check (a model you do not have, a desk you
do not own).

### AI-written contributions

Welcome, if you say so in the pull request, you have run it, and the
tests pass. It is the same rule the project holds itself to: [the
FAQ](docs/user/faq.md#is-this-ai-slop) says how it was built.

## Licence and the contributor agreement

<!-- Depends on the licence decision (AGPL-3.0 plus a commercial licence
     by agreement). The agreement's text is the maintainer's, drafted with
     a lawyer, and is linked here when it exists. See
     docs/product/release-checklist.md. -->

Contributions are under the project's licence: see [LICENSE](LICENSE).

**Code contributions also need a short contributor licence agreement**,
signed once. The project is offered under a commercial licence as well
as its open-source one, and it can only offer that on code it holds the
rights to. The agreement is linked from your first pull request.

Desk test reports, war stories, conventions files and bug reports need
no agreement.
