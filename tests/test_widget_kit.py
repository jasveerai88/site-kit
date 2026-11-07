#!/usr/bin/env python3
"""Tests for widget-kit. Stdlib unittest only.

Run from the pack root:
    python3 -m unittest discover -s tests -v

Expectations are worked out from the fixtures by hand, not
copied from the tool's own output:

- The bundled sample (examples/widgets.json) is a fictional
  bakery: a 3-question FAQ, 3 pricing tiers ($12 / $29 / $95,
  only "Household" flagged highlight), a countdown to
  2027-06-01T09:00:00-07:00 — that is 2027-06-01 16:00:00
  UTC, epoch 1,811,865,600 s, so data-target must read
  1811865600000 — and 3 SAMPLE proof entries fed from
  examples/proof-entries.json.
- The FAQ's visible questions/answers and its JSON-LD
  mainEntity must be the SAME list, in the same order — the
  schema-spam failure is the two drifting apart, so the test
  extracts both independently and compares them to the
  config and to each other.
- examples/bad-config.json was built to hold exactly SIX
  problems: a faq item missing "a", an unknown type "chat",
  a numeric price, a cta_label with no cta_url, a countdown
  missing ended_text and a countdown target with no UTC
  offset. One run must report all six and write nothing.
- A question holding "<script>alert(1)</script>" must
  appear in the visible HTML only as escaped text, and in
  the JSON-LD only as \\u003c escapes that parse back to the
  exact original string.
- Proof renders only what it is given: 3 entries in means
  exactly 3 cards out, in input order, and the fragment
  contains no computed claim (no "average", no count line).
"""
import html
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parents[1]
TOOL = PACK_ROOT / "src" / "widget_kit.py"
SAMPLE = PACK_ROOT / "examples" / "widget-kit" / "widgets.json"
BAD = PACK_ROOT / "examples" / "widget-kit" / "bad-config.json"
PAST = PACK_ROOT / "examples" / "widget-kit" / "past-countdown.json"
CSV_ENTRIES = PACK_ROOT / "examples" / "widget-kit" / "proof-entries.csv"

EPOCH_MS = "1811865600000"  # 2027-06-01T09:00:00-07:00


def run(args, cwd):
    return subprocess.run([sys.executable, str(TOOL)] + args,
                          capture_output=True, text=True, cwd=cwd)


def faq_visible(fragment):
    qs = re.findall(r"<summary>(.*?)</summary>", fragment, re.S)
    ans = re.findall(r'<div class="wk-faq-a">(.*?)</div>',
                     fragment, re.S)
    return [(html.unescape(q), html.unescape(a))
            for q, a in zip(qs, ans)]


def faq_jsonld(fragment):
    m = re.search(r'<script type="application/ld\+json">\n'
                  r"(.*?)\n  </script>", fragment, re.S)
    assert m, "no JSON-LD block found"
    return json.loads(m.group(1))


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write_config(self, data, name="config.json"):
        path = self.tmp / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def make(self, config, out_name="out", extra=()):
        out = self.tmp / out_name
        proc = run(["make", "--config", str(config),
                    "--out", str(out)] + list(extra), self.tmp)
        return proc, out


class TestSampleMake(TempDirTest):
    def test_sample_exit_0_and_files(self):
        proc, out = self.make(SAMPLE)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("Warnings: none", proc.stdout)
        for name in ("faq.html", "pricing.html",
                     "bake-sale.html", "proof.html"):
            self.assertTrue((out / name).is_file(), name)

    def test_json_shape_and_sizes(self):
        proc, out = self.make(SAMPLE, extra=("--json",))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        obj = json.loads(proc.stdout)
        self.assertEqual(obj["tool"], "widget-kit")
        self.assertEqual(obj["warnings"], [])
        frags = {f["file"]: f for f in obj["fragments"]}
        self.assertEqual(set(frags), {"faq.html", "pricing.html",
                                      "bake-sale.html",
                                      "proof.html"})
        for name, frag in frags.items():
            self.assertEqual(
                frag["bytes"],
                len((out / name).read_bytes()), name)
        self.assertEqual(frags["faq.html"]["summary"],
                         "3 question(s)")
        self.assertEqual(frags["proof.html"]["summary"],
                         "3 supplied entries")

    def test_deterministic_byte_identical(self):
        _p1, out1 = self.make(SAMPLE, "one")
        _p2, out2 = self.make(SAMPLE, "two")
        for name in ("faq.html", "pricing.html",
                     "bake-sale.html", "proof.html"):
            self.assertEqual((out1 / name).read_bytes(),
                             (out2 / name).read_bytes(), name)


class TestFaq(TempDirTest):
    def test_visible_matches_config(self):
        _proc, out = self.make(SAMPLE)
        items = faq_visible((out / "faq.html").read_text())
        cfg = json.loads(SAMPLE.read_text())
        expected = [(i["q"], i["a"])
                    for i in cfg["widgets"][0]["items"]]
        self.assertEqual(items, expected)

    def test_jsonld_matches_visible_and_config(self):
        _proc, out = self.make(SAMPLE)
        fragment = (out / "faq.html").read_text()
        ld = faq_jsonld(fragment)
        self.assertEqual(ld["@type"], "FAQPage")
        from_ld = [(e["name"], e["acceptedAnswer"]["text"])
                   for e in ld["mainEntity"]]
        self.assertEqual(from_ld, faq_visible(fragment))
        cfg = json.loads(SAMPLE.read_text())
        expected = [(i["q"], i["a"])
                    for i in cfg["widgets"][0]["items"]]
        self.assertEqual(from_ld, expected)

    def test_only_script_is_jsonld(self):
        _proc, out = self.make(SAMPLE)
        fragment = (out / "faq.html").read_text()
        self.assertEqual(fragment.count("<script"), 1)
        self.assertIn('<script type="application/ld+json">',
                      fragment)
        self.assertIn("<details", fragment)
        self.assertIn("<summary>", fragment)

    def test_script_in_question_escaped_both_ways(self):
        evil = "<script>alert(1)</script>"
        cfg = self.write_config({"widgets": [
            {"type": "faq", "items": [
                {"q": evil, "a": "Harmless answer."}]}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        fragment = (out / "faq.html").read_text()
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;",
                      fragment)
        self.assertEqual(fragment.count("<script"), 1)
        self.assertIn("\\u003cscript\\u003e", fragment)
        ld = faq_jsonld(fragment)
        self.assertEqual(
            ld["mainEntity"][0]["name"], evil)

    def test_title_optional(self):
        cfg = self.write_config({"widgets": [
            {"type": "faq", "items": [{"q": "Q?", "a": "A."}]}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        fragment = (out / "faq.html").read_text()
        self.assertNotIn("<h2", fragment)
        self.assertIn('aria-label="Frequently asked questions"',
                      fragment)

    def test_empty_items_warns_exit_1(self):
        cfg = self.write_config({"widgets": [
            {"type": "faq", "title": "Empty", "items": []}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("no items", proc.stdout)
        self.assertTrue((out / "faq.html").is_file())

    def test_missing_answer_problem(self):
        cfg = self.write_config({"widgets": [
            {"type": "faq", "items": [{"q": "Q?"}]}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing required field 'a'", proc.stdout)
        self.assertFalse(out.exists())


class TestPricing(TempDirTest):
    def _fragment(self):
        _proc, out = self.make(SAMPLE)
        return (out / "pricing.html").read_text()

    def test_prices_verbatim(self):
        fragment = self._fragment()
        for price in ("$12", "$29", "$95"):
            self.assertIn(price, fragment)
        self.assertIn("/mo", fragment)

    def test_highlight_only_flagged_tier(self):
        fragment = self._fragment()
        self.assertEqual(
            fragment.count('class="wk-tier wk-tier-hl"'), 1)
        cards = fragment.split('<div class="wk-tier')
        household = [c for c in cards if "Household" in c]
        self.assertEqual(len(household), 1)
        self.assertTrue(
            household[0].startswith(' wk-tier-hl"'))

    def test_no_invented_badge_text(self):
        fragment = self._fragment().lower()
        self.assertNotIn("most popular", fragment)
        self.assertNotIn("recommended", fragment)
        self.assertNotIn("best value", fragment)

    def test_cta_links_rendered(self):
        fragment = self._fragment()
        self.assertIn('href="https://example.org/crumb-club/'
                      'join"', fragment)
        self.assertIn('href="https://example.org/crumb-club/'
                      'join-household"', fragment)
        self.assertIn("Join the Taster", fragment)

    def test_no_highlight_when_unflagged(self):
        cfg = self.write_config({"widgets": [
            {"type": "pricing", "tiers": [
                {"name": "Solo", "price": "$5",
                 "features": []}]}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        fragment = (out / "pricing.html").read_text()
        self.assertNotIn('class="wk-tier wk-tier-hl"', fragment)

    def test_cta_javascript_url_refused(self):
        cfg = self.write_config({"widgets": [
            {"type": "pricing", "tiers": [
                {"name": "X", "price": "$5", "features": [],
                 "cta_label": "Go",
                 "cta_url": "javascript:alert(1)"}]}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("scheme 'javascript' is not allowed",
                      proc.stdout)
        self.assertFalse(out.exists())

    def test_cta_label_without_url_problem(self):
        cfg = self.write_config({"widgets": [
            {"type": "pricing", "tiers": [
                {"name": "X", "price": "$5", "features": [],
                 "cta_label": "Go"}]}]})
        proc, _out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must be given together", proc.stdout)

    def test_price_must_be_string(self):
        cfg = self.write_config({"widgets": [
            {"type": "pricing", "tiers": [
                {"name": "X", "price": 49, "features": []}]}]})
        proc, _out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must be a string rendered exactly as "
                      "written", proc.stdout)


class TestCountdown(TempDirTest):
    def test_future_target_epoch_and_fallback(self):
        _proc, out = self.make(SAMPLE)
        fragment = (out / "bake-sale.html").read_text()
        self.assertIn(f'data-target="{EPOCH_MS}"', fragment)
        self.assertIn("Ends 1 Jun 2027, 09:00 (UTC-07:00)",
                      fragment)
        self.assertIn("Summer bake sale ends in", fragment)
        self.assertIn('class="wk-cd-ended" hidden', fragment)
        self.assertIn("The summer bake sale has ended",
                      fragment)

    def test_z_suffix_same_epoch(self):
        cfg = self.write_config({"widgets": [
            {"type": "countdown",
             "target": "2027-06-01T16:00:00Z",
             "ended_text": "Done."}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        fragment = (out / "countdown.html").read_text()
        self.assertIn(f'data-target="{EPOCH_MS}"', fragment)
        self.assertIn("(UTC+00:00)", fragment)

    def test_past_target_warns_and_shows_ended(self):
        proc, out = self.make(PAST)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("already in the past", proc.stdout)
        fragment = (out / "sale.html").read_text()
        self.assertIn("This countdown ended long ago.", fragment)
        self.assertNotIn("data-target", fragment)
        self.assertNotIn("<script", fragment)

    def test_naive_target_refused(self):
        cfg = self.write_config({"widgets": [
            {"type": "countdown",
             "target": "2027-06-01T09:00:00",
             "ended_text": "Done."}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("explicit UTC offset", proc.stdout)
        self.assertFalse(out.exists())

    def test_date_only_target_refused(self):
        cfg = self.write_config({"widgets": [
            {"type": "countdown", "target": "2027-06-01",
             "ended_text": "Done."}]})
        proc, _out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("explicit UTC offset", proc.stdout)

    def test_missing_ended_text_problem(self):
        cfg = self.write_config({"widgets": [
            {"type": "countdown",
             "target": "2027-06-01T09:00:00-07:00"}]})
        proc, _out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing required field 'ended_text'",
                      proc.stdout)

    def test_garbage_target_problem(self):
        cfg = self.write_config({"widgets": [
            {"type": "countdown", "target": "next Friday",
             "ended_text": "Done."}]})
        proc, _out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a valid ISO 8601 datetime",
                      proc.stdout)


class TestProof(TempDirTest):
    def test_renders_only_supplied_in_order(self):
        _proc, out = self.make(SAMPLE)
        fragment = (out / "proof.html").read_text()
        self.assertEqual(fragment.count('class="wk-proof-card"'),
                         3)
        positions = [fragment.index(name) for name in
                     ("Sample Customer A", "Sample Customer B",
                      "Sample Café (fictional)")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Rated 5 out of 5", fragment)
        self.assertIn("★★★★☆", fragment)

    def test_no_computed_claims(self):
        _proc, out = self.make(SAMPLE)
        fragment = (out / "proof.html").read_text().lower()
        self.assertNotIn("average", fragment)
        self.assertNotIn("happy customers", fragment)
        self.assertNotIn("reviews", fragment)

    def test_input_order_preserved_not_sorted(self):
        cfg = self.write_config({"widgets": [
            {"type": "proof", "entries": [
                {"name": "Zed Last", "text": "First in file."},
                {"name": "Amy First",
                 "text": "Second in file."}]}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        fragment = (out / "proof.html").read_text()
        self.assertLess(fragment.index("Zed Last"),
                        fragment.index("Amy First"))

    def test_csv_entries_file(self):
        # entries_file resolves against the config's folder,
        # so the CSV sits beside the config
        (self.tmp / "entries.csv").write_text(
            CSV_ENTRIES.read_text(), encoding="utf-8")
        cfg = self.write_config({"widgets": [
            {"type": "proof", "entries_file": "entries.csv"}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        fragment = (out / "proof.html").read_text()
        self.assertEqual(fragment.count('class="wk-proof-card"'),
                         2)
        self.assertIn("Rated 5 out of 5", fragment)

    def test_entries_object_form_file(self):
        entries_path = self.tmp / "e.json"
        entries_path.write_text(json.dumps({"entries": [
            {"name": "Obj Form", "text": "Works."}]}),
            encoding="utf-8")
        cfg = self.write_config({"widgets": [
            {"type": "proof", "entries_file": "e.json"}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("Obj Form",
                      (out / "proof.html").read_text())

    def test_rating_out_of_range_problem(self):
        for bad in (6, 0, "five", 4.5, True):
            cfg = self.write_config({"widgets": [
                {"type": "proof", "entries": [
                    {"name": "A", "text": "T.",
                     "rating": bad}]}]}, name=f"c-{bad}.json")
            proc, _out = self.make(cfg)
            self.assertEqual(proc.returncode, 2, bad)
            self.assertIn("integer 1-5", proc.stdout)

    def test_bad_date_problem(self):
        cfg = self.write_config({"widgets": [
            {"type": "proof", "entries": [
                {"name": "A", "text": "T.",
                 "date": "2026-02-30"}]}]})
        proc, _out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("real date as YYYY-MM-DD", proc.stdout)

    def test_both_entries_and_file_problem(self):
        cfg = self.write_config({"widgets": [
            {"type": "proof",
             "entries": [{"name": "A", "text": "T."}],
             "entries_file": "x.json"}]})
        proc, _out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not both", proc.stdout)

    def test_missing_entries_file_problem(self):
        cfg = self.write_config({"widgets": [
            {"type": "proof", "entries_file": "nope.json"}]})
        proc, _out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read entries_file", proc.stdout)

    def test_neither_entries_nor_file_problem(self):
        cfg = self.write_config({"widgets": [{"type": "proof"}]})
        proc, _out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("needs 'entries' or 'entries_file'",
                      proc.stdout)

    def test_empty_entries_warns(self):
        cfg = self.write_config({"widgets": [
            {"type": "proof", "title": "None yet",
             "entries": []}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("no entries", proc.stdout)
        self.assertTrue((out / "proof.html").is_file())


class TestValidation(TempDirTest):
    def test_bad_config_collects_six_problems(self):
        proc, out = self.make(BAD)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("6 problem(s)", proc.stdout)
        for needle in (
                "missing required field 'a'",
                "unknown widget type 'chat'",
                "valid types: faq, pricing, countdown, proof",
                "must be a string rendered exactly as written",
                "must be given together",
                "missing required field 'ended_text'",
                "explicit UTC offset"):
            self.assertIn(needle, proc.stdout)
        self.assertFalse(out.exists())

    def test_bad_config_json_problems(self):
        proc, _out = self.make(BAD, extra=("--json",))
        self.assertEqual(proc.returncode, 2)
        obj = json.loads(proc.stdout)
        self.assertIn("error", obj)
        self.assertEqual(len(obj["problems"]), 6)

    def test_duplicate_output_filename(self):
        cfg = self.write_config({"widgets": [
            {"type": "faq", "items": [{"q": "Q", "a": "A"}]},
            {"type": "faq", "items": [{"q": "Q2", "a": "A2"}]}]})
        proc, _out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("already used by", proc.stdout)

    def test_distinct_ids_allow_same_type_twice(self):
        cfg = self.write_config({"widgets": [
            {"type": "faq", "id": "faq-a",
             "items": [{"q": "Q", "a": "A"}]},
            {"type": "faq", "id": "faq-b",
             "items": [{"q": "Q2", "a": "A2"}]}]})
        proc, out = self.make(cfg)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue((out / "faq-a.html").is_file())
        self.assertTrue((out / "faq-b.html").is_file())

    def test_widgets_missing_and_empty(self):
        for data in ({}, {"widgets": []}, {"widgets": "x"}):
            cfg = self.write_config(data)
            proc, _out = self.make(cfg)
            self.assertEqual(proc.returncode, 2, data)
            self.assertIn("'widgets'", proc.stdout)

    def test_invalid_id_problem(self):
        cfg = self.write_config({"widgets": [
            {"type": "faq", "id": "Bad ID!",
             "items": [{"q": "Q", "a": "A"}]}]})
        proc, _out = self.make(cfg)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("field 'id'", proc.stdout)

    def test_missing_config_file(self):
        proc = run(["make", "--config", "nope.json",
                    "--out", str(self.tmp / "o")], self.tmp)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("ERROR: cannot read config file",
                      proc.stdout)
        proc = run(["make", "--config", "nope.json",
                    "--out", str(self.tmp / "o"), "--json"],
                   self.tmp)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", json.loads(proc.stdout))

    def test_malformed_json_config(self):
        path = self.tmp / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        proc, _out = self.make(path)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not valid JSON", proc.stdout)
        self.assertNotIn("Traceback", proc.stdout)

    def test_argparse_error_is_json_in_json_mode(self):
        proc = run(["make", "--json"], self.tmp)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", json.loads(proc.stdout))

    def test_out_path_is_a_file(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("x", encoding="utf-8")
        proc = run(["make", "--config", str(SAMPLE),
                    "--out", str(blocker)], self.tmp)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a directory", proc.stdout)


class TestFragmentContract(TempDirTest):
    def test_no_external_references(self):
        _proc, out = self.make(SAMPLE)
        allowed_hrefs = {
            "https://example.org/crumb-club/join",
            "https://example.org/crumb-club/join-household"}
        for name in ("faq.html", "pricing.html",
                     "bake-sale.html", "proof.html"):
            fragment = (out / name).read_text()
            self.assertNotIn("src=", fragment, name)
            self.assertNotIn("<link", fragment, name)
            self.assertNotIn("@import", fragment, name)
            self.assertNotIn("url(", fragment, name)
            hrefs = set(re.findall(r'href="([^"]+)"', fragment))
            self.assertLessEqual(hrefs, allowed_hrefs, name)
            urls = set(re.findall(r"https?://[^\s\"'<>]+",
                                  fragment))
            self.assertLessEqual(
                urls, allowed_hrefs | {"https://schema.org"},
                name)

    def test_no_network_code_in_source(self):
        source = TOOL.read_text(encoding="utf-8")
        for banned in ("urllib", "socket", "urlopen",
                       "http.client", "import requests"):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
