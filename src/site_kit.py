#!/usr/bin/env python3
"""site-kit — is this static site ready to launch?

One suite, five tools that used to be five separate
tools, merged (FLEET-AUDIT-2026-11-04, flagship B4)
without changing a single check or generator:

    site-kit site-audit audit DIR ...
        Pre-launch audit of a static site's deploy
        folder: titles, meta, headings, alt text,
        internal links, JSON-LD, sitemap and robots —
        a prioritised plain-language fix list.
    site-kit compliance-pages make|check ...
        Privacy, terms and cookie pages plus a
        self-hosted consent banner, generated from one
        site-profile JSON — templates that state only
        the facts the profile gives them.
    site-kit widget-kit make ...
        The four boring website widgets — FAQ (with
        matching JSON-LD), pricing, countdown, social
        proof — as static fragments you own.
    site-kit link-page-kit build|preview ...
        One config file in, one self-contained
        link-in-bio page out: no trackers, no monthly
        fee, no lock-in.
    site-kit wall-of-love build|preview ...
        A testimonials file in, one self-contained
        wall-of-love page out, with schema.org JSON-LD
        generated from the same data.
    site-kit launch-check DIR
        Every module that has something to check in
        one site folder, as a single launch-readiness
        receipt — read-only (see below).

Every module keeps its source tool's checks, generators,
verdict words and honesty limits — the engines are
ported, not rewritten. launch-check writes NOTHING into
the folder it checks: audits and previews are read-only
by design, compliance-pages runs its `check` (never
`make`), and widget-kit — whose only mode renders
fragments — renders into a temporary directory that is
discarded, so the run validates the config and counts
the fragments without touching the site. A module with
no discoverable input reports itself skipped with the
reason; skipped is never counted as passed. A READY
verdict means every module that ran reported no errors
under its own rules — never that the site is legally
compliant (compliance-pages generates templates, not
legal advice) or that any platform will accept it.

(stdlib only, local only, no network.)
"""

import argparse
import csv
import io
import json
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import compliance_pages
import link_page_kit
import site_audit
import wall_of_love
import widget_kit

__version__ = "1.0.0"

TOOL = "site-kit"

MODULES = {
    "site-audit": site_audit,
    "compliance-pages": compliance_pages,
    "widget-kit": widget_kit,
    "link-page-kit": link_page_kit,
    "wall-of-love": wall_of_love,
}

_MODULE_BLURBS = {
    "site-audit": "the deploy folder vs the pre-launch "
                  "audit checks",
    "compliance-pages": "the site profile vs the facts "
                        "the legal pages need",
    "widget-kit": "the widgets config, validated by a "
                  "trial render",
    "link-page-kit": "the link-page config vs the "
                     "structural checks",
    "wall-of-love": "the testimonials file vs the wall "
                    "checks",
}

DISCLAIMER = (
    "site-kit is a local checking and generation aid. "
    "launch-check writes nothing into the folder it "
    "checks (widget fragments are trial-rendered into a "
    "temporary directory and discarded). A READY verdict "
    "means every module that ran reported clean under "
    "its own rules — never that the site is legally "
    "compliant or will pass any platform or app-store "
    "review. compliance-pages generates templates from "
    "the facts a profile states; they are not legal "
    "advice — have them reviewed before relying on "
    "them.")

HELP = """usage: site-kit <command> [args...]

Is this static site ready to launch? Five tools, one
suite. Every command accepts --json (one JSON object,
exit 0 pass / 1 findings / 2 usage or input error).

commands:
  site-audit      audit DIR ...
                                 pre-launch audit of the
                                 deploy folder: titles,
                                 meta, links, JSON-LD,
                                 sitemap, robots
  compliance-pages make|check ...
                                 privacy / terms / cookie
                                 pages + consent banner
                                 from one profile JSON
  widget-kit      make ...
                                 FAQ, pricing, countdown
                                 and social-proof fragments
                                 from one config JSON
  link-page-kit   build|preview ...
                                 one self-contained
                                 link-in-bio page from one
                                 config JSON
  wall-of-love    build|preview ...
                                 one testimonials wall
                                 page (JSON-LD included)
                                 from a JSON/CSV file
  launch-check    DIR            every module over one
                                 site folder, as a single
                                 launch-readiness receipt
                                 (read-only)

Run `site-kit <command> --help` for a module's own
options. Read-only and local: launch-check reads the
folder and writes nothing into it. A READY verdict is
a statement about the modules' own checks, never about
legal compliance — see the disclaimer in every report."""


class ToolError(Exception):
    """A user-facing failure: printed without a traceback,
    exit code 2 (same convention as the five modules)."""


class _JsonAwareParser(argparse.ArgumentParser):
    """ArgumentParser that reports usage errors as JSON in
    --json mode ({"error": ...} on stdout, same exit code 2).
    The flag lives on the class so subparsers share it."""

    json_mode = False

    def error(self, message):
        if self.json_mode:
            print(json.dumps({"error": message}))
            self.exit(2)
        super().error(message)


# ---------------------------------------------------------------------------
# Combined launch-check run
# ---------------------------------------------------------------------------

def _iter_files(d, suffix):
    """Files under DIR with the given suffix, in sorted,
    deterministic order; .git is never entered. The
    suffix match is case-insensitive."""
    out = []
    for p in sorted(d.rglob("*")):
        if ".git" in p.relative_to(d).parts:
            continue
        if p.is_file() and p.name.lower().endswith(suffix):
            out.append(p)
    return out


def _load_json(path):
    """Parse a JSON file (UTF-8, BOM tolerated); None when
    it does not parse."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _normalized_header(path):
    """The CSV header as a set of normalized names
    (non-alphanumerics stripped, lowercased), or None
    when the file has no readable header row."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.reader(fh):
                if row:
                    return {"".join(ch for ch in cell.lower()
                                    if ch.isalnum())
                            for cell in row}
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    return None


def _first_json(d, claimed, predicate):
    """The first .json under DIR (sorted order, not
    already claimed by another module) that parses and
    satisfies predicate(data). Returns (path, data) or
    (None, None)."""
    for p in _iter_files(d, ".json"):
        if p in claimed:
            continue
        data = _load_json(p)
        if data is not None and predicate(data):
            return p, data
    return None, None


def _is_compliance_profile(data):
    """A compliance-pages profile: an object carrying a
    business object and a pages list naming at least one
    of the three generatable pages."""
    return (isinstance(data, dict)
            and isinstance(data.get("business"), dict)
            and isinstance(data.get("pages"), list)
            and bool({str(x) for x in data["pages"]}
                     & {"privacy", "terms", "cookies"}))


def _is_widget_config(data):
    """A widget-kit config: an object carrying a widgets
    list."""
    return (isinstance(data, dict)
            and isinstance(data.get("widgets"), list))


def _is_link_config(data):
    """A link-page-kit config: an object carrying a name
    and a links list."""
    return (isinstance(data, dict)
            and isinstance(data.get("name"), str)
            and isinstance(data.get("links"), list))


def _is_wall_json(data):
    """A wall-of-love testimonials file: an object
    carrying a testimonials list."""
    return (isinstance(data, dict)
            and isinstance(data.get("testimonials"), list))


def _discover_wall(d, claimed):
    """The testimonials input wall-of-love is pointed at
    during a combined run: a .json carrying a
    testimonials list, else the first .csv whose header
    names both name and quote columns. Returns None
    when neither qualifies."""
    path, _data = _first_json(d, claimed, _is_wall_json)
    if path is not None:
        return path
    for p in _iter_files(d, ".csv"):
        if p in claimed:
            continue
        header = _normalized_header(p)
        if header and {"name", "quote"} <= header:
            return p
    return None


def _run_capture(module_main, args):
    """Run a module's own CLI in-process and capture what it
    prints. Returns (exit_code, stdout_text). The module's
    main() may raise SystemExit (argparse errors, --help);
    its code is honoured either way."""
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            code = module_main(args)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
    return code, buf.getvalue()


def _run_json_section(module_main, args):
    """Run a module in --json mode; its section is the exact
    object the module itself prints, plus its exit code."""
    code, text = _run_capture(module_main, args)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {"error": "module produced no JSON output",
                   "raw": text.strip()[:500]}
    payload = dict(payload)
    payload["exit_code"] = code
    return payload


def _skipped_section(name, reason):
    section = {"tool": name, "status": "skipped",
               "reason": reason, "clean": None,
               "exit_code": None}
    module = MODULES[name]
    version = getattr(module, "__version__", None)
    if version is not None:
        section["version"] = version
    return section


def _section_clean(section):
    """A run section is clean exactly when the module's
    own run exited 0; an error payload is never clean; a
    skipped section is neither (None)."""
    if section.get("status") == "skipped":
        return None
    if "error" in section:
        return False
    return section.get("exit_code") == 0


def _has_pages(d):
    """True when the folder holds at least one HTML page
    site-audit can audit."""
    return bool(_iter_files(d, ".html")
                or _iter_files(d, ".htm"))


def launch_check(d, as_of=None, want_text=False):
    """Run every module that has an input in the site
    folder DIR. Returns (payload, sections_text) — the
    payload is the combined receipt (JSON mode);
    sections_text holds each run module's own captured
    text output (text mode only; the modules are
    deterministic, so the second run is identical).

    Read-only: site-audit audits, compliance-pages
    checks, link-page-kit and wall-of-love preview, and
    widget-kit renders into a temporary directory that
    is discarded when the run ends. Nothing is written
    into DIR."""
    sections_json = {}
    sections_text = {}
    inputs = {name: None for name in MODULES}
    claimed = set()

    def _text(name, module_main, args):
        if not want_text:
            return (None, None)
        return _run_capture(module_main, args)

    # The widget trial render goes to a scratch folder
    # with a FIXED name under the system temp dir —
    # created fresh and removed when the run ends — so
    # the combined receipt stays byte-identical across
    # runs (a random temp path would leak into
    # widget-kit's own reported output_dir).
    scratch = Path(tempfile.gettempdir()) / \
        "site-kit-launch-check"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    try:
        # site-audit: the folder itself, when it holds
        # pages.
        if _has_pages(d):
            inputs["site-audit"] = str(d)
            args = ["audit", str(d)]
            sections_json["site-audit"] = _run_json_section(
                site_audit.main, args + ["--json"])
            sections_text["site-audit"] = _text(
                "site-audit", site_audit.main, args)
        else:
            sections_json["site-audit"] = _skipped_section(
                "site-audit",
                "no HTML pages (.html/.htm) found under "
                "the folder")
            sections_text["site-audit"] = (None, None)

        # compliance-pages: the discovered site profile,
        # checked (never generated) by the combined run.
        profile, _ = _first_json(d, claimed,
                                 _is_compliance_profile)
        if profile is not None:
            claimed.add(profile)
            inputs["compliance-pages"] = str(profile)
            args = ["check", "--profile", str(profile)]
            if as_of is not None:
                args += ["--as-of", as_of]
            sections_json["compliance-pages"] = \
                _run_json_section(compliance_pages.main,
                                  args + ["--json"])
            sections_text["compliance-pages"] = _text(
                "compliance-pages", compliance_pages.main,
                args)
        else:
            sections_json["compliance-pages"] = \
                _skipped_section(
                    "compliance-pages",
                    "no site-profile JSON found under the "
                    "folder (looked for a .json carrying a "
                    "business object and a pages list "
                    "naming privacy, terms or cookies)")
            sections_text["compliance-pages"] = (None, None)

        # widget-kit: the discovered widgets config,
        # trial-rendered into the scratch folder.
        config, _ = _first_json(d, claimed, _is_widget_config)
        if config is not None:
            claimed.add(config)
            inputs["widget-kit"] = str(config)
            args = ["make", "--config", str(config),
                    "--out", str(Path(scratch) / "widgets")]
            section = _run_json_section(widget_kit.main,
                                        args + ["--json"])
            section["output_note"] = (
                "fragments trial-rendered into a temporary "
                "directory for validation and discarded — "
                "nothing was written into the site folder; "
                "run `site-kit widget-kit make` to generate "
                "them for real")
            sections_json["widget-kit"] = section
            sections_text["widget-kit"] = _text(
                "widget-kit", widget_kit.main, args)
        else:
            sections_json["widget-kit"] = _skipped_section(
                "widget-kit",
                "no widgets config found under the folder "
                "(looked for a .json carrying a widgets "
                "list)")
            sections_text["widget-kit"] = (None, None)

        # link-page-kit: the discovered link-page config,
        # previewed (build writes the page; the combined
        # run never does).
        config, _ = _first_json(d, claimed, _is_link_config)
        if config is not None:
            claimed.add(config)
            inputs["link-page-kit"] = str(config)
            args = ["preview", str(config)]
            sections_json["link-page-kit"] = \
                _run_json_section(link_page_kit.main,
                                  args + ["--json"])
            sections_text["link-page-kit"] = _text(
                "link-page-kit", link_page_kit.main, args)
        else:
            sections_json["link-page-kit"] = _skipped_section(
                "link-page-kit",
                "no link-page config found under the folder "
                "(looked for a .json carrying a name and a "
                "links list)")
            sections_text["link-page-kit"] = (None, None)

        # wall-of-love: the discovered testimonials file,
        # previewed.
        wall = _discover_wall(d, claimed)
        if wall is not None:
            claimed.add(wall)
            inputs["wall-of-love"] = str(wall)
            args = ["preview", str(wall)]
            sections_json["wall-of-love"] = \
                _run_json_section(wall_of_love.main,
                                  args + ["--json"])
            sections_text["wall-of-love"] = _text(
                "wall-of-love", wall_of_love.main, args)
        else:
            sections_json["wall-of-love"] = _skipped_section(
                "wall-of-love",
                "no testimonials file found under the "
                "folder (looked for a .json carrying a "
                "testimonials list, or a .csv whose "
                "header names name and quote)")
            sections_text["wall-of-love"] = (None, None)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    run = [n for n, s in sections_json.items()
           if s.get("status") != "skipped"]
    skipped = [n for n, s in sections_json.items()
               if s.get("status") == "skipped"]
    clean_modules = [n for n in run
                     if _section_clean(sections_json[n]) is True]
    finding_modules = [n for n in run
                       if _section_clean(sections_json[n])
                       is False]
    ready = bool(run) and not finding_modules
    payload = {
        "tool": TOOL, "version": __version__,
        "command": "launch-check", "dir": str(d),
        "inputs": inputs,
        "modules": sections_json,
        "summary": {
            "modules_run": len(run),
            "modules_skipped": len(skipped),
            "clean_modules": len(clean_modules),
            "finding_modules": len(finding_modules),
            "skipped": skipped,
        },
        "ready": ready,
        "verdict": "READY" if ready else "NOT READY",
        "disclaimer": DISCLAIMER,
    }
    return payload, sections_text


def cmd_launch_check(a):
    d = Path(a.dir)
    if not d.exists():
        raise ToolError(f"no such folder: {a.dir}")
    if not d.is_dir():
        raise ToolError(f"not a folder: {a.dir}")
    payload, sections_text = launch_check(
        d, as_of=a.as_of, want_text=not a.json)
    if a.json:
        print(json.dumps(payload, indent=2))
        return 0 if payload["ready"] else 1
    s = payload["summary"]
    print(f"{TOOL} v{__version__} — launch-check · "
          f"folder {d.name}")
    print(f"{s['modules_run']} module(s) run · "
          f"{s['clean_modules']} clean · "
          f"{s['finding_modules']} with findings · "
          f"{s['modules_skipped']} skipped")
    for name in MODULES:
        section = payload["modules"][name]
        print()
        print(f"===== {name} — {_MODULE_BLURBS[name]} =====")
        if section.get("status") == "skipped":
            print(f"SKIPPED — {section['reason']}")
            continue
        _code, text = sections_text[name]
        print(text.rstrip())
        if name == "widget-kit":
            print("(fragments above were trial-rendered "
                  "into a temporary directory and "
                  "discarded — nothing was written into "
                  "this folder)")
    print()
    if payload["ready"]:
        passed = [n for n, sec in payload["modules"].items()
                  if _section_clean(sec) is True]
        line = ("VERDICT: READY — every module that ran "
                "was clean (" + ", ".join(passed) + ")")
        if s["skipped"]:
            line += ("; skipped, NOT checked: "
                     + ", ".join(s["skipped"]))
        print(line + ". READY covers only the modules' "
              "own checks — it is never a statement of "
              "legal compliance or platform acceptance.")
    elif s["modules_run"] == 0:
        print("VERDICT: NOT READY — no module had inputs "
              "to check in this folder, so nothing was "
              "verified. A READY verdict requires at "
              "least one module to have run clean.")
    else:
        names = [n for n, sec in payload["modules"].items()
                 if _section_clean(sec) is False]
        print("VERDICT: NOT READY — findings in "
              + ", ".join(names)
              + " — fix each module's section above "
                "before launch.")
    print()
    print(DISCLAIMER)
    return 0 if payload["ready"] else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _launch_check_parser():
    ap = _JsonAwareParser(
        prog=f"{TOOL} launch-check",
        description="Run every module over one site "
                    "folder and print a single "
                    "launch-readiness receipt. Read-only: "
                    "nothing is written into the folder "
                    "(widget fragments are trial-rendered "
                    "into a temporary directory and "
                    "discarded).")
    ap.add_argument("dir", help="the site folder holding "
                                "the deploy pages and the "
                                "modules' config files")
    ap.add_argument("--as-of", default=None,
                    metavar="YYYY-MM-DD",
                    help="generation date passed to "
                         "compliance-pages' check (the "
                         "only module that takes one; the "
                         "other modules never read the "
                         "clock for their verdicts)")
    ap.add_argument("--json", action="store_true",
                    help="print one JSON object (with a "
                         "per-module section) instead of "
                         "text")
    return ap


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(HELP)
        return 0
    if argv[0] in ("-v", "--version"):
        print(f"{TOOL} v{__version__}")
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in MODULES:
        return MODULES[cmd].main(rest)
    if cmd == "launch-check":
        _JsonAwareParser.json_mode = "--json" in rest
        ap = _launch_check_parser()
        a = ap.parse_args(rest)

        def fail(msg):
            if getattr(a, "json", False):
                print(json.dumps({"error": msg}))
            else:
                print(f"ERROR: {msg}")
            return 2

        try:
            return cmd_launch_check(a)
        except ToolError as exc:
            return fail(str(exc))
    if "--json" in argv:
        print(json.dumps(
            {"error": f"unknown command: {cmd} "
                      f"(expected one of: "
                      f"{', '.join(MODULES)}, launch-check)"}))
    else:
        print(f"ERROR: unknown command: {cmd}")
        print()
        print(HELP)
    return 2


if __name__ == "__main__":
    sys.exit(main())
