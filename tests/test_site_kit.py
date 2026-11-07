#!/usr/bin/env python3
"""Tests for the site-kit dispatcher and the combined
launch-check run. Stdlib unittest only, temp dirs only.

Run from the pack root:
    python3 -m unittest discover -s tests -v

The five module engines carry their own ported suites
(test_site_audit.py, test_compliance_pages.py,
test_widget_kit.py, test_link_page_kit.py,
test_wall_of_love.py — the source tools' suites,
unchanged except each suite's examples paths). This
file tests only what is new: routing, the JSON/error
contract at the suite level, launch-check's discovery,
skip honesty and verdict math, read-only behaviour,
and determinism.

The fixtures are built by examples/make_fixture.py.
Every expectation is stated from the fixture's
construction (see that file's docstring), not copied
from the tool's output: the faulty folder plants
exactly one fault per module (the <title> removed ->
site-audit title-missing, 1 error 0 warnings; the
profile's retention fact removed -> compliance-pages
exactly 1 gap; a countdown target in 2020 ->
widget-kit exactly 1 warning; the first link
duplicated -> link-page-kit exactly 1 warning; the
same quote twice -> wall-of-love exactly 1 warning),
and the clean folder's inputs are the modules' own
proven samples, each pinned clean by its ported
suite.
"""

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parent.parent
SRC = PACK_ROOT / "src"
EXAMPLES = PACK_ROOT / "examples"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(EXAMPLES))

import site_kit as sk  # noqa: E402
import make_fixture  # noqa: E402
import site_audit  # noqa: E402

MODULE_NAMES = ["site-audit", "compliance-pages",
                "widget-kit", "link-page-kit",
                "wall-of-love"]


def run_cli(argv):
    """Run the dispatcher in-process; return
    (exit_code, stdout_text)."""
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            code = sk.main(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
    return code, buf.getvalue()


def tree_hashes(root):
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


class FixtureCase(unittest.TestCase):
    """Base: a temp dir holding both fixtures."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.clean = make_fixture.build_clean(base / "clean")
        self.faulty = make_fixture.build_faulty(
            base / "faulty")


class TestRouting(unittest.TestCase):

    def test_no_args_prints_help_exit_0(self):
        code, out = run_cli([])
        self.assertEqual(code, 0)
        self.assertIn("usage: site-kit", out)
        self.assertIn("launch-check", out)

    def test_version(self):
        code, out = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "site-kit v1.0.0")

    def test_unknown_command_text(self):
        code, out = run_cli(["bogus"])
        self.assertEqual(code, 2)
        self.assertIn("unknown command: bogus", out)

    def test_unknown_command_json(self):
        code, out = run_cli(["bogus", "--json"])
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertIn("error", payload)
        self.assertIn("bogus", payload["error"])

    def test_module_routing_matches_direct_call(self):
        target = str(EXAMPLES / "site-audit" / "faulty-site")
        via_suite, out_suite = run_cli(
            ["site-audit", "audit", target, "--json"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            direct = site_audit.main(
                ["audit", target, "--json"])
        self.assertEqual(via_suite, direct)
        self.assertEqual(out_suite, buf.getvalue())
        self.assertEqual(
            json.loads(out_suite)["summary"]["errors"], 5)

    def test_launch_check_usage_error_is_json(self):
        code, out = run_cli(["launch-check", "--json"])
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(out))

    def test_every_module_routes(self):
        ex = EXAMPLES
        code, out = run_cli(
            ["compliance-pages", "check", "--profile",
             str(ex / "compliance-pages"
                 / "sample-site.json"), "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["complete"])
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run_cli(
                ["widget-kit", "make", "--config",
                 str(ex / "widget-kit" / "widgets.json"),
                 "--out", tmp, "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(
                len(json.loads(out)["fragments"]), 4)
        code, out = run_cli(
            ["link-page-kit", "preview",
             str(ex / "link-page-kit"
                 / "sample-config.json"), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["warnings"], [])
        code, out = run_cli(
            ["wall-of-love", "preview",
             str(ex / "wall-of-love"
                 / "sample-testimonials.csv"), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["count"], 3)


class TestLaunchCheckInputs(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_missing_folder_text(self):
        code, out = run_cli(
            ["launch-check", str(self.base / "nope")])
        self.assertEqual(code, 2)
        self.assertIn("ERROR: no such folder", out)

    def test_missing_folder_json(self):
        code, out = run_cli(
            ["launch-check", str(self.base / "nope"),
             "--json"])
        self.assertEqual(code, 2)
        self.assertIn("no such folder",
                      json.loads(out)["error"])

    def test_file_not_folder(self):
        f = self.base / "a-file.txt"
        f.write_text("x")
        code, out = run_cli(
            ["launch-check", str(f), "--json"])
        self.assertEqual(code, 2)
        self.assertIn("not a folder",
                      json.loads(out)["error"])


class TestLaunchCheckClean(FixtureCase):

    def test_clean_json_ready(self):
        code, out = run_cli(
            ["launch-check", str(self.clean), "--json"])
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["tool"], "site-kit")
        self.assertEqual(d["command"], "launch-check")
        self.assertEqual(d["verdict"], "READY")
        self.assertTrue(d["ready"])
        self.assertEqual(d["summary"], {
            "modules_run": 5, "modules_skipped": 0,
            "clean_modules": 5, "finding_modules": 0,
            "skipped": []})
        for name in MODULE_NAMES:
            self.assertIsNotNone(d["inputs"][name], name)
            self.assertEqual(
                d["modules"][name]["exit_code"], 0, name)
        self.assertIn("not legal advice", d["disclaimer"])

    def test_clean_widget_section_records_trial_render(self):
        code, out = run_cli(
            ["launch-check", str(self.clean), "--json"])
        d = json.loads(out)
        section = d["modules"]["widget-kit"]
        self.assertEqual(len(section["fragments"]), 4)
        self.assertIn("temporary directory",
                      section["output_note"])
        self.assertEqual(section["warnings"], [])

    def test_clean_text_ready(self):
        code, out = run_cli(["launch-check", str(self.clean)])
        self.assertEqual(code, 0)
        self.assertIn("VERDICT: READY", out)
        for name in MODULE_NAMES:
            self.assertIn(f"===== {name}", out)
        self.assertIn("trial-rendered", out)


class TestLaunchCheckFaulty(FixtureCase):

    def test_faulty_json_not_ready(self):
        code, out = run_cli(
            ["launch-check", str(self.faulty), "--json"])
        self.assertEqual(code, 1)
        d = json.loads(out)
        self.assertEqual(d["verdict"], "NOT READY")
        self.assertFalse(d["ready"])
        self.assertEqual(d["summary"]["modules_run"], 5)
        self.assertEqual(d["summary"]["clean_modules"], 0)
        self.assertEqual(d["summary"]["finding_modules"], 5)

    def test_faulty_site_audit_fault_is_the_plant(self):
        _code, out = run_cli(
            ["launch-check", str(self.faulty), "--json"])
        section = json.loads(out)["modules"]["site-audit"]
        self.assertEqual(section["summary"]["errors"], 1)
        self.assertEqual(section["summary"]["warnings"], 0)
        self.assertEqual(
            [f["check"] for f in section["findings"]],
            ["title-missing"])

    def test_faulty_compliance_fault_is_the_plant(self):
        _code, out = run_cli(
            ["launch-check", str(self.faulty), "--json"])
        section = json.loads(
            out)["modules"]["compliance-pages"]
        self.assertFalse(section["complete"])
        self.assertEqual(
            [g["field"] for g in section["gaps"]],
            ["retention"])
        self.assertEqual(section["contradictions"], [])

    def test_faulty_widget_fault_is_the_plant(self):
        _code, out = run_cli(
            ["launch-check", str(self.faulty), "--json"])
        section = json.loads(out)["modules"]["widget-kit"]
        self.assertEqual(len(section["warnings"]), 1)
        self.assertIn("already in the past",
                      section["warnings"][0])

    def test_faulty_link_fault_is_the_plant(self):
        _code, out = run_cli(
            ["launch-check", str(self.faulty), "--json"])
        section = json.loads(out)["modules"]["link-page-kit"]
        self.assertEqual(len(section["warnings"]), 1)
        self.assertIn("duplicate URL",
                      section["warnings"][0])

    def test_faulty_wall_fault_is_the_plant(self):
        _code, out = run_cli(
            ["launch-check", str(self.faulty), "--json"])
        section = json.loads(out)["modules"]["wall-of-love"]
        self.assertEqual(len(section["warnings"]), 1)
        self.assertIn("duplicate quote",
                      section["warnings"][0])

    def test_faulty_text_names_all_five(self):
        code, out = run_cli(
            ["launch-check", str(self.faulty)])
        self.assertEqual(code, 1)
        self.assertIn("VERDICT: NOT READY — findings in",
                      out)
        for name in MODULE_NAMES:
            self.assertIn(name, out)


class TestSkipHonesty(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_empty_folder_not_ready(self):
        empty = self.base / "empty"
        empty.mkdir()
        code, out = run_cli(
            ["launch-check", str(empty), "--json"])
        self.assertEqual(code, 1)
        d = json.loads(out)
        self.assertEqual(d["verdict"], "NOT READY")
        self.assertEqual(d["summary"]["modules_run"], 0)
        self.assertEqual(d["summary"]["skipped"],
                         MODULE_NAMES)
        for name in MODULE_NAMES:
            section = d["modules"][name]
            self.assertEqual(section["status"], "skipped")
            self.assertIsNone(section["clean"])
            self.assertTrue(section["reason"])
            self.assertIsNone(d["inputs"][name])

    def test_empty_folder_text_says_nothing_verified(self):
        empty = self.base / "empty"
        empty.mkdir()
        code, out = run_cli(["launch-check", str(empty)])
        self.assertEqual(code, 1)
        self.assertIn("no module had inputs", out)

    def test_pages_only_ready_with_skips_named(self):
        folder = self.base / "pages-only"
        folder.mkdir()
        clean = make_fixture.build_clean(self.base / "src")
        (folder / "index.html").write_bytes(
            (clean / "index.html").read_bytes())
        code, out = run_cli(
            ["launch-check", str(folder), "--json"])
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["verdict"], "READY")
        self.assertEqual(d["summary"]["modules_run"], 1)
        self.assertEqual(
            d["summary"]["skipped"],
            ["compliance-pages", "widget-kit",
             "link-page-kit", "wall-of-love"])
        code2, text = run_cli(["launch-check", str(folder)])
        self.assertEqual(code2, 0)
        self.assertIn("skipped, NOT checked", text)

    def test_module_error_is_findings_not_ready(self):
        folder = self.base / "bad-widgets"
        folder.mkdir()
        (folder / "widgets.json").write_bytes(
            (EXAMPLES / "widget-kit"
             / "bad-config.json").read_bytes())
        code, out = run_cli(
            ["launch-check", str(folder), "--json"])
        self.assertEqual(code, 1)
        d = json.loads(out)
        self.assertEqual(d["verdict"], "NOT READY")
        section = d["modules"]["widget-kit"]
        self.assertIn("error", section)
        self.assertEqual(d["summary"]["finding_modules"], 1)


class TestDiscovery(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_wall_json_preferred_over_csv(self):
        folder = self.base / "wall-both"
        folder.mkdir()
        (folder / "aaa.csv").write_text(
            "name,quote\nAna Ruiz,Great boots.\n")
        (folder / "zzz.json").write_bytes(
            (EXAMPLES / "wall-of-love"
             / "sample-testimonials.json").read_bytes())
        _code, out = run_cli(
            ["launch-check", str(folder), "--json"])
        d = json.loads(out)
        self.assertTrue(
            d["inputs"]["wall-of-love"].endswith("zzz.json"))
        self.assertEqual(
            d["modules"]["wall-of-love"]["count"], 6)

    def test_wall_csv_discovered(self):
        folder = self.base / "wall-csv"
        folder.mkdir()
        (folder / "quotes.csv").write_bytes(
            (EXAMPLES / "wall-of-love"
             / "sample-testimonials.csv").read_bytes())
        _code, out = run_cli(
            ["launch-check", str(folder), "--json"])
        d = json.loads(out)
        self.assertTrue(
            d["inputs"]["wall-of-love"].endswith(
                "quotes.csv"))
        self.assertEqual(
            d["modules"]["wall-of-love"]["count"], 3)

    def test_uppercase_suffix_discovered(self):
        folder = self.base / "upper"
        folder.mkdir()
        (folder / "WIDGETS.JSON").write_bytes(
            (EXAMPLES / "widget-kit"
             / "widgets.json").read_bytes())
        (folder / "proof-entries.json").write_bytes(
            (EXAMPLES / "widget-kit"
             / "proof-entries.json").read_bytes())
        _code, out = run_cli(
            ["launch-check", str(folder), "--json"])
        d = json.loads(out)
        self.assertIsNotNone(d["inputs"]["widget-kit"])
        self.assertEqual(
            d["modules"]["widget-kit"]["exit_code"], 0)

    def test_nested_inputs_discovered(self):
        folder = self.base / "nested"
        sub = folder / "data"
        sub.mkdir(parents=True)
        (sub / "profile.json").write_bytes(
            (EXAMPLES / "compliance-pages"
             / "sample-site.json").read_bytes())
        (sub / "quotes.csv").write_bytes(
            (EXAMPLES / "wall-of-love"
             / "sample-testimonials.csv").read_bytes())
        _code, out = run_cli(
            ["launch-check", str(folder), "--json"])
        d = json.loads(out)
        self.assertEqual(
            d["summary"]["modules_run"], 2)
        self.assertTrue(
            d["inputs"]["compliance-pages"].endswith(
                "data/profile.json"))
        self.assertTrue(
            d["inputs"]["wall-of-love"].endswith(
                "data/quotes.csv"))

    def test_as_of_passed_to_compliance(self):
        folder = self.base / "as-of"
        folder.mkdir()
        profile = json.loads(
            (EXAMPLES / "compliance-pages"
             / "sample-site.json").read_text())
        del profile["as_of"]
        (folder / "profile.json").write_text(
            json.dumps(profile))
        _c, out = run_cli(
            ["launch-check", str(folder), "--json"])
        section = json.loads(
            out)["modules"]["compliance-pages"]
        self.assertFalse(section["complete"])
        self.assertIn("as_of",
                      [g["field"] for g in section["gaps"]])
        _c, out = run_cli(
            ["launch-check", str(folder),
             "--as-of", "2026-04-01", "--json"])
        section = json.loads(
            out)["modules"]["compliance-pages"]
        self.assertTrue(section["complete"])


class TestReadOnlyAndDeterminism(FixtureCase):

    def test_launch_check_writes_nothing(self):
        for fixture in (self.clean, self.faulty):
            before = tree_hashes(fixture)
            run_cli(["launch-check", str(fixture), "--json"])
            run_cli(["launch-check", str(fixture)])
            self.assertEqual(tree_hashes(fixture), before)

    def test_json_runs_byte_identical(self):
        _c1, out1 = run_cli(
            ["launch-check", str(self.clean), "--json"])
        _c2, out2 = run_cli(
            ["launch-check", str(self.clean), "--json"])
        self.assertEqual(out1, out2)

    def test_text_runs_byte_identical(self):
        _c1, out1 = run_cli(["launch-check", str(self.clean)])
        _c2, out2 = run_cli(["launch-check", str(self.clean)])
        self.assertEqual(out1, out2)

    def test_faulty_json_runs_byte_identical(self):
        _c1, out1 = run_cli(
            ["launch-check", str(self.faulty), "--json"])
        _c2, out2 = run_cli(
            ["launch-check", str(self.faulty), "--json"])
        self.assertEqual(out1, out2)


if __name__ == "__main__":
    unittest.main()
