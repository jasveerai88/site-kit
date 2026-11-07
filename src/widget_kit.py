#!/usr/bin/env python3
"""widget-kit — the four boring widgets every small site
needs, generated as static fragments you own: an FAQ block
(with matching FAQPage JSON-LD), a pricing table, a countdown
bar and a social-proof card row. No account, no subscription,
no view metering, no third-party script phoning home.

Hosted widget services rent display volume. Elfsight charges
$5-6/mo for a single app and $15-36/mo for all apps, with the
view allowance SHARED across every site on the plan — G2
reviewers report "one client can eat all the credits in a
widget" and reviews being deactivated even on paid plans.
Fomo charges $25-149/mo by notification volume, plus $75/mo
for agency white-label, with complaints about auto-upgrades
and overage fees. But a widget is markup. Markup is a file.
widget-kit writes the files: paste each fragment into any
page — a hand-built site, a CMS template, a static host — and
it works forever, for free, however many people look at it.

Config (one JSON file):

  {
    "widgets": [
      {"type": "faq", "id": "faq", "title": "Questions",
       "items": [{"q": "Do you deliver?", "a": "Yes, ..."}]},
      {"type": "pricing", "id": "pricing",
       "tiers": [{"name": "Basic", "price": "$19",
                  "period": "/mo", "features": ["..."],
                  "highlight": true,
                  "cta_label": "Start", "cta_url": "https://..."}]},
      {"type": "countdown", "id": "launch",
       "target": "2027-06-01T09:00:00-07:00",
       "label": "Spring sale ends in",
       "ended_text": "The spring sale has ended."},
      {"type": "proof", "id": "proof",
       "entries_file": "proof-entries.json"}
    ]
  }

  widgets   required, a non-empty list. Each widget makes ONE
            fragment file, "<id>.html", in the output folder.
  id        optional per widget: lowercase letters, digits
            and dashes; defaults to the widget type. Two
            widgets may not share an output filename.
  title     optional heading for faq / pricing / proof.

  faq       items: a list of {"q", "a"} — both required,
            non-empty. The visible <details>/<summary> block
            and the FAQPage JSON-LD are generated from the
            SAME list, so the schema can never drift from
            what visitors read.
  pricing   tiers: name and price required; price is a
            string rendered EXACTLY as written ("$49",
            "£25", "Free") — the tool does no currency math.
            period optional ("/mo"); features a required list
            of strings (may be empty); highlight an optional
            boolean — the ONLY thing that highlights a tier,
            and no badge text is invented for it; cta_label
            and cta_url are an optional pair (both or neither).
  countdown target: an ISO 8601 datetime WITH a UTC offset
            (a bare date or a naive datetime is refused — a
            countdown that guesses a timezone counts to the
            wrong moment). ended_text is required: it is what
            the fragment shows once the moment has passed,
            including immediately, if the target is already
            past when you generate (that is a WARNING, exit 1
            — never a silent countdown to a finished event).
            label is an optional line above the timer. With
            JavaScript off, the fragment still shows the
            target date as plain text.
  proof     entries inline ({"entries": [...]}) or from
            entries_file (JSON or CSV, resolved relative to
            the config file). Each entry: name and text
            required; date optional (YYYY-MM-DD); rating
            optional integer 1-5. Entries render in the order
            given, exactly as written — see Honesty.

Honesty (proof): the tool renders ONLY the entries you
supply, in your words, in your order. It computes NOTHING
about them — no average rating, no entry count on the page,
no "500+ happy customers" line, ever. If a number like that
appears on your site, you typed it into a text field
yourself. Publish only proof you actually have; the samples
bundled with this tool are labelled SAMPLE throughout for
exactly that reason.

Validation collects EVERY problem before failing: one run
reports a bad price type in widgets[0], an unknown widget
type in widgets[1] and a missing ended_text in widgets[2]
together, exits 2, and writes nothing. Warnings (exit 1,
fragments still written): a countdown whose target has
already passed, and a faq/pricing/proof widget with an
empty content list (the fragment renders its heading only).

Escaping: every user-supplied string is HTML-escaped in text
and attributes — a question containing "<script>" renders as
text. The JSON-LD block is additionally escaped for
embedding (<, >, & written as JSON unicode escapes), so a
question can never break out of the data block. The only
URLs in any fragment are the pricing CTA links you
configured, rendered as hrefs — plus the schema.org context
identifier inside the FAQ JSON-LD, which names a vocabulary
and is never fetched. No fragment loads anything: no
external stylesheets, fonts, images or scripts.

Exit codes: 0 = clean · 1 = warnings (fragments written) ·
2 = ERROR — clean message, never a traceback; with --json
the error is {"error": ...}. The one command takes --json:
one JSON object with the same facts and exit codes as the
text view.
"""
import argparse
import csv
import html
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

__version__ = "0.1.0"
TOOL = "widget-kit"

WIDGET_TYPES = ("faq", "pricing", "countdown", "proof")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LINK_SCHEMES = ("https", "http", "mailto", "tel")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_FONT_STACK = ("-apple-system,BlinkMacSystemFont,\"Segoe UI\","
               "Roboto,Helvetica,Arial,sans-serif")


class ToolError(Exception):
    """A clean, user-facing failure (printed as ERROR, exit 2)."""


class ConfigError(ToolError):
    """Validation failed; carries EVERY problem found, so one
    run reports them all and writes nothing."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__(
            f"config validation failed with "
            f"{len(self.problems)} problem(s)")


# ---------------------------------------------------------------------------
# validation — every problem is collected, none aborts the pass
# ---------------------------------------------------------------------------

def _req_str(obj, field, label, problems):
    """obj[field] as a non-empty string; appends a problem and
    returns None on any failure."""
    if field not in obj or obj[field] is None:
        problems.append(f"{label}: missing required field {field!r}")
        return None
    value = obj[field]
    if not isinstance(value, str):
        problems.append(f"{label}: field {field!r} must be a string "
                        f"(got {value!r})")
        return None
    if not value.strip():
        problems.append(f"{label}: field {field!r} must not be empty")
        return None
    return value


def _opt_str(obj, field, label, problems):
    """Optional string; None when absent, problem when present
    but not a string."""
    value = obj.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        problems.append(f"{label}: field {field!r} must be a string "
                        f"(got {value!r})")
        return None
    return value


def _check_link(url, label, problems):
    """Structural check of a CTA link (offline — shape, never
    liveness). Appends a problem unless the shape is sound."""
    if url != url.strip() or any(ch.isspace() for ch in url):
        problems.append(f"{label}: URL contains whitespace: {url!r}")
        return
    if url.startswith("//"):
        problems.append(f"{label}: URL is scheme-relative "
                        f"(no scheme): {url!r}")
        return
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", url)
    if not m:
        problems.append(f"{label}: URL has no scheme: {url!r}")
        return
    scheme = m.group(1).lower()
    if scheme not in _LINK_SCHEMES:
        problems.append(f"{label}: scheme {scheme!r} is not allowed "
                        f"(allowed: https, http, mailto, tel): {url!r}")
        return
    if scheme in ("https", "http"):
        host = url.split(":", 1)[1].lstrip("/")
        if not host:
            problems.append(f"{label}: {scheme} URL has no host: "
                            f"{url!r}")
    elif scheme == "mailto":
        address = url.split(":", 1)[1].split("?", 1)[0]
        if "@" not in address or not address.strip("@"):
            problems.append(f"{label}: mailto: URL has no address: "
                            f"{url!r}")
    else:  # tel
        if not any(ch.isdigit() for ch in url.split(":", 1)[1]):
            problems.append(f"{label}: tel: URL has no digits: "
                            f"{url!r}")


def _validate_faq(w, label, problems, warnings):
    items_raw = w.get("items")
    if items_raw is None:
        problems.append(f"{label}: missing required field 'items'")
        return None
    if not isinstance(items_raw, list):
        problems.append(f"{label}: field 'items' must be a list "
                        f"(got {items_raw!r})")
        return None
    items = []
    for i, item in enumerate(items_raw):
        ilabel = f"{label}.items[{i}]"
        if not isinstance(item, dict):
            problems.append(f"{ilabel}: each item must be an object "
                            f"(got {item!r})")
            continue
        q = _req_str(item, "q", ilabel, problems)
        a = _req_str(item, "a", ilabel, problems)
        if q is not None and a is not None:
            items.append({"q": q, "a": a})
    if isinstance(items_raw, list) and not items_raw:
        warnings.append(f"{label}: faq has no items — the fragment "
                        f"will hold only its heading")
    return {"items": items}


def _validate_pricing(w, label, problems, warnings):
    tiers_raw = w.get("tiers")
    if tiers_raw is None:
        problems.append(f"{label}: missing required field 'tiers'")
        return None
    if not isinstance(tiers_raw, list):
        problems.append(f"{label}: field 'tiers' must be a list "
                        f"(got {tiers_raw!r})")
        return None
    tiers = []
    for i, tier in enumerate(tiers_raw):
        tlabel = f"{label}.tiers[{i}]"
        if not isinstance(tier, dict):
            problems.append(f"{tlabel}: each tier must be an object "
                            f"(got {tier!r})")
            continue
        name = _req_str(tier, "name", tlabel, problems)
        price = tier.get("price")
        if price is None:
            problems.append(f"{tlabel}: missing required field "
                            f"'price'")
        elif not isinstance(price, str) or isinstance(price, bool):
            problems.append(f"{tlabel}: field 'price' must be a "
                            f"string rendered exactly as written, "
                            f"e.g. \"$49\" (got {price!r})")
            price = None
        elif not price.strip():
            problems.append(f"{tlabel}: field 'price' must not be "
                            f"empty")
            price = None
        period = _opt_str(tier, "period", tlabel, problems)
        features = tier.get("features")
        if features is None:
            problems.append(f"{tlabel}: missing required field "
                            f"'features'")
            features = None
        elif not isinstance(features, list) or \
                any(not isinstance(f, str) for f in features):
            problems.append(f"{tlabel}: field 'features' must be "
                            f"a list of strings (got {features!r})")
            features = None
        highlight = tier.get("highlight", False)
        if not isinstance(highlight, bool):
            problems.append(f"{tlabel}: field 'highlight' must be "
                            f"true or false (got {highlight!r})")
            highlight = False
        cta_label = _opt_str(tier, "cta_label", tlabel, problems)
        cta_url = _opt_str(tier, "cta_url", tlabel, problems)
        if (cta_label is None) != (cta_url is None):
            problems.append(f"{tlabel}: 'cta_label' and 'cta_url' "
                            f"must be given together (both or "
                            f"neither)")
        elif cta_url is not None:
            _check_link(cta_url, f"{tlabel}.cta_url", problems)
        tiers.append({"name": name, "price": price,
                      "period": period,
                      "features": features or [],
                      "highlight": highlight,
                      "cta_label": cta_label, "cta_url": cta_url})
    if isinstance(tiers_raw, list) and not tiers_raw:
        warnings.append(f"{label}: pricing has no tiers — the "
                        f"fragment will hold only its heading")
    return {"tiers": tiers}


def _parse_target(raw, label, problems):
    """ISO 8601 datetime WITH a UTC offset -> aware datetime.
    A naive value is a problem: a countdown that guesses a
    timezone counts to the wrong moment."""
    text = raw.strip()
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) \
        else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        problems.append(f"{label}: field 'target' is not a valid "
                        f"ISO 8601 datetime: {raw!r}")
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        problems.append(f"{label}: field 'target' must carry an "
                        f"explicit UTC offset, e.g. "
                        f"\"2027-06-01T09:00:00-07:00\" (got "
                        f"{raw!r}) — a countdown that guesses a "
                        f"timezone counts to the wrong moment")
        return None
    return dt


def _validate_countdown(w, label, problems, warnings):
    target_raw = _req_str(w, "target", label, problems)
    ended = _req_str(w, "ended_text", label, problems)
    text = _opt_str(w, "label", label, problems)
    dt = _parse_target(target_raw, label, problems) \
        if target_raw is not None else None
    if dt is not None and dt <= datetime.now(dt.tzinfo):
        warnings.append(
            f"{label}: countdown target {target_raw!r} is already "
            f"in the past — the fragment will show its ended_text")
    return {"target": dt, "target_raw": target_raw,
            "ended_text": ended, "label": text}


def _validate_entry(entry, label, problems):
    """One proof entry -> a cleaned dict (fields that failed
    are None; the run fails on problems anyway)."""
    if not isinstance(entry, dict):
        problems.append(f"{label}: each entry must be an object "
                        f"(got {entry!r})")
        return None
    name = _req_str(entry, "name", label, problems)
    text = _req_str(entry, "text", label, problems)
    date = _opt_str(entry, "date", label, problems)
    if date is not None:
        ok = bool(_DATE_RE.match(date))
        if ok:
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                ok = False
        if not ok:
            problems.append(f"{label}: field 'date' must be a "
                            f"real date as YYYY-MM-DD (got "
                            f"{date!r})")
            date = None
    rating = entry.get("rating")
    if rating is not None:
        if isinstance(rating, bool) or not isinstance(rating, int) \
                or not 1 <= rating <= 5:
            problems.append(f"{label}: field 'rating' must be an "
                            f"integer 1-5 (got {rating!r})")
            rating = None
    return {"name": name, "text": text, "date": date,
            "rating": rating}


def _load_entries_file(path_text, config_dir, label, problems):
    """entries_file (JSON or CSV), resolved against the
    config file's directory -> the raw entry list."""
    path = Path(path_text)
    if not path.is_absolute():
        path = config_dir / path
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        problems.append(f"{label}: cannot read entries_file "
                        f"{path_text!r}: {exc}")
        return None
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(f"{label}: entries_file {path_text!r} "
                            f"is not valid JSON: {exc}")
            return None
        if isinstance(data, dict):
            data = data.get("entries")
            if data is None:
                problems.append(f"{label}: entries_file "
                                f"{path_text!r}: object form must "
                                f"hold an 'entries' list")
                return None
        if not isinstance(data, list):
            problems.append(f"{label}: entries_file {path_text!r}: "
                            f"expected a list of entries (got "
                            f"{type(data).__name__})")
            return None
        return data
    if suffix == ".csv":
        rows = list(csv.reader(io.StringIO(raw)))
        if not rows:
            problems.append(f"{label}: entries_file {path_text!r} "
                            f"is empty")
            return None
        header = [c.strip() for c in rows[0]]
        for column in ("name", "text"):
            if column not in header:
                problems.append(f"{label}: entries_file "
                                f"{path_text!r}: CSV must have a "
                                f"{column!r} column (header: "
                                f"{rows[0]!r})")
                return None
        entries = []
        for row in rows[1:]:
            if not row or all(not c.strip() for c in row):
                continue
            entry = {}
            for j, column in enumerate(header):
                if column in ("name", "text", "date", "rating") \
                        and j < len(row) and row[j].strip():
                    value = row[j].strip()
                    if column == "rating":
                        try:
                            value = int(value)
                        except ValueError:
                            pass  # validation flags the string
                    entry[column] = value
            entries.append(entry)
        return entries
    problems.append(f"{label}: entries_file {path_text!r} must "
                    f"be a .json or .csv file")
    return None


def _validate_proof(w, label, config_dir, problems, warnings):
    inline = w.get("entries")
    from_file = w.get("entries_file")
    raw_entries = None
    if inline is not None and from_file is not None:
        problems.append(f"{label}: give 'entries' or "
                        f"'entries_file', not both")
    elif inline is not None:
        if not isinstance(inline, list):
            problems.append(f"{label}: field 'entries' must be a "
                            f"list (got {inline!r})")
        else:
            raw_entries = inline
    elif from_file is not None:
        if not isinstance(from_file, str) or not from_file.strip():
            problems.append(f"{label}: field 'entries_file' must "
                            f"be a non-empty string (got "
                            f"{from_file!r})")
        else:
            raw_entries = _load_entries_file(from_file, config_dir,
                                             label, problems)
    else:
        problems.append(f"{label}: proof needs 'entries' or "
                        f"'entries_file'")
    entries = []
    if raw_entries is not None:
        for i, entry in enumerate(raw_entries):
            cleaned = _validate_entry(entry, f"{label}.entries[{i}]",
                                      problems)
            if cleaned is not None:
                entries.append(cleaned)
        if not raw_entries:
            warnings.append(f"{label}: proof has no entries — the "
                            f"fragment will hold only its heading")
    return {"entries": entries}


_VALIDATORS = {"faq": _validate_faq, "pricing": _validate_pricing,
               "countdown": _validate_countdown}


def load_config(path):
    """Read and fully validate a config file. Returns
    (widgets, warnings): each widget is a cleaned dict with
    type, id, title and its type-specific data. Every problem
    found is collected into one ConfigError."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"cannot read config file {path!r}: {exc}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"config file {path!r} is not valid JSON: "
                        f"{exc}")
    if not isinstance(data, dict):
        raise ToolError(f"config file {path!r}: top level must be "
                        f"an object (got {type(data).__name__})")
    config_dir = Path(path).resolve().parent

    problems = []
    warnings = []
    widgets_raw = data.get("widgets")
    if widgets_raw is None:
        problems.append("config: missing required field 'widgets'")
        widgets_raw = []
    elif not isinstance(widgets_raw, list):
        problems.append(f"config: field 'widgets' must be a list "
                        f"(got {widgets_raw!r})")
        widgets_raw = []
    elif not widgets_raw:
        problems.append("config: field 'widgets' must hold at "
                        "least one widget")

    widgets = []
    filenames = {}
    for i, w in enumerate(widgets_raw):
        label = f"widgets[{i}]"
        if not isinstance(w, dict):
            problems.append(f"{label}: each widget must be an "
                            f"object (got {w!r})")
            continue
        wtype = w.get("type")
        if wtype is None:
            problems.append(f"{label}: missing required field "
                            f"'type'")
            continue
        if wtype not in WIDGET_TYPES:
            problems.append(f"{label}: unknown widget type "
                            f"{wtype!r} (valid types: "
                            f"{', '.join(WIDGET_TYPES)})")
            continue
        label = f"widgets[{i}] ({wtype})"
        wid = w.get("id", wtype)
        if not isinstance(wid, str) or not _ID_RE.match(wid):
            problems.append(f"{label}: field 'id' must be "
                            f"lowercase letters, digits and "
                            f"dashes, starting with a letter or "
                            f"digit (got {wid!r})")
            wid = wtype
        filename = f"{wid}.html"
        if filename in filenames:
            problems.append(f"{label}: output file {filename!r} "
                            f"is already used by "
                            f"{filenames[filename]} — give one of "
                            f"them a different 'id'")
        else:
            filenames[filename] = label
        title = _opt_str(w, "title", label, problems)
        if wtype == "proof":
            body = _validate_proof(w, label, config_dir,
                                   problems, warnings)
        else:
            body = _VALIDATORS[wtype](w, label, problems, warnings)
        widget = {"type": wtype, "id": wid, "title": title,
                  "file": filename}
        if body:
            widget.update(body)
        widgets.append(widget)

    if problems:
        raise ConfigError(problems)
    return widgets, warnings


# ---------------------------------------------------------------------------
# rendering — one self-contained fragment per widget
# ---------------------------------------------------------------------------

def _esc(text):
    return html.escape(text)


def _when_text(dt):
    """The countdown's static date line, e.g.
    '1 Jun 2027, 09:00 (UTC-07:00)' — shown with or without
    JavaScript, and derived only from the configured target."""
    offset = dt.utcoffset()
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return (f"{dt.day} {_MONTHS[dt.month - 1]} {dt.year}, "
            f"{dt.hour:02d}:{dt.minute:02d} "
            f"(UTC{sign}{total // 3600:02d}:"
            f"{(total % 3600) // 60:02d})")


def _heading(widget, css_class):
    if not widget["title"]:
        return ""
    return (f'\n  <h2 class="{css_class}">'
            f'{_esc(widget["title"])}</h2>')


def render_faq(w):
    """FAQ -> <details>/<summary> items (works with JavaScript
    disabled) plus the FAQPage JSON-LD generated from the SAME
    item list, escaped for embedding so a '<' in a question
    can never break out of the data block."""
    esc = html.escape
    items_html = ""
    for item in w["items"]:
        items_html += (
            f'\n    <details class="wk-faq-item">'
            f'<summary>{esc(item["q"])}</summary>'
            f'<div class="wk-faq-a">{esc(item["a"])}</div>'
            f'</details>')
    ld = {"@context": "https://schema.org", "@type": "FAQPage",
          "mainEntity": [
              {"@type": "Question", "name": item["q"],
               "acceptedAnswer": {"@type": "Answer",
                                  "text": item["a"]}}
              for item in w["items"]]}
    ld_text = json.dumps(ld, ensure_ascii=True, indent=2) \
        .replace("&", "\\u0026").replace("<", "\\u003c") \
        .replace(">", "\\u003e")
    label = w["title"] or "Frequently asked questions"
    css = (
        f".wk-faq{{font-family:{_FONT_STACK};max-width:720px;"
        f"margin:0 auto;color:#1b1b1b;line-height:1.55}}\n"
        f".wk-faq-title{{font-size:1.35rem;margin:0 0 14px}}\n"
        f".wk-faq-item{{border:1px solid #d8d8d8;"
        f"border-radius:10px;margin:0 0 10px;background:#fff}}\n"
        f".wk-faq-item summary{{cursor:pointer;"
        f"padding:12px 16px;font-weight:600}}\n"
        f".wk-faq-a{{padding:0 16px 14px}}")
    return (
        f"<!-- widget-kit v{__version__} · faq fragment — "
        f"self-contained; paste into any page -->\n"
        f'<section class="wk-faq" aria-label="{esc(label, quote=True)}">\n'
        f"  <style>\n{css}\n  </style>"
        f'{_heading(w, "wk-faq-title")}{items_html}\n'
        f'  <script type="application/ld+json">\n{ld_text}\n'
        f"  </script>\n</section>\n")


def render_pricing(w):
    """Pricing -> one card per tier. Prices render exactly as
    configured; a tier is highlighted only when the config
    flags it, and no badge text is invented."""
    esc = html.escape
    tiers_html = ""
    for tier in w["tiers"]:
        cls = "wk-tier wk-tier-hl" if tier["highlight"] \
            else "wk-tier"
        period = (f'<span class="wk-period">'
                  f'{esc(tier["period"])}</span>'
                  if tier["period"] else "")
        features = "".join(
            f"\n        <li>{esc(f)}</li>" for f in tier["features"])
        features_html = (f'\n      <ul class="wk-features">'
                         f"{features}\n      </ul>"
                         if tier["features"] else "")
        cta = ""
        if tier["cta_url"]:
            cta = (f'\n      <p class="wk-cta"><a href="'
                   f'{esc(tier["cta_url"], quote=True)}">'
                   f'{esc(tier["cta_label"])}</a></p>')
        tiers_html += (
            f'\n    <div class="{cls}">'
            f'\n      <h3 class="wk-tier-name">'
            f'{esc(tier["name"])}</h3>'
            f'\n      <p class="wk-price">{esc(tier["price"])}'
            f"{period}</p>{features_html}{cta}\n    </div>")
    label = w["title"] or "Pricing"
    css = (
        f".wk-pricing{{font-family:{_FONT_STACK};max-width:960px;"
        f"margin:0 auto;color:#1b1b1b;line-height:1.5}}\n"
        f".wk-pricing-title{{font-size:1.35rem;margin:0 0 14px}}\n"
        f".wk-tiers{{display:flex;gap:14px;flex-wrap:wrap}}\n"
        f".wk-tier{{flex:1 1 200px;border:1px solid #d8d8d8;"
        f"border-radius:12px;padding:18px;background:#fff}}\n"
        f".wk-tier-hl{{border:2px solid #2563eb;"
        f"box-shadow:0 4px 18px rgba(0,0,0,.08)}}\n"
        f".wk-tier-name{{margin:0 0 8px;font-size:1.05rem}}\n"
        f".wk-price{{font-size:1.8rem;font-weight:700;"
        f"margin:0 0 10px}}\n"
        f".wk-period{{font-size:1rem;font-weight:400;"
        f"color:#5c5c5c}}\n"
        f".wk-features{{margin:0;padding-left:20px}}\n"
        f".wk-features li{{margin:4px 0}}\n"
        f".wk-cta{{margin:14px 0 0}}\n"
        f".wk-cta a{{display:inline-block;padding:9px 18px;"
        f"background:#2563eb;color:#fff;border-radius:8px;"
        f"text-decoration:none;font-weight:600}}")
    return (
        f"<!-- widget-kit v{__version__} · pricing fragment — "
        f"self-contained; paste into any page -->\n"
        f'<section class="wk-pricing" aria-label="'
        f'{esc(label, quote=True)}">\n'
        f"  <style>\n{css}\n  </style>"
        f'{_heading(w, "wk-pricing-title")}\n'
        f'  <div class="wk-tiers">{tiers_html}\n  </div>\n'
        f"</section>\n")


def render_countdown(w):
    """Countdown -> a bar counting to the configured target.
    The fragment embeds the target only — never the generation
    time. With JavaScript off, the static target date still
    shows. A target already past renders ended_text alone."""
    esc = html.escape
    dt = w["target"]
    css = (
        f".wk-cd{{font-family:{_FONT_STACK};max-width:720px;"
        f"margin:0 auto;background:#141414;color:#f2f2f2;"
        f"border-radius:10px;padding:16px 20px;text-align:center;"
        f"line-height:1.5}}\n"
        f".wk-cd-label{{margin:0 0 4px;font-size:.95rem;"
        f"color:#c9c9c9}}\n"
        f".wk-cd-timer{{margin:0;font-size:1.5rem;"
        f"font-weight:700;font-variant-numeric:tabular-nums}}\n"
        f".wk-cd-timer .wk-unit{{font-size:.85rem;"
        f"font-weight:400;color:#c9c9c9}}\n"
        f".wk-cd-when{{margin:4px 0 0;font-size:.9rem;"
        f"color:#c9c9c9}}\n"
        f".wk-cd-ended{{margin:0;font-size:1.15rem;"
        f"font-weight:600}}")
    if dt <= datetime.now(dt.tzinfo):
        return (
            f"<!-- widget-kit v{__version__} · countdown "
            f"fragment (target already past — ended text) -->\n"
            f'<div class="wk-cd wk-cd-over">\n'
            f"  <style>\n{css}\n  </style>\n"
            f'  <p class="wk-cd-ended">{esc(w["ended_text"])}</p>\n'
            f"</div>\n")
    element_id = f"wk-cd-{w['id']}"
    epoch_ms = int(dt.timestamp() * 1000)
    label_html = (f'\n  <p class="wk-cd-label">'
                  f'{esc(w["label"])}</p>' if w["label"] else "")
    js = (
        f"(function(){{\n"
        f"var el=document.getElementById("
        f"{json.dumps(element_id)});\n"
        f"if(!el)return;\n"
        f"var target=parseInt(el.getAttribute(\"data-target\"),"
        f"10);\n"
        f"var timer=el.querySelector(\".wk-cd-timer\");\n"
        f"var ended=el.querySelector(\".wk-cd-ended\");\n"
        f"function pad(n){{return (n<10?\"0\":\"\")+n;}}\n"
        f"function tick(){{\n"
        f"var left=target-Date.now();\n"
        f"if(left<=0){{timer.hidden=true;ended.hidden=false;"
        f"return;}}\n"
        f"var s=Math.floor(left/1000);\n"
        f"var d=Math.floor(s/86400);s-=d*86400;\n"
        f"var h=Math.floor(s/3600);s-=h*3600;\n"
        f"var m=Math.floor(s/60);var sec=s-m*60;\n"
        f"el.querySelector(\"[data-d]\").textContent=d;\n"
        f"el.querySelector(\"[data-h]\").textContent=pad(h);\n"
        f"el.querySelector(\"[data-m]\").textContent=pad(m);\n"
        f"el.querySelector(\"[data-s]\").textContent=pad(sec);\n"
        f"setTimeout(tick,1000);\n"
        f"}}\n"
        f"tick();\n"
        f"}})();")
    return (
        f"<!-- widget-kit v{__version__} · countdown fragment — "
        f"self-contained; paste into any page -->\n"
        f'<div class="wk-cd" id="{esc(element_id, quote=True)}" '
        f'data-target="{epoch_ms}">\n'
        f"  <style>\n{css}\n  </style>{label_html}\n"
        f'  <p class="wk-cd-timer"><span data-d>–</span> '
        f'<span class="wk-unit">days</span> '
        f'<span data-h>–</span> <span class="wk-unit">hrs</span> '
        f'<span data-m>–</span> <span class="wk-unit">min</span> '
        f'<span data-s>–</span> <span class="wk-unit">sec</span>'
        f"</p>\n"
        f'  <p class="wk-cd-when">Ends {_when_text(dt)}</p>\n'
        f'  <p class="wk-cd-ended" hidden>'
        f'{esc(w["ended_text"])}</p>\n'
        f"  <script>\n{js}\n  </script>\n</div>\n")


def render_proof(w):
    """Proof -> one card per supplied entry, in the order
    given, verbatim. Nothing is computed about the entries:
    no average, no count on the page, no summary claim."""
    esc = html.escape
    cards = ""
    for entry in w["entries"]:
        stars = ""
        if entry["rating"] is not None:
            marks = "★" * entry["rating"] + \
                "☆" * (5 - entry["rating"])
            stars = (f'\n      <p class="wk-proof-stars" '
                     f'role="img" aria-label="Rated '
                     f'{entry["rating"]} out of 5">{marks}</p>')
        date = (f'\n      <p class="wk-proof-date">'
                f'{esc(entry["date"])}</p>'
                if entry["date"] else "")
        cards += (
            f'\n    <figure class="wk-proof-card">{stars}'
            f'\n      <blockquote class="wk-proof-text">'
            f'{esc(entry["text"])}</blockquote>'
            f'\n      <figcaption class="wk-proof-name">'
            f'{esc(entry["name"])}</figcaption>{date}'
            f"\n    </figure>")
    label = w["title"] or "What customers say"
    css = (
        f".wk-proof{{font-family:{_FONT_STACK};max-width:960px;"
        f"margin:0 auto;color:#1b1b1b;line-height:1.55}}\n"
        f".wk-proof-title{{font-size:1.35rem;margin:0 0 14px}}\n"
        f".wk-proof-cards{{display:grid;gap:14px;"
        f"grid-template-columns:repeat(auto-fit,"
        f"minmax(240px,1fr))}}\n"
        f".wk-proof-card{{border:1px solid #ddd6c9;"
        f"border-radius:12px;padding:16px;background:#fff;"
        f"margin:0}}\n"
        f".wk-proof-stars{{margin:0 0 8px;color:#d97706;"
        f"letter-spacing:2px}}\n"
        f".wk-proof-text{{margin:0 0 10px}}\n"
        f".wk-proof-name{{font-weight:600}}\n"
        f".wk-proof-date{{margin:2px 0 0;color:#5c5c5c;"
        f"font-size:.9rem}}")
    return (
        f"<!-- widget-kit v{__version__} · proof fragment — "
        f"self-contained; paste into any page -->\n"
        f'<section class="wk-proof" aria-label="'
        f'{esc(label, quote=True)}">\n'
        f"  <style>\n{css}\n  </style>"
        f'{_heading(w, "wk-proof-title")}\n'
        f'  <div class="wk-proof-cards">{cards}\n  </div>\n'
        f"</section>\n")


_RENDERERS = {"faq": render_faq, "pricing": render_pricing,
              "countdown": render_countdown, "proof": render_proof}


def _widget_summary(w):
    """One human line of countable facts about a widget, for
    the make report."""
    if w["type"] == "faq":
        return f"{len(w['items'])} question(s)"
    if w["type"] == "pricing":
        return f"{len(w['tiers'])} tier(s)"
    if w["type"] == "countdown":
        return f"target {_when_text(w['target'])}"
    return f"{len(w['entries'])} supplied entr" + \
        ("y" if len(w["entries"]) == 1 else "ies")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_make(a):
    widgets, warnings = load_config(a.config)
    rendered = []
    for w in widgets:
        text = _RENDERERS[w["type"]](w)
        rendered.append((w, text, len(text.encode("utf-8"))))
    out_dir = Path(a.out)
    if out_dir.exists() and not out_dir.is_dir():
        raise ToolError(f"output path {a.out!r} exists and is "
                        f"not a directory")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        for w, text, _size in rendered:
            (out_dir / w["file"]).write_text(text,
                                             encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"cannot write fragments into "
                        f"{a.out!r}: {exc}")
    exit_code = 1 if warnings else 0
    if a.json:
        print(json.dumps({
            "tool": TOOL, "version": __version__,
            "command": "make",
            "config_file": Path(a.config).name,
            "output_dir": str(out_dir),
            "fragments": [
                {"widget": w["type"], "id": w["id"],
                 "file": w["file"], "bytes": size,
                 "summary": _widget_summary(w)}
                for w, _text, size in rendered],
            "warnings": warnings,
        }))
        return exit_code
    print(f"{TOOL} v{__version__} — make · config "
          f"{Path(a.config).name}")
    print(f"Wrote {len(rendered)} fragment(s) into {out_dir}:")
    for w, _text, size in rendered:
        print(f"  {w['file']} — {size:,} bytes · {w['type']} · "
              f"{_widget_summary(w)}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  ! {warning}")
    else:
        print("Warnings: none")
    return exit_code


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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    _JsonAwareParser.json_mode = "--json" in argv
    ap = _JsonAwareParser(
        prog=TOOL,
        description="Generate the four boring site widgets — "
                    "FAQ (+ JSON-LD), pricing, countdown, "
                    "social proof — as static fragments you "
                    "own: no account, no view metering, no "
                    "third-party script (stdlib only, local "
                    "only).")
    sub = ap.add_subparsers(dest="command", required=True,
                            parser_class=_JsonAwareParser)

    p_make = sub.add_parser(
        "make", help="validate the config and write one "
                     "fragment per widget into --out")
    p_make.add_argument("--config", required=True,
                        help="config JSON file")
    p_make.add_argument("--out", required=True,
                        help="output directory for the fragments")
    p_make.add_argument("--json", action="store_true",
                        help="one JSON object instead of text "
                             "output")
    p_make.set_defaults(func=cmd_make)

    a = ap.parse_args(argv)

    def fail(exc):
        if isinstance(exc, ConfigError) and \
                getattr(a, "json", False):
            print(json.dumps({"error": str(exc),
                              "problems": exc.problems}))
            return 2
        if getattr(a, "json", False):
            print(json.dumps({"error": str(exc)}))
        elif isinstance(exc, ConfigError):
            print(f"ERROR: {exc}:")
            for problem in exc.problems:
                print(f"  - {problem}")
        else:
            print(f"ERROR: {exc}")
        return 2

    try:
        return a.func(a)
    except ToolError as exc:
        return fail(exc)
    except BrokenPipeError:
        return 2


if __name__ == "__main__":
    sys.exit(main())
