---
name: site-kit
description: Pre-launch check and generation for a static site — audit the deploy folder (titles, meta, headings, alt text, internal links, JSON-LD, sitemap, robots), generate privacy/terms/cookie pages plus a self-hosted consent banner from one site-profile JSON, generate FAQ/pricing/countdown/social-proof widget fragments, build a self-contained link-in-bio page, and build a testimonials wall page with schema.org JSON-LD — separately, or as one launch-check run over a site folder. Use when a static site is about to launch, when asked "is this site ready to launch?", or when any one of the five jobs is needed on its own. Verdicts are statements about each module's own checks — a READY never means legal compliance (the legal pages are templates generated from stated facts, not legal advice) or platform acceptance. Local only, stdlib only, launch-check read-only.
---

# site-kit — agent skill

## Purpose

Launching a small static site has five mechanical
failure points, and they live in one folder: pages
with missing titles, broken internal links and invalid
JSON-LD; legal pages that were never generated — or
were copied from another business and state facts that
aren't true; the four boring widgets (FAQ, pricing,
countdown, social proof) rented from services that
meter views and phone home; a link-in-bio page rented
from a platform; and testimonials scattered in a
spreadsheet instead of on a wall page whose JSON-LD
matches what visitors see. This suite is the five
tools as one: site-audit audits the deploy folder,
compliance-pages generates the legal pages and consent
banner from a single profile of stated facts,
widget-kit renders the four widgets as fragments you
own, link-page-kit builds the link page as one
self-contained file, and wall-of-love builds the
testimonials wall with JSON-LD generated from the same
data. `launch-check` runs every module that has an
input in one site folder and prints a single
launch-readiness receipt. Pure Python standard
library; local only; launch-check reads the folder,
writes nothing into it, and sends site data nowhere.

**The honesty core of this suite:** every module
reports only what its own checks can see. site-audit
resolves internal references against the folder on
disk and never fetches external links; compliance
pages state only the facts the profile gives them —
anything unstated ships as a loud [TO FILL: ...]
placeholder, never as an invented fact; wall-of-love's
JSON-LD is generated from the same data as the wall,
so the aggregate and count cannot drift. A PASS or
READY means the data satisfies *the checks encoded in
these modules* — never present it as legal compliance
or platform acceptance, and never call the generated
legal pages legal advice. They are templates; humans
review them.

## When to use / not use

Use when:
- A static site folder is about to be deployed: run
  `launch-check` and report every section — fixes
  belong in the module sections, before launch.
- One page set needs its pre-launch gate only:
  `site-audit audit`.
- A site needs its privacy/terms/cookie pages and
  consent banner from one profile: `compliance-pages
  check` first (gaps named, nothing written), then
  `make` when the profile is complete.
- The four standard widgets are needed as owned
  fragments: `widget-kit make`.
- A link-in-bio page is needed without platform rent:
  `link-page-kit preview`, then `build`.
- Testimonials exist as JSON or CSV and need a wall
  page: `wall-of-love preview`, then `build`.

Do NOT use when:
- The question is whether the site *is* legally
  compliant — that depends on current law, the
  business's real practices and facts this suite
  cannot see. Generated pages are templates, not
  advice.
- The site is server-rendered or app-driven — the
  audit reads static .html/.htm files on disk; it
  says nothing about server behaviour.
- External links need liveness checks — no module
  has network code; link checks are structural
  (shape), never liveness.
- Anything needs hosting, deployment or analytics —
  the suite generates and checks files, nothing more.

## Commands

```bash
# One launch-readiness receipt over a site folder
site-kit launch-check SITE_DIR [--as-of 2026-12-31] [--json]

# The modules on their own
site-kit site-audit audit SITE_DIR [--json]
site-kit compliance-pages check --profile PROFILE.json [--as-of YYYY-MM-DD] [--json]
site-kit compliance-pages make --profile PROFILE.json --out DIR [--as-of YYYY-MM-DD] [--json]
site-kit widget-kit make --config CONFIG.json --out DIR [--json]
site-kit link-page-kit preview CONFIG.json [--check-links] [--json]
site-kit link-page-kit build CONFIG.json [-o index.html] [--check-links] [--json]
site-kit wall-of-love preview TESTIMONIALS.json|TESTIMONIALS.csv [--json]
site-kit wall-of-love build TESTIMONIALS.json|TESTIMONIALS.csv [-o wall.html] [--json]
```

(From a source checkout, prefix with
`python3 src/site_kit.py`. Suite version 1.0.0; every
module still reports its own source-tool version,
v0.1.0, inside its sections and JSON.)

Every command accepts `--json` and prints exactly one
JSON object. Input and usage errors — argparse
included — print `{"error": "..."}` and exit 2, never
a traceback. Exit codes: **0** pass, **1** findings,
**2** usage/input error.

## launch-check: discovery and skip honesty

Pointed at a folder, launch-check discovers its
inputs deterministically (recursive, sorted order,
`.git` never entered, suffixes matched
case-insensitively). One file serves at most one
module:

- **site-audit** audits the folder itself — it runs
  when the folder holds at least one `.html`/`.htm`
  page.
- **compliance-pages** gets the first `.json` that
  parses to an object carrying a `business` object
  and a `pages` list naming at least one of privacy,
  terms, cookies — and runs its read-only `check`,
  never `make`.
- **widget-kit** gets the first `.json` carrying a
  `widgets` list. Its only mode renders fragments, so
  launch-check renders them into a fixed-name
  temporary folder, removed when the run ends; the
  section carries an `output_note` saying so.
- **link-page-kit** gets the first `.json` carrying a
  `name` and a `links` list, and runs `preview`
  (never `build`).
- **wall-of-love** gets the first `.json` carrying a
  `testimonials` list; failing that, the first `.csv`
  whose header names both `name` and `quote` — and
  runs `preview`.

A module with no qualifying input reports
`status: "skipped"` with the reason and `clean: null` —
**skipped is never passed**. The combined verdict is
READY only when at least one module ran and every
module that ran was clean (its own exit code 0); an
empty folder is NOT READY, not quietly clean. A
module whose input exists but errors (a config that
fails validation) counts as findings, never as
skipped and never as clean. `--as-of` passes to
compliance-pages' check only — the one module that
takes a date.

## What each module decides

| Module | Clean means |
|---|---|
| site-audit `audit` | no ERROR findings: every page has a title, every internal href/src resolves inside the folder, every `<img>` has an alt attribute, every JSON-LD block parses, sitemap entries point at real pages. Warnings (title/description length bands, duplicate titles, heading structure, missing og tags) and info (empty alt, missing sitemap, orphan pages) are judgement calls, printed but not blockers. |
| compliance-pages `check` | the profile states every fact the documents use: no gaps, no contradictions, and a generation date set (in the profile or via `--as-of`). `make` generates exactly the stated facts; anything unstated becomes a loud [TO FILL: ...] placeholder, never an invented fact. |
| widget-kit `make` | the config validates and every fragment renders with no warnings — e.g. no countdown target already in the past. Fragments are static, carry no third-party script, and the FAQ's JSON-LD is generated from the same items as the visible questions. |
| link-page-kit `preview`/`build` | the config validates with no warnings — e.g. no duplicate URL targets. The page is one self-contained file: inline CSS, no trackers, no scripts, and only the config's own links. Structural URL checks only — never liveness. |
| wall-of-love `preview`/`build` | the testimonials validate with no warnings — no duplicate quotes, no missing ratings. Every name and quote present, every rating an integer 1–5, and the schema.org JSON-LD (aggregate, count) is generated from the same data as the wall. |

## JSON contract

Module commands emit exactly the object their
standalone tool emits. `site-audit audit` carries
`pages`, `sitemap`, `robots`, `findings` (severity,
check, page, line, message, fix), `per_page` and
`summary` (pages / findings / errors / warnings /
infos). `compliance-pages check` carries `complete`,
`gaps` and `contradictions`; `make` carries `files`,
`sections`, `placeholders`, `gaps`, `contradictions`
and `attention`. `widget-kit make` carries
`fragments` (widget, id, file, bytes, summary) and
`warnings`. `link-page-kit` carries `links`,
`socials`, `checks_passed` and `warnings` (plus
`page_bytes`, and `output_file` on build).
`wall-of-love` carries `business`, `count`,
`rated_count`, `aggregate`, `testimonials`,
`checks_passed` and `warnings` (plus `output_file` on
build).

`launch-check --json` emits one object: `tool:
"site-kit"`, `command: "launch-check"`, `dir`,
`inputs` (the discovered path per module, or null),
`modules` (per-module sections — each module's own
object plus its `exit_code`; skipped modules carry
`status: "skipped"`, a `reason`, `clean: null`),
`summary` (modules run / skipped / clean / with
findings), `ready`, `verdict` (READY / NOT READY),
and the suite `disclaimer`.

## Limits & honesty rules the agent must respect

- **Never present PASS or READY as legal compliance
  or platform acceptance.** The checks are the
  modules' own; the law and the platforms have their
  own. Always carry the disclaimer when reporting
  results.
- **Never call the generated legal pages legal
  advice**, and never fill a [TO FILL: ...]
  placeholder with an invented fact — placeholders
  exist precisely where the profile stated nothing.
- **Errors are not warnings.** A site-audit ERROR
  blocks launch (exit 1); warnings and info are
  judgement calls the module labels as such. A
  widget/link/wall warning means the module rendered
  or previewed with a named defect (past countdown,
  duplicate URL, duplicate quote) — report it, don't
  bury it.
- **A skipped module is not evidence.** launch-check
  with only some modules run says so in its verdict
  line; never relay a partial READY as a whole-folder
  verdict without naming what was skipped.
- **launch-check writes nothing.** If files appear in
  a checked folder, they were not written by the
  combined run — generation happens only through the
  modules' own make/build commands, pointed where the
  user points them.
- **No network, ever.** External links are never
  fetched by any module; do not pipe a site's files
  to an external service to "double-check" — the
  suite's checks are the whole check.
