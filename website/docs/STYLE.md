# Style

The pages under `src/content/docs/` are generated from the user guide in
the development repository, and **its** `docs/user/STYLE.md` is the style
guide for them: voice, words, formatting, and the rule that every worked
example is run before it is committed. Edit a page there, never here.

Rules for this site only:

- **The theme** (`src/styles/theme.css`) follows the app's own look: dark
  first, near-black, the brass accent, sharp corners, bold uppercase
  labels. Check a change in the dark theme first, then light.
- **The sidebar sections** come from the converter's `SECTIONS` table in
  the development repository; `astro.config.mjs` only names them. A new
  section needs both.
- **Before a change here ships:** `npm run build` and
  `npm run check-links` (every internal link and anchor resolves).
