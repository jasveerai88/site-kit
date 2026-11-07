#!/usr/bin/env python3
"""Tests for compliance-pages. Stdlib unittest only.

Run from the pack root:
    python3 -m unittest discover -s tests -v

Expectations below are derived by hand from the two bundled
fixtures and the placeholder placement map — never copied
from the tool's own output without checking.

The complete sample (examples/sample-site.json) states every
fact, so: exit 0, six files, ZERO placeholders. Its sections,
by hand from the profile's facts:
  privacy: Who we are / Information we collect / How we use
    information / Third-party services / Cookies / How long
    we keep information / Your choices and how to contact us
  terms: Who operates this site / Using this site / Quotes
    and estimates (quotes_are_estimates is true) / Site
    content and intellectual property / Limits of liability /
    Governing law / Changes to these terms / Contact
  cookies: What cookies are / Cookies this site sets / The
    consent banner and your stored choice / Managing cookies
    in your browser / Contact + category: Essential +
    category: Analytics (marketing is false, so no Marketing)

The incomplete sample (examples/incomplete-site.json) states
only business.name, business.country and site.name. The
placeholder placement map (one loud marker per unstated fact
per place a document uses it):
  business.legal_form   privacy Who we are, terms Who
                        operates                       = 2
  business.address      privacy Who we are             = 1
  business.contact_email  privacy Choices, terms Contact,
                        cookies Contact                = 3
  site.url              privacy Who we are, terms Who
                        operates                       = 2
  data_collected        privacy Information we collect = 1
  data_use              privacy How we use information = 1
  services              privacy Third-party services   = 1
  cookies               privacy Cookies, cookies
                        Cookies this site sets         = 2
  retention             privacy How long we keep       = 1
  governing_law         terms Governing law           = 1
  TOTAL                                                  15
Per file: privacy 9, terms 4, cookies 2, banner 0,
consent.js 0. check on the same profile: 10 gaps (the ten
fields above), 0 contradictions, exit 1.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parents[1]
SRC = PACK_ROOT / "src" / "compliance_pages.py"
EXAMPLES = PACK_ROOT / "examples" / "compliance-pages"
sys.path.insert(0, str(PACK_ROOT / "src"))

import compliance_pages as cp  # noqa: E402


def full_profile(**over):
    """A complete minimal profile (distinct from the bundled
    sample): no optional cookies, no analytics, so no consent
    note is owed and nothing contradicts."""
    base = {
        "business": {"name": "Test Biz",
                     "legal_form": "corporation",
                     "country": "Canada", "province": "Ontario",
                     "address": "1 Test Street",
                     "contact_email": "team@test.example"},
        "site": {"name": "Test Site",
                 "url": "https://test.example"},
        "as_of": "2026-11-04",
        "data_collected": ["email addresses from the form"],
        "data_use": ["to reply to enquiries"],
        "services": {"hosting": "HostCo", "analytics": None,
                     "payments": None, "embeds": []},
        "cookies": {"essential": True, "analytics": False,
                    "marketing": False},
        "retention": "Kept for one year.",
        "governing_law": "the laws of Ontario",
    }
    base.update(over)
    return base


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SRC), *args],
        capture_output=True, text=True, timeout=60)


def write_profile(tmp, data, name="profile.json"):
    path = Path(tmp) / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def make(tmp, data, *extra):
    profile = write_profile(tmp, data)
    out = Path(tmp) / "out"
    result = run_cli("make", "--profile", str(profile),
                     "--out", str(out), *extra)
    return result, out


def read(out, name):
    return (Path(out) / name).read_text(encoding="utf-8")


SAMPLE_PRIVACY_SECTIONS = [
    "Who we are", "Information we collect",
    "How we use information", "Third-party services",
    "Cookies", "How long we keep information",
    "Your choices and how to contact us"]
SAMPLE_TERMS_SECTIONS = [
    "Who operates this site", "Using this site",
    "Quotes and estimates",
    "Site content and intellectual property",
    "Limits of liability", "Governing law",
    "Changes to these terms", "Contact"]
SAMPLE_COOKIES_SECTIONS = [
    "What cookies are", "Cookies this site sets",
    "The consent banner and your stored choice",
    "Managing cookies in your browser", "Contact",
    "category: Essential", "category: Analytics"]
SIX_FILES = ["privacy.html", "terms.html", "cookies.html",
             "consent.js", "banner.html", "manifest.txt"]


class TestCompleteSample(unittest.TestCase):

    def test_make_exit0_six_files_no_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, out = make(
                tmp, json.loads((EXAMPLES / "sample-site.json")
                                .read_text(encoding="utf-8")))
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             sorted(SIX_FILES))
            for name in SIX_FILES:
                self.assertNotIn("[TO FILL:", read(out, name),
                                 name)

    def test_sections_match_hand_derived_lists(self):
        profile = cp.validate_profile(json.loads(
            (EXAMPLES / "sample-site.json").read_text(
                encoding="utf-8")))
        _, privacy = cp.render_privacy(profile, "2026-11-04")
        _, terms = cp.render_terms(profile, "2026-11-04")
        _, cookies = cp.render_cookies(profile, "2026-11-04")
        self.assertEqual(privacy, SAMPLE_PRIVACY_SECTIONS)
        self.assertEqual(terms, SAMPLE_TERMS_SECTIONS)
        self.assertEqual(cookies, SAMPLE_COOKIES_SECTIONS)

    def test_notice_and_stamp_on_every_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = make(
                tmp, json.loads((EXAMPLES / "sample-site.json")
                                .read_text(encoding="utf-8")))
            for name in ("privacy.html", "terms.html",
                         "cookies.html"):
                text = read(out, name)
                self.assertIn("Template —", text)
                self.assertIn("not legal advice", text)
                self.assertIn("Last updated: 2026-11-04", text)

    def test_canada_variant_names_the_commissioner(self):
        profile = cp.validate_profile(full_profile())
        text, _ = cp.render_privacy(profile, "2026-11-04")
        self.assertIn("Privacy Commissioner of Canada", text)

    def test_generic_variant_uses_local_authority(self):
        data = full_profile()
        data["business"]["country"] = "Germany"
        profile = cp.validate_profile(data)
        self.assertEqual(profile["variant"], "generic")
        text, _ = cp.render_privacy(profile, "2026-11-04")
        self.assertIn("local data-protection authority", text)
        self.assertNotIn("Privacy Commissioner of Canada", text)

    def test_banner_for_sample_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = make(
                tmp, json.loads((EXAMPLES / "sample-site.json")
                                .read_text(encoding="utf-8")))
            banner = read(out, "banner.html")
            self.assertIn('data-cp-category="analytics"',
                          banner)
            self.assertNotIn('data-cp-category="marketing"',
                             banner)
            self.assertIn("data-cp-accept-all", banner)
            self.assertIn("data-cp-save", banner)
            self.assertIn('href="cookies.html"', banner)


class TestIncompleteSample(unittest.TestCase):

    def setUp(self):
        self.data = json.loads(
            (EXAMPLES / "incomplete-site.json").read_text(
                encoding="utf-8"))

    def test_make_exit1_and_placeholder_counts_per_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, out = make(tmp, self.data)
            self.assertEqual(result.returncode, 1,
                             result.stdout + result.stderr)
            expected = {"privacy.html": 9, "terms.html": 4,
                        "cookies.html": 2, "banner.html": 0,
                        "consent.js": 0}
            total = 0
            for name, count in expected.items():
                found = read(out, name).count("[TO FILL:")
                self.assertEqual(found, count, name)
                total += found
            self.assertEqual(total, 15)

    def test_manifest_lists_every_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = make(tmp, self.data)
            manifest = read(out, "manifest.txt")
            self.assertIn(
                "Placeholders in the generated documents: 15",
                manifest)
            for marker in (
                    "business mailing address",
                    "contact email for privacy and terms",
                    "how long collected information is kept",
                    "legal form of the business",
                    "the personal information this site "
                    "collects",
                    "third-party services this site uses",
                    "website address (URL)",
                    "what the collected information is used "
                    "for",
                    "which cookies this site sets",
                    "the governing law for these terms"):
                self.assertIn(marker, manifest)

    def test_check_reports_the_ten_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = write_profile(tmp, self.data)
            result = run_cli("check", "--profile",
                             str(profile), "--json")
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(
                [g["field"] for g in payload["gaps"]],
                ["business.legal_form", "business.address",
                 "business.contact_email", "site.url",
                 "data_collected", "data_use", "services",
                 "cookies", "retention", "governing_law"])
            self.assertEqual(payload["contradictions"], [])
            self.assertFalse(payload["complete"])


class TestCheck(unittest.TestCase):

    def test_complete_profile_check_exit0(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = write_profile(tmp, full_profile())
            result = run_cli("check", "--profile", str(profile))
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)
            self.assertIn("Verdict: COMPLETE", result.stdout)

    def test_check_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_profile(tmp, full_profile())
            before = sorted(p.name for p in Path(tmp).iterdir())
            run_cli("check", "--profile",
                    str(Path(tmp) / "profile.json"))
            after = sorted(p.name for p in Path(tmp).iterdir())
            self.assertEqual(before, after)

    def test_missing_date_is_a_gap_in_check(self):
        data = full_profile()
        del data["as_of"]
        with tempfile.TemporaryDirectory() as tmp:
            profile = write_profile(tmp, data)
            result = run_cli("check", "--profile",
                             str(profile), "--json")
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertIn("as_of",
                          [g["field"] for g in payload["gaps"]])
            self.assertIsNone(payload["as_of"])


class TestContradictions(unittest.TestCase):

    def _check_json(self, tmp, data):
        profile = write_profile(tmp, data)
        result = run_cli("check", "--profile", str(profile),
                         "--json")
        return result, json.loads(result.stdout)

    def test_cookies_page_requested_but_no_cookies(self):
        data = full_profile()  # all cookie categories exist
        data["cookies"] = {"essential": False,
                           "analytics": False,
                           "marketing": False}
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self._check_json(tmp, data)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(len(payload["contradictions"]), 1)
            self.assertIn("sets no cookies",
                          payload["contradictions"][0])

    def test_analytics_service_but_analytics_cookies_off(self):
        data = full_profile()
        data["services"]["analytics"] = "Example Metrics"
        with tempfile.TemporaryDirectory() as tmp:
            _, payload = self._check_json(tmp, data)
            self.assertEqual(len(payload["contradictions"]), 1)
            self.assertIn("reconcile services.analytics",
                          payload["contradictions"][0])

    def test_optional_cookies_without_consent_note(self):
        data = full_profile()
        data["cookies"] = {"essential": True,
                           "analytics": False,
                           "marketing": True}
        with tempfile.TemporaryDirectory() as tmp:
            result, out = make(tmp, data)
            self.assertEqual(result.returncode, 1)
            cookies_html = read(out, "cookies.html")
            self.assertIn(
                "[TO FILL: how analytics and marketing "
                "scripts are gated", cookies_html)
            banner = read(out, "banner.html")
            self.assertIn('data-cp-category="marketing"',
                          banner)
            _, payload = self._check_json(tmp, data)
            self.assertEqual(len(payload["contradictions"]), 1)
            self.assertIn("consent_note",
                          payload["contradictions"][0])

    def test_consent_note_present_means_no_contradiction(self):
        data = full_profile(
            consent_note="Analytics loads only after consent.")
        data["cookies"] = {"essential": True,
                           "analytics": False,
                           "marketing": True}
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self._check_json(tmp, data)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(payload["contradictions"], [])


class TestSectionPresence(unittest.TestCase):

    def test_no_analytics_anywhere_when_not_declared(self):
        profile = cp.validate_profile(full_profile())
        cookies_html, sections = cp.render_cookies(
            profile, "2026-11-04")
        self.assertNotIn("category: Analytics", sections)
        self.assertNotIn("<h3>Analytics</h3>", cookies_html)
        privacy_html, _ = cp.render_privacy(profile,
                                            "2026-11-04")
        self.assertNotIn("<td>Analytics</td>", privacy_html)

    def test_payments_named_only_when_declared(self):
        data = full_profile()
        data["services"]["payments"] = "CardCo"
        profile = cp.validate_profile(data)
        text, _ = cp.render_privacy(profile, "2026-11-04")
        self.assertIn("CardCo", text)
        profile2 = cp.validate_profile(full_profile())
        text2, _ = cp.render_privacy(profile2, "2026-11-04")
        self.assertNotIn("<td>Payments</td>", text2)

    def test_quotes_section_only_when_flag_set(self):
        data = full_profile(quotes_are_estimates=True)
        _, sections = cp.render_terms(
            cp.validate_profile(data), "2026-11-04")
        self.assertIn("Quotes and estimates", sections)
        _, sections2 = cp.render_terms(
            cp.validate_profile(full_profile()), "2026-11-04")
        self.assertNotIn("Quotes and estimates", sections2)

    def test_no_cookies_page_when_not_requested(self):
        data = full_profile(pages=["privacy", "terms"])
        with tempfile.TemporaryDirectory() as tmp:
            result, out = make(tmp, data)
            self.assertEqual(result.returncode, 0)
            names = sorted(p.name for p in out.iterdir())
            self.assertNotIn("cookies.html", names)
            self.assertEqual(len(names), 5)
            banner = read(out, "banner.html")
            self.assertNotIn('href="cookies.html"', banner)


class TestHygiene(unittest.TestCase):

    def test_only_url_is_the_sites_own_as_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = make(
                tmp, json.loads((EXAMPLES / "sample-site.json")
                                .read_text(encoding="utf-8")))
            for name in ("privacy.html", "terms.html",
                         "cookies.html", "banner.html",
                         "consent.js"):
                text = read(out, name)
                urls = re.findall(r"https?://[^\s\"'<)]+", text)
                # no external URL anywhere; the one URL that
                # may appear is the site's own, as text
                self.assertLessEqual(
                    set(urls), {"https://ovph.example"}, name)
                self.assertNotIn('href="http', text, name)
                self.assertNotIn('src="http', text, name)
            # and the site's own URL does appear, as text, on
            # the pages that name the site
            for name in ("privacy.html", "terms.html"):
                self.assertIn("https://ovph.example",
                              read(out, name))

    def test_consent_js_has_no_network_or_beacon_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = make(tmp, full_profile())
            js = read(out, "consent.js")
            lowered = js.lower()
            for banned in ("fetch", "xmlhttprequest",
                           "sendbeacon", "beacon", "http://",
                           "https://", "<script"):
                self.assertNotIn(banned, lowered)
            self.assertIn("localStorage", js)
            self.assertIn(cp.STORAGE_KEY, js)
            self.assertIn("cp:consent", js)
            self.assertIn("cpConsent", js)
            self.assertIn("reset", js)
            self.assertIn("removeItem", js)

    def test_business_name_with_script_tag_is_escaped(self):
        data = full_profile()
        data["business"]["name"] = \
            "Bad <script>alert(1)</script> Co"
        with tempfile.TemporaryDirectory() as tmp:
            _, out = make(tmp, data)
            for name in ("privacy.html", "terms.html"):
                text = read(out, name)
                self.assertIn("&lt;script&gt;alert(1)", text)
                self.assertNotIn("<script>alert(1)", text)
            self.assertNotIn("<script",
                             read(out, "consent.js").lower())

    def test_deterministic_byte_identical(self):
        data = json.loads((EXAMPLES / "sample-site.json")
                          .read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            _, out1 = make(tmp, data)
            profile = Path(tmp) / "profile.json"
            out2 = Path(tmp) / "out2"
            result = run_cli("make", "--profile", str(profile),
                             "--out", str(out2))
            self.assertEqual(result.returncode, 0)
            for name in SIX_FILES:
                self.assertEqual(read(out1, name),
                                 read(out2, name), name)


class TestDatesAndErrors(unittest.TestCase):

    def test_as_of_flag_overrides_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, out = make(tmp, full_profile(),
                               "--as-of", "2027-01-15")
            self.assertEqual(result.returncode, 0)
            manifest = read(out, "manifest.txt")
            self.assertIn("Stamped date: 2027-01-15 "
                          "(from the --as-of flag)", manifest)
            self.assertIn("Last updated: 2027-01-15",
                          read(out, "privacy.html"))

    def test_no_date_anywhere_is_a_clean_error(self):
        data = full_profile()
        del data["as_of"]
        with tempfile.TemporaryDirectory() as tmp:
            result, out = make(tmp, data)
            self.assertEqual(result.returncode, 2)
            self.assertIn("as_of", result.stdout)
            self.assertIn("--as-of", result.stdout)
            self.assertFalse(out.exists())

    def test_corrupt_profile_errors_and_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            before = path.read_bytes()
            result = run_cli("make", "--profile", str(path),
                             "--out", str(Path(tmp) / "out"))
            self.assertEqual(result.returncode, 2)
            self.assertIn("not valid JSON", result.stdout)
            self.assertEqual(path.read_bytes(), before)

    def test_unknown_page_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = make(tmp, full_profile(
                pages=["privacy", "faq"]))
            self.assertEqual(result.returncode, 2)
            self.assertIn("'faq'", result.stdout)

    def test_half_given_cookies_block_is_a_clean_error(self):
        data = full_profile()
        data["cookies"] = {"essential": True, "analytics": True}
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = make(tmp, data)
            self.assertEqual(result.returncode, 2)
            self.assertIn("cookies.marketing", result.stdout)

    def test_missing_profile_file_is_a_clean_error(self):
        result = run_cli("check", "--profile",
                         "/tmp/definitely-not-here-cp.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not found", result.stdout)

    def test_argparse_error_is_json_in_json_mode(self):
        result = run_cli("make", "--profile", "--json")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertIn("error", payload)

    def test_out_path_that_is_a_file_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = write_profile(tmp, full_profile())
            blocker = Path(tmp) / "blocker"
            blocker.write_text("x", encoding="utf-8")
            result = run_cli("make", "--profile", str(profile),
                             "--out", str(blocker))
            self.assertEqual(result.returncode, 2)
            self.assertIn("not a folder", result.stdout)


class TestJsonMode(unittest.TestCase):

    def test_make_json_shape_and_recount(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = write_profile(tmp, json.loads(
                (EXAMPLES / "incomplete-site.json").read_text(
                    encoding="utf-8")))
            out = Path(tmp) / "out"
            result = run_cli("make", "--profile", str(profile),
                             "--out", str(out), "--json")
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["files"], SIX_FILES)
            self.assertEqual(
                payload["placeholders"]["total"], 15)
            recount = sum(i["count"] for i in
                          payload["placeholders"]["items"])
            self.assertEqual(recount, 15)
            self.assertTrue(payload["attention"])

    def test_make_json_complete_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = write_profile(tmp, json.loads(
                (EXAMPLES / "sample-site.json").read_text(
                    encoding="utf-8")))
            result = run_cli("make", "--profile", str(profile),
                             "--out", str(Path(tmp) / "out"),
                             "--json")
            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["sections"]["privacy.html"],
                             SAMPLE_PRIVACY_SECTIONS)
            self.assertEqual(payload["sections"]["terms.html"],
                             SAMPLE_TERMS_SECTIONS)
            self.assertEqual(
                payload["sections"]["cookies.html"],
                SAMPLE_COOKIES_SECTIONS)
            self.assertFalse(payload["attention"])


if __name__ == "__main__":
    unittest.main()
