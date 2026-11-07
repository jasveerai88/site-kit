#!/usr/bin/env python3
"""Tests for wall-of-love. Stdlib unittest only.

Run from the pack root:
    python3 -m unittest discover -s tests -v

Expectations are worked out from the fixtures below by hand,
not copied from the tool's own output:

- The bundled sample (examples/sample-testimonials.json)
  carries 6 testimonials with ratings 5, 5, 4, 5, 4, 5 — sum
  28, mean 28/6 = 4.666..., so the aggregate is 4.7 and the
  review count is 6. Display order is rating first, then
  newest date: Priya (5, 2026-09-14), Marcus (5, 2026-08-02),
  Tom (5, 2026-07-19), Dan (5, 2026-05-23), Elena (4,
  2026-10-05), Aisha (4, 2026-06-11).
- The warnings sample repeats one quote verbatim under two
  names and leaves a third testimonial unrated: two warnings,
  exit 1, aggregate (5 + 4) / 2 = 4.5 from 2 rated, count 3.
- The CSV sample's ratings are 5, 5, 4 — sum 14, mean 4.7.
- Rounding is half-up: ratings 5, 4, 4, 4 give mean 4.25,
  which must render as 4.3 (banker's rounding would say 4.2).
- A quote holding "</script><script>alert(1)</script>" must
  appear on the page only as escaped text; the page must
  contain exactly ONE <script> element — the inert JSON-LD
  block — and the JSON-LD must parse back to the exact
  original quote.
- The wall shows only what the file holds: 3 testimonials in
  means exactly 3 cards out.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parents[1]
TOOL = PACK_ROOT / "src" / "wall_of_love.py"
SAMPLE = PACK_ROOT / "examples" / "wall-of-love" / "sample-testimonials.json"
WARNINGS_SAMPLE = PACK_ROOT / "examples" / "wall-of-love" / "sample-warnings.json"
CSV_SAMPLE = PACK_ROOT / "examples" / "wall-of-love" / "sample-testimonials.csv"


def run(args, cwd):
    return subprocess.run([sys.executable, str(TOOL)] + args,
                          capture_output=True, text=True, cwd=cwd)


def extract_jsonld(page):
    m = re.search(r'<script type="application/ld\+json">\n(.*?)\n'
                  r'</script>', page, re.S)
    assert m, "no JSON-LD block found"
    return json.loads(m.group(1))


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write_input(self, obj, name="input.json"):
        path = self.dir / name
        path.write_text(json.dumps(obj), encoding="utf-8")
        return path

    def write_text(self, text, name):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def base(self, **overrides):
        cfg = {"business": "Test Biz",
               "testimonials": [
                   {"name": "Ann", "quote": "Great work.",
                    "rating": 5, "date": "2026-09-01"}]}
        cfg.update(overrides)
        return cfg


# ---------------------------------------------------------------------------
# build: the happy path
# ---------------------------------------------------------------------------

class BuildTests(TempDirTest):
    def build_sample(self):
        out = self.dir / "wall.html"
        r = run(["build", str(SAMPLE), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return out.read_text(encoding="utf-8")

    def test_build_writes_one_file_exit_0(self):
        out = self.dir / "wall.html"
        r = run(["build", str(SAMPLE), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(out.is_file())
        self.assertIn("<h1>Okanagan Stone &amp; Cedar</h1>",
                      out.read_text(encoding="utf-8"))

    def test_build_default_output_is_wall_html(self):
        r = run(["build", str(SAMPLE)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.dir / "wall.html").is_file())

    def test_page_contains_all_six_quotes(self):
        page = self.build_sample()
        for fragment in ("survived two winters",
                         "re-decked three of our rental",
                         "stone retaining wall",
                         "done a week early",
                         "honest about the wait",
                         "common-area fencing"):
            self.assertIn(fragment, page)

    def test_display_order_rating_then_newest(self):
        page = self.build_sample()
        names = ["Priya Nair", "Marcus Webb", "Tom Bergeron",
                 "Dan Whitfield", "Elena Petrova", "Aisha Khan"]
        positions = [page.index(n) for n in names]
        self.assertEqual(positions, sorted(positions))

    def test_six_in_six_cards_out(self):
        page = self.build_sample()
        self.assertEqual(page.count('<figure class="card">'), 6)

    def test_aggregate_and_count_on_the_wall(self):
        page = self.build_sample()
        self.assertIn("<strong>4.7 out of 5</strong>", page)
        self.assertIn("from 6 review(s)", page)

    def test_stars_rendered_as_text(self):
        page = self.build_sample()
        self.assertIn("★★★★★", page)
        self.assertIn("★★★★☆", page)

    def test_jsonld_parses_and_matches_wall(self):
        page = self.build_sample()
        ld = extract_jsonld(page)
        self.assertEqual(ld["@type"], "LocalBusiness")
        self.assertEqual(ld["name"], "Okanagan Stone & Cedar")
        agg = ld["aggregateRating"]
        self.assertEqual(agg["ratingValue"], "4.7")
        self.assertEqual(agg["reviewCount"], 6)
        self.assertEqual(len(ld["review"]), 6)
        self.assertEqual(ld["review"][0]["author"]["name"],
                         "Priya Nair")
        self.assertEqual(
            ld["review"][0]["reviewRating"]["ratingValue"], 5)
        # the displayed number and the JSON-LD number are one fact
        self.assertIn(f"<strong>{agg['ratingValue']} out of 5"
                      f"</strong>", page)

    def test_exactly_one_script_element(self):
        page = self.build_sample()
        self.assertEqual(page.count("<script"), 1)
        self.assertEqual(page.count("</script>"), 1)

    def test_external_urls_are_exactly_the_configured_set(self):
        page = self.build_sample()
        found = set(re.findall(r'https?://[^" <>]+', page))
        self.assertEqual(found, {
            "https://example.org/okanagan/logo.png",
            "https://example.org/avatars/priya.jpg",
            "https://example.org/reviews/priya-nair",
            "https://example.org/reviews/tom-bergeron",
            # the JSON-LD vocabulary identifier — a namespace
            # name, never fetched by a browser
            "https://schema.org",
        })

    def test_logo_and_avatar_referenced_not_embedded(self):
        page = self.build_sample()
        self.assertIn('<img class="logo" '
                      'src="https://example.org/okanagan/logo.png"',
                      page)
        self.assertIn('src="https://example.org/avatars/priya.jpg"',
                      page)
        self.assertNotIn("data:image", page)
        self.assertNotIn("base64", page)

    def test_source_link_rendered(self):
        page = self.build_sample()
        self.assertIn('<a href="https://example.org/reviews/'
                      'priya-nair" rel="noopener">Original review'
                      '</a>', page)

    def test_dark_mode_palette(self):
        cfg = self.base(theme={"mode": "dark"})
        path = self.write_input(cfg)
        out = self.dir / "dark.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("background:#16130f",
                      out.read_text(encoding="utf-8"))

    def test_bare_list_input(self):
        path = self.write_input(
            [{"name": "Solo", "quote": "One voice.", "rating": 4}])
        out = self.dir / "solo.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        page = out.read_text(encoding="utf-8")
        self.assertIn("<h1>Wall of Love</h1>", page)
        self.assertEqual(page.count('<figure class="card">'), 1)

    def test_only_what_the_file_holds(self):
        cfg = self.base(testimonials=[
            {"name": "A", "quote": "First.", "rating": 5},
            {"name": "B", "quote": "Second.", "rating": 4},
            {"name": "C", "quote": "Third.", "rating": 3}])
        path = self.write_input(cfg)
        out = self.dir / "three.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        page = out.read_text(encoding="utf-8")
        self.assertEqual(page.count('<figure class="card">'), 3)
        self.assertIn("from 3 review(s)", page)


# ---------------------------------------------------------------------------
# preview + page weight
# ---------------------------------------------------------------------------

class PreviewTests(TempDirTest):
    def test_preview_writes_nothing(self):
        r = run(["preview", str(SAMPLE)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_preview_weight_equals_written_bytes(self):
        out = self.dir / "wall.html"
        run(["build", str(SAMPLE), "-o", str(out)], self.dir)
        size = len(out.read_bytes())
        r = run(["preview", str(SAMPLE)], self.dir)
        self.assertIn(f"page weight {size:,} bytes", r.stdout)

    def test_preview_json_shape(self):
        r = run(["preview", str(SAMPLE), "--json"], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["tool"], "wall-of-love")
        self.assertEqual(payload["count"], 6)
        self.assertEqual(payload["rated_count"], 6)
        self.assertEqual(payload["aggregate"], 4.7)
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(payload["testimonials"][0]["name"],
                         "Priya Nair")

    def test_build_json_adds_output_file(self):
        out = self.dir / "w.html"
        r = run(["build", str(SAMPLE), "-o", str(out), "--json"],
                self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["output_file"], str(out))
        self.assertEqual(payload["page_bytes"],
                         len(out.read_bytes()))


# ---------------------------------------------------------------------------
# sorting
# ---------------------------------------------------------------------------

class SortingTests(TempDirTest):
    def order_of_names(self, testimonials):
        path = self.write_input({"testimonials": testimonials})
        r = run(["preview", str(path), "--json"], self.dir)
        payload = json.loads(r.stdout)
        return [t["name"] for t in payload["testimonials"]]

    def test_same_rating_newer_first(self):
        names = self.order_of_names([
            {"name": "Old", "quote": "q1", "rating": 5,
             "date": "2025-01-01"},
            {"name": "New", "quote": "q2", "rating": 5,
             "date": "2026-01-01"}])
        self.assertEqual(names, ["New", "Old"])

    def test_unrated_sorts_after_rated_even_when_newest(self):
        names = self.order_of_names([
            {"name": "UnratedNew", "quote": "q1",
             "date": "2026-12-01"},
            {"name": "RatedOld", "quote": "q2", "rating": 1,
             "date": "2020-01-01"}])
        self.assertEqual(names, ["RatedOld", "UnratedNew"])

    def test_undated_after_dated_at_same_rating(self):
        names = self.order_of_names([
            {"name": "Undated", "quote": "q1", "rating": 3},
            {"name": "Dated", "quote": "q2", "rating": 3,
             "date": "2020-01-01"}])
        self.assertEqual(names, ["Dated", "Undated"])

    def test_full_tie_keeps_input_order(self):
        names = self.order_of_names([
            {"name": "First", "quote": "q1", "rating": 4,
             "date": "2026-01-01"},
            {"name": "Second", "quote": "q2", "rating": 4,
             "date": "2026-01-01"}])
        self.assertEqual(names, ["First", "Second"])


# ---------------------------------------------------------------------------
# aggregate math
# ---------------------------------------------------------------------------

class AggregateTests(TempDirTest):
    def aggregate(self, ratings):
        testimonials = [
            {"name": f"T{i}", "quote": f"quote {i}", "rating": r}
            for i, r in enumerate(ratings)]
        path = self.write_input({"testimonials": testimonials})
        r = run(["preview", str(path), "--json"], self.dir)
        return json.loads(r.stdout)

    def test_half_up_rounding(self):
        # 5+4+4+4 = 17, 17/4 = 4.25 -> 4.3 half-up (not 4.2)
        payload = self.aggregate([5, 4, 4, 4])
        self.assertEqual(payload["aggregate"], 4.3)

    def test_single_rating(self):
        self.assertEqual(self.aggregate([1])["aggregate"], 1.0)
        self.assertEqual(self.aggregate([5])["aggregate"], 5.0)

    def test_even_split(self):
        self.assertEqual(self.aggregate([5, 4])["aggregate"], 4.5)

    def test_unrated_excluded_from_mean_but_counted(self):
        path = self.write_input({"testimonials": [
            {"name": "A", "quote": "q1", "rating": 5},
            {"name": "B", "quote": "q2"}]})
        r = run(["preview", str(path), "--json"], self.dir)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["aggregate"], 5.0)
        self.assertEqual(payload["rated_count"], 1)
        self.assertEqual(payload["count"], 2)

    def test_no_ratings_no_aggregate(self):
        path = self.write_input({"testimonials": [
            {"name": "A", "quote": "q1"},
            {"name": "B", "quote": "q2"}]})
        out = self.dir / "none.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        page = out.read_text(encoding="utf-8")
        ld = extract_jsonld(page)
        self.assertNotIn("aggregateRating", ld)
        self.assertNotIn("out of 5</strong>", page)


# ---------------------------------------------------------------------------
# warnings
# ---------------------------------------------------------------------------

class WarningTests(TempDirTest):
    def test_warnings_sample_exit_1_page_built(self):
        out = self.dir / "w.html"
        r = run(["build", str(WARNINGS_SAMPLE), "-o", str(out)],
                self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(out.is_file())
        self.assertIn("duplicate quote", r.stdout)
        self.assertIn("missing rating", r.stdout)

    def test_duplicate_detection_ignores_case_and_whitespace(self):
        path = self.write_input({"testimonials": [
            {"name": "A", "quote": "Great  work here.",
             "rating": 5},
            {"name": "B", "quote": "great work here.",
             "rating": 5}]})
        r = run(["preview", str(path)], self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("duplicate quote", r.stdout)

    def test_distinct_quotes_no_warning(self):
        path = self.write_input({"testimonials": [
            {"name": "A", "quote": "Great work.", "rating": 5},
            {"name": "B", "quote": "Great work, again!",
             "rating": 5}]})
        r = run(["preview", str(path)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_unrated_shows_without_stars(self):
        path = self.write_input({"testimonials": [
            {"name": "A", "quote": "q1"}]})
        out = self.dir / "w.html"
        run(["build", str(path), "-o", str(out)], self.dir)
        page = out.read_text(encoding="utf-8")
        self.assertNotIn('class="stars"', page.split(
            '<figure class="card">', 1)[1])


# ---------------------------------------------------------------------------
# escaping
# ---------------------------------------------------------------------------

class EscapingTests(TempDirTest):
    HOSTILE = "</script><script>alert(1)</script> Great & \"fast\""

    def build_hostile(self):
        path = self.write_input({"testimonials": [
            {"name": "Eve <Admin>", "quote": self.HOSTILE,
             "rating": 5, "date": "2026-10-01"}]})
        out = self.dir / "h.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return out.read_text(encoding="utf-8")

    def test_script_quote_renders_as_text_only(self):
        page = self.build_hostile()
        self.assertEqual(page.count("<script"), 1)
        self.assertEqual(page.count("</script>"), 1)
        self.assertNotIn(self.HOSTILE, page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_jsonld_round_trips_hostile_quote_exactly(self):
        page = self.build_hostile()
        ld = extract_jsonld(page)
        self.assertEqual(ld["review"][0]["reviewBody"],
                         self.HOSTILE)

    def test_name_and_ampersands_escaped(self):
        page = self.build_hostile()
        self.assertIn("Eve &lt;Admin&gt;", page)
        self.assertIn("Great &amp;", page)

    def test_attribute_escaping(self):
        path = self.write_input({"testimonials": [
            {"name": "A", "quote": "q", "rating": 5,
             "avatar": "https://example.org/a.jpg?x=1&y=2"}]})
        out = self.dir / "a.html"
        run(["build", str(path), "-o", str(out)], self.dir)
        page = out.read_text(encoding="utf-8")
        self.assertIn("a.jpg?x=1&amp;y=2", page)

    def test_unicode_and_emoji_verbatim(self):
        quote = "Café ☕ — très bien, merci !"
        path = self.write_input({"testimonials": [
            {"name": "Chloé", "quote": quote, "rating": 5}]})
        out = self.dir / "u.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        page = out.read_text(encoding="utf-8")
        self.assertIn(quote, page)
        ld = extract_jsonld(page)
        self.assertEqual(ld["review"][0]["reviewBody"], quote)

    def test_very_long_quote_rendered_in_full(self):
        quote = "word " * 1000  # 5,000 characters
        path = self.write_input({"testimonials": [
            {"name": "A", "quote": quote.strip(), "rating": 5}]})
        out = self.dir / "long.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(quote.strip(),
                      out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# CSV input
# ---------------------------------------------------------------------------

class CsvTests(TempDirTest):
    def test_csv_sample_builds_with_hand_computed_aggregate(self):
        r = run(["preview", str(CSV_SAMPLE), "--json"], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["aggregate"], 4.7)  # 14/3

    def test_csv_empty_rating_is_a_warning_not_an_error(self):
        path = self.write_text(
            "name,quote,rating\nA,Nice work.,\n", "in.csv")
        r = run(["preview", str(path)], self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("missing rating", r.stdout)

    def test_csv_extra_columns_ignored(self):
        path = self.write_text(
            "name,quote,rating,internal_id\nA,Good.,5,XYZ\n",
            "in.csv")
        r = run(["preview", str(path)], self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_csv_quoted_comma_in_quote(self):
        path = self.write_text(
            'name,quote,rating\nA,"Fast, friendly, fair.",5\n',
            "in.csv")
        r = run(["preview", str(path), "--json"], self.dir)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["testimonials"][0]["quote"],
                         "Fast, friendly, fair.")

    def test_csv_missing_quote_column(self):
        path = self.write_text("name,role\nA,B\n", "in.csv")
        r = run(["build", str(path)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("'quote' column", r.stdout)

    def test_csv_missing_name_column(self):
        path = self.write_text("quote,role\nQ,B\n", "in.csv")
        r = run(["build", str(path)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("'name' column", r.stdout)

    def test_csv_header_without_rows(self):
        path = self.write_text("name,quote,rating\n", "in.csv")
        r = run(["build", str(path)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no testimonial rows", r.stdout)

    def test_csv_bad_rating_names_the_row(self):
        path = self.write_text(
            "name,quote,rating\nA,Good.,five\n", "in.csv")
        r = run(["build", str(path)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("row[0]", r.stdout)
        self.assertIn("'rating'", r.stdout)


# ---------------------------------------------------------------------------
# errors: clean exit 2, naming the field, nothing written
# ---------------------------------------------------------------------------

class ErrorTests(TempDirTest):
    def expect_error(self, obj, *fragments, name="input.json"):
        path = self.write_input(obj, name)
        out = self.dir / "should-not-exist.html"
        r = run(["build", str(path), "-o", str(out)], self.dir)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(out.exists())
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        for fragment in fragments:
            self.assertIn(fragment, r.stdout)
        return r

    def test_rating_zero(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "quote": "q", "rating": 0}]),
            "'rating'", "from 1 to 5")

    def test_rating_six(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "quote": "q", "rating": 6}]),
            "'rating'", "from 1 to 5")

    def test_rating_word(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "quote": "q", "rating": "five"}]),
            "'rating'")

    def test_rating_float(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "quote": "q", "rating": 4.5}]),
            "'rating'")

    def test_rating_bool(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "quote": "q", "rating": True}]),
            "'rating'")

    def test_rating_string_number_is_accepted(self):
        path = self.write_input({"testimonials": [
            {"name": "A", "quote": "q", "rating": "4"}]})
        r = run(["preview", str(path), "--json"], self.dir)
        self.assertEqual(json.loads(r.stdout)["aggregate"], 4.0)

    def test_empty_quote(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "quote": "", "rating": 5}]),
            "'quote'", "must not be empty")

    def test_whitespace_only_quote(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "quote": "   ", "rating": 5}]),
            "'quote'")

    def test_missing_name(self):
        self.expect_error(self.base(testimonials=[
            {"quote": "q", "rating": 5}]), "'name'")

    def test_missing_quote(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "rating": 5}]), "'quote'")

    def test_empty_testimonials_list(self):
        self.expect_error({"testimonials": []}, "non-empty")

    def test_entry_not_an_object(self):
        self.expect_error({"testimonials": ["just a string"]},
                          "must be an object")

    def test_bad_date_format(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "quote": "q", "rating": 5,
             "date": "14/09/2026"}]), "'date'", "YYYY-MM-DD")

    def test_impossible_date(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "quote": "q", "rating": 5,
             "date": "2026-02-30"}]), "'date'", "not a real date")

    def test_source_javascript_scheme_refused(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "quote": "q", "rating": 5,
             "source": "javascript:alert(1)"}]), "source")

    def test_source_without_scheme_refused(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "quote": "q", "rating": 5,
             "source": "example.org/review"}]), "source")

    def test_avatar_data_scheme_refused(self):
        self.expect_error(self.base(testimonials=[
            {"name": "A", "quote": "q", "rating": 5,
             "avatar": "data:image/png;base64,AAAA"}]), "avatar")

    def test_logo_javascript_scheme_refused(self):
        self.expect_error(self.base(logo="javascript:alert(1)"),
                          "logo")

    def test_bad_accent(self):
        self.expect_error(self.base(theme={"accent": "red"}),
                          "theme.accent")

    def test_bad_mode(self):
        self.expect_error(self.base(theme={"mode": "sepia"}),
                          "theme.mode")

    def test_object_without_testimonials_key(self):
        self.expect_error({"business": "X"}, "'testimonials'")

    def test_top_level_scalar(self):
        path = self.write_text("42", "scalar.json")
        r = run(["build", str(path)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("top level", r.stdout)

    def test_malformed_json(self):
        path = self.write_text("[1, 2", "broken.json")
        r = run(["build", str(path)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not valid JSON", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def test_malformed_json_error_shape_with_json_flag(self):
        path = self.write_text("{oops", "broken.json")
        r = run(["build", str(path), "--json"], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(list(json.loads(r.stdout)), ["error"])
        self.assertNotIn("Traceback", r.stderr)

    def test_empty_file(self):
        path = self.write_text("", "empty.json")
        r = run(["build", str(path)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("empty file", r.stdout)

    def test_missing_file(self):
        r = run(["build", str(self.dir / "nope.json")], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("cannot read", r.stdout)

    def test_unknown_extension(self):
        path = self.write_text("name,quote\nA,q\n", "in.txt")
        r = run(["build", str(path)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn(".json or .csv", r.stdout)

    def test_unwritable_output(self):
        path = self.write_input(self.base())
        r = run(["build", str(path), "-o", str(self.dir)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("cannot write", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def test_argparse_error_is_json_in_json_mode(self):
        r = run(["build", "--json"], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(list(json.loads(r.stdout)), ["error"])

    def test_argparse_error_is_text_without_json(self):
        r = run(["build"], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stderr)


if __name__ == "__main__":
    unittest.main()
