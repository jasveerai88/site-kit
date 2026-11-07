#!/usr/bin/env python3
"""link-page-kit — turn one config JSON file into a link-in-bio
page you own: one static HTML file, all CSS inline, no trackers,
no scripts, no subscription, no platform that can fold, shut down
or start charging rent on a list of links.

Linktree charges up to $288/yr, takes 9% seller fees and offers
a custom domain on no plan; Linkpop was discontinued, Koji and
Bento were folded. This tool is the answer to that: generate the
page once, host it anywhere — GitHub Pages, your own site, any
static host — and it stays yours, forever, for free.

Config (one JSON file):

  {
    "name": "Maya Chen",
    "bio": "Trail rider and host of The Kelowna Trailcast.",
    "avatar": "https://example.org/maya/avatar.jpg",
    "theme": {"accent": "#2e7d4f", "mode": "light"},
    "links": [
      {"label": "Watch on YouTube",
       "url": "https://youtube.com/@KelownaTrailcast",
       "note": "New video every Friday"},
      {"label": "Email me", "url": "mailto:maya@example.org"}
    ],
    "socials": [
      {"label": "TikTok", "url": "https://tiktok.com/@kelownatrailcast"}
    ]
  }

  name    required, non-empty string.
  bio     optional string, printed under the name.
  avatar  optional: an http(s) URL or a local path, REFERENCED
          (an <img src>), never embedded — the page stays one
          small file and the image can live beside it.
  theme   optional: {"accent": "#rrggbb" or "#rgb",
                     "mode": "light" (default) or "dark"}.
  links   required, at least one entry: {"label", "url",
          "note"?}. socials: same shape, optional.

Commands:
  build CONFIG [-o page.html] [--check-links]
            validate the config and write the page. Default
            output file is index.html in the current directory.
            Exit 0 = clean, 1 = built but with warnings
            (duplicate URLs), 2 = ERROR and nothing written.
  preview CONFIG [--check-links]
            print a summary without writing anything: the name,
            the links in order, the socials, the page weight in
            bytes, and the checks passed. Same exit codes.

URL rules (checked OFFLINE — this tool never fetches the
network, so it validates shape, never liveness):
  - scheme must be https, http, mailto or tel. javascript:,
    data:, file:, scheme-relative //host and scheme-less
    values are refused.
  - http(s) URLs need a host and no whitespace anywhere.
  - mailto: needs an address containing @; tel: needs digits.
  - duplicate URLs (after normalising scheme/host case and a
    trailing slash) are flagged as warnings, not errors: the
    page still builds, exit 1, and the warning names them.

Escaping: every user-supplied string is HTML-escaped before it
is written, in text and in attributes — a label containing
"<script>" renders as text, never as markup. The page contains
no <script> at all, and the only external references it makes
are the links, socials and avatar you configured — no fonts,
no CDN, no analytics, no requests of any other kind. System
font stack only, so the page is fast by construction.

Exit codes: 0 = ok · 1 = a finding (duplicate URLs) · 2 =
ERROR — clean message, never a traceback; with --json the
error is {"error": ...}. Every command takes --json: one JSON
object with the same facts and exit codes as the text view.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

__version__ = "0.1.0"
TOOL = "link-page-kit"

_ALLOWED_SCHEMES = ("https", "http", "mailto", "tel")
_ACCENT_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

_PALETTES = {
    "light": {"bg": "#fafafa", "fg": "#1b1b1b", "card": "#ffffff",
              "muted": "#5c5c5c"},
    "dark": {"bg": "#141414", "fg": "#f2f2f2", "card": "#1e1e1e",
             "muted": "#a8a8a8"},
}


class ToolError(Exception):
    """A clean, user-facing failure (printed as ERROR, exit 2)."""


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def _require_str(obj, field, label):
    """obj[field] must be a string; missing/None is an error naming
    the field. Returns the value."""
    if field not in obj or obj[field] is None:
        raise ToolError(f"{label}: missing required field {field!r}")
    if not isinstance(obj[field], str):
        raise ToolError(f"{label}: field {field!r} must be a string "
                        f"(got {obj[field]!r})")
    return obj[field]


def _require_nonempty_str(obj, field, label):
    value = _require_str(obj, field, label)
    if not value.strip():
        raise ToolError(f"{label}: field {field!r} must not be empty")
    return value


def check_url(url, label):
    """Validate one URL structurally (offline). Returns a short
    human description of the target for --check-links output.
    Raises ToolError naming the field on any problem."""
    if not isinstance(url, str):
        raise ToolError(f"{label}: must be a string (got {url!r})")
    if url != url.strip():
        raise ToolError(f"{label}: URL has leading or trailing "
                        f"whitespace: {url!r}")
    if any(ch.isspace() for ch in url):
        raise ToolError(f"{label}: URL contains whitespace: {url!r}")
    if url.startswith("//"):
        raise ToolError(f"{label}: URL is scheme-relative (no scheme): "
                        f"{url!r}")
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", url)
    if not m:
        raise ToolError(f"{label}: URL has no scheme: {url!r}")
    scheme = m.group(1).lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ToolError(f"{label}: scheme {scheme!r} is not allowed "
                        f"(allowed: https, http, mailto, tel): {url!r}")
    rest = url[m.end():]
    if scheme in ("https", "http"):
        host = urlsplit(url).netloc
        if not host:
            raise ToolError(f"{label}: {scheme} URL has no host: {url!r}")
        return f"scheme {scheme} · host {host.lower()}"
    if scheme == "mailto":
        address = rest.split("?", 1)[0]
        if "@" not in address or not address.strip("@"):
            raise ToolError(f"{label}: mailto: URL has no address: {url!r}")
        return f"scheme mailto · address {address}"
    digits = [ch for ch in rest if ch.isdigit()]
    if not digits:
        raise ToolError(f"{label}: tel: URL has no digits: {url!r}")
    return f"scheme tel · number {''.join(digits)}"


def normalize_url(url):
    """Canonical form for duplicate detection: scheme and host
    lowercased, one trailing slash on the path removed. mailto:
    and tel: targets are lowercased wholesale."""
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", url)
    scheme = m.group(1).lower()
    if scheme in ("mailto", "tel"):
        return url.lower()
    parts = urlsplit(url)
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return f"{scheme}://{parts.netloc.lower()}{path}" + (
        f"?{parts.query}" if parts.query else "")


def _validate_entry(entry, label):
    """One links/socials entry -> a cleaned dict. Errors name
    the entry's field."""
    if not isinstance(entry, dict):
        raise ToolError(f"{label}: each entry must be an object "
                        f"(got {entry!r})")
    label_text = _require_nonempty_str(entry, "label", label)
    url = _require_nonempty_str(entry, "url", label)
    detail = check_url(url, f"{label}.url")
    note = entry.get("note")
    if note is not None and not isinstance(note, str):
        raise ToolError(f"{label}: field 'note' must be a string "
                        f"(got {note!r})")
    return {"label": label_text, "url": url,
            "note": note if note else None, "detail": detail}


def _validate_theme(theme):
    """theme (optional object) -> (accent, mode, accent_custom)."""
    accent = "#2563eb"
    mode = "light"
    custom = False
    if theme is None:
        return accent, mode, custom
    if not isinstance(theme, dict):
        raise ToolError("theme: must be an object (got "
                        f"{theme!r})")
    if theme.get("accent") is not None:
        accent_raw = theme["accent"]
        if not isinstance(accent_raw, str) or \
                not _ACCENT_RE.match(accent_raw.strip()):
            raise ToolError("theme.accent: must be a hex colour "
                            f"#rgb or #rrggbb (got {accent_raw!r})")
        accent = accent_raw.strip().lower()
        custom = True
    if theme.get("mode") is not None:
        mode_raw = theme["mode"]
        if mode_raw not in ("light", "dark"):
            raise ToolError(f"theme.mode: must be 'light' or 'dark' "
                            f"(got {mode_raw!r})")
        mode = mode_raw
    return accent, mode, custom


def load_config(path):
    """Read and fully validate a config file. Returns
    (config, warnings) where warnings is a list of strings
    (duplicate URLs); hard problems raise ToolError."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"cannot read config file {path!r}: {exc}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"config file {path!r} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise ToolError(f"config file {path!r}: top level must be an "
                        f"object (got {type(data).__name__})")

    name = _require_nonempty_str(data, "name", "config")
    bio = data.get("bio")
    if bio is not None and not isinstance(bio, str):
        raise ToolError(f"config: field 'bio' must be a string "
                        f"(got {bio!r})")
    avatar = data.get("avatar")
    if avatar is not None:
        if not isinstance(avatar, str) or not avatar.strip():
            raise ToolError("config: field 'avatar' must be a "
                            "non-empty string")
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", avatar):
            scheme = avatar.split(":", 1)[0].lower()
            if scheme not in ("https", "http"):
                raise ToolError(f"config.avatar: scheme {scheme!r} is "
                                f"not allowed for an avatar (use an "
                                f"http(s) URL or a local path)")

    links_raw = data.get("links")
    if links_raw is None:
        raise ToolError("config: missing required field 'links'")
    if not isinstance(links_raw, list) or not links_raw:
        raise ToolError("config: field 'links' must be a non-empty "
                        "list")
    links = [_validate_entry(e, f"links[{i}]")
             for i, e in enumerate(links_raw)]

    socials = []
    socials_raw = data.get("socials")
    if socials_raw is not None:
        if not isinstance(socials_raw, list):
            raise ToolError("config: field 'socials' must be a list "
                            f"(got {socials_raw!r})")
        socials = [_validate_entry(e, f"socials[{i}]")
                   for i, e in enumerate(socials_raw)]

    accent, mode, accent_custom = _validate_theme(data.get("theme"))

    # duplicate detection across links + socials, normalised
    seen = {}
    warnings = []
    for kind, entries in (("links", links), ("socials", socials)):
        for i, entry in enumerate(entries):
            key = normalize_url(entry["url"])
            if key in seen:
                warnings.append(
                    f"duplicate URL: {entry['url']!r} ({kind}[{i}] "
                    f"'{entry['label']}') is the same target as "
                    f"{seen[key]}")
            else:
                seen[key] = f"{kind}[{i}] '{entry['label']}'"
    return {
        "name": name, "bio": bio, "avatar": avatar,
        "accent": accent, "mode": mode,
        "accent_custom": accent_custom,
        "links": links, "socials": socials,
    }, warnings


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def render_page(cfg):
    """Config -> the complete HTML page (a string). All CSS is
    inline in one <style> block; no <script> anywhere; the only
    external references are the configured links, socials and
    avatar. Every user-supplied string is escaped."""
    pal = _PALETTES[cfg["mode"]]
    esc = html.escape
    name = esc(cfg["name"])
    title = f"{name} — links"
    desc = esc(cfg["bio"][:160]) if cfg["bio"] else name
    avatar_html = ""
    if cfg["avatar"]:
        alt = esc(f"Portrait of {cfg['name']}")
        avatar_html = (f'\n    <img class="avatar" src="'
                       f'{esc(cfg["avatar"], quote=True)}" alt="{alt}">')

    bio_html = ""
    if cfg["bio"]:
        bio_html = f'\n    <p class="bio">{esc(cfg["bio"])}</p>'

    link_items = []
    for entry in cfg["links"]:
        note = (f'<span class="note">{esc(entry["note"])}</span>'
                if entry["note"] else "")
        link_items.append(
            f'      <li><a class="link" href="'
            f'{esc(entry["url"], quote=True)}">{esc(entry["label"])}'
            f'{note}</a></li>')
    links_html = "\n".join(link_items)

    socials_html = ""
    if cfg["socials"]:
        items = "\n".join(
            f'      <li><a href="{esc(e["url"], quote=True)}">'
            f'{esc(e["label"])}</a></li>' for e in cfg["socials"])
        socials_html = (f'\n  <nav aria-label="Social profiles">\n'
                        f'    <ul class="socials">\n{items}\n    </ul>\n'
                        f'  </nav>')

    css = (
        f":root{{--accent:{cfg['accent']}}}\n"
        f"*{{box-sizing:border-box}}\n"
        f"body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"
        f"\"Segoe UI\",Roboto,Helvetica,Arial,sans-serif;"
        f"background:{pal['bg']};color:{pal['fg']};line-height:1.5}}\n"
        f".page{{max-width:640px;margin:0 auto;padding:32px 20px 48px}}\n"
        f"header{{text-align:center;margin-bottom:28px}}\n"
        f".avatar{{width:96px;height:96px;border-radius:50%;"
        f"object-fit:cover;border:3px solid var(--accent)}}\n"
        f"h1{{font-size:1.6rem;margin:14px 0 6px}}\n"
        f".bio{{color:{pal['muted']};margin:0 auto;max-width:46ch}}\n"
        f"ul.links,ul.socials{{list-style:none;margin:0;padding:0}}\n"
        f"ul.links li{{margin:0 0 12px}}\n"
        f"a.link{{display:block;padding:14px 18px;background:"
        f"{pal['card']};border:2px solid var(--accent);"
        f"border-radius:14px;color:{pal['fg']};text-decoration:none;"
        f"text-align:center;font-weight:600}}\n"
        f"a.link .note{{display:block;font-weight:400;font-size:.9rem;"
        f"color:{pal['muted']};margin-top:2px}}\n"
        f"a.link:hover,a.link:focus-visible{{background:var(--accent);"
        f"color:#fff}}\n"
        f"a.link:hover .note,a.link:focus-visible .note{{"
        f"color:rgba(255,255,255,.85)}}\n"
        f"a:focus-visible{{outline:3px solid var(--accent);"
        f"outline-offset:2px}}\n"
        f"ul.socials{{display:flex;gap:10px;justify-content:center;"
        f"margin-top:20px;flex-wrap:wrap}}\n"
        f"ul.socials a{{display:block;padding:8px 16px;border:1px solid "
        f"var(--accent);border-radius:999px;color:{pal['fg']};"
        f"text-decoration:none;font-size:.95rem}}\n"
        f"ul.socials a:hover,ul.socials a:focus-visible{{"
        f"background:var(--accent);color:#fff}}\n")

    return (f"<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            f"<meta charset=\"utf-8\">\n"
            f"<meta name=\"viewport\" content=\"width=device-width,"
            f" initial-scale=1\">\n"
            f"<title>{title}</title>\n"
            f"<meta name=\"description\" content=\"{desc}\">\n"
            f"<style>\n{css}</style>\n</head>\n<body>\n"
            f"<div class=\"page\">\n  <header>{avatar_html}\n"
            f"    <h1>{name}</h1>{bio_html}\n  </header>\n"
            f"  <main>\n    <nav aria-label=\"Links\">\n"
            f"    <ul class=\"links\">\n{links_html}\n    </ul>\n"
            f"    </nav>{socials_html}\n  </main>\n</div>\n"
            f"</body>\n</html>\n")


def page_bytes(cfg):
    """The page's weight in bytes — what preview reports and what
    the written file must match."""
    return len(render_page(cfg).encode("utf-8"))


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------

def checks_passed(cfg, warnings):
    """The rule checks the page passes, as human lines."""
    checks = ["name present",
              f"{len(cfg['links'])} link(s), every label present",
              "every URL uses an allowed scheme (https, http, "
              "mailto, tel)",
              "single file, no external requests besides the "
              "configured links, socials and avatar"]
    if cfg["avatar"]:
        checks.append("avatar is referenced, not embedded")
    if cfg["accent_custom"]:
        checks.append("accent colour is a valid hex value")
    if not warnings:
        checks.append("no duplicate URLs")
    return checks


def _check_lines(cfg, show_details):
    """Per-link detail lines for --check-links output."""
    if not show_details:
        return []
    lines = []
    for kind, entries in (("links", cfg["links"]),
                          ("socials", cfg["socials"])):
        for i, entry in enumerate(entries):
            lines.append(f"  {kind}[{i}] {entry['label']!r} — "
                         f"{entry['url']} · {entry['detail']}")
    return lines


def _links_json(entries):
    out = []
    for entry in entries:
        item = {"label": entry["label"], "url": entry["url"]}
        if entry["note"]:
            item["note"] = entry["note"]
        out.append(item)
    return out


def cmd_build(a):
    cfg, warnings = load_config(a.config)
    # duplicate detection also needs the original theme flag
    html_text = render_page(cfg)
    out_path = Path(a.output) if a.output else Path("index.html")
    try:
        out_path.write_text(html_text, encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"cannot write output file {str(out_path)!r}: "
                        f"{exc}")
    size = len(html_text.encode("utf-8"))
    checks = checks_passed(cfg, warnings)
    exit_code = 1 if warnings else 0
    if a.json:
        print(json.dumps({
            "tool": TOOL, "version": __version__, "command": "build",
            "config_file": Path(a.config).name,
            "output_file": str(out_path), "page_bytes": size,
            "name": cfg["name"], "links": _links_json(cfg["links"]),
            "socials": _links_json(cfg["socials"]),
            "checks_passed": checks, "warnings": warnings,
        }))
        return exit_code
    print(f"{TOOL} v{__version__} — build · config "
          f"{Path(a.config).name}")
    print(f"Wrote {out_path} — {size:,} bytes · "
          f"{len(cfg['links'])} link(s), {len(cfg['socials'])} "
          f"social(s)")
    detail = _check_lines(cfg, a.check_links)
    if detail:
        print("Link checks (structural, offline — shape, not "
              "liveness):")
        for line in detail:
            print(line)
    print("Checks passed:")
    for check in checks:
        print(f"  ✓ {check}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  ! {warning}")
    else:
        print("Warnings: none")
    return exit_code


def cmd_preview(a):
    cfg, warnings = load_config(a.config)
    size = page_bytes(cfg)
    checks = checks_passed(cfg, warnings)
    exit_code = 1 if warnings else 0
    if a.json:
        print(json.dumps({
            "tool": TOOL, "version": __version__, "command": "preview",
            "config_file": Path(a.config).name,
            "name": cfg["name"], "page_bytes": size,
            "links": _links_json(cfg["links"]),
            "socials": _links_json(cfg["socials"]),
            "checks_passed": checks, "warnings": warnings,
        }))
        return exit_code
    print(f"{TOOL} v{__version__} — preview · config "
          f"{Path(a.config).name}")
    print(f"{cfg['name']} · {len(cfg['links'])} link(s), "
          f"{len(cfg['socials'])} social(s) · page weight "
          f"{size:,} bytes")
    print()
    print("Links, in order:")
    for i, entry in enumerate(cfg["links"], 1):
        note = f" — {entry['note']}" if entry["note"] else ""
        print(f"  {i}. {entry['label']} — {entry['url']}{note}")
    if cfg["socials"]:
        print()
        print("Socials:")
        for i, entry in enumerate(cfg["socials"], 1):
            print(f"  {i}. {entry['label']} — {entry['url']}")
    detail = _check_lines(cfg, a.check_links)
    if detail:
        print()
        print("Link checks (structural, offline — shape, not "
              "liveness):")
        for line in detail:
            print(line)
    print()
    print("Checks passed:")
    for check in checks:
        print(f"  ✓ {check}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  ! {warning}")
    else:
        print("Warnings: none")
    return exit_code


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class _JsonAwareParser(argparse.ArgumentParser):
    """ArgumentParser that reports usage errors as JSON in --json
    mode ({"error": ...} on stdout, same exit code 2) — an agent
    driving this tool with --json never gets plain text or a
    traceback. The flag lives on the class so subparsers share
    it."""

    json_mode = False

    def error(self, message):
        if self.json_mode:
            print(json.dumps({"error": message}))
            self.exit(2)
        super().error(message)


def _json_arg(p):
    p.add_argument("--json", action="store_true",
                   help="one JSON object instead of text output")


def _check_arg(p):
    p.add_argument("--check-links", action="store_true",
                   help="list the structural check for every URL")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    _JsonAwareParser.json_mode = "--json" in argv
    ap = _JsonAwareParser(
        prog=TOOL,
        description="Turn one config JSON file into a link-in-bio "
                    "page you own: one static HTML file, all CSS "
                    "inline, no trackers, no scripts, no platform "
                    "rent (stdlib only, local only).")
    sub = ap.add_subparsers(dest="command", required=True,
                            parser_class=_JsonAwareParser)

    p_build = sub.add_parser(
        "build", help="validate the config and write the page "
                      "(default output: index.html)")
    p_build.add_argument("config", help="config JSON file")
    p_build.add_argument("-o", "--output", default=None,
                         help="output HTML file (default: index.html)")
    _check_arg(p_build)
    _json_arg(p_build)
    p_build.set_defaults(func=cmd_build)

    p_preview = sub.add_parser(
        "preview", help="summarise the page without writing "
                        "anything: links in order, page weight, "
                        "checks passed")
    p_preview.add_argument("config", help="config JSON file")
    _check_arg(p_preview)
    _json_arg(p_preview)
    p_preview.set_defaults(func=cmd_preview)

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
    except BrokenPipeError:
        return 2


if __name__ == "__main__":
    sys.exit(main())
