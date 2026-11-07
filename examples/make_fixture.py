#!/usr/bin/env python3
"""Build the site-kit example fixtures.

Two folders for one fictional small-business site —
Exampleton Trail Gear — in the shapes site-kit
launch-check discovers: the deploy pages themselves
(site-audit's input), a compliance-pages site profile,
a widget-kit config, a link-page-kit config and a
wall-of-love testimonials file, side by side in one
folder, the way a real site's working folder holds
them.

The module inputs are the modules' own proven samples,
gathered verbatim from the ported examples (the
complete compliance profile, the four-widget config
with its proof entries, the link-page config, the
six-testimonial wall file), so the clean folder's
expectations rest on inputs whose standalone verdicts
are already pinned by the ported suites.

build_clean(root) — everything checks out:
  index.html       one page with every element the
                   audit asks for (site-audit: 0
                   findings, 0 errors)
  sitemap.xml,
  robots.txt       copied from the ported clean-site
                   example; the sitemap resolves
  profile.json     the complete sample profile
                   (compliance-pages check: COMPLETE,
                   0 gaps, 0 contradictions)
  widgets.json     the sample four-widget config plus
  proof-entries.*  its entries files (widget-kit make:
                   4 fragments, 0 warnings)
  links.json       the sample link-page config
                   (link-page-kit preview: 0 warnings)
  testimonials.json  the sample wall file
                   (wall-of-love preview: 6
                   testimonials, 0 warnings)
  => launch-check: 5 modules run, 5 clean, READY,
     exit 0 — and the folder is byte-identical
     afterwards (launch-check writes nothing into it)

build_faulty(root) — ONE planted fault per module:
  index.html       the <title> element REMOVED, every
                   other element present (site-audit:
                   exactly 1 finding — the error
                   title-missing; 0 warnings)
  profile.json     the complete profile with the
                   "retention" fact REMOVED
                   (compliance-pages check: exactly 1
                   gap, field retention; 0
                   contradictions; INCOMPLETE)
  widgets.json     one countdown whose target is
                   2020-01-01 (widget-kit make: exactly
                   1 warning — the target is in the
                   past)
  links.json       the sample config with its first
                   link DUPLICATED at the end
                   (link-page-kit preview: exactly 1
                   warning — duplicate URL)
  testimonials.json  two testimonials carrying the
                   SAME quote verbatim (wall-of-love
                   preview: exactly 1 warning —
                   duplicate quote)
  => launch-check: 5 modules run, 0 clean, NOT READY,
     exit 1

Every expectation above was stated from the fixture's
construction and verified against the modules'
standalone runs before the fixture was pinned.

Usage:
    python3 examples/make_fixture.py TARGET [--clean]
"""

import json
import shutil
import sys
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent

PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{title}<meta name="description" content="A full sentence describing this page for search results and shared links.">
<meta property="og:title" content="Exampleton Trail Gear">
<meta property="og:description" content="A full sentence describing this page for search results and shared links.">
</head>
<body>
<h1>Exampleton Trail Gear</h1>
<p>Boots, packs and honest advice.</p>
</body>
</html>
"""

FAULTY_TESTIMONIALS = {
    "business": "Exampleton Trail Gear",
    "testimonials": [
        {"name": "Ana Ruiz",
         "quote": "The boots survived the whole trail "
                  "season.",
         "rating": 5},
        {"name": "Ben Osei",
         "quote": "The boots survived the whole trail "
                  "season.",
         "rating": 4},
    ],
}


def _copy(src, dst):
    shutil.copy(EXAMPLES / src, dst)


def _write_json(obj, dst):
    dst.write_text(json.dumps(obj, indent=2) + "\n",
                   encoding="utf-8")


def _load(rel):
    return json.loads((EXAMPLES / rel).read_text(
        encoding="utf-8"))


def build_clean(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(
        PAGE_HEAD.format(
            title="<title>Exampleton Trail Gear</title>\n"),
        encoding="utf-8")
    _copy("site-audit/clean-site/sitemap.xml",
          root / "sitemap.xml")
    _copy("site-audit/clean-site/robots.txt",
          root / "robots.txt")
    _copy("compliance-pages/sample-site.json",
          root / "profile.json")
    _copy("widget-kit/widgets.json", root / "widgets.json")
    _copy("widget-kit/proof-entries.json",
          root / "proof-entries.json")
    _copy("widget-kit/proof-entries.csv",
          root / "proof-entries.csv")
    _copy("link-page-kit/sample-config.json",
          root / "links.json")
    _copy("wall-of-love/sample-testimonials.json",
          root / "testimonials.json")
    return root


def build_faulty(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(
        PAGE_HEAD.format(title=""), encoding="utf-8")
    _copy("site-audit/clean-site/sitemap.xml",
          root / "sitemap.xml")
    _copy("site-audit/clean-site/robots.txt",
          root / "robots.txt")
    profile = _load("compliance-pages/sample-site.json")
    del profile["retention"]
    _write_json(profile, root / "profile.json")
    _copy("widget-kit/past-countdown.json",
          root / "widgets.json")
    links = _load("link-page-kit/sample-config.json")
    links["links"] = links["links"] + [links["links"][0]]
    _write_json(links, root / "links.json")
    _write_json(FAULTY_TESTIMONIALS,
                root / "testimonials.json")
    return root


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or len(argv) > 2:
        print("usage: make_fixture.py TARGET [--clean]")
        return 2
    target = Path(argv[0])
    if "--clean" in argv[1:]:
        build_clean(target)
    else:
        build_faulty(target)
    print(f"fixture written to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
