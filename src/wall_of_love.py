#!/usr/bin/env python3
"""wall-of-love — turn a testimonials file (JSON or CSV) into a
wall of love you own: one static HTML page, all CSS inline, no
JavaScript (the only <script> is an inert schema.org JSON-LD
block), no trackers, no subscription, no platform that can fold,
shut down or start charging rent on quotes your customers wrote.

Senja charges $29/mo and caps its free tier at 15 testimonials
for the lifetime of the account; Testimonial.to charges $25/mo
and still caps video; Famewall keeps its branding until the
$79.99/mo plan. $300 a year for what is, essentially, a
guestbook. This tool generates the guestbook instead: one file,
hosted anywhere — GitHub Pages, your own site, any static
host — yours, forever, for free.

Input (one JSON or CSV file):

  JSON — either a bare list of testimonials, or an object:
  {
    "business": "Okanagan Stone & Cedar",
    "tagline": "Fences and decks, built once.",
    "logo": "https://example.org/logo.png",
    "theme": {"accent": "#7a4a21", "mode": "light"},
    "testimonials": [
      {"name": "Priya Nair", "role": "Homeowner, Kelowna",
       "quote": "The fence has survived two winters...",
       "rating": 5, "date": "2026-09-14",
       "source": "https://example.org/reviews/42",
       "avatar": "https://example.org/avatars/priya.jpg"}
    ]
  }

  CSV — a header row with columns:
    name,role,quote,rating,date,source,avatar
  (only name and quote are required columns; extra columns are
  ignored; page fields — business, tagline, logo, theme — come
  from the JSON object form only.)

  Per testimonial:
  name     required, non-empty string.
  role     optional string ("role/company" — one free-text
           line, e.g. "Owner, Trailhead Coffee").
  quote    required, non-empty string.
  rating   optional integer 1-5. Missing is a WARNING (the
           testimonial still shows; it is excluded from the
           aggregate). Present but not an integer 1-5 — 0, 6,
           "five", 4.5 — is an ERROR: a rating the tool cannot
           defend does not reach the page.
  date     optional, YYYY-MM-DD exactly.
  source   optional http(s) URL where the testimonial lives.
  avatar   optional: an http(s) URL or a local path, REFERENCED
           (an <img src>), never embedded.

Commands:
  build TESTIMONIALS [-o wall.html]
            validate the input and write the page. Default
            output file is wall.html in the current directory.
            Exit 0 = clean, 1 = built but with warnings
            (duplicate quotes, missing ratings), 2 = ERROR and
            nothing written.
  preview TESTIMONIALS
            print a summary without writing anything: the
            testimonials in display order, the aggregate, the
            page weight in bytes, and the checks passed. Same
            exit codes.

Sorting: highest rating first, then newest date; unrated
testimonials sort after rated ones, undated after dated; ties
keep input order.

The aggregate is the exact mean of the ratings present,
rounded to one decimal (half-up), and the review count is the
number of testimonials in the file. Both are computed once and
the SAME numbers are printed on the wall and written into the
JSON-LD — the two can never drift apart.

Honesty: the wall shows only the testimonials in the input
file, verbatim — never invented, padded, paraphrased or
"improved". Three testimonials in the file means three on the
wall. There is no network code in this tool: it reads the file
you point it at and writes the page you ask for.

Escaping: every user-supplied string is HTML-escaped before it
is written, in text and in attributes — a quote containing
"<script>" renders as text, never as markup. The JSON-LD block
is escaped for embedding too (<, > and & are written as JSON
unicode escapes), so a quote can never break out of the data
block or interact with the parser around it.

Exit codes: 0 = ok · 1 = a finding (warnings) · 2 = ERROR —
clean message, never a traceback; with --json the error is
{"error": ...}. Every command takes --json: one JSON object
with the same facts and exit codes as the text view.
"""
import argparse
import csv
import html
import io
import json
import re
import sys
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

__version__ = "0.1.0"
TOOL = "wall-of-love"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ACCENT_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

_PALETTES = {
    "light": {"bg": "#faf7f2", "fg": "#1f1a14", "card": "#ffffff",
              "muted": "#6b5d4f"},
    "dark": {"bg": "#16130f", "fg": "#f4efe8", "card": "#211c16",
             "muted": "#b3a48f"},
}

_CSV_COLUMNS = ("name", "role", "quote", "rating", "date",
                "source", "avatar")


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


def _optional_str(obj, field, label):
    """Optional string field: None -> None; a non-string value is
    an error naming the field."""
    value = obj.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"{label}: field {field!r} must be a string "
                        f"(got {value!r})")
    return value if value.strip() else None


def _check_ref(value, label):
    """An avatar/logo reference: an http(s) URL or a local path.
    Any other scheme is refused — a data: or javascript: "image"
    is not an image."""
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
        scheme = value.split(":", 1)[0].lower()
        if scheme not in ("https", "http"):
            raise ToolError(f"{label}: scheme {scheme!r} is not "
                            f"allowed (use an http(s) URL or a "
                            f"local path)")
        if any(ch.isspace() for ch in value):
            raise ToolError(f"{label}: URL contains whitespace: "
                            f"{value!r}")
        host = value.split(":", 1)[1].lstrip("/")
        if not host:
            raise ToolError(f"{label}: {scheme} URL has no host: "
                            f"{value!r}")


def _check_source(url, label):
    """A source link: http(s) only, with a host, no whitespace."""
    if any(ch.isspace() for ch in url):
        raise ToolError(f"{label}: URL contains whitespace: {url!r}")
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", url)
    if not m:
        raise ToolError(f"{label}: URL has no scheme: {url!r}")
    scheme = m.group(1).lower()
    if scheme not in ("https", "http"):
        raise ToolError(f"{label}: scheme {scheme!r} is not allowed "
                        f"for a source link (allowed: https, http): "
                        f"{url!r}")
    host = url[m.end():].lstrip("/")
    if not host:
        raise ToolError(f"{label}: {scheme} URL has no host: {url!r}")


def _parse_date(value, label):
    """date (optional) -> a datetime.date, YYYY-MM-DD exactly."""
    if value is None:
        return None
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise ToolError(f"{label}: field 'date' must be YYYY-MM-DD "
                        f"(got {value!r})")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ToolError(f"{label}: field 'date' is not a real date "
                        f"(got {value!r})")


def _parse_rating(value, label):
    """rating (optional) -> int 1-5 or None. Present-but-invalid
    is an error, for JSON values and CSV strings alike: 0, 6,
    'five' and 4.5 are all refused, naming the field."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ToolError(f"{label}: field 'rating' must be an "
                        f"integer from 1 to 5 (got {value!r})")
    if isinstance(value, int):
        rating = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            rating = int(text, 10)
        except ValueError:
            raise ToolError(f"{label}: field 'rating' must be an "
                            f"integer from 1 to 5 (got {value!r})")
        if str(rating) != text.lstrip("+"):
            raise ToolError(f"{label}: field 'rating' must be an "
                            f"integer from 1 to 5 (got {value!r})")
    else:
        raise ToolError(f"{label}: field 'rating' must be an "
                        f"integer from 1 to 5 (got {value!r})")
    if not 1 <= rating <= 5:
        raise ToolError(f"{label}: field 'rating' must be from 1 "
                        f"to 5 (got {rating})")
    return rating


def _validate_testimonial(entry, label):
    """One testimonial -> a cleaned dict. Errors name the field."""
    if not isinstance(entry, dict):
        raise ToolError(f"{label}: each testimonial must be an "
                        f"object (got {entry!r})")
    name = _require_nonempty_str(entry, "name", label)
    quote = _require_nonempty_str(entry, "quote", label)
    role = _optional_str(entry, "role", label)
    rating = _parse_rating(entry.get("rating"), label)
    day = _parse_date(entry.get("date"), label)
    source = _optional_str(entry, "source", label)
    if source is not None:
        _check_source(source, f"{label}.source")
    avatar = _optional_str(entry, "avatar", label)
    if avatar is not None:
        _check_ref(avatar, f"{label}.avatar")
    return {"name": name, "role": role, "quote": quote,
            "rating": rating, "date": day, "source": source,
            "avatar": avatar}


def _validate_theme(theme):
    """theme (optional object) -> (accent, mode, accent_custom)."""
    accent = "#b3541e"
    mode = "light"
    custom = False
    if theme is None:
        return accent, mode, custom
    if not isinstance(theme, dict):
        raise ToolError(f"theme: must be an object (got {theme!r})")
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


def _normalise_quote(quote):
    """Duplicate detection key: case-folded, whitespace collapsed."""
    return " ".join(quote.casefold().split())


def _sort_key(indexed):
    """Display order: rating desc (unrated last), date desc
    (undated last), then input order."""
    index, t = indexed
    rating_key = (0, -t["rating"]) if t["rating"] is not None \
        else (1, 0)
    date_key = (0, -t["date"].toordinal()) if t["date"] is not None \
        else (1, 0)
    return (rating_key, date_key, index)


def _assemble(page, raw_testimonials, label_prefix):
    """Validate a list of raw testimonials + page fields ->
    (data, warnings). Warnings: duplicate quotes and missing
    ratings; hard problems raise ToolError."""
    if not isinstance(raw_testimonials, list) or not raw_testimonials:
        raise ToolError("testimonials: must be a non-empty list")
    items = [_validate_testimonial(e, f"{label_prefix}[{i}]")
             for i, e in enumerate(raw_testimonials)]

    warnings = []
    seen = {}
    for i, t in enumerate(items):
        key = _normalise_quote(t["quote"])
        if key in seen:
            warnings.append(
                f"duplicate quote: testimonials[{i}] "
                f"('{t['name']}') repeats testimonials[{seen[key]}] "
                f"verbatim — the wall shows what the file holds, "
                f"but a repeated quote reads as padding")
        else:
            seen[key] = i
        if t["rating"] is None:
            warnings.append(
                f"missing rating: testimonials[{i}] "
                f"('{t['name']}') has no rating — it is shown "
                f"without stars and excluded from the aggregate")

    ordered = [t for _, t in sorted(enumerate(items), key=_sort_key)]
    ratings = [t["rating"] for t in items if t["rating"] is not None]
    if ratings:
        mean = (Decimal(sum(ratings)) / Decimal(len(ratings)))
        aggregate = float(mean.quantize(Decimal("0.1"),
                                        rounding=ROUND_HALF_UP))
    else:
        aggregate = None

    accent, mode, accent_custom = _validate_theme(page.get("theme"))
    return {
        "business": page.get("business"),
        "tagline": page.get("tagline"),
        "logo": page.get("logo"),
        "accent": accent, "mode": mode,
        "accent_custom": accent_custom,
        "testimonials": ordered,
        "count": len(items),
        "rated_count": len(ratings),
        "aggregate": aggregate,
    }, warnings


def _page_fields(data, label):
    """Page-level fields from a JSON object -> a cleaned dict."""
    page = {}
    business = data.get("business")
    if business is not None:
        if not isinstance(business, str) or not business.strip():
            raise ToolError(f"{label}: field 'business' must be a "
                            f"non-empty string")
        page["business"] = business
    tagline = data.get("tagline")
    if tagline is not None:
        if not isinstance(tagline, str):
            raise ToolError(f"{label}: field 'tagline' must be a "
                            f"string (got {tagline!r})")
        page["tagline"] = tagline if tagline.strip() else None
    logo = data.get("logo")
    if logo is not None:
        if not isinstance(logo, str) or not logo.strip():
            raise ToolError(f"{label}: field 'logo' must be a "
                            f"non-empty string")
        _check_ref(logo, f"{label}.logo")
        page["logo"] = logo
    page["theme"] = data.get("theme")
    return page


def _load_json(raw, path):
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"file {path!r} is not valid JSON: {exc}")
    if isinstance(data, list):
        return {}, data
    if isinstance(data, dict):
        if "testimonials" not in data:
            raise ToolError(f"file {path!r}: object form must carry "
                            f"a 'testimonials' list")
        return _page_fields(data, "config"), data["testimonials"]
    raise ToolError(f"file {path!r}: top level must be a list of "
                    f"testimonials or an object with a "
                    f"'testimonials' list (got "
                    f"{type(data).__name__})")


def _load_csv(raw, path):
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames is None:
        raise ToolError(f"file {path!r}: empty file (no header row)")
    headers = [(h or "").strip() for h in reader.fieldnames]
    for required in ("name", "quote"):
        if required not in headers:
            raise ToolError(f"file {path!r}: CSV must have a "
                            f"{required!r} column (header: "
                            f"{', '.join(headers)})")
    rows = []
    try:
        for row in reader:
            item = {}
            for col in _CSV_COLUMNS:
                if col in headers:
                    value = row.get(col)
                    item[col] = value if value is not None else ""
            rows.append(item)
    except csv.Error as exc:
        raise ToolError(f"file {path!r} is not valid CSV: {exc}")
    if not rows:
        raise ToolError(f"file {path!r}: CSV has a header but no "
                        f"testimonial rows")
    return {}, rows


def load_testimonials(path):
    """Read and fully validate a testimonials file (JSON or CSV,
    chosen by extension). Returns (data, warnings); hard problems
    raise ToolError."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"cannot read testimonials file {path!r}: "
                        f"{exc}")
    if not raw.strip():
        raise ToolError(f"file {path!r}: empty file")
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        page, raw_items = _load_csv(raw, path)
        prefix = "row"
    elif suffix == ".json":
        page, raw_items = _load_json(raw, path)
        prefix = "testimonials"
    else:
        raise ToolError(f"file {path!r}: expected a .json or .csv "
                        f"file (got suffix {suffix!r})")
    return _assemble(page, raw_items, prefix)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _stars(rating):
    """★★★★★ / ★★★★☆ text stars — characters, not images."""
    return "★" * rating + "☆" * (5 - rating)


def build_jsonld(data):
    """The schema.org block, computed from the same validated data
    the wall renders — the aggregate and count are the wall's."""
    business = data["business"] or "Wall of Love"
    ld = {"@context": "https://schema.org",
          "@type": "LocalBusiness",
          "name": business}
    if data["aggregate"] is not None:
        ld["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": f"{data['aggregate']:.1f}",
            "reviewCount": data["count"],
            "bestRating": "5",
            "worstRating": "1",
        }
    reviews = []
    for t in data["testimonials"]:
        review = {"@type": "Review",
                  "author": {"@type": "Person", "name": t["name"]},
                  "reviewBody": t["quote"]}
        if t["rating"] is not None:
            review["reviewRating"] = {
                "@type": "Rating", "ratingValue": t["rating"],
                "bestRating": "5", "worstRating": "1"}
        if t["date"] is not None:
            review["datePublished"] = t["date"].isoformat()
        if t["source"] is not None:
            review["url"] = t["source"]
        reviews.append(review)
    ld["review"] = reviews
    text = json.dumps(ld, ensure_ascii=False, indent=2)
    # Embedding safety: a quote holding "</script>" (or a bare
    # "<script>") must never interact with the HTML parser around
    # the data block. Writing <, > and & as JSON unicode escapes
    # keeps every character inert to HTML while remaining exactly
    # the same string to a JSON parser.
    return (text.replace("&", "\\u0026")
                .replace("<", "\\u003c")
                .replace(">", "\\u003e"))


def render_page(data):
    """Validated data -> the complete HTML page (a string). All
    CSS is inline in one <style> block; the only <script> is the
    inert JSON-LD data block; the only external references are
    the configured logo, avatars and source links. Every
    user-supplied string is escaped."""
    pal = _PALETTES[data["mode"]]
    esc = html.escape
    business = data["business"] or "Wall of Love"
    title = f"{esc(business)} — Wall of Love" \
        if data["business"] else "Wall of Love"
    desc = esc((data["tagline"] or
                f"What customers say about {business}.")[:160])

    logo_html = ""
    if data["logo"]:
        logo_html = (f'\n    <img class="logo" src="'
                     f'{esc(data["logo"], quote=True)}" '
                     f'alt="{esc(business)} logo">')
    tagline_html = ""
    if data["tagline"]:
        tagline_html = f'\n    <p class="tagline">' \
                       f'{esc(data["tagline"])}</p>'

    summary_html = ""
    if data["aggregate"] is not None:
        summary_html = (
            f'\n    <p class="summary"><span class="stars" '
            f'aria-hidden="true">{_stars(round(data["aggregate"]))}'
            f'</span> <strong>{data["aggregate"]:.1f} out of 5'
            f'</strong> from {data["count"]} review(s) · '
            f'{data["rated_count"]} with ratings</p>')

    cards = []
    for t in data["testimonials"]:
        avatar_html = ""
        if t["avatar"]:
            avatar_html = (f'\n        <img class="avatar" src="'
                           f'{esc(t["avatar"], quote=True)}" alt="" '
                           f'loading="lazy">')
        stars_html = ""
        if t["rating"] is not None:
            stars_html = (f'\n        <p class="stars" '
                          f'aria-label="Rated {t["rating"]} out of '
                          f'5">{_stars(t["rating"])}</p>')
        role_html = (f' · {esc(t["role"])}' if t["role"] else "")
        date_html = (f' · <time datetime="{t["date"].isoformat()}">'
                     f'{t["date"].isoformat()}</time>'
                     if t["date"] is not None else "")
        source_html = ""
        if t["source"]:
            source_html = (f'\n        <p class="source">'
                           f'<a href="'
                           f'{esc(t["source"], quote=True)}" '
                           f'rel="noopener">Original review</a></p>')
        cards.append(
            f'      <figure class="card">\n'
            f'        <blockquote>{esc(t["quote"])}'
            f'</blockquote>{stars_html}\n'
            f'        <figcaption>{avatar_html}\n'
            f'          <span class="name">{esc(t["name"])}</span>'
            f'{role_html}{date_html}{source_html}\n'
            f'        </figcaption>\n'
            f'      </figure>')
    cards_html = "\n".join(cards)

    css = (
        f":root{{--accent:{data['accent']}}}\n"
        f"*{{box-sizing:border-box}}\n"
        f"body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"
        f"\"Segoe UI\",Roboto,Helvetica,Arial,sans-serif;"
        f"background:{pal['bg']};color:{pal['fg']};line-height:1.55}}\n"
        f".page{{max-width:960px;margin:0 auto;padding:36px 20px 56px}}\n"
        f"header{{text-align:center;margin-bottom:30px}}\n"
        f".logo{{max-height:64px;max-width:240px}}\n"
        f"h1{{font-size:1.9rem;margin:14px 0 6px}}\n"
        f".tagline{{color:{pal['muted']};margin:0 auto;max-width:56ch}}\n"
        f".summary{{margin:14px 0 0;font-size:1.05rem}}\n"
        f".stars{{color:var(--accent);letter-spacing:2px}}\n"
        f".wall{{display:grid;grid-template-columns:repeat("
        f"auto-fill,minmax(260px,1fr));gap:16px}}\n"
        f".card{{margin:0;background:{pal['card']};border:1px solid "
        f"var(--accent);border-radius:14px;padding:18px;"
        f"display:flex;flex-direction:column;gap:8px}}\n"
        f"blockquote{{margin:0;font-size:1.02rem}}\n"
        f"figcaption{{margin-top:auto;color:{pal['muted']};"
        f"font-size:.92rem;display:flex;flex-wrap:wrap;gap:6px;"
        f"align-items:center}}\n"
        f".avatar{{width:36px;height:36px;border-radius:50%;"
        f"object-fit:cover}}\n"
        f".name{{font-weight:700;color:{pal['fg']}}}\n"
        f".source{{margin:0;width:100%}}\n"
        f".source a{{color:var(--accent)}}\n"
        f"a:focus-visible{{outline:3px solid var(--accent);"
        f"outline-offset:2px}}\n")

    jsonld = build_jsonld(data)
    return (f"<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            f"<meta charset=\"utf-8\">\n"
            f"<meta name=\"viewport\" content=\"width=device-width,"
            f" initial-scale=1\">\n"
            f"<title>{title}</title>\n"
            f"<meta name=\"description\" content=\"{desc}\">\n"
            f"<style>\n{css}</style>\n"
            f"<script type=\"application/ld+json\">\n{jsonld}\n"
            f"</script>\n</head>\n<body>\n"
            f"<div class=\"page\">\n  <header>{logo_html}\n"
            f"    <h1>{esc(business)}</h1>{tagline_html}"
            f"{summary_html}\n  </header>\n"
            f"  <main>\n    <section class=\"wall\" "
            f"aria-label=\"Testimonials\">\n{cards_html}\n"
            f"    </section>\n  </main>\n</div>\n"
            f"</body>\n</html>\n")


def page_bytes(data):
    """The page's weight in bytes — what preview reports and what
    the written file must match."""
    return len(render_page(data).encode("utf-8"))


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------

def checks_passed(data, warnings):
    """The rule checks the wall passes, as human lines."""
    checks = [f"{data['count']} testimonial(s), every name and "
              f"quote present",
              "every rating present is an integer from 1 to 5",
              "single file, no external requests besides the "
              "configured logo, avatars and source links",
              "JSON-LD generated from the same data as the wall — "
              "aggregate and count cannot drift"]
    if data["aggregate"] is not None:
        checks.append(f"aggregate {data['aggregate']:.1f} from "
                      f"{data['rated_count']} rated testimonial(s)")
    if data["accent_custom"]:
        checks.append("accent colour is a valid hex value")
    if not warnings:
        checks.append("no duplicate quotes, no missing ratings")
    return checks


def _testimonial_json(t):
    item = {"name": t["name"], "quote": t["quote"]}
    if t["role"]:
        item["role"] = t["role"]
    if t["rating"] is not None:
        item["rating"] = t["rating"]
    if t["date"] is not None:
        item["date"] = t["date"].isoformat()
    if t["source"]:
        item["source"] = t["source"]
    if t["avatar"]:
        item["avatar"] = t["avatar"]
    return item


def _report_json(a, data, warnings, output_file=None):
    payload = {
        "tool": TOOL, "version": __version__, "command": a.command,
        "input_file": Path(a.input).name,
        "business": data["business"],
        "page_bytes": page_bytes(data),
        "count": data["count"],
        "rated_count": data["rated_count"],
        "aggregate": data["aggregate"],
        "testimonials": [_testimonial_json(t)
                         for t in data["testimonials"]],
        "checks_passed": checks_passed(data, warnings),
        "warnings": warnings,
    }
    if output_file is not None:
        payload["output_file"] = output_file
    print(json.dumps(payload))
    return 1 if warnings else 0


def _print_report(a, data, warnings, wrote=None):
    business = data["business"] or "Wall of Love"
    size = page_bytes(data)
    print(f"{TOOL} v{__version__} — {a.command} · file "
          f"{Path(a.input).name}")
    if wrote is not None:
        print(f"Wrote {wrote} — {size:,} bytes · "
              f"{data['count']} testimonial(s)")
    else:
        print(f"{business} · {data['count']} testimonial(s) · "
              f"page weight {size:,} bytes")
    if data["aggregate"] is not None:
        print(f"Aggregate: {data['aggregate']:.1f} out of 5 from "
              f"{data['rated_count']} rated testimonial(s) · "
              f"review count {data['count']}")
    else:
        print("Aggregate: none — no testimonial carries a rating")
    print()
    print("Testimonials, in display order (rating, then newest):")
    for i, t in enumerate(data["testimonials"], 1):
        stars = _stars(t["rating"]) if t["rating"] is not None \
            else "no rating"
        role = f" · {t['role']}" if t["role"] else ""
        day = f" · {t['date'].isoformat()}" if t["date"] else ""
        print(f"  {i}. {t['name']}{role} — {stars}{day}")
    print()
    print("Checks passed:")
    for check in checks_passed(data, warnings):
        print(f"  ✓ {check}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  ! {warning}")
    else:
        print("Warnings: none")
    return 1 if warnings else 0


def cmd_build(a):
    data, warnings = load_testimonials(a.input)
    html_text = render_page(data)
    out_path = Path(a.output) if a.output else Path("wall.html")
    try:
        out_path.write_text(html_text, encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"cannot write output file "
                        f"{str(out_path)!r}: {exc}")
    if a.json:
        return _report_json(a, data, warnings,
                            output_file=str(out_path))
    return _print_report(a, data, warnings, wrote=str(out_path))


def cmd_preview(a):
    data, warnings = load_testimonials(a.input)
    if a.json:
        return _report_json(a, data, warnings)
    return _print_report(a, data, warnings)


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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    _JsonAwareParser.json_mode = "--json" in argv
    ap = _JsonAwareParser(
        prog=TOOL,
        description="Turn a testimonials file (JSON or CSV) into "
                    "a wall of love you own: one static HTML page "
                    "with schema.org JSON-LD, all CSS inline, no "
                    "JavaScript, no platform rent (stdlib only, "
                    "local only).")
    sub = ap.add_subparsers(dest="command", required=True,
                            parser_class=_JsonAwareParser)

    p_build = sub.add_parser(
        "build", help="validate the testimonials and write the "
                      "page (default output: wall.html)")
    p_build.add_argument("input", help="testimonials .json or "
                                       ".csv file")
    p_build.add_argument("-o", "--output", default=None,
                         help="output HTML file (default: wall.html)")
    _json_arg(p_build)
    p_build.set_defaults(func=cmd_build)

    p_preview = sub.add_parser(
        "preview", help="summarise the wall without writing "
                        "anything: display order, aggregate, page "
                        "weight, checks passed")
    p_preview.add_argument("input", help="testimonials .json or "
                                         ".csv file")
    _json_arg(p_preview)
    p_preview.set_defaults(func=cmd_preview)

    a = ap.parse_args(argv)
    a.command = a.func.__name__.removeprefix("cmd_")

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
