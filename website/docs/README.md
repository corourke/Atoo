# Atoo user documentation

The public user guide for Atoo, built with [Astro](https://astro.build) +
[Starlight](https://starlight.astro.build), the same way as GigWrangler's
(`corourke/gigmanager`, `website/docs/`). Target: **docs.atoo.app**.

Hosting: a **Cloudflare Workers** project (Workers Builds), `atoo-docs`,
serving the static `dist/` as assets: separate from the marketing site
(`website/`).

> **Style guide:** [`STYLE.md`](./STYLE.md)

---

## Where the pages come from

**Do not edit `src/content/docs/` by hand.** Until the two repositories'
workflow is settled, the user guide's source of truth is `docs/user/` in the
development repository, where its worked examples are re-run by the test
suite. The pages here are a one-way port of it:

```bash
cd website/docs
python3 tools/port_user_docs.py <path to the development repo>/docs/user
npm run build && npm run check-links
```

The port (`tools/port_user_docs.py`) rebuilds `src/content/docs/` and
`src/assets/img/` from scratch every run:

- each page goes to its section's folder (the `SECTIONS` table in the
  script), with its H1 as `title`, its first paragraph as `description` and
  its place in the table as `sidebar.order`;
- the old product name becomes Atoo everywhere: commands, `ATOO_*`
  variables, `~/.atoo.config`, `~/Documents/Atoo`;
- a link to another page becomes the site's URL, with its anchor; a link
  that leaves the user guide (the developer docs, the repository's own
  files) keeps its text and loses the link, and the port lists each one;
- `docs/user/README.md` becomes the front page, without its section for
  the pages' writers.

A page added to `docs/user/` without a place in `SECTIONS` stops the port,
and so does a link to a page that does not exist.

**The command reference** (`reference/cli-reference`) is generated twice
over: `tools/gen_cli_reference.py` in the development repository writes
`docs/user/cli-reference.md` from the CLI's own argparse tree (a test there
fails while it is stale), and the port carries it here like any page. Never
edit its option tables.

---

## Run it locally

```bash
cd website/docs
npm install          # first time only (Node >= 22.12)
npm run dev          # http://localhost:4321, hot-reloads as you edit
```

The production build, as Cloudflare runs it:

```bash
npm run build        # static site → website/docs/dist/
npm run check-links  # every internal link and anchor in dist/ resolves
npm run preview      # serve dist/ at http://localhost:4321
```

You do **not** commit `dist/`; Cloudflare runs `npm run build` itself.

### Hiding unfinished pages

`draft: true` in a page's frontmatter keeps it out of `npm run build`
(production and Cloudflare previews); `npm run dev` and
`npm run build:staging` still show it. The port sets it for the pages in its
`DRAFTS` set (none today). A published page must not link to a draft:
`check-links` reports it.

---

## Look

Dark first, matching the app (`src/styles/theme.css`): near-black, the
app's brass accent, sharp corners and bold uppercase labels.
`astro.config.mjs` makes dark the default for a first visit; a reader's own
choice in the theme menu is kept. Light is a secondary check.

---

## Publish (Cloudflare Workers Builds)

Once the Worker is connected (first-time setup below), pushing deploys:
**`main`** → `npm run build`, then `npx wrangler deploy` → docs.atoo.app; any
other branch or a PR → `npx wrangler versions upload` → a preview URL on the
PR.

First-time setup, once, with access to the `atoo.app` zone:

1. Dashboard → **Workers & Pages** → **Create** → **Import a repository** →
   pick **`corourke/Atoo`**.
2. **Set up your application**:
   | Field | Value |
   | --- | --- |
   | Project name | `atoo-docs` |
   | Build command | `npm run build` |
   | Deploy command | `npx wrangler deploy` |
   | Non-production branch deploy command | `npx wrangler versions upload` |
   | Path *(Advanced settings)* | `website/docs` |
3. **Deploy**, then open the `atoo-docs.<subdomain>.workers.dev` URL.
4. Custom domain: the Worker → **Settings** → **Domains & Routes** →
   **Add** → **Custom domain** → `docs.atoo.app` (or uncomment `routes` in
   `wrangler.jsonc`).

`.nvmrc` pins Node 22 for the Cloudflare build.

---

## Where things live

| Path | What |
| --- | --- |
| `astro.config.mjs` | Site config and the sidebar sections |
| `src/content/docs/**` | The pages: **generated** by the port |
| `src/assets/img/` | Screenshots: **copied** by the port |
| `src/assets/logo.svg`, `public/favicon.svg` | The A2 mark |
| `src/styles/theme.css` | The app-matching theme |
| `tools/port_user_docs.py` | The one-way port from `docs/user/` |
| `tools/check_links.py` | Internal link and anchor check over `dist/` |
| `wrangler.jsonc` | Cloudflare Worker deploy config |
| `dist/` | Build output (git-ignored) |
