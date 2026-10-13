# atoo.app

The public page for Atoo: one static `index.html`, its images in `img/` and
`favicon.svg`. It is separate from the user documentation in
[`docs/`](./docs), which is its own site at docs.atoo.app.

Hosting: a **Cloudflare Workers** project (Workers Builds), `atoo-site`,
serving this folder as static assets ([`wrangler.jsonc`](./wrangler.jsonc)).
[`.assetsignore`](./.assetsignore) keeps `docs/`, the config, this README and wrangler's
local `.wrangler/` folder out of the upload.

## Edit it

There is no build. Open `index.html` in a browser to preview, edit, commit
and push. The page is dark only and must work at phone width (390px) with
no sideways scrolling. Below 600px the page swaps each screenshot for its
`-phone` crop, which is narrower and reads larger.

## Day-to-day

Cloudflare Workers Builds reacts to every push:

- a push to **`main`** runs `npx wrangler deploy` and goes to **production**
  at atoo.app;
- a push to any **other branch**, or a PR, runs `npx wrangler versions
  upload` and gets a **preview** URL, posted on the PR.

To roll back: the Worker's **Deployments** tab, then **Rollback**.

## First-time Cloudflare setup

Do this once, with access to the `atoo.app` zone.

**Don't attach atoo.app until this repository is public and holds the
code, and docs.atoo.app is up.** Until then the page's GitHub links 404 for
visitors, its `pipx install` line fails, and its Docs link goes nowhere.
Steps 1 to 3 are safe before that: the `*.workers.dev` URL is only a
preview.

1. Dashboard -> **Workers & Pages** -> **Create** -> **Import a repository** ->
   pick **`corourke/Atoo`**.
2. On **Set up your application**:

   | Field | Value |
   | --- | --- |
   | Project name | `atoo-site` |
   | Build command | *(leave empty)* |
   | Deploy command | `npx wrangler deploy` |
   | Non-production branch deploy command | `npx wrangler versions upload` |
   | Path *(Advanced settings)* | `website` |

3. **Deploy**, then open the `*.workers.dev` URL and check the page.
4. Custom domain, only once the bold condition above holds: the Worker -> **Settings** -> **Domains & Routes** ->
   **Add** -> **Custom domain** -> `atoo.app` (and `www.atoo.app` if wanted).

## Screenshots

The images are crops of the app running its packaged Demo show, captured at
1100px wide at 2x (and 560px for the `-phone` text crops). When the Demo
show or the screens change, retake them so the page never shows something
the app no longer does.
