#!/usr/bin/env python3
"""site-audit — a plain-language audit of a static site's
deploy folder, before launch.

Pure Python standard library. Local only: it reads the HTML
files in the ONE folder you point it at, checks them against
each other and against the folder itself, and sends nothing
anywhere. Internal links are resolved against the folder on
disk; external links are never fetched — there is no network
code in this tool at all.

THE PROBLEM: a crawl tool like Screaming Frog costs
£199/yr/user (~₹26,575 / CAD $391), caps its free tier at 500
URLs, and — in its reviewers' words — "reports raw crawl
data… turning it into a client report takes work". So small
sites launch with missing titles, duplicate meta, broken
internal links and images with no alt text, because nobody
ran the plain-language pass. site-audit is that pass: point
it at the folder you are about to deploy and get a
prioritised fix list a client can read — each finding names
the page, the measured fact, and the one-line fix.

WHAT IT CHECKS (the full table, with each check's class and
basis, lives in SKILL.md):

  per page   title present/unique/length band · meta
             description present/unique/length band ·
             viewport · charset · <html lang> · exactly one
             <h1> · heading order · image alt attributes ·
             Open Graph basics · JSON-LD parses
  site-wide  internal hrefs/srcs resolve to real files in
             the folder · sitemap.xml entries resolve ·
             robots.txt Sitemap line resolves · pages no
             other page links to (orphans)

THE BANDS ARE HEURISTICS, labelled as such wherever they
appear: title 10–60 characters, meta description 50–160
characters. They are the widely used display-length rules of
thumb, not laws — a 61-character title is a warning to look,
not a broken page. The ERROR class is reserved for facts:
no title at all, a link to a file that does not exist, an
image with no alt attribute, a JSON-LD block that does not
parse, a sitemap entry for a page that is not there.

NO SCORE: the summary reports counts only. This tool never
invents a "health score" — a folder has 5 errors or it has
none, and the counts are the whole story.

MALFORMED HTML IS INPUT, NOT AN EXCEPTION: pages are parsed
with html.parser and decoded leniently, so a broken page
yields findings, never a traceback.

Exit codes: 0 = no errors (warnings/info may exist) ·
1 = at least one ERROR finding · 2 = input error (folder
missing, not a folder, or no HTML files in it) — clean
message, never a traceback; with --json the error is
{"error": ...}.
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

__version__ = "0.1.0"
TOOL = "site-audit"

# Heuristic display-length bands (see module docstring and
# SKILL.md — warnings, never errors).
TITLE_MIN, TITLE_MAX = 10, 60
DESC_MIN, DESC_MAX = 50, 160

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
HTML_SUFFIXES = {".html", ".htm"}
INDEX_NAMES = ("index.html", "index.htm")


class ToolError(Exception):
    """An input error: clean message, exit 2, no traceback."""


def finding(page, line, check, severity, message, fix):
    return {"page": page, "line": line, "check": check,
            "severity": severity, "message": message, "fix": fix}


def norm_text(text):
    """Collapse whitespace and case-fold, for duplicate
    comparisons (the same rule wall-of-love uses for quotes)."""
    return " ".join((text or "").split()).casefold()


# ----------------------------------------------------------------
# Page parsing — html.parser only; tolerant by construction.
# ----------------------------------------------------------------

class PageParser(HTMLParser):
    """Collects exactly what the checks need from one page:
    the <html> attributes, meta tags, title text, headings in
    document order, images, href/src references, and the raw
    text of any JSON-LD blocks. getpos() at a start tag gives
    the 1-based line the finding should point at."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.html_attrs = None          # attrs of first <html>
        self.metas = []                 # (attrs dict, line)
        self.title = None               # stripped title text
        self.title_line = None
        self.headings = []              # (level, line)
        self.h1_text = None             # text of the first <h1>
        self.images = []                # (attrs dict, line)
        self.refs = []                  # (tag, attr, value, line)
        self.jsonld = []                # (raw text, line)
        self._in_title = False
        self._title_parts = []
        self._in_h1 = False
        self._h1_parts = []
        self._in_jsonld = False
        self._jsonld_parts = []
        self._jsonld_line = None

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        ad = {}
        for k, v in attrs:
            ad.setdefault(k.lower(), v if v is not None else "")
        if tag == "html" and self.html_attrs is None:
            self.html_attrs = ad
        elif tag == "meta":
            self.metas.append((ad, line))
        elif tag == "title" and self.title is None \
                and not self._in_title:
            self._in_title = True
            self._title_parts = []
            self.title_line = line
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.headings.append((int(tag[1]), line))
            if tag == "h1" and self.h1_text is None \
                    and not self._in_h1:
                self._in_h1 = True
                self._h1_parts = []
        elif tag == "img":
            self.images.append((ad, line))
        elif tag == "script" and \
                ad.get("type", "").strip().lower() == \
                "application/ld+json":
            self._in_jsonld = True
            self._jsonld_parts = []
            self._jsonld_line = line
        for attr in ("href", "src"):
            if attr in ad:
                self.refs.append((tag, attr, ad[attr], line))

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = "".join(self._title_parts).strip()
        elif tag == "h1" and self._in_h1:
            self._in_h1 = False
            self.h1_text = "".join(self._h1_parts).strip()
        elif tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self.jsonld.append(
                ("".join(self._jsonld_parts), self._jsonld_line))

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)
        if self._in_h1:
            self._h1_parts.append(data)
        if self._in_jsonld:
            self._jsonld_parts.append(data)

    def finish(self):
        """Flush an unclosed <title>/<h1>/<script> at EOF —
        malformed pages still yield their facts."""
        if self._in_title:
            self._in_title = False
            self.title = "".join(self._title_parts).strip()
        if self._in_h1:
            self._in_h1 = False
            self.h1_text = "".join(self._h1_parts).strip()
        if self._in_jsonld:
            self._in_jsonld = False
            self.jsonld.append(
                ("".join(self._jsonld_parts), self._jsonld_line))


def parse_page(path):
    """Read and parse one HTML file. Decoding is lenient
    (errors replaced) and parsing is wrapped, so a broken
    page produces facts, never an exception."""
    text = path.read_bytes().decode("utf-8", errors="replace")
    parser = PageParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        # html.parser is tolerant by design; if anything still
        # trips it, the facts collected so far are the audit.
        pass
    parser.finish()
    return parser


# ----------------------------------------------------------------
# Reference resolution — the folder is the whole world.
# ----------------------------------------------------------------

def _inside(root, candidate):
    """Absolute-normalised candidate must stay within root."""
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_target(root, base_dir, raw):
    """Resolve one reference against the folder.

    Returns None when the reference is not existence-checked
    (empty, anchor-only, any scheme, protocol-relative, or a
    bare query/fragment), else (ok, rel_posix_or_None, reason)
    where reason describes a failure in plain words."""
    value = (raw or "").strip()
    if not value or value.startswith("#"):
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return None                     # external / other scheme
    path_part = unquote(parts.path)
    if not path_part:
        return None                     # same-page query/fragment
    root_abs = Path(root).resolve()
    if path_part.startswith("/"):
        candidate = root_abs / path_part.lstrip("/")
    else:
        candidate = Path(base_dir).resolve() / path_part
    candidate = Path(os.path.normpath(candidate))
    if not _inside(root_abs, candidate):
        return (False, None, "points outside the site folder")
    if candidate.is_file():
        return (True, candidate.relative_to(root_abs)
                .as_posix(), "")
    if candidate.is_dir():
        for name in INDEX_NAMES:
            idx = candidate / name
            if idx.is_file():
                return (True, idx.relative_to(root_abs)
                        .as_posix(), "")
        return (False, None,
                "resolves to a folder with no index.html in it")
    return (False, None, "does not resolve to a file in the folder")


# ----------------------------------------------------------------
# Per-page checks
# ----------------------------------------------------------------

def check_page(rel, page, root):
    """All per-page checks except duplicates and orphans
    (those need the whole site). Returns a findings list."""
    out = []
    page_dir = (root / rel).parent

    # --- title presence & length (duplicates are site-wide) ---
    if page.title is None or page.title == "":
        out.append(finding(
            rel, page.title_line, "title-missing", "error",
            "the page has no <title> (or it is empty) — "
            "browsers and search results will show the URL "
            "instead",
            "add a <title> in the <head> naming this page"))
    else:
        n = len(page.title)
        if n < TITLE_MIN or n > TITLE_MAX:
            out.append(finding(
                rel, page.title_line, "title-length", "warning",
                f"title is {n} characters (heuristic band "
                f"{TITLE_MIN}–{TITLE_MAX}: shorter rarely "
                "describes the page, longer is usually "
                "truncated in search results)",
                "rewrite the title to describe this page "
                "within the band"))

    # --- meta description presence & length ---
    descs = [ad.get("content", "") for ad, _ in page.metas
             if ad.get("name", "").strip().lower()
             == "description"]
    if not descs or not descs[0].strip():
        out.append(finding(
            rel, None, "meta-description-missing", "warning",
            "no meta description — search results will show a "
            "random snippet of the page text instead",
            "add <meta name=\"description\" content=\"...\"> "
            "summarising this page"))
    else:
        n = len(descs[0].strip())
        if n < DESC_MIN or n > DESC_MAX:
            out.append(finding(
                rel, None, "meta-description-length", "warning",
                f"meta description is {n} characters (heuristic "
                f"band {DESC_MIN}–{DESC_MAX}: shorter is usually "
                "truncated by nothing and says little, longer "
                "is usually cut off in results)",
                "aim for one or two full sentences in the band"))

    # --- viewport / charset / lang ---
    if not any(ad.get("name", "").strip().lower() == "viewport"
               for ad, _ in page.metas):
        out.append(finding(
            rel, None, "meta-viewport-missing", "warning",
            "no viewport meta — phones will render the page at "
            "desktop width and shrink it",
            "add <meta name=\"viewport\" "
            "content=\"width=device-width, initial-scale=1\">"))
    has_charset = any(
        "charset" in ad or
        (ad.get("http-equiv", "").strip().lower()
         == "content-type"
         and "charset" in ad.get("content", "").lower())
        for ad, _ in page.metas)
    if not has_charset:
        out.append(finding(
            rel, None, "charset-missing", "warning",
            "no character encoding declared — browsers guess, "
            "and guessed encodings mangle punctuation and "
            "names",
            "add <meta charset=\"utf-8\"> as the first element "
            "of the <head>"))
    if page.html_attrs is None or \
            not page.html_attrs.get("lang", "").strip():
        out.append(finding(
            rel, None, "html-lang-missing", "warning",
            "the <html> element declares no lang — screen "
            "readers and translation tools cannot tell what "
            "language the page is in",
            "add a lang attribute, e.g. <html lang=\"en\">"))

    # --- headings ---
    h1_lines = [ln for lvl, ln in page.headings if lvl == 1]
    if not h1_lines:
        out.append(finding(
            rel, None, "h1-count", "warning",
            "the page has no <h1> — nothing tells a reader or "
            "a search engine what this page is mainly about",
            "add exactly one <h1> naming the page's topic"))
    elif len(h1_lines) > 1:
        out.append(finding(
            rel, h1_lines[1], "h1-count", "warning",
            f"the page has {len(h1_lines)} <h1> elements — "
            "exactly one is the convention every outline tool "
            "expects",
            "demote the extra <h1> elements to <h2>"))
    for (prev, _), (lvl, ln) in zip(page.headings,
                                    page.headings[1:]):
        if lvl > prev + 1:
            out.append(finding(
                rel, ln, "heading-order-skip", "warning",
                f"heading level jumps from h{prev} to h{lvl} — "
                "a level is skipped, which breaks the document "
                "outline for screen readers",
                f"use h{prev + 1} here, or add the missing "
                "level above it"))

    # --- images ---
    for ad, ln in page.images:
        src = ad.get("src", "")
        if "alt" not in ad:
            out.append(finding(
                rel, ln, "img-alt-missing", "error",
                f"image \"{src}\" has no alt attribute at all — "
                "screen readers and broken-image fallbacks have "
                "nothing to say for it",
                "add alt text describing the image, or alt=\"\" "
                "if it is purely decorative"))
        elif ad.get("alt", "") == "":
            out.append(finding(
                rel, ln, "img-alt-empty", "info",
                f"image \"{src}\" has an empty alt — correct "
                "for a decorative image, a lost description if "
                "it carries meaning",
                "leave it if the image is decorative; describe "
                "it if it carries meaning"))

    # --- Open Graph basics ---
    props = {ad.get("property", "").strip().lower()
             for ad, _ in page.metas}
    if "og:title" not in props:
        out.append(finding(
            rel, None, "og-title-missing", "warning",
            "no og:title — links to this page shared in chats "
            "and social feeds fall back to the <title> or the "
            "URL",
            "add <meta property=\"og:title\" content=\"...\">"))
    if "og:description" not in props:
        out.append(finding(
            rel, None, "og-description-missing", "warning",
            "no og:description — shared links show no summary "
            "line under the title",
            "add <meta property=\"og:description\" "
            "content=\"...\">"))

    # --- JSON-LD validity ---
    for raw, ln in page.jsonld:
        try:
            json.loads(raw)
        except json.JSONDecodeError as exc:
            out.append(finding(
                rel, ln, "jsonld-invalid", "error",
                f"a JSON-LD block does not parse as JSON "
                f"({exc.msg} at line {exc.lineno} of the "
                "block) — search engines discard the whole "
                "block",
                "fix the JSON syntax in the "
                "application/ld+json block"))

    # --- internal references resolve ---
    for tag, attr, value, ln in page.refs:
        res = resolve_target(root, page_dir, value)
        if res is None:
            continue
        ok, _target, reason = res
        if not ok:
            out.append(finding(
                rel, ln, "broken-internal-link", "error",
                f"{tag}[{attr}] \"{value.strip()}\" {reason}",
                "point the reference at an existing file in "
                "the folder, or add the missing file"))
    return out


# ----------------------------------------------------------------
# Site-wide checks
# ----------------------------------------------------------------

def check_duplicates(pages):
    """Duplicate titles across the site. A repeated title
    whose page also repeats the first page's <h1> is reported
    as the stronger duplicate-title-h1 instead — one finding
    per extra page, never both."""
    out = []
    by_title = {}
    for rel in sorted(pages):
        page = pages[rel]
        if page.title:
            by_title.setdefault(norm_text(page.title),
                                []).append(rel)
    for _key, rels in by_title.items():
        if len(rels) < 2:
            continue
        first = rels[0]
        first_h1 = pages[first].h1_text
        for rel in rels[1:]:
            page = pages[rel]
            h1 = page.h1_text
            if first_h1 and h1 \
                    and norm_text(h1) == norm_text(first_h1):
                out.append(finding(
                    rel, page.title_line, "duplicate-title-h1",
                    "warning",
                    f"title \"{page.title}\" and first heading "
                    f"\"{h1}\" are identical to {first}'s — the "
                    "two pages present as the same page to "
                    "search results and readers",
                    "give this page its own title and heading, "
                    "or merge the two pages"))
            else:
                out.append(finding(
                    rel, page.title_line, "title-duplicate",
                    "warning",
                    f"title \"{page.title}\" is also used on "
                    f"{first} — duplicate titles compete with "
                    "each other in search results",
                    "give each page a unique title"))
    # Duplicate meta descriptions (title rule does not apply).
    by_desc = {}
    for rel in sorted(pages):
        for ad, _ in pages[rel].metas:
            if ad.get("name", "").strip().lower() \
                    == "description":
                content = ad.get("content", "").strip()
                if content:
                    by_desc.setdefault(norm_text(content),
                                       []).append(rel)
                break
    for _key, rels in by_desc.items():
        if len(rels) < 2:
            continue
        for rel in rels[1:]:
            out.append(finding(
                rel, None, "meta-description-duplicate",
                "warning",
                f"this page's meta description is identical to "
                f"{rels[0]}'s — each page should summarise "
                "itself",
                "write a description for this page's own "
                "content"))
    return out


def check_orphans(pages, root):
    """A page (other than the root index) that no other page
    links to with an <a href>. Self-links do not count, and
    sitemap entries do not count — a page only a sitemap
    knows about is a page no visitor can reach."""
    inbound = set()
    for rel in sorted(pages):
        page_dir = (root / rel).parent
        for tag, attr, value, _ln in pages[rel].refs:
            if tag != "a" or attr != "href":
                continue
            res = resolve_target(root, page_dir, value)
            if res and res[0] and res[1] \
                    and res[1] != rel \
                    and res[1].lower().endswith(
                        tuple(HTML_SUFFIXES)):
                inbound.add(res[1])
    out = []
    for rel in sorted(pages):
        if rel in INDEX_NAMES:
            continue                    # the root index is home
        if rel not in inbound:
            out.append(finding(
                rel, None, "orphan-page", "info",
                "no other page in the folder links to this "
                "page — visitors can only reach it by typing "
                "the URL or from a sitemap",
                "link to it from a related page, or remove it "
                "if it is retired"))
    return out


def _loc_paths(sitemap_path):
    """The <loc> texts of a sitemap, by local tag name (the
    sitemap namespace is ignored on purpose). Raises
    ToolError-free ValueError on malformed XML."""
    tree = ET.parse(sitemap_path)
    locs = []
    for elem in tree.getroot().iter():
        if elem.tag.rsplit("}", 1)[-1] == "loc" \
                and elem.text and elem.text.strip():
            locs.append(elem.text.strip())
    return locs


def check_sitemap(root):
    """Returns (findings, present, entry_count)."""
    sm = root / "sitemap.xml"
    if not sm.is_file():
        return ([finding(
            "(site)", None, "sitemap-missing", "info",
            "the folder has no sitemap.xml — search engines "
            "will still crawl links, but nothing hands them "
            "the page list",
            "add a sitemap.xml listing the public pages, or "
            "ignore this if the site is not meant to be "
            "indexed")], False, 0)
    try:
        locs = _loc_paths(sm)
    except ET.ParseError as exc:
        return ([finding(
            "sitemap.xml", None, "sitemap-invalid", "error",
            f"sitemap.xml is not well-formed XML ({exc}) — "
            "search engines will discard it",
            "fix the XML syntax in sitemap.xml")], True, 0)
    out = []
    for loc in locs:
        # A sitemap loc is one of the site's own URLs; its
        # path maps onto the folder root. A loc with no path
        # is the site root itself.
        path = urlsplit(loc).path or "/"
        res = resolve_target(root, root, path)
        if res is not None and not res[0]:
            out.append(finding(
                "sitemap.xml", None, "sitemap-entry-broken",
                "error",
                f"sitemap entry \"{loc}\" {res[2]} — the "
                "sitemap promises a page the folder does not "
                "contain",
                "add the page, or remove the entry from "
                "sitemap.xml"))
    return (out, True, len(locs))


def check_robots(root):
    """robots.txt, when present: a Sitemap: line pointing at
    a file the folder does not contain. Returns (findings,
    present)."""
    rb = root / "robots.txt"
    if not rb.is_file():
        return ([], False)
    out = []
    text = rb.read_bytes().decode("utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("sitemap:"):
            url = stripped[len("sitemap:"):].strip()
            path = urlsplit(url).path
            res = resolve_target(root, root,
                                 path if path else "/")
            if res is not None and not res[0]:
                out.append(finding(
                    "robots.txt", None, "robots-sitemap-missing",
                    "warning",
                    f"robots.txt points search engines at "
                    f"sitemap \"{url}\", which {res[2]}",
                    "fix the Sitemap line in robots.txt, or "
                    "add the sitemap file"))
    return (out, True)


# ----------------------------------------------------------------
# The audit
# ----------------------------------------------------------------

def discover_pages(root):
    """All .html/.htm files under root, as sorted posix
    relative paths. Dot-directories (.git and friends) are
    skipped — they are not the deployable site."""
    rels = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in HTML_SUFFIXES:
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts[:-1]):
            continue
        rels.append(rel.as_posix())
    return sorted(rels)


def audit_folder(folder):
    root = Path(folder)
    if not root.exists():
        raise ToolError(f"folder not found: {folder}")
    if not root.is_dir():
        raise ToolError(f"not a folder: {folder}")
    rels = discover_pages(root)
    if not rels:
        raise ToolError(
            f"no HTML files (.html/.htm) found in: {folder}")

    pages = {}
    findings = []
    for rel in rels:
        page = parse_page(root / rel)
        pages[rel] = page
        findings.extend(check_page(rel, page, root))
    findings.extend(check_duplicates(pages))
    findings.extend(check_orphans(pages, root))
    sm_findings, sm_present, sm_entries = check_sitemap(root)
    findings.extend(sm_findings)
    rb_findings, rb_present = check_robots(root)
    findings.extend(rb_findings)

    findings.sort(key=lambda f: (
        SEVERITY_ORDER[f["severity"]], f["page"],
        f["check"], f["line"] or 0, f["message"]))

    per_page = {}
    for rel in rels:
        per_page[rel] = {"errors": 0, "warnings": 0, "infos": 0}
    site_counts = {"errors": 0, "warnings": 0, "infos": 0}
    for f in findings:
        bucket = {"error": "errors", "warning": "warnings",
                  "info": "infos"}[f["severity"]]
        site_counts[bucket] += 1
        if f["page"] in per_page:
            per_page[f["page"]][bucket] += 1

    return {
        "tool": TOOL,
        "version": __version__,
        "command": "audit",
        "folder": str(folder),
        "pages": rels,
        "sitemap": {"present": sm_present,
                    "entries": sm_entries},
        "robots": {"present": rb_present},
        "findings": findings,
        "per_page": per_page,
        "summary": {"pages": len(rels),
                    "findings": len(findings),
                    **site_counts},
    }


def render_text(result):
    s = result["summary"]
    lines = [
        f"{TOOL} v{result['version']} — audit · folder "
        f"{result['folder']}",
        f"{s['pages']} page(s) · sitemap.xml "
        f"{'present' if result['sitemap']['present'] else 'absent'}"
        f" · robots.txt "
        f"{'present' if result['robots']['present'] else 'absent'}",
        "Local only: internal references are checked against "
        "the folder on disk; external links are never fetched.",
        "",
    ]
    groups = [("error", "ERRORS — fix before launch"),
              ("warning", "WARNINGS — should fix"),
              ("info", "INFO — worth knowing")]
    for severity, label in groups:
        group = [f for f in result["findings"]
                 if f["severity"] == severity]
        if not group:
            continue
        lines.append(f"{label} ({len(group)}):")
        for f in group:
            where = f["page"]
            if f["line"]:
                where += f":{f['line']}"
            lines.append(f"[{f['check']}] {where} — "
                         f"{f['message']}")
            lines.append(f"  fix: {f['fix']}")
        lines.append("")
    lines.append("Per-page summary (counts only):")
    for rel in result["pages"]:
        c = result["per_page"][rel]
        lines.append(f"  {rel} — {c['errors']} error(s) · "
                     f"{c['warnings']} warning(s) · "
                     f"{c['infos']} info")
    lines.append("")
    lines.append(
        f"Summary: {s['findings']} finding(s) · {s['errors']} "
        f"error(s) · {s['warnings']} warning(s) · "
        f"{s['infos']} info across {s['pages']} page(s)")
    if s["errors"]:
        lines.append(f"Verdict: FAIL — {s['errors']} error(s) "
                     "to fix before launch.")
    else:
        lines.append("Verdict: PASS — no errors. Warnings and "
                     "info above are judgement calls, not "
                     "blockers.")
    return "\n".join(lines)


# ----------------------------------------------------------------
# CLI
# ----------------------------------------------------------------

class _JsonAwareParser(argparse.ArgumentParser):
    """ArgumentParser that reports usage errors as JSON in
    --json mode ({"error": ...} on stdout, same exit code 2) —
    an agent driving this tool with --json never gets plain
    text or a traceback. The flag lives on the class so
    subparsers share it."""

    json_mode = False

    def error(self, message):
        if self.json_mode:
            print(json.dumps({"error": message}))
            self.exit(2)
        super().error(message)


def cmd_audit(a):
    result = audit_folder(a.folder)
    if a.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_text(result))
    return 1 if result["summary"]["errors"] else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    _JsonAwareParser.json_mode = "--json" in argv
    ap = _JsonAwareParser(
        prog=TOOL,
        description="Audit a static site's deploy folder "
                    "before launch: titles, meta, headings, "
                    "alt text, internal-link resolution, "
                    "JSON-LD, sitemap — a prioritised, "
                    "plain-language fix list (stdlib only, "
                    "local only, no network).")
    sub = ap.add_subparsers(dest="command", required=True,
                            parser_class=_JsonAwareParser)

    p_audit = sub.add_parser(
        "audit", help="audit one site folder: exit 1 when any "
                      "ERROR finding exists, else 0")
    p_audit.add_argument("folder",
                         help="the deploy folder to audit "
                              "(walked for .html/.htm files)")
    p_audit.add_argument("--json", action="store_true",
                         help="print one JSON object instead "
                              "of text")
    p_audit.set_defaults(func=cmd_audit)

    a = ap.parse_args(argv)

    def fail(msg):
        if getattr(a, "json", False):
            print(json.dumps({"error": msg}))
        else:
            print(f"ERROR: {msg}")
        return 2

    try:
        return a.func(a)
    except ToolError as exc:
        return fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())
