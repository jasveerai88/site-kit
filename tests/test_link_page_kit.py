#!/usr/bin/env python3
"""Tests for link-page-kit. Stdlib unittest only.

Run from the pack root:
    python3 -m unittest discover -s tests -v

Expectations are worked out from the configs below by hand,
not copied from the tool's own output:

- The bundled sample config (examples/sample-config.json)
  carries 6 links (YouTube, Instagram, a shop product, the
  podcast, a trail map, one mailto) and 2 socials (TikTok, X),
  an http(s) avatar, and no duplicate URLs, so a clean build
  exits 0 and a preview lists the six links in file order.
- Page weight is defined as len(page_text.encode("utf-8")) —
  preview's number must equal the byte length of the file
  build writes, byte for byte.
- Duplicates are matched after normalisation: scheme and host
  case and one trailing path slash are ignored, so
  "HTTPS://Example.ORG/page/" and "https://example.org/page"
  are the same target. A duplicate is a WARNING (exit 1, the
  page still builds); a bad scheme, missing label or missing
  url is an ERROR (exit 2, nothing is written).
- Escaping: the label "<script>alert(1)</script>" must appear
  in the page only in escaped form (&lt;script&gt;...), and
  the page must contain no <script> element at all — the
  generator emits no JavaScript.
- External references: every http:// or https:// occurrence in
  the page must be one of the configured links, socials or
  avatar — no fonts, no CDN, no analytics.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parents[1]
TOOL = PACK_ROOT / "src" / "link_page_kit.py"
SAMPLE = PACK_ROOT / "examples" / "link-page-kit" / "sample-config.json"


def run(args, cwd):
    return subprocess.run([sys.executable, str(TOOL)] + args,
                          capture_output=True, text=True, cwd=cwd)


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write_config(self, obj, name="config.json"):
        path = self.dir / name
        path.write_text(json.dumps(obj), encoding="utf-8")
        return path

    def base(self, **overrides):
        cfg = {"name": "Test Person",
               "links": [{"label": "Site",
                          "url": "https://example.org/home"}]}
        cfg.update(overrides)
        return cfg


# ---------------------------------------------------------------------------
# build: the happy path
# ---------------------------------------------------------------------------

class BuildTests(TempDirTest):
    def test_build_writes_one_file_exit_0(self):
        out = self.dir / "page.html"
        r = run(["build", str(SAMPLE), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(out.is_file())
        html_text = out.read_text(encoding="utf-8")
        self.assertIn("<h1>Maya Chen</h1>", html_text)

    def test_build_default_output_is_index_html(self):
        r = run(["build", str(SAMPLE)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.dir / "index.html").is_file())

    def test_build_page_contains_all_six_links_and_two_socials(self):
        out = self.dir / "page.html"
        run(["build", str(SAMPLE), "-o", str(out)], self.dir)
        html_text = out.read_text(encoding="utf-8")
        for label in ("Watch on YouTube", "Follow on Instagram",
                      "Trailcast stickers — my shop",
                      "Listen to the podcast",
                      "Trail conditions map", "Email me",
                      "TikTok", "X"):
            self.assertIn(label, html_text)
        self.assertIn('href="mailto:maya@example.org"', html_text)

    def test_build_notes_rendered_when_present(self):
        out = self.dir / "page.html"
        run(["build", str(SAMPLE), "-o", str(out)], self.dir)
        html_text = out.read_text(encoding="utf-8")
        self.assertIn("New video every Friday", html_text)
        self.assertIn('class="note"', html_text)

    def test_build_page_is_valid_semantics(self):
        out = self.dir / "page.html"
        run(["build", str(SAMPLE), "-o", str(out)], self.dir)
        html_text = out.read_text(encoding="utf-8")
        self.assertTrue(html_text.startswith("<!DOCTYPE html>"))
        self.assertIn('<html lang="en">', html_text)
        self.assertIn('<meta name="viewport"', html_text)
        self.assertIn("<style>", html_text)
        self.assertIn(":focus-visible", html_text)
        self.assertIn('alt="Portrait of Maya Chen"', html_text)
        self.assertIn('aria-label="Links"', html_text)
        self.assertIn('aria-label="Social profiles"', html_text)

    def test_build_page_has_no_script_anywhere(self):
        out = self.dir / "page.html"
        run(["build", str(SAMPLE), "-o", str(out)], self.dir)
        html_text = out.read_text(encoding="utf-8")
        self.assertNotIn("<script", html_text.lower())
        self.assertNotIn("onclick", html_text.lower())

    def test_build_external_urls_are_only_the_configured_ones(self):
        out = self.dir / "page.html"
        run(["build", str(SAMPLE), "-o", str(out)], self.dir)
        html_text = out.read_text(encoding="utf-8")
        found = set(re.findall(r"https?://[^\s\"'<>]+", html_text))
        expected = {
            "https://example.org/maya/avatar.jpg",
            "https://youtube.com/@KelownaTrailcast",
            "https://instagram.com/kelownatrailcast",
            "https://example.org/shop/stickers",
            "https://example.org/trailcast",
            "https://example.org/trail-conditions",
            "https://tiktok.com/@kelownatrailcast",
            "https://x.com/kelownatrailcast",
        }
        self.assertEqual(found, expected)

    def test_build_accent_appears_in_css(self):
        out = self.dir / "page.html"
        run(["build", str(SAMPLE), "-o", str(out)], self.dir)
        html_text = out.read_text(encoding="utf-8")
        self.assertIn("--accent:#2e7d4f", html_text)

    def test_build_dark_mode_palette(self):
        cfg = self.base(theme={"mode": "dark"})
        path = self.write_config(cfg)
        out = self.dir / "page.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("background:#141414", out.read_text())

    def test_build_no_avatar_no_bio_still_valid(self):
        path = self.write_config(self.base())
        out = self.dir / "page.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout)
        html_text = out.read_text()
        self.assertNotIn("<img", html_text)
        self.assertNotIn('class="bio"', html_text)

    def test_build_local_path_avatar_accepted(self):
        path = self.write_config(self.base(avatar="images/me.jpg"))
        out = self.dir / "page.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('src="images/me.jpg"', out.read_text())

    def test_build_unwritable_output_is_clean_error(self):
        r = run(["build", str(SAMPLE), "-o",
                 str(self.dir / "nope" / "page.html")], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("ERROR", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)


# ---------------------------------------------------------------------------
# escaping
# ---------------------------------------------------------------------------

class EscapingTests(TempDirTest):
    def build_with(self, cfg):
        path = self.write_config(cfg)
        out = self.dir / "page.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout)
        return out.read_text(encoding="utf-8")

    def test_script_in_label_is_text_never_markup(self):
        html_text = self.build_with(self.base(links=[
            {"label": "<script>alert(1)</script>",
             "url": "https://example.org/x"}]))
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;",
                      html_text)
        self.assertNotIn("<script>alert(1)</script>", html_text)
        self.assertNotIn("<script", html_text.lower())

    def test_html_in_name_and_bio_escaped(self):
        html_text = self.build_with(self.base(
            name='Ann "A&B" <Admin>', bio="5 < 6 & 7 > 2"))
        self.assertIn("Ann &quot;A&amp;B&quot; &lt;Admin&gt;",
                      html_text)
        self.assertIn("5 &lt; 6 &amp; 7 &gt; 2", html_text)
        self.assertNotIn("<Admin>", html_text)

    def test_ampersand_in_url_escaped_in_href(self):
        html_text = self.build_with(self.base(links=[
            {"label": "Q", "url": "https://example.org/?a=1&b=2"}]))
        self.assertIn('href="https://example.org/?a=1&amp;b=2"',
                      html_text)


# ---------------------------------------------------------------------------
# validation: errors name the field, exit 2, nothing written
# ---------------------------------------------------------------------------

class ValidationTests(TempDirTest):
    def build_expect_error(self, cfg, needle):
        path = self.write_config(cfg)
        out = self.dir / "page.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn(needle, r.stdout)
        self.assertFalse(out.exists())
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        return r

    def test_javascript_scheme_refused(self):
        self.build_expect_error(self.base(links=[
            {"label": "x", "url": "javascript:alert(1)"}]),
            "links[0].url")

    def test_data_scheme_refused(self):
        self.build_expect_error(self.base(links=[
            {"label": "x", "url": "data:text/html;base64,AAAA"}]),
            "links[0].url")

    def test_file_scheme_refused(self):
        self.build_expect_error(self.base(links=[
            {"label": "x", "url": "file:///etc/passwd"}]),
            "links[0].url")

    def test_scheme_relative_refused(self):
        self.build_expect_error(self.base(links=[
            {"label": "x", "url": "//evil.example.org/x"}]),
            "links[0].url")

    def test_schemeless_refused(self):
        self.build_expect_error(self.base(links=[
            {"label": "x", "url": "example.org/x"}]), "links[0].url")

    def test_https_without_host_refused(self):
        self.build_expect_error(self.base(links=[
            {"label": "x", "url": "https:///path"}]), "links[0].url")

    def test_url_with_space_refused(self):
        self.build_expect_error(self.base(links=[
            {"label": "x", "url": "https://example.org/a b"}]),
            "links[0].url")

    def test_mailto_without_address_refused(self):
        self.build_expect_error(self.base(links=[
            {"label": "x", "url": "mailto:nobody"}]),
            "links[0].url")

    def test_tel_without_digits_refused(self):
        self.build_expect_error(self.base(links=[
            {"label": "x", "url": "tel:call-me"}]), "links[0].url")

    def test_http_and_tel_and_uppercase_scheme_accepted(self):
        cfg = self.base(links=[
            {"label": "a", "url": "http://example.org/plain"},
            {"label": "b", "url": "tel:+1-250-555-0100"},
            {"label": "c", "url": "HTTPS://EXAMPLE.ORG/UPPER"}])
        path = self.write_config(cfg)
        out = self.dir / "page.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_missing_label_names_field(self):
        self.build_expect_error(self.base(links=[
            {"url": "https://example.org"}]), "links[0]")

    def test_empty_label_names_field(self):
        self.build_expect_error(self.base(links=[
            {"label": "  ", "url": "https://example.org"}]),
            "links[0]")

    def test_missing_url_names_field(self):
        self.build_expect_error(self.base(links=[{"label": "x"}]),
                                "links[0]")

    def test_missing_name_names_field(self):
        cfg = self.base()
        del cfg["name"]
        self.build_expect_error(cfg, "'name'")

    def test_empty_name_names_field(self):
        self.build_expect_error(self.base(name=""), "'name'")

    def test_missing_links_names_field(self):
        cfg = self.base()
        del cfg["links"]
        self.build_expect_error(cfg, "'links'")

    def test_empty_links_list_is_error(self):
        self.build_expect_error(self.base(links=[]), "'links'")

    def test_links_not_a_list_is_error(self):
        self.build_expect_error(self.base(links="nope"), "'links'")

    def test_entry_not_an_object_is_error(self):
        self.build_expect_error(self.base(links=["https://x.org"]),
                                "links[0]")

    def test_bad_accent_names_field(self):
        self.build_expect_error(
            self.base(theme={"accent": "green"}), "theme.accent")

    def test_accent_without_hash_names_field(self):
        self.build_expect_error(
            self.base(theme={"accent": "2e7d4f"}), "theme.accent")

    def test_short_hex_accent_accepted(self):
        path = self.write_config(self.base(theme={"accent": "#0F8"}))
        out = self.dir / "page.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("--accent:#0f8", out.read_text())

    def test_bad_mode_names_field(self):
        self.build_expect_error(
            self.base(theme={"mode": "sepia"}), "theme.mode")

    def test_theme_not_object_is_error(self):
        self.build_expect_error(self.base(theme="dark"), "theme")

    def test_avatar_data_scheme_refused(self):
        self.build_expect_error(
            self.base(avatar="data:image/png;base64,AAAA"), "avatar")

    def test_socials_bad_url_names_socials_field(self):
        self.build_expect_error(self.base(socials=[
            {"label": "s", "url": "javascript:x"}]), "socials[0].url")

    def test_note_not_string_is_error(self):
        self.build_expect_error(self.base(links=[
            {"label": "x", "url": "https://example.org", "note": 5}]),
            "links[0]")

    def test_missing_file_is_clean_error(self):
        r = run(["build", str(self.dir / "absent.json")], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("ERROR", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def test_malformed_json_is_clean_error(self):
        bad = self.dir / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        r = run(["build", str(bad)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def test_top_level_not_object_is_clean_error(self):
        path = self.write_config([1, 2, 3])
        r = run(["build", str(path)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("top level", r.stdout)


# ---------------------------------------------------------------------------
# duplicates: warnings, exit 1, page still builds
# ---------------------------------------------------------------------------

class DuplicateTests(TempDirTest):
    def test_exact_duplicate_flagged_exit_1_page_built(self):
        cfg = self.base(links=[
            {"label": "a", "url": "https://example.org/page"},
            {"label": "b", "url": "https://example.org/page"}])
        path = self.write_config(cfg)
        out = self.dir / "page.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("duplicate URL", r.stdout)
        self.assertTrue(out.is_file())

    def test_normalised_duplicate_flagged(self):
        cfg = self.base(links=[
            {"label": "a", "url": "HTTPS://Example.ORG/page/"},
            {"label": "b", "url": "https://example.org/page"}])
        path = self.write_config(cfg)
        r = run(["build", str(path)], self.dir)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("duplicate URL", r.stdout)

    def test_duplicate_across_links_and_socials_flagged(self):
        cfg = self.base(
            links=[{"label": "a", "url": "https://example.org/x"}],
            socials=[{"label": "s", "url": "https://example.org/x"}])
        path = self.write_config(cfg)
        r = run(["preview", str(path)], self.dir)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("duplicate URL", r.stdout)

    def test_distinct_urls_are_not_duplicates(self):
        cfg = self.base(links=[
            {"label": "a", "url": "https://example.org/page"},
            {"label": "b", "url": "https://example.org/page?x=1"},
            {"label": "c", "url": "https://example.org/other"}])
        path = self.write_config(cfg)
        r = run(["build", str(path)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("Warnings: none", r.stdout)
        self.assertIn("no duplicate URLs", r.stdout)

    def test_no_duplicate_check_line_dropped_when_duplicates(self):
        cfg = self.base(links=[
            {"label": "a", "url": "https://example.org/page"},
            {"label": "b", "url": "https://example.org/page"}])
        path = self.write_config(cfg)
        r = run(["preview", str(path)], self.dir)
        self.assertNotIn("✓ no duplicate URLs", r.stdout)


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------

class PreviewTests(TempDirTest):
    def test_preview_sample_facts(self):
        r = run(["preview", str(SAMPLE)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("Maya Chen · 6 link(s), 2 social(s)", r.stdout)
        self.assertIn("1. Watch on YouTube — "
                      "https://youtube.com/@KelownaTrailcast",
                      r.stdout)
        self.assertIn("6. Email me — mailto:maya@example.org",
                      r.stdout)
        self.assertIn("Checks passed:", r.stdout)

    def test_preview_writes_nothing(self):
        run(["preview", str(SAMPLE)], self.dir)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_preview_page_weight_matches_build_bytes(self):
        r = run(["preview", str(SAMPLE)], self.dir)
        m = re.search(r"page weight ([\d,]+) bytes", r.stdout)
        self.assertIsNotNone(m)
        preview_bytes = int(m.group(1).replace(",", ""))
        out = self.dir / "page.html"
        run(["build", str(SAMPLE), "-o", str(out)], self.dir)
        actual = len(out.read_bytes())
        self.assertEqual(preview_bytes, actual)

    def test_preview_check_links_lists_details(self):
        r = run(["preview", str(SAMPLE), "--check-links"], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("links[0] 'Watch on YouTube'", r.stdout)
        self.assertIn("scheme https · host youtube.com", r.stdout)
        self.assertIn("scheme mailto · address maya@example.org",
                      r.stdout)

    def test_preview_error_exit_2(self):
        path = self.write_config(self.base(links=[
            {"label": "x", "url": "javascript:alert(1)"}]))
        r = run(["preview", str(path)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stdout + r.stderr)


# ---------------------------------------------------------------------------
# --json mode
# ---------------------------------------------------------------------------

class JsonTests(TempDirTest):
    def test_build_json_shape(self):
        out = self.dir / "page.html"
        r = run(["build", str(SAMPLE), "-o", str(out), "--json"],
                self.dir)
        self.assertEqual(r.returncode, 0, r.stdout)
        obj = json.loads(r.stdout)
        self.assertEqual(obj["tool"], "link-page-kit")
        self.assertEqual(obj["version"], "0.1.0")
        self.assertEqual(obj["command"], "build")
        self.assertEqual(obj["name"], "Maya Chen")
        self.assertEqual(obj["page_bytes"], len(out.read_bytes()))
        self.assertEqual(len(obj["links"]), 6)
        self.assertEqual(len(obj["socials"]), 2)
        self.assertEqual(obj["links"][0]["label"], "Watch on YouTube")
        self.assertEqual(obj["links"][0]["note"],
                         "New video every Friday")
        self.assertEqual(obj["warnings"], [])

    def test_preview_json_shape(self):
        r = run(["preview", str(SAMPLE), "--json"], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout)
        obj = json.loads(r.stdout)
        self.assertEqual(obj["command"], "preview")
        self.assertEqual(obj["links"][5]["url"],
                         "mailto:maya@example.org")
        self.assertNotIn("output_file", obj)

    def test_json_duplicate_exit_1_and_warning_present(self):
        cfg = self.base(links=[
            {"label": "a", "url": "https://example.org/page"},
            {"label": "b", "url": "https://example.org/page"}])
        path = self.write_config(cfg)
        r = run(["build", str(path), "--json"], self.dir)
        self.assertEqual(r.returncode, 1, r.stdout)
        obj = json.loads(r.stdout)
        self.assertEqual(len(obj["warnings"]), 1)
        self.assertIn("duplicate URL", obj["warnings"][0])

    def test_json_error_shape_on_bad_config(self):
        path = self.write_config(self.base(links=[
            {"label": "x", "url": "javascript:alert(1)"}]))
        r = run(["build", str(path), "--json"], self.dir)
        self.assertEqual(r.returncode, 2)
        obj = json.loads(r.stdout)
        self.assertIn("error", obj)
        self.assertIn("links[0].url", obj["error"])

    def test_json_argparse_error_is_json_object(self):
        r = run(["build", str(SAMPLE), "--bogus", "--json"], self.dir)
        self.assertEqual(r.returncode, 2)
        obj = json.loads(r.stdout)
        self.assertIn("error", obj)
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def test_argparse_error_without_json_is_plain_usage(self):
        r = run(["build", str(SAMPLE), "--bogus"], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)

    def test_json_malformed_config_is_error_object(self):
        bad = self.dir / "bad.json"
        bad.write_text("[1,2", encoding="utf-8")
        r = run(["preview", str(bad), "--json"], self.dir)
        self.assertEqual(r.returncode, 2)
        obj = json.loads(r.stdout)
        self.assertIn("error", obj)


if __name__ == "__main__":
    unittest.main()
