#!/usr/bin/env python3
"""Tests for site-audit. Stdlib unittest only.

Run from the pack root:
    python3 -m unittest discover -s tests -v

The two bundled fixtures were built by hand with planted
faults, and the expectations below were counted by hand from
the fixture files — never copied from the tool's output:

faulty-site (5 pages, fictional Harbourline Roofing):
    index.html    ERROR img-alt-missing, broken-internal-link
                  (quote.html), jsonld-invalid (trailing comma)
                  WARN og-description-missing,
                  heading-order-skip (h1 -> h3)
                  INFO img-alt-empty
    about.html    ERROR title-missing
                  WARN meta-description-missing,
                  meta-viewport-missing,
                  og-description-missing, h1-count (two <h1>)
    contact.html  WARN title-length (7 chars),
                  meta-description-length (8 chars),
                  charset-missing, html-lang-missing,
                  h1-count (no <h1>)
    services.html WARN duplicate-title-h1 (title + h1 both
                  repeat services-alt.html, which sorts first)
    sitemap.xml   ERROR sitemap-entry-broken (pricing.html)
    => 18 findings · 5 errors · 12 warnings · 1 info · exit 1

clean-site (1 page, fictional Pinecrest Plumbing):
    => 0 findings · exit 0

Both directions are covered: a clean folder exits 0, planted
faults exit 1, and every broken input exits 2 with a clean
message — in text AND in --json mode.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
SRC = PACK / "src" / "site_audit.py"
FAULTY = PACK / "examples" / "site-audit" / "faulty-site"
CLEAN = PACK / "examples" / "site-audit" / "clean-site"

sys.path.insert(0, str(PACK / "src"))
import site_audit  # noqa: E402


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SRC), *args],
        capture_output=True, text=True, cwd=PACK)


def checks(result, name, page=None):
    return [f for f in result["findings"]
            if f["check"] == name
            and (page is None or f["page"] == page)]


GOOD_DESC = ("A full sentence describing this page for "
             "search results and shared links.")


def good_page(title="A perfectly fine title", desc=GOOD_DESC,
              h1=None, head_extra="", body=""):
    h1 = title if h1 is None else h1
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
{head_extra}
</head>
<body>
<h1>{h1}</h1>
{body}
</body>
</html>
"""


class SiteCase(unittest.TestCase):
    """Builds a temp site folder; by default adds a valid
    sitemap.xml pointing at the root so the sitemap-missing
    INFO does not leak into per-check expectations."""

    def make_site(self, files, sitemap=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                p.write_bytes(content)
            else:
                p.write_text(content, encoding="utf-8")
        if sitemap and not (root / "sitemap.xml").exists():
            (root / "sitemap.xml").write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/'
                'sitemap/0.9">\n'
                "<url><loc>https://site.example/</loc></url>\n"
                "</urlset>\n", encoding="utf-8")
        return root

    def audit(self, files, sitemap=True):
        root = self.make_site(files, sitemap=sitemap)
        return site_audit.audit_folder(root)


class TestFixtures(unittest.TestCase):
    def test_faulty_totals(self):
        r = site_audit.audit_folder(FAULTY)
        s = r["summary"]
        self.assertEqual((s["pages"], s["findings"]), (5, 18))
        self.assertEqual(
            (s["errors"], s["warnings"], s["infos"]),
            (5, 12, 1))

    def test_faulty_check_inventory(self):
        r = site_audit.audit_folder(FAULTY)
        expected = {
            "title-missing": 1, "img-alt-missing": 1,
            "broken-internal-link": 1, "jsonld-invalid": 1,
            "sitemap-entry-broken": 1,
            "og-description-missing": 2, "heading-order-skip": 1,
            "meta-description-missing": 1,
            "meta-viewport-missing": 1, "h1-count": 2,
            "title-length": 1, "meta-description-length": 1,
            "charset-missing": 1, "html-lang-missing": 1,
            "duplicate-title-h1": 1, "img-alt-empty": 1,
        }
        got = {}
        for f in r["findings"]:
            got[f["check"]] = got.get(f["check"], 0) + 1
        self.assertEqual(got, expected)

    def test_faulty_per_page_counts(self):
        r = site_audit.audit_folder(FAULTY)
        pp = r["per_page"]
        self.assertEqual(pp["index.html"],
                         {"errors": 3, "warnings": 2, "infos": 1})
        self.assertEqual(pp["about.html"],
                         {"errors": 1, "warnings": 4, "infos": 0})
        self.assertEqual(pp["contact.html"],
                         {"errors": 0, "warnings": 5, "infos": 0})
        self.assertEqual(pp["services.html"],
                         {"errors": 0, "warnings": 1, "infos": 0})
        self.assertEqual(pp["services-alt.html"],
                         {"errors": 0, "warnings": 0, "infos": 0})

    def test_faulty_broken_link_line_number(self):
        r = site_audit.audit_folder(FAULTY)
        [f] = checks(r, "broken-internal-link")
        lines = (FAULTY / "index.html").read_text(
            encoding="utf-8").splitlines()
        want = next(i + 1 for i, ln in enumerate(lines)
                    if "quote.html" in ln)
        self.assertEqual(f["line"], want)
        self.assertEqual(f["page"], "index.html")

    def test_faulty_cli_exit_1(self):
        p = run_cli("audit", "examples/site-audit/faulty-site")
        self.assertEqual(p.returncode, 1)
        self.assertIn("Verdict: FAIL", p.stdout)
        self.assertIn("18 finding(s)", p.stdout)

    def test_clean_fixture(self):
        r = site_audit.audit_folder(CLEAN)
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["summary"]["pages"], 1)
        p = run_cli("audit", "examples/site-audit/clean-site")
        self.assertEqual(p.returncode, 0)
        self.assertIn("Verdict: PASS", p.stdout)

    def test_json_summary_recounts(self):
        """The summary and per-page counts are recounted from
        the findings list itself — an independent recount in
        the test, not a copy of the tool's arithmetic."""
        p = run_cli("audit", "examples/site-audit/faulty-site", "--json")
        self.assertEqual(p.returncode, 1)
        r = json.loads(p.stdout)
        recount = {"error": 0, "warning": 0, "info": 0}
        per_page = {}
        for f in r["findings"]:
            recount[f["severity"]] += 1
            pp = per_page.setdefault(
                f["page"], {"error": 0, "warning": 0, "info": 0})
            pp[f["severity"]] += 1
        s = r["summary"]
        self.assertEqual(s["errors"], recount["error"])
        self.assertEqual(s["warnings"], recount["warning"])
        self.assertEqual(s["infos"], recount["info"])
        self.assertEqual(s["findings"], len(r["findings"]))
        for page, counts in per_page.items():
            if page in r["per_page"]:
                self.assertEqual(
                    r["per_page"][page],
                    {"errors": counts["error"],
                     "warnings": counts["warning"],
                     "infos": counts["info"]})

    def test_deterministic_output(self):
        a = run_cli("audit", "examples/site-audit/faulty-site")
        b = run_cli("audit", "examples/site-audit/faulty-site")
        self.assertEqual(a.stdout, b.stdout)
        aj = run_cli("audit", "examples/site-audit/faulty-site", "--json")
        bj = run_cli("audit", "examples/site-audit/faulty-site", "--json")
        self.assertEqual(aj.stdout, bj.stdout)


class TestTitles(SiteCase):
    def test_missing_title_is_error(self):
        r = self.audit({"index.html": good_page().replace(
            "<title>A perfectly fine title</title>\n", "")})
        [f] = checks(r, "title-missing")
        self.assertEqual(f["severity"], "error")

    def test_empty_title_is_missing(self):
        r = self.audit({"index.html": good_page(title="  ")})
        self.assertEqual(len(checks(r, "title-missing")), 1)

    def test_title_length_boundaries(self):
        for n, want in ((9, 1), (10, 0), (60, 0), (61, 1)):
            r = self.audit({"index.html":
                            good_page(title="T" * n)})
            self.assertEqual(
                len(checks(r, "title-length")), want,
                f"title of {n} chars")

    def test_title_length_message_measures(self):
        r = self.audit({"index.html": good_page(title="Short")})
        [f] = checks(r, "title-length")
        self.assertIn("5 characters", f["message"])
        self.assertIn("heuristic", f["message"])

    def test_duplicate_title_different_h1(self):
        r = self.audit({
            "index.html": good_page(
                title="Shared Title Here",
                body='<a href="other.html">o</a>'),
            "other.html": good_page(title="Shared Title Here",
                                    h1="A Different Heading"),
        })
        self.assertEqual(len(checks(r, "title-duplicate")), 1)
        self.assertEqual(len(checks(r, "duplicate-title-h1")), 0)
        [f] = checks(r, "title-duplicate")
        self.assertEqual(f["page"], "other.html")
        self.assertIn("index.html", f["message"])

    def test_duplicate_title_and_h1_is_stronger_finding(self):
        r = self.audit({
            "index.html": good_page(
                title="Shared Title Here",
                body='<a href="other.html">o</a>'),
            "other.html": good_page(title="Shared Title Here"),
        })
        self.assertEqual(len(checks(r, "title-duplicate")), 0)
        self.assertEqual(len(checks(r, "duplicate-title-h1")), 1)

    def test_duplicate_matching_ignores_case_and_space(self):
        r = self.audit({
            "index.html": good_page(
                title="Our  Services Page",
                body='<a href="other.html">o</a>'),
            "other.html": good_page(title="our services page",
                                    h1="Something Else Entirely"),
        })
        self.assertEqual(len(checks(r, "title-duplicate")), 1)


class TestMeta(SiteCase):
    def test_description_missing(self):
        page = good_page().replace(
            f'<meta name="description" content="{GOOD_DESC}">\n',
            "")
        r = self.audit({"index.html": page})
        self.assertEqual(
            len(checks(r, "meta-description-missing")), 1)

    def test_description_length_boundaries(self):
        for n, want in ((49, 1), (50, 0), (160, 0), (161, 1)):
            r = self.audit({"index.html":
                            good_page(desc="d" * n)})
            self.assertEqual(
                len(checks(r, "meta-description-length")), want,
                f"description of {n} chars")

    def test_duplicate_description(self):
        r = self.audit({
            "index.html": good_page(
                title="First Page Title",
                body='<a href="other.html">o</a>'),
            "other.html": good_page(title="Second Page Title"),
        })
        [f] = checks(r, "meta-description-duplicate")
        self.assertEqual(f["page"], "other.html")

    def test_viewport_missing(self):
        page = good_page().replace(
            '<meta name="viewport" content="width=device-width, '
            'initial-scale=1">\n', "")
        r = self.audit({"index.html": page})
        self.assertEqual(
            len(checks(r, "meta-viewport-missing")), 1)

    def test_charset_missing_and_http_equiv_form(self):
        page = good_page().replace(
            '<meta charset="utf-8">\n', "")
        r = self.audit({"index.html": page})
        self.assertEqual(len(checks(r, "charset-missing")), 1)
        page2 = good_page().replace(
            '<meta charset="utf-8">',
            '<meta http-equiv="content-type" '
            'content="text/html; charset=utf-8">')
        r2 = self.audit({"index.html": page2})
        self.assertEqual(len(checks(r2, "charset-missing")), 0)

    def test_html_lang_missing(self):
        page = good_page().replace('<html lang="en">', "<html>")
        r = self.audit({"index.html": page})
        self.assertEqual(len(checks(r, "html-lang-missing")), 1)

    def test_og_missing_each(self):
        page = good_page().replace(
            '<meta property="og:title" content="A perfectly '
            'fine title">\n', "").replace(
            f'<meta property="og:description" '
            f'content="{GOOD_DESC}">\n', "")
        r = self.audit({"index.html": page})
        self.assertEqual(len(checks(r, "og-title-missing")), 1)
        self.assertEqual(
            len(checks(r, "og-description-missing")), 1)


class TestHeadings(SiteCase):
    def test_no_h1(self):
        page = good_page().replace(
            "<h1>A perfectly fine title</h1>\n", "<h2>Sub</h2>")
        r = self.audit({"index.html": page})
        [f] = checks(r, "h1-count")
        self.assertIn("no <h1>", f["message"])

    def test_two_h1(self):
        page = good_page(body="<h1>Second top heading</h1>")
        r = self.audit({"index.html": page})
        [f] = checks(r, "h1-count")
        self.assertIn("2 <h1>", f["message"])

    def test_heading_skip(self):
        r = self.audit({"index.html":
                        good_page(body="<h3>Deep</h3>")})
        [f] = checks(r, "heading-order-skip")
        self.assertIn("h1 to h3", f["message"])

    def test_heading_skip_later(self):
        body = "<h2>Ok</h2><h4>Too deep</h4>"
        r = self.audit({"index.html": good_page(body=body)})
        self.assertEqual(len(checks(r, "heading-order-skip")),
                         1)

    def test_heading_downward_is_fine(self):
        body = "<h2>A</h2><h3>B</h3><h2>C</h2>"
        r = self.audit({"index.html": good_page(body=body)})
        self.assertEqual(len(checks(r, "heading-order-skip")),
                         0)


class TestImages(SiteCase):
    def test_missing_alt_is_error(self):
        r = self.audit({
            "index.html": good_page(
                body='<img src="pic.jpg">'),
            "pic.jpg": "x",
        })
        [f] = checks(r, "img-alt-missing")
        self.assertEqual(f["severity"], "error")
        self.assertIn("pic.jpg", f["message"])

    def test_empty_alt_is_info(self):
        r = self.audit({
            "index.html": good_page(
                body='<img src="pic.jpg" alt="">'),
            "pic.jpg": "x",
        })
        [f] = checks(r, "img-alt-empty")
        self.assertEqual(f["severity"], "info")
        self.assertEqual(len(checks(r, "img-alt-missing")), 0)

    def test_alt_present_no_finding(self):
        r = self.audit({
            "index.html": good_page(
                body='<img src="pic.jpg" alt="A picture">'),
            "pic.jpg": "x",
        })
        self.assertEqual(len(checks(r, "img-alt-missing")), 0)
        self.assertEqual(len(checks(r, "img-alt-empty")), 0)

    def test_missing_image_file_is_broken_link_too(self):
        r = self.audit({
            "index.html": good_page(
                body='<img src="gone.jpg" alt="Gone">'),
        })
        self.assertEqual(
            len(checks(r, "broken-internal-link")), 1)
        self.assertEqual(len(checks(r, "img-alt-missing")), 0)


class TestLinks(SiteCase):
    def test_broken_relative_link(self):
        r = self.audit({"index.html": good_page(
            body='<a href="nope.html">x</a>')})
        [f] = checks(r, "broken-internal-link")
        self.assertEqual(f["severity"], "error")
        self.assertIn("nope.html", f["message"])

    def test_root_relative_link(self):
        r = self.audit({
            "index.html": good_page(
                body='<a href="sub/page.html">s</a>'),
            "sub/page.html": good_page(
                title="Sub Page Title",
                body='<a href="/other.html">o</a>'),
            "other.html": good_page(title="Other Page Title"),
        })
        self.assertEqual(
            len(checks(r, "broken-internal-link")), 0)

    def test_relative_from_subfolder(self):
        r = self.audit({
            "index.html": good_page(
                body='<a href="sub/page.html">s</a>'),
            "sub/page.html": good_page(
                title="Sub Page Title",
                body='<a href="sibling.html">sib</a>'
                     '<a href="../index.html">home</a>'),
            "sub/sibling.html": good_page(
                title="Sibling Page Title"),
        })
        self.assertEqual(
            len(checks(r, "broken-internal-link")), 0)

    def test_escape_outside_root_is_broken(self):
        r = self.audit({"index.html": good_page(
            body='<a href="../outside.html">x</a>')})
        [f] = checks(r, "broken-internal-link")
        self.assertIn("outside the site folder", f["message"])

    def test_directory_link_with_index_ok(self):
        r = self.audit({
            "index.html": good_page(
                body='<a href="docs/">docs</a>'),
            "docs/index.html": good_page(
                title="Docs Index Title"),
        })
        self.assertEqual(
            len(checks(r, "broken-internal-link")), 0)

    def test_directory_link_without_index_broken(self):
        r = self.audit({
            "index.html": good_page(
                body='<a href="docs/">docs</a>'),
            "docs/readme.txt": "not a page",
        })
        [f] = checks(r, "broken-internal-link")
        self.assertIn("no index.html", f["message"])

    def test_query_and_fragment_stripped(self):
        r = self.audit({
            "index.html": good_page(
                body='<a href="other.html?ref=nav#top">o</a>'),
            "other.html": good_page(title="Other Page Title"),
        })
        self.assertEqual(
            len(checks(r, "broken-internal-link")), 0)

    def test_percent_decoding(self):
        r = self.audit({
            "index.html": good_page(
                body='<a href="my%20page.html">o</a>'),
            "my page.html": good_page(title="Spaced Title"),
        })
        self.assertEqual(
            len(checks(r, "broken-internal-link")), 0)

    def test_unchecked_reference_kinds(self):
        body = ('<a href="#frag">a</a>'
                '<a href="https://example.com/x">b</a>'
                '<a href="http://example.com">c</a>'
                '<a href="//cdn.example.com/x.css">d</a>'
                '<a href="mailto:a@example.com">e</a>'
                '<a href="tel:+15550100">f</a>'
                '<a href="javascript:void(0)">g</a>'
                '<img src="data:image/gif;base64,R0lGOD" '
                'alt="dot">')
        r = self.audit({"index.html": good_page(body=body)})
        self.assertEqual(
            len(checks(r, "broken-internal-link")), 0)

    def test_stylesheet_and_script_refs_checked(self):
        body = ""
        head = ('<link rel="stylesheet" href="missing.css">'
                '<script src="missing.js"></script>')
        r = self.audit({"index.html":
                        good_page(head_extra=head, body=body)})
        self.assertEqual(
            len(checks(r, "broken-internal-link")), 2)


class TestJsonLd(SiteCase):
    def test_invalid_block_is_error(self):
        head = ('<script type="application/ld+json">'
                '{"a": 1,}</script>')
        r = self.audit({"index.html":
                        good_page(head_extra=head)})
        [f] = checks(r, "jsonld-invalid")
        self.assertEqual(f["severity"], "error")

    def test_valid_block_ok(self):
        head = ('<script type="application/ld+json">'
                '{"@type": "Thing"}</script>')
        r = self.audit({"index.html":
                        good_page(head_extra=head)})
        self.assertEqual(len(checks(r, "jsonld-invalid")), 0)

    def test_second_block_bad(self):
        head = ('<script type="application/ld+json">'
                '{"ok": true}</script>'
                '<script type="application/ld+json">'
                'not json</script>')
        r = self.audit({"index.html":
                        good_page(head_extra=head)})
        self.assertEqual(len(checks(r, "jsonld-invalid")), 1)

    def test_type_match_is_case_insensitive(self):
        head = ('<script type="Application/ld+JSON">'
                '{bad}</script>')
        r = self.audit({"index.html":
                        good_page(head_extra=head)})
        self.assertEqual(len(checks(r, "jsonld-invalid")), 1)

    def test_plain_script_ignored(self):
        head = '<script>var x = {not: "json"};</script>'
        r = self.audit({"index.html":
                        good_page(head_extra=head)})
        self.assertEqual(len(checks(r, "jsonld-invalid")), 0)


class TestSitemapRobots(SiteCase):
    def test_sitemap_absent_is_info(self):
        r = self.audit({"index.html": good_page()},
                       sitemap=False)
        [f] = checks(r, "sitemap-missing")
        self.assertEqual(f["severity"], "info")
        self.assertFalse(r["sitemap"]["present"])

    def test_sitemap_broken_entry(self):
        root = self.make_site({"index.html": good_page()},
                              sitemap=False)
        (root / "sitemap.xml").write_text(
            '<?xml version="1.0"?>\n<urlset xmlns="http://www.'
            'sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://site.example/ghost.html</loc>"
            "</url></urlset>", encoding="utf-8")
        r = site_audit.audit_folder(root)
        [f] = checks(r, "sitemap-entry-broken")
        self.assertEqual(f["severity"], "error")

    def test_sitemap_relative_loc(self):
        root = self.make_site({
            "index.html": good_page(
                body='<a href="about.html">a</a>'),
            "about.html": good_page(title="About Page Title"),
        }, sitemap=False)
        (root / "sitemap.xml").write_text(
            '<?xml version="1.0"?>\n<urlset xmlns="http://www.'
            'sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>about.html</loc></url></urlset>",
            encoding="utf-8")
        r = site_audit.audit_folder(root)
        self.assertEqual(
            len(checks(r, "sitemap-entry-broken")), 0)

    def test_sitemap_malformed_xml(self):
        root = self.make_site({"index.html": good_page()},
                              sitemap=False)
        (root / "sitemap.xml").write_text(
            "<urlset><url><loc>oops", encoding="utf-8")
        r = site_audit.audit_folder(root)
        [f] = checks(r, "sitemap-invalid")
        self.assertEqual(f["severity"], "error")

    def test_robots_sitemap_missing_target(self):
        root = self.make_site({"index.html": good_page()})
        (root / "robots.txt").write_text(
            "User-agent: *\n"
            "Sitemap: https://site.example/maps/main.xml\n",
            encoding="utf-8")
        r = site_audit.audit_folder(root)
        self.assertEqual(
            len(checks(r, "robots-sitemap-missing")), 1)
        self.assertTrue(r["robots"]["present"])

    def test_robots_sitemap_ok_and_absent(self):
        r = self.audit({"index.html": good_page()})
        self.assertEqual(
            len(checks(r, "robots-sitemap-missing")), 0)
        self.assertFalse(r["robots"]["present"])
        root = self.make_site({"index.html": good_page()})
        (root / "robots.txt").write_text(
            "User-agent: *\n"
            "Sitemap: https://site.example/sitemap.xml\n",
            encoding="utf-8")
        r2 = site_audit.audit_folder(root)
        self.assertEqual(
            len(checks(r2, "robots-sitemap-missing")), 0)


class TestOrphans(SiteCase):
    def test_unlinked_page_is_orphan_info(self):
        r = self.audit({
            "index.html": good_page(),
            "hidden.html": good_page(title="Hidden Page Title"),
        })
        [f] = checks(r, "orphan-page", page="hidden.html")
        self.assertEqual(f["severity"], "info")

    def test_linked_page_not_orphan(self):
        r = self.audit({
            "index.html": good_page(
                body='<a href="other.html">o</a>'),
            "other.html": good_page(title="Other Page Title"),
        })
        self.assertEqual(len(checks(r, "orphan-page")), 0)

    def test_root_index_never_orphan(self):
        r = self.audit({
            "index.html": good_page(),
            "other.html": good_page(
                title="Other Page Title",
                body='<a href="other.html">self</a>'),
        })
        pages = [f["page"] for f in checks(r, "orphan-page")]
        self.assertNotIn("index.html", pages)
        # A self-link does not rescue a page either.
        self.assertIn("other.html", pages)

    def test_subfolder_index_not_exempt(self):
        r = self.audit({
            "index.html": good_page(),
            "blog/index.html": good_page(
                title="Blog Index Title"),
        })
        self.assertEqual(
            len(checks(r, "orphan-page", page="blog/index.html")),
            1)

    def test_directory_link_counts_as_inbound(self):
        r = self.audit({
            "index.html": good_page(
                body='<a href="blog/">blog</a>'),
            "blog/index.html": good_page(
                title="Blog Index Title"),
        })
        self.assertEqual(len(checks(r, "orphan-page")), 0)


class TestRobustness(SiteCase):
    def test_malformed_html_yields_findings_not_traceback(self):
        broken = (b"<!DOCTYPE html><html><head><title>Half "
                  b"a page<body><h1>Oops<p>never closed "
                  b"<<<>>> \xff\xfe binary")
        r = self.audit({"index.html": broken})
        self.assertIsInstance(r["findings"], list)
        self.assertGreaterEqual(r["summary"]["findings"], 1)

    def test_empty_page_file(self):
        r = self.audit({"index.html": ""})
        self.assertEqual(len(checks(r, "title-missing")), 1)
        self.assertEqual(len(checks(r, "h1-count")), 1)

    def test_htm_extension_and_uppercase(self):
        r = self.audit({
            "index.html": good_page(
                body='<a href="PAGE.HTM">p</a>'),
            "PAGE.HTM": good_page(title="Upper Page Title"),
        })
        self.assertEqual(r["summary"]["pages"], 2)
        self.assertEqual(
            len(checks(r, "broken-internal-link")), 0)

    def test_dot_directories_skipped(self):
        r = self.audit({
            "index.html": good_page(),
            ".git/hooks/page.html": good_page(
                title="Hook Page Title"),
        })
        self.assertEqual(r["summary"]["pages"], 1)


class TestInputErrors(unittest.TestCase):
    def test_missing_folder(self):
        p = run_cli("audit", "no-such-folder-here")
        self.assertEqual(p.returncode, 2)
        self.assertIn("ERROR: folder not found", p.stdout)
        self.assertNotIn("Traceback", p.stdout + p.stderr)

    def test_missing_folder_json(self):
        p = run_cli("audit", "no-such-folder-here", "--json")
        self.assertEqual(p.returncode, 2)
        self.assertIn("error", json.loads(p.stdout))

    def test_file_as_folder(self):
        p = run_cli("audit", "examples/site-audit/clean-site/index.html")
        self.assertEqual(p.returncode, 2)
        self.assertIn("not a folder", p.stdout)

    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as d:
            p = run_cli("audit", d)
            self.assertEqual(p.returncode, 2)
            self.assertIn("no HTML files", p.stdout)

    def test_folder_without_html(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "notes.txt").write_text("hi")
            p = run_cli("audit", d)
            self.assertEqual(p.returncode, 2)

    def test_argparse_error_is_json_in_json_mode(self):
        p = run_cli("audit", "--json")
        self.assertEqual(p.returncode, 2)
        self.assertIn("error", json.loads(p.stdout))

    def test_api_raises_tool_error(self):
        with self.assertRaises(site_audit.ToolError):
            site_audit.audit_folder("/definitely/not/here")


class TestContracts(unittest.TestCase):
    def test_no_network_code_in_source(self):
        src = SRC.read_text(encoding="utf-8")
        for token in ("urllib.request", "urlopen", "socket",
                      "http.client", "ftplib", "smtplib"):
            self.assertNotIn(token, src)

    def test_no_score_anywhere_in_output(self):
        p = run_cli("audit", "examples/site-audit/faulty-site")
        self.assertNotIn("score", p.stdout.lower())
        pj = run_cli("audit", "examples/site-audit/faulty-site", "--json")
        self.assertNotIn("score", pj.stdout.lower())

    def test_every_finding_has_fix_and_message(self):
        r = site_audit.audit_folder(FAULTY)
        for f in r["findings"]:
            self.assertTrue(f["message"])
            self.assertTrue(f["fix"])
            self.assertIn(f["severity"],
                          ("error", "warning", "info"))


if __name__ == "__main__":
    unittest.main()
