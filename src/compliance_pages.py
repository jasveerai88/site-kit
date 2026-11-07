#!/usr/bin/env python3
"""compliance-pages — turn one site-profile JSON into the
privacy, terms and cookie pages a small website needs, plus a
self-hosted consent banner, generated locally as files you own.

Pure Python standard library. Local only: no network, no
uploads, no accounts. The profile never leaves your machine,
and the generated pages make no external requests either.

Consent platforms rent the same pages back to you PER DOMAIN:
CookieYes bills $10/$25/$55 per domain per month (an agency
running ten client sites pays roughly $250 a month, with no
multi-domain bundle) and iubenda charges $4.99–79.99 per site
per month plus pageview overages. But the pages are documents,
and a document is a file, not a subscription. compliance-pages
is the file: one JSON profile of stated facts in, static
privacy.html / terms.html / cookies.html plus a dependency-free
consent banner (banner.html + consent.js) out — generate once
per site, own the files, no per-domain rent, no view metering.

WHAT THIS TOOL IS NOT — read this before the output:

  * These are TEMPLATES, stamped on every page: "Template —
    have a qualified professional review this page before
    relying on it." They are NOT legal advice and NOT a
    guarantee that any law is satisfied. The tool never uses
    the word "compliant" about its own output, and neither
    should you.
  * The tool NEVER invents a fact. A fact the documents need
    but the profile does not state becomes a loud placeholder
    — [TO FILL: ...] — in the output, listed in the manifest,
    and `make` exits 1 while any remain. Sections appear only
    when the profile's facts call for them: no analytics in
    the profile, no analytics section claiming any.
  * The banner records a visitor's choice in the visitor's
    OWN browser (localStorage). It does NOT log consent on a
    server, does NOT implement IAB TCF, and BLOCKS NOTHING by
    itself: the site owner must still wire their analytics
    and marketing scripts to load only after the stored
    choice allows them (consent.js publishes the choice as
    window.cpConsent and a "cp:consent" event for exactly
    that wiring — see the manifest). Laws differ by
    jurisdiction; the profile drives a modest generic or
    Canada-flavoured variant, nothing more.

The profile is a single JSON file. Every field is a STATED
FACT supplied by the site owner; absent means "not stated",
never "the tool may guess":

  business    {"name", "legal_form", "country", "province",
               "address", "contact_email", "contact_name"} —
              who operates the site. "country" selects the
              variant: "Canada" (any case) -> Canada-flavoured
              labels; anything else -> generic.
  site        {"name", "url"} — the website itself.
  as_of       generation / "last updated" date, YYYY-MM-DD.
              May also be given with --as-of (which wins).
              One of the two is REQUIRED: the stamp date is
              never read from the machine clock.
  data_collected  list of strings — the personal information
              the site collects, in the owner's words.
  data_use    list of strings — what it is used for.
  services    {"hosting": str|null, "analytics": str|null,
               "payments": str|null, "embeds": [str]} — the
              third-party services the site uses. A key set
              to null (or omitted) means "not used". If the
              whole block is absent, the profile states
              nothing about services and the privacy page
              carries a placeholder instead of a guess.
  cookies     {"essential": bool, "analytics": bool,
               "marketing": bool} — which cookie categories
              the site sets. All three keys are required when
              the block is present. Absent block = not stated
              (placeholder), NOT "no cookies".
  consent_note  a string describing how analytics/marketing
              scripts are gated on the visitor's consent
              choice on this site — the owner's words for
              wiring that actually exists.
  retention   a string — how long collected information is
              kept, in the owner's words.
  governing_law  a string — the governing-law line for the
              terms page, in the owner's words.
  quotes_are_estimates  bool, default false — when true, the
              terms page gains a "Quotes and estimates"
              section saying quotes are estimates until
              confirmed in writing.
  pages       subset of ["privacy", "terms", "cookies"],
              default all three — which pages to generate.
              (consent.js, banner.html and manifest.txt are
              always generated.)

Commands:
  make      --profile FILE --out DIR [--as-of DATE] [--json]
            — generate the pages, banner and manifest into
            DIR. Exit 0 when the profile was complete (no
            placeholders, no contradictions); exit 1 when
            the files were written but need attention
            (placeholders remain and/or contradictions were
            flagged); exit 2 on a clean error (nothing
            written).
  check     --profile FILE [--json] — report the profile's
            gaps (facts the documents need but the profile
            does not state) and contradictions, WITHOUT
            writing anything. Exit 0 complete, 1 gaps or
            contradictions, 2 error.

Exit codes: 0 = ok · 1 = ATTENTION — files written (make) or
report printed (check), but placeholders/contradictions need
a human · 2 = ERROR — clean message, never a traceback; with
--json the error is {"error": ...}. A corrupt profile is an
error and is NEVER overwritten or silently wiped.
"""
import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path
from string import Template

__version__ = "0.1.0"
TOOL = "compliance-pages"

PAGES = ("privacy", "terms", "cookies")
PAGE_FILES = {"privacy": "privacy.html", "terms": "terms.html",
              "cookies": "cookies.html"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STORAGE_KEY = "cp-consent-v1"

# The template notice printed at the top of every generated
# page. It is part of the honesty contract: it ships WITH the
# document, not just in this tool's README.
TEMPLATE_NOTICE = (
    "Template — this page was generated from a site profile "
    "by compliance-pages. It is a starting point, not legal "
    "advice: have a qualified professional review it before "
    "relying on it.")

# One canonical loud placeholder per fact the documents need.
# Placeholders are constants (never built from profile data),
# so counting "[TO FILL:" occurrences in the generated files
# is an exact audit of what the profile failed to state.
PH = {
    "business.name":
        "[TO FILL: business name]",
    "business.legal_form":
        "[TO FILL: legal form of the business — e.g. "
        "corporation, sole proprietorship, partnership]",
    "business.country":
        "[TO FILL: country the business is based in]",
    "business.address":
        "[TO FILL: business mailing address]",
    "business.contact_email":
        "[TO FILL: contact email for privacy and terms "
        "questions]",
    "site.name":
        "[TO FILL: website name]",
    "site.url":
        "[TO FILL: website address (URL)]",
    "data_collected":
        "[TO FILL: the personal information this site "
        "collects]",
    "data_use":
        "[TO FILL: what the collected information is used "
        "for]",
    "services":
        "[TO FILL: third-party services this site uses — "
        "hosting, analytics, payments, embeds — or remove "
        "this section if there are none]",
    "cookies":
        "[TO FILL: which cookies this site sets — essential, "
        "analytics, marketing]",
    "consent_note":
        "[TO FILL: how analytics and marketing scripts are "
        "gated on the visitor's consent choice]",
    "retention":
        "[TO FILL: how long collected information is kept]",
    "governing_law":
        "[TO FILL: the governing law for these terms]",
}


class ToolError(Exception):
    """A clean, user-facing failure (printed as ERROR, exit 2)."""


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def parse_date(value, label):
    """Strict YYYY-MM-DD -> date, or a clean ToolError naming
    `label`."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ToolError(f"{label} must be a date as YYYY-MM-DD "
                        f"(got {value!r})")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"{label} is not a real calendar date: "
                        f"{value!r}")


def _reject_json_constant(name):
    raise ValueError(f"invalid constant {name}")


def load_json_file(path, kind):
    """Read + parse a JSON file -> its data, or a clean
    ToolError. The file is only READ here; a corrupt file is
    reported, never repaired in place."""
    if not path.is_file():
        raise ToolError(f"{kind} not found: {path}")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolError(f"could not read {kind} {path.name} "
                        f"({exc.__class__.__name__}) — the file "
                        f"was left untouched")
    try:
        return json.loads(text, parse_constant=_reject_json_constant)
    except ValueError as exc:
        raise ToolError(f"{kind} {path.name} is not valid JSON: "
                        f"{exc} — the file was left untouched")


def _esc(text):
    return html.escape(text, quote=True)


def _fill(value, ph_key):
    """A stated fact, or its loud placeholder. In HTML output
    the placeholder is wrapped in a highlighted span by
    _fill_h; this plain form is for the JS config and any
    non-HTML context."""
    return value if value else PH[ph_key]


def _fill_h(value, ph_key):
    """_fill for HTML: stated facts are escaped text; a
    placeholder ships as a visibly highlighted span whose text
    is still the literal [TO FILL: ...] marker."""
    if value:
        return _esc(value)
    return f'<span class="tofill">{PH[ph_key]}</span>'


# --------------------------------------------------------------------------
# the profile — load + structural validation
# (structural problems are collected and raised together, exit 2;
#  missing FACTS are not structural — they become placeholders)
# --------------------------------------------------------------------------

def _opt_str(block, key, label, problems):
    """An optional string field: absent/null/empty -> None
    (not stated); a non-string is a structural problem."""
    raw = block.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        problems.append(f"{label} must be a string "
                        f"(got {raw!r})")
        return None
    return raw.strip() or None


def _opt_str_list(block, key, label, problems):
    """An optional list-of-strings field: absent/null -> None;
    an empty list states nothing either, so it also -> None
    (the fact is treated as not stated and will placeholder)."""
    raw = block.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list):
        problems.append(f"{label} must be a list of strings "
                        f"(got {raw!r})")
        return None
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            problems.append(f"{label}[{i}] must be a non-empty "
                            f"string")
        else:
            out.append(item.strip())
    return out or None


def _party(raw, label, keys, problems):
    """A {"name", ...} block of optional strings -> dict of
    key -> str|None. A block of the wrong type is structural;
    a missing block means every fact in it is unstated."""
    if raw is None:
        return {k: None for k in keys}
    if not isinstance(raw, dict):
        problems.append(f"{label} must be an object of fields "
                        f"({', '.join(keys)})")
        return {k: None for k in keys}
    return {k: _opt_str(raw, k, f"{label}.{k}", problems)
            for k in keys}


def validate_profile(data):
    """Validate a parsed profile -> a clean profile dict.
    Structural problems (wrong types, unknown page names, an
    impossible date, a half-given cookies block) are collected
    and raised together in ONE ToolError — nothing is
    generated from a structurally broken profile. Missing
    facts pass through as None and become placeholders."""
    if not isinstance(data, dict):
        raise ToolError("the profile must be a JSON object of "
                        "fields (business, site, as_of, "
                        "data_collected, services, cookies, "
                        "...)")
    problems = []
    business = _party(data.get("business"), "business",
                      ("name", "legal_form", "country",
                       "province", "address", "contact_email",
                       "contact_name"), problems)
    site = _party(data.get("site"), "site", ("name", "url"),
                  problems)
    as_of = None
    if data.get("as_of") is not None:
        try:
            as_of = parse_date(data.get("as_of"),
                               "'as_of'").isoformat()
        except ToolError as exc:
            problems.append(str(exc))
    data_collected = _opt_str_list(data, "data_collected",
                                   "data_collected", problems)
    data_use = _opt_str_list(data, "data_use", "data_use",
                             problems)
    services = None
    raw_services = data.get("services")
    if raw_services is not None:
        if not isinstance(raw_services, dict):
            problems.append("services must be an object with "
                            "hosting, analytics, payments and "
                            "embeds")
        else:
            services = {
                "hosting": _opt_str(raw_services, "hosting",
                                    "services.hosting", problems),
                "analytics": _opt_str(raw_services, "analytics",
                                      "services.analytics",
                                      problems),
                "payments": _opt_str(raw_services, "payments",
                                     "services.payments",
                                     problems),
                "embeds": _opt_str_list(raw_services, "embeds",
                                        "services.embeds",
                                        problems) or [],
            }
    cookies = None
    raw_cookies = data.get("cookies")
    if raw_cookies is not None:
        if not isinstance(raw_cookies, dict):
            problems.append("cookies must be an object with "
                            "essential, analytics and marketing")
        else:
            cookies = {}
            for key in ("essential", "analytics", "marketing"):
                val = raw_cookies.get(key)
                if not isinstance(val, bool):
                    problems.append(
                        f"cookies.{key} is required when the "
                        f"cookies block is given, and must be "
                        f"true or false (got {val!r})")
                    val = False
                cookies[key] = val
    consent_note = _opt_str(data, "consent_note", "consent_note",
                            problems)
    retention = _opt_str(data, "retention", "retention",
                         problems)
    governing_law = _opt_str(data, "governing_law",
                             "governing_law", problems)
    quotes = data.get("quotes_are_estimates", False)
    if not isinstance(quotes, bool):
        problems.append(f"quotes_are_estimates must be true or "
                        f"false (got {quotes!r})")
        quotes = False
    pages = list(PAGES)
    raw_pages = data.get("pages")
    if raw_pages is not None:
        if not isinstance(raw_pages, list) or not raw_pages:
            problems.append("pages must be a non-empty list "
                            "drawn from: " + ", ".join(PAGES))
        else:
            bad = [p for p in raw_pages if p not in PAGES]
            if bad:
                problems.append(
                    f"pages names unknown page(s): "
                    f"{', '.join(repr(p) for p in bad)} — "
                    f"available pages: {', '.join(PAGES)}")
            else:
                pages = [p for p in PAGES if p in raw_pages]
    if problems:
        listing = "\n".join(f"  - {p}" for p in problems)
        raise ToolError(f"the profile has {len(problems)} "
                        f"problem(s) — nothing was written:\n"
                        f"{listing}")
    country = business["country"]
    variant = ("canada" if country and
               country.casefold() == "canada" else "generic")
    return {
        "business": business,
        "site": site,
        "as_of": as_of,
        "data_collected": data_collected,
        "data_use": data_use,
        "services": services,
        "cookies": cookies,
        "consent_note": consent_note,
        "retention": retention,
        "governing_law": governing_law,
        "quotes_are_estimates": quotes,
        "pages": pages,
        "variant": variant,
    }


# --------------------------------------------------------------------------
# analysis — gaps (unstated facts) and contradictions
# --------------------------------------------------------------------------

def analyse(profile):
    """-> (gaps, contradictions).

    gaps: ordered list of {"field", "placeholder"} for every
    fact the documents need that the profile does not state,
    in schema order. contradictions: ordered list of strings
    naming facts that fight each other. Both are derived from
    the profile alone — the same analysis drives `check`,
    `make`'s manifest and the exit codes."""
    b = profile["business"]
    s = profile["site"]
    gaps = []

    def gap(field):
        gaps.append({"field": field, "placeholder": PH[field]})

    if not b["name"]:
        gap("business.name")
    if not b["legal_form"]:
        gap("business.legal_form")
    if not b["country"]:
        gap("business.country")
    if not b["address"]:
        gap("business.address")
    if not b["contact_email"]:
        gap("business.contact_email")
    if not s["name"]:
        gap("site.name")
    if not s["url"]:
        gap("site.url")
    if not profile["data_collected"]:
        gap("data_collected")
    if not profile["data_use"]:
        gap("data_use")
    if profile["services"] is None:
        gap("services")
    if profile["cookies"] is None:
        gap("cookies")
    if not profile["retention"]:
        gap("retention")
    if not profile["governing_law"]:
        gap("governing_law")

    contradictions = []
    cookies = profile["cookies"]
    services = profile["services"]
    if "cookies" in profile["pages"] and cookies is not None \
            and not any(cookies.values()):
        contradictions.append(
            "the profile asks for a cookies page but also "
            "says the site sets no cookies (essential, "
            "analytics and marketing are all false) — the "
            "generated cookies page states that no cookies "
            "are set; drop \"cookies\" from pages or correct "
            "the cookie facts")
    if services is not None and services["analytics"] \
            and cookies is not None and not cookies["analytics"]:
        contradictions.append(
            f"an analytics service is declared "
            f"({services['analytics']}) but analytics cookies "
            f"are marked off — analytics tools usually set "
            f"cookies; reconcile services.analytics with "
            f"cookies.analytics")
    optional_cookies = cookies is not None and \
        (cookies["analytics"] or cookies["marketing"])
    if optional_cookies and not profile["consent_note"]:
        contradictions.append(
            "analytics and/or marketing cookies are declared "
            "but the profile has no consent_note describing "
            "how those scripts are gated on the visitor's "
            "consent choice — the banner records a choice "
            "but blocks nothing by itself; add a consent_note "
            "once that wiring exists (until then the cookies "
            "page carries a placeholder where the note "
            "belongs)")
    return gaps, contradictions


# --------------------------------------------------------------------------
# rendering — self-contained HTML pages (escaped, deterministic)
# --------------------------------------------------------------------------

_CSS = """
body { font-family: Georgia, 'Times New Roman', serif; color: #222;
  margin: 0; background: #f7f5f0; }
.page { max-width: 760px; margin: 0 auto; background: #fff;
  padding: 48px 56px; }
.kicker { font-size: 12px; letter-spacing: 3px; text-transform:
  uppercase; color: #8a7f5c; margin: 0 0 8px; }
h1 { font-size: 30px; line-height: 1.2; margin: 0 0 6px; }
h2 { font-size: 16px; letter-spacing: 1px; text-transform:
  uppercase; color: #5c5340; margin: 32px 0 10px;
  border-bottom: 1px solid #e3ddcd; padding-bottom: 6px; }
h3 { font-size: 16px; margin: 20px 0 6px; }
p { line-height: 1.6; margin: 0 0 12px; }
ul { line-height: 1.6; margin: 0 0 12px; padding-left: 20px; }
table { width: 100%; border-collapse: collapse; margin: 8px 0 12px; }
th { text-align: left; font-size: 13px; border-bottom: 2px solid
  #222; padding: 6px 8px; }
td { padding: 8px; border-bottom: 1px solid #e9e4d6;
  vertical-align: top; }
.meta { color: #555; font-size: 14px; margin: 14px 0 4px; }
.notice { border: 2px solid #b3261e; background: #fdf0ef;
  color: #6b1712; padding: 12px 16px; margin: 20px 0;
  font-size: 14px; line-height: 1.5; }
.tofill { background: #ffe58a; color: #5c4300; padding: 0 3px;
  font-weight: bold; }
.foot { margin-top: 44px; padding-top: 14px;
  border-top: 1px solid #e3ddcd; color: #777; font-size: 13px;
  line-height: 1.6; }
"""

_PAGE = Template("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>$title</title>
<style>$css</style>
</head>
<body>
<div class="page">
<p class="kicker">$kicker</p>
<h1>$heading</h1>
<p class="meta">Last updated: $as_of</p>
<div class="notice">$notice</div>
$body
<div class="foot">$foot</div>
</div>
</body>
</html>
""")


def _stamp(profile, as_of):
    """The footer stamp on every page: what generated this,
    when, from whose profile — and the standing warning."""
    who = profile["business"]["name"] or profile["site"]["name"] \
        or "the site profile"
    return (f"Template generated by compliance-pages "
            f"v{__version__} on {_esc(as_of)} from the site "
            f"profile of {_esc(who)}. This page is a "
            f"starting-point template, not legal advice, and "
            f"not a guarantee that any law is satisfied. Laws "
            f"differ by jurisdiction.")


def _page(profile, as_of, page_key, heading, body):
    site_name = profile["site"]["name"]
    title = heading + (f" — {site_name}" if site_name else "")
    return _PAGE.substitute(
        title=_esc(title), css=_CSS, kicker=_esc(
            site_name or "Website"),
        heading=_esc(heading), as_of=_esc(as_of),
        notice=_esc(TEMPLATE_NOTICE), body=body,
        foot=_stamp(profile, as_of))


def _ul(items):
    lis = "\n".join(f"<li>{_esc(i)}</li>" for i in items)
    return f"<ul>\n{lis}\n</ul>"


def _contact_section(profile):
    """The closing contact section, identical on all three
    pages: the profile's contact email, or its placeholder."""
    email = profile["business"]["contact_email"]
    name = profile["business"]["contact_name"]
    line = "Questions about this page: contact "
    line += _fill_h(email, "business.contact_email")
    if name:
        line += f" ({_esc(name)})"
    line += "."
    return ("Contact", f"<p>{line}</p>")


def render_privacy(profile, as_of):
    """-> (html, [section names]). Sections appear only when
    the profile's facts call for them; an unstated fact shows
    as its loud placeholder inside the section that needs it,
    never as an invented sentence."""
    b = profile["business"]
    s = profile["site"]
    sections = []
    parts = []

    # 1. Who we are
    place = _fill_h(b["country"], "business.country")
    if b["province"]:
        place = f"{_esc(b['province'])}, " + place
    who = (f"<p>This policy covers {_fill_h(s['name'], 'site.name')}"
           f" ({_fill_h(s['url'], 'site.url')}), operated by "
           f"{_fill_h(b['name'], 'business.name')}, a "
           f"{_fill_h(b['legal_form'], 'business.legal_form')} "
           f"based in {place}"
           f", at {_fill_h(b['address'], 'business.address')}."
           f"</p>")
    sections.append("Who we are")
    parts.append(f"<h2>Who we are</h2>\n{who}")

    # 2. Information we collect
    if profile["data_collected"]:
        body = ("<p>The site collects the following personal "
                "information:</p>\n"
                + _ul(profile["data_collected"]))
    else:
        body = (f"<p>{_fill_h(None, 'data_collected')}</p>")
    sections.append("Information we collect")
    parts.append(f"<h2>Information we collect</h2>\n{body}")

    # 3. How we use information
    if profile["data_use"]:
        body = ("<p>The information is used as follows:</p>\n"
                + _ul(profile["data_use"]))
    else:
        body = f"<p>{_fill_h(None, 'data_use')}</p>"
    sections.append("How we use information")
    parts.append(f"<h2>How we use information</h2>\n{body}")

    # 4. Third-party services
    services = profile["services"]
    if services is None:
        body = f"<p>{_fill_h(None, 'services')}</p>"
    else:
        rows = []
        for key, label in (("hosting", "Hosting"),
                           ("analytics", "Analytics"),
                           ("payments", "Payments")):
            if services[key]:
                rows.append((label, services[key]))
        if not rows and not services["embeds"]:
            body = ("<p>The site profile declares no "
                    "third-party services.</p>")
        else:
            chunks = []
            if rows:
                trs = "\n".join(
                    f"<tr><td>{_esc(label)}</td>"
                    f"<td>{_esc(value)}</td></tr>"
                    for label, value in rows)
                chunks.append(
                    "<table>\n<tr><th>Service</th>"
                    "<th>Provider</th></tr>\n"
                    f"{trs}\n</table>")
            if services["embeds"]:
                chunks.append(
                    "<p>Embedded content from third parties:"
                    "</p>\n" + _ul(services["embeds"]))
            body = "\n".join(chunks)
    sections.append("Third-party services")
    parts.append(f"<h2>Third-party services</h2>\n{body}")

    # 5. Cookies — a summary pointing at the cookies page
    cookies = profile["cookies"]
    if cookies is None:
        body = f"<p>{_fill_h(None, 'cookies')}</p>"
    else:
        cats = [name for name in ("essential", "analytics",
                                  "marketing") if cookies[name]]
        if cats:
            body = (f"<p>This site sets {', '.join(cats)} "
                    f"cookies. The cookies page describes each "
                    f"category and how to control it.</p>")
        else:
            body = ("<p>According to the site profile, this "
                    "site sets no cookies.</p>")
    sections.append("Cookies")
    parts.append(f"<h2>Cookies</h2>\n{body}")

    # 6. How long we keep information
    if profile["retention"]:
        body = f"<p>{_esc(profile['retention'])}</p>"
    else:
        body = f"<p>{_fill_h(None, 'retention')}</p>"
    sections.append("How long we keep information")
    parts.append(
        f"<h2>How long we keep information</h2>\n{body}")

    # 7. Your choices and how to contact us
    if profile["variant"] == "canada":
        authority = ("If we cannot resolve a concern, you may "
                     "contact the Office of the Privacy "
                     "Commissioner of Canada, and — where your "
                     "province has its own privacy commissioner "
                     "for private-sector matters — that office "
                     "as well.")
    else:
        authority = ("If we cannot resolve a concern, you may "
                     "contact your local data-protection "
                     "authority.")
    _, contact_html = _contact_section(profile)
    body = (f"<p>You may ask what personal information we "
            f"hold about you, ask for it to be corrected, and "
            f"ask for it to be deleted where the law allows. "
            f"{_esc(authority)}</p>\n{contact_html}")
    sections.append("Your choices and how to contact us")
    parts.append(
        f"<h2>Your choices and how to contact us</h2>\n{body}")

    return _page(profile, as_of, "privacy", "Privacy Policy",
                 "\n".join(parts)), sections


def render_terms(profile, as_of):
    """-> (html, [section names])."""
    b = profile["business"]
    s = profile["site"]
    sections = []
    parts = []

    # 1. Who operates this site
    body = (f"<p>{_fill_h(s['name'], 'site.name')} "
            f"({_fill_h(s['url'], 'site.url')}) is a website "
            f"of {_fill_h(b['name'], 'business.name')}, a "
            f"{_fill_h(b['legal_form'], 'business.legal_form')} "
            f"based in "
            f"{_fill_h(b['country'], 'business.country')}.</p>")
    sections.append("Who operates this site")
    parts.append(f"<h2>Who operates this site</h2>\n{body}")

    # 2. Using this site
    body = ("<p>You may browse this site and contact us "
            "through it for the purposes the site offers. Do "
            "not misuse the site: no attempting to break its "
            "security, no submitting false information through "
            "its forms, and no copying the site wholesale. We "
            "try to keep the information on this site accurate "
            "and current, but we do not warrant that it is "
            "complete or error-free, and details such as prices "
            "and availability may change without notice.</p>")
    sections.append("Using this site")
    parts.append(f"<h2>Using this site</h2>\n{body}")

    # 3. Quotes and estimates — only when the profile says so
    if profile["quotes_are_estimates"]:
        body = ("<p>Any quote or estimate we give — on this "
                "site, by email or in a generated proposal — "
                "is an estimate based on the information "
                "available at the time. It becomes a firm "
                "price only when we confirm it in writing for "
                "the agreed scope of work.</p>")
        sections.append("Quotes and estimates")
        parts.append(f"<h2>Quotes and estimates</h2>\n{body}")

    # 4. Site content and intellectual property
    body = (f"<p>The text, images and layout of this site "
            f"belong to {_fill_h(b['name'], 'business.name')} "
            f"or are used with permission. You may print or "
            f"save pages for your own use in dealing with us; "
            f"any other reuse needs our written permission "
            f"first.</p>")
    sections.append("Site content and intellectual property")
    parts.append(
        f"<h2>Site content and intellectual property</h2>\n"
        f"{body}")

    # 5. Limits of liability
    body = ("<p>To the extent permitted by law, we are not "
            "liable for indirect or consequential losses "
            "arising from use of this site or reliance on its "
            "content. Nothing in these terms limits liability "
            "that cannot be limited under applicable law.</p>")
    sections.append("Limits of liability")
    parts.append(f"<h2>Limits of liability</h2>\n{body}")

    # 6. Governing law
    if profile["governing_law"]:
        body = (f"<p>These terms are governed by "
                f"{_esc(profile['governing_law'])}.</p>")
    else:
        body = (f"<p>These terms are governed by "
                f"{_fill_h(None, 'governing_law')}.</p>")
    sections.append("Governing law")
    parts.append(f"<h2>Governing law</h2>\n{body}")

    # 7. Changes to these terms
    body = ("<p>We may update these terms from time to time. "
            "The version on this page, with its \"last "
            "updated\" date, is the current one.</p>")
    sections.append("Changes to these terms")
    parts.append(f"<h2>Changes to these terms</h2>\n{body}")

    # 8. Contact
    heading, contact_html = _contact_section(profile)
    sections.append(heading)
    parts.append(f"<h2>{heading}</h2>\n{contact_html}")

    return _page(profile, as_of, "terms", "Terms of Use",
                 "\n".join(parts)), sections


def render_cookies(profile, as_of):
    """-> (html, [section names]). Category subsections
    appear only for categories the profile declares."""
    sections = []
    parts = []

    # 1. What cookies are
    body = ("<p>Cookies are small text files a website asks "
            "your browser to store. Some are needed for the "
            "site to work at all; others remember choices, "
            "measure visits, or support marketing. This page "
            "describes, by category, the cookies the site "
            "profile says this site sets.</p>")
    sections.append("What cookies are")
    parts.append(f"<h2>What cookies are</h2>\n{body}")

    # 2. Cookies this site sets
    cookies = profile["cookies"]
    chunks = []
    subsections = []
    if cookies is None:
        chunks.append(f"<p>{_fill_h(None, 'cookies')}</p>")
    elif not any(cookies.values()):
        chunks.append("<p>According to the site profile, "
                      "this site sets no cookies.</p>")
    else:
        if cookies["essential"]:
            subsections.append("Essential")
            chunks.append(
                "<h3>Essential</h3>\n<p>Cookies needed for "
                "the site to function — security, load "
                "balancing, and remembering the consent "
                "choice described below. These are always on "
                "because the site cannot work without them."
                "</p>")
        if cookies["analytics"]:
            subsections.append("Analytics")
            service = None
            if profile["services"] is not None:
                service = profile["services"]["analytics"]
            text = ("<h3>Analytics</h3>\n<p>Cookies that "
                    "measure how visitors use the site, so we "
                    "can see which pages help people and which "
                    "do not.")
            if service:
                text += (f" Provided by {_esc(service)}.")
            text += (" These load only if you accept them in "
                     "the consent banner.</p>")
            chunks.append(text)
        if cookies["marketing"]:
            subsections.append("Marketing")
            chunks.append(
                "<h3>Marketing</h3>\n<p>Cookies used to "
                "measure advertising and to show relevant "
                "ads on other sites. These load only if you "
                "accept them in the consent banner.</p>")
    sections.append("Cookies this site sets")
    parts.append("<h2>Cookies this site sets</h2>\n"
                 + "\n".join(chunks))

    # 3. The consent banner and your stored choice
    chunks = [
        "<p>The consent banner on this site is served from "
        "this site's own files — no third-party consent "
        "service is involved. When you make a choice, the "
        "banner stores it in your own browser's local "
        "storage (under the key \"" + STORAGE_KEY + "\"), "
        "not in a cookie and not on a server: nothing about "
        "your choice is sent anywhere. Clearing your "
        "browser's site data deletes the stored choice, and "
        "the banner will ask again.</p>",
        "<p>The banner itself blocks nothing. It records "
        "your choice, and this site's optional scripts are "
        "responsible for honouring it, as described here:"
        "</p>",
    ]
    optional = cookies is not None and \
        (cookies["analytics"] or cookies["marketing"])
    if profile["consent_note"]:
        chunks.append(f"<p>{_esc(profile['consent_note'])}</p>")
    elif optional:
        chunks.append(
            f"<p>{_fill_h(None, 'consent_note')}</p>")
    else:
        chunks.append(
            "<p>This site sets no optional (analytics or "
            "marketing) cookies, so there is nothing further "
            "to gate.</p>")
    sections.append("The consent banner and your stored choice")
    parts.append(
        "<h2>The consent banner and your stored choice</h2>\n"
        + "\n".join(chunks))

    # 4. Managing cookies in your browser
    body = ("<p>Every major browser lets you view, block "
            "and delete cookies in its settings, and to "
            "browse privately so cookies are discarded when "
            "you close the window. Blocking essential cookies "
            "may break parts of this site.</p>")
    sections.append("Managing cookies in your browser")
    parts.append(
        f"<h2>Managing cookies in your browser</h2>\n{body}")

    # 5. Contact
    heading, contact_html = _contact_section(profile)
    sections.append(heading)
    parts.append(f"<h2>{heading}</h2>\n{contact_html}")

    html_text = _page(profile, as_of, "cookies", "Cookie Policy",
                      "\n".join(parts))
    return html_text, sections + \
        [f"category: {name}" for name in subsections]


# --------------------------------------------------------------------------
# the consent banner — banner.html fragment + consent.js
# (self-hosted, dependency-free, no network requests of any kind;
#  the choice lives in the visitor's own browser local storage)
# --------------------------------------------------------------------------

_JS = Template("""/* compliance-pages consent wiring — generated file.
   Self-hosted and dependency-free: it makes no network
   requests of any kind. It reads the banner fragment
   (id "cp-banner", from banner.html), and when the visitor
   makes a choice it stores that choice in the visitor's own
   browser local storage under the key below. Nothing is
   sent to any server; there is no consent log.
   The banner records a choice — it blocks nothing by
   itself. Site owners: gate your analytics and marketing
   scripts on the stored choice. The choice is published as
   window.cpConsent.get() and as a "cp:consent" event on
   window, both on page load (when a choice already exists)
   and the moment a new choice is saved.
   window.cpConsent.reset() clears the stored choice and
   shows the banner again — wire it to a "cookie settings"
   link so visitors can change their mind. */
(function () {
  "use strict";
  var CONFIG = $config;
  var KEY = CONFIG.storageKey;

  function read() {
    try {
      var raw = window.localStorage.getItem(KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function write(choice) {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(choice));
    } catch (e) {
      /* storage unavailable (private mode, disabled): the
         choice simply does not persist, and the banner will
         ask again on the next page. */
    }
  }

  var bannerEl = null;
  var current = null;

  function publish(choice) {
    current = choice;
    window.cpConsent = {
      get: function () { return current; },
      reset: function () {
        try {
          window.localStorage.removeItem(KEY);
        } catch (e) { /* storage unavailable: nothing stored */ }
        current = null;
        if (bannerEl) { bannerEl.hidden = false; }
      }
    };
    try {
      window.dispatchEvent(
        new window.CustomEvent("cp:consent", { detail: choice }));
    } catch (e) { /* older browsers: cpConsent.get() remains */ }
  }

  function onReady(fn) {
    if (document.readyState !== "loading") {
      fn();
    } else {
      document.addEventListener("DOMContentLoaded", fn);
    }
  }

  onReady(function () {
    var banner = document.getElementById("cp-banner");
    bannerEl = banner;
    var existing = read();
    if (existing) {
      publish(existing);
      if (banner) { banner.hidden = true; }
      return;
    }
    if (!banner) { return; }
    banner.hidden = false;

    function save(choice) {
      choice.essential = true;
      choice.savedAt = new Date().toISOString();
      write(choice);
      publish(choice);
      banner.hidden = true;
    }

    var ok = banner.querySelector("[data-cp-ok]");
    if (ok) {
      ok.addEventListener("click", function () {
        save({ analytics: false, marketing: false });
      });
    }
    var acceptAll = banner.querySelector("[data-cp-accept-all]");
    if (acceptAll) {
      acceptAll.addEventListener("click", function () {
        var choice = { analytics: false, marketing: false };
        if (CONFIG.analytics) { choice.analytics = true; }
        if (CONFIG.marketing) { choice.marketing = true; }
        save(choice);
      });
    }
    var saveBtn = banner.querySelector("[data-cp-save]");
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        var choice = { analytics: false, marketing: false };
        var boxes = banner.querySelectorAll("[data-cp-category]");
        for (var i = 0; i < boxes.length; i++) {
          var name = boxes[i].getAttribute("data-cp-category");
          if (name === "analytics" || name === "marketing") {
            choice[name] = boxes[i].checked === true;
          }
        }
        save(choice);
      });
    }
  });
})();
""")


def render_consent_js(profile):
    """The consent wiring. The only profile data embedded is
    the site name and which optional categories exist, as a
    JSON config with "<" escaped so no profile string can
    break out of the script."""
    cookies = profile["cookies"] or {}
    config = {
        "storageKey": STORAGE_KEY,
        "siteName": profile["site"]["name"] or "",
        "analytics": bool(cookies.get("analytics")),
        "marketing": bool(cookies.get("marketing")),
    }
    config_json = json.dumps(config, indent=2).replace(
        "<", "\\u003c")
    return _JS.substitute(config=config_json)


_BANNER_CSS = """
#cp-banner { position: fixed; left: 16px; right: 16px;
  bottom: 16px; z-index: 9999; background: #1c2430;
  color: #f2f4f7; padding: 16px 20px; border-radius: 10px;
  font-family: Helvetica, Arial, sans-serif; font-size: 14px;
  line-height: 1.5; box-shadow: 0 6px 24px rgba(0,0,0,.35); }
#cp-banner p { margin: 0 0 10px; }
#cp-banner label { display: inline-block; margin: 0 14px 8px 0; }
#cp-banner .cp-actions { margin-top: 6px; }
#cp-banner button { font-size: 14px; padding: 8px 16px;
  margin-right: 8px; border-radius: 6px; border: 1px solid
  #f2f4f7; background: #f2f4f7; color: #1c2430;
  cursor: pointer; }
#cp-banner button.cp-secondary { background: transparent;
  color: #f2f4f7; }
"""


def render_banner(profile):
    """The banner fragment: paste before </body> and load
    consent.js after it. Category checkboxes appear only for
    optional categories the profile declares; with none, the
    banner is a plain essential-cookies notice."""
    cookies = profile["cookies"] or {}
    optional = [name for name in ("analytics", "marketing")
                if cookies.get(name)]
    site = _fill_h(profile["site"]["name"], "site.name")
    lines = [
        "<!-- compliance-pages consent banner — generated "
        "fragment.",
        "     Paste this fragment into each page just before "
        "</body>, and load",
        "     consent.js after it:",
        '     <script src="consent.js" defer></script>',
        "     Without consent.js the banner does nothing: the "
        "script stores the",
        "     visitor's choice in their own browser local "
        "storage and publishes",
        "     it as window.cpConsent / a \"cp:consent\" event "
        "for your other",
        "     scripts to honour. The banner blocks nothing "
        "by itself. -->",
        '<div id="cp-banner" class="cp-banner" hidden>',
        "<style>" + _BANNER_CSS + "</style>",
    ]
    if optional:
        cats = " and ".join(optional)
        lines.append(
            f"<p>{site} uses essential cookies to run, and "
            f"{_esc(cats)} cookies only with your permission. "
            f"Choose below; essential cookies are always on "
            f"because the site cannot work without them.</p>")
        for name in optional:
            lines.append(
                f'<label><input type="checkbox" '
                f'data-cp-category="{name}"> '
                f'{name.capitalize()} cookies</label>')
        lines.append(
            '<div class="cp-actions">'
            '<button type="button" data-cp-accept-all>'
            'Accept all</button>'
            '<button type="button" class="cp-secondary" '
            'data-cp-save>Save my choices</button></div>')
    else:
        lines.append(
            f"<p>{site} uses only essential cookies — the "
            f"kind a site needs in order to work, such as "
            f"remembering this notice. It sets no analytics "
            f"or marketing cookies.</p>")
        lines.append(
            '<div class="cp-actions">'
            '<button type="button" data-cp-ok>OK</button>'
            '</div>')
    if "cookies" in profile["pages"]:
        lines.append(
            '<p><a href="cookies.html" style="color:#f2f4f7">'
            'Read the cookie policy</a></p>')
    lines.append("</div>")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# placeholder audit + manifest
# --------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\[TO FILL: [^\]]*\]")


def audit_placeholders(files):
    """Count [TO FILL: ...] markers in the generated
    DOCUMENTS (the manifest lists them, so it is excluded —
    counting it would double-count). -> (total, items) with
    items in canonical file order, first-appearance order:
    {"text", "count", "files"}."""
    counts = {}
    order = []
    total = 0
    for name, text in files:
        for match in _PLACEHOLDER_RE.findall(text):
            total += 1
            if match not in counts:
                counts[match] = {"text": match, "count": 0,
                                 "files": []}
                order.append(match)
            counts[match]["count"] += 1
            if name not in counts[match]["files"]:
                counts[match]["files"].append(name)
    return total, [counts[key] for key in order]


def _shown(value):
    return value if value else "(not stated)"


def _profile_value_lines(profile, as_of):
    """The profile values the documents were built from, in
    fixed schema order — the manifest's audit trail."""
    b = profile["business"]
    s = profile["site"]
    lines = [
        ("business.name", _shown(b["name"])),
        ("business.legal_form", _shown(b["legal_form"])),
        ("business.country", _shown(b["country"])),
        ("business.province", _shown(b["province"])),
        ("business.address", _shown(b["address"])),
        ("business.contact_email", _shown(b["contact_email"])),
        ("business.contact_name", _shown(b["contact_name"])),
        ("site.name", _shown(s["name"])),
        ("site.url", _shown(s["url"])),
        ("as_of", as_of),
    ]
    for key in ("data_collected", "data_use"):
        value = profile[key]
        lines.append((key, f"{len(value)} item(s) stated"
                      if value else "(not stated)"))
    services = profile["services"]
    if services is None:
        lines.append(("services", "(not stated)"))
    else:
        for key in ("hosting", "analytics", "payments"):
            lines.append((f"services.{key}",
                          _shown(services[key])))
        lines.append(("services.embeds",
                      f"{len(services['embeds'])} item(s) "
                      f"stated" if services["embeds"]
                      else "(none)"))
    cookies = profile["cookies"]
    if cookies is None:
        lines.append(("cookies", "(not stated)"))
    else:
        for key in ("essential", "analytics", "marketing"):
            lines.append((f"cookies.{key}",
                          "true" if cookies[key] else "false"))
    lines.append(("consent_note",
                  _shown(profile["consent_note"])))
    lines.append(("retention", _shown(profile["retention"])))
    lines.append(("governing_law",
                  _shown(profile["governing_law"])))
    lines.append(("quotes_are_estimates",
                  "true" if profile["quotes_are_estimates"]
                  else "false"))
    lines.append(("pages", ", ".join(profile["pages"])))
    return lines


def render_manifest(profile, profile_name, as_of, date_source,
                    file_sections, placeholders, ph_items,
                    contradictions):
    """The plain-text manifest: what was generated, from
    which stated values, what is still placeholder, and the
    wiring the owner still owes. Deterministic."""
    out = [f"{TOOL} v{__version__} — generation manifest",
           f"Profile: {profile_name}",
           f"Stamped date: {as_of} (from {date_source})",
           f"Variant: {profile['variant']}", "",
           "Files written:"]
    for name in list(file_sections) + ["manifest.txt"]:
        out.append(f"  {name}")
    out += ["", "Sections generated:"]
    for name, sections in file_sections.items():
        if sections:
            out.append(f"  {name}: {'; '.join(sections)}")
    out += ["", "Profile values used:"]
    for key, value in _profile_value_lines(profile, as_of):
        out.append(f"  {key}: {value}")
    out += ["",
            f"Placeholders in the generated documents: "
            f"{placeholders}",
            "  (counted in the pages, banner.html and "
            "consent.js; this manifest",
            "   lists the markers, so it is not counted "
            "itself)"]
    for item in ph_items:
        out.append(f"  {item['text']} x{item['count']} — "
                   f"{', '.join(item['files'])}")
    out += ["", f"Contradictions flagged: "
                f"{len(contradictions)}"]
    for text in contradictions:
        out.append(f"  - {text}")
    out += ["",
            "Owner wiring still to do:",
            "  - Paste banner.html into every page before "
            "</body> and load",
            "    consent.js after it.",
            "  - Gate analytics and marketing scripts on "
            "the stored choice:",
            "    consent.js publishes window.cpConsent.get() "
            "and fires a",
            "    \"cp:consent\" event; the banner records a "
            "choice and blocks",
            "    nothing by itself.",
            "  - Consent is stored only in the visitor's "
            "browser (local",
            "    storage); there is no server-side consent "
            "log and no IAB",
            "    TCF support.",
            "  - Have a qualified professional review the "
            "generated pages",
            "    before relying on them. These are "
            "templates, not legal",
            "    advice; laws differ by jurisdiction."]
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

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


def _json_arg(p):
    p.add_argument("--json", action="store_true",
                   help="print one JSON object instead of text")


def _resolve_as_of(profile, flag_value):
    """The stamp date: --as-of wins, then the profile's
    as_of. Never the machine clock — a missing date is a
    clean error naming both ways to pin one."""
    if flag_value is not None:
        return parse_date(flag_value, "--as-of").isoformat(), \
            "the --as-of flag"
    if profile["as_of"]:
        return profile["as_of"], "the profile's as_of"
    raise ToolError("no generation date: set \"as_of\" in "
                    "the profile or pass --as-of YYYY-MM-DD "
                    "— the stamped date is never read from "
                    "the clock")


def _load_profile(a):
    path = Path(a.profile)
    data = load_json_file(path, "profile")
    return path, validate_profile(data)


def cmd_make(a):
    profile_path, profile = _load_profile(a)
    as_of, date_source = _resolve_as_of(profile, a.as_of)
    gaps, contradictions = analyse(profile)
    documents = []          # (filename, text), canonical order
    file_sections = {}
    builders = {"privacy": render_privacy,
                "terms": render_terms,
                "cookies": render_cookies}
    for page in PAGES:
        if page in profile["pages"]:
            text, sections = builders[page](profile, as_of)
            documents.append((PAGE_FILES[page], text))
            file_sections[PAGE_FILES[page]] = sections
    documents.append(("consent.js", render_consent_js(profile)))
    file_sections["consent.js"] = []
    documents.append(("banner.html", render_banner(profile)))
    file_sections["banner.html"] = []
    total, ph_items = audit_placeholders(documents)
    manifest = render_manifest(
        profile, profile_path.name, as_of, date_source,
        file_sections, total, ph_items, contradictions)
    documents.append(("manifest.txt", manifest))
    file_sections["manifest.txt"] = []

    out_dir = Path(a.out)
    if out_dir.exists() and not out_dir.is_dir():
        raise ToolError(f"--out {a.out} exists and is not a "
                        f"folder — nothing was written")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, text in documents:
            (out_dir / name).write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"could not write into {a.out} "
                        f"({exc.__class__.__name__}: {exc})")
    attention = bool(total or contradictions)
    if a.json:
        print(json.dumps({
            "tool": TOOL, "version": __version__,
            "command": "make", "profile": profile_path.name,
            "as_of": as_of, "variant": profile["variant"],
            "out_dir": str(out_dir),
            "files": [name for name, _ in documents],
            "sections": {name: secs for name, secs
                         in file_sections.items() if secs},
            "placeholders": {"total": total, "items": ph_items},
            "gaps": gaps,
            "contradictions": contradictions,
            "attention": attention,
        }, indent=2))
    else:
        names = ", ".join(name for name, _ in documents)
        print(f"Wrote {len(documents)} file(s) into "
              f"{out_dir}: {names}")
        if total:
            print(f"  Placeholders remaining: {total} — the "
                  f"profile did not state every fact the "
                  f"documents use (listed in manifest.txt)")
        else:
            print("  Placeholders remaining: 0 — the profile "
                  "stated every fact the documents use")
        if contradictions:
            print(f"  Contradictions flagged: "
                  f"{len(contradictions)} (listed in "
                  f"manifest.txt)")
        print("  compliance-pages generated templates only — "
              "not legal advice; have them reviewed before "
              "relying on them.")
    return 1 if attention else 0


def cmd_check(a):
    profile_path, profile = _load_profile(a)
    gaps, contradictions = analyse(profile)
    date_set = a.as_of is not None or profile["as_of"] is not None
    all_gaps = list(gaps)
    if not date_set:
        all_gaps.append({"field": "as_of", "placeholder": None})
    complete = not all_gaps and not contradictions
    if a.json:
        print(json.dumps({
            "tool": TOOL, "version": __version__,
            "command": "check", "profile": profile_path.name,
            "variant": profile["variant"],
            "as_of": (a.as_of or profile["as_of"]),
            "pages": profile["pages"],
            "gaps": all_gaps,
            "contradictions": contradictions,
            "complete": complete,
        }, indent=2))
    else:
        print(f"{TOOL} v{__version__} — check · profile "
              f"{profile_path.name}")
        pages = ", ".join(profile["pages"])
        print(f"Variant: {profile['variant']} · pages make "
              f"would generate: {pages} "
              f"(+ consent.js, banner.html, manifest.txt "
              f"always)")
        if date_set:
            print(f"Generation date: "
                  f"{a.as_of or profile['as_of']}")
        else:
            print("Generation date: NOT SET — make will "
                  "refuse until as_of is in the profile or "
                  "--as-of is passed")
        print("")
        if all_gaps:
            print(f"GAPS — facts the documents need that "
                  f"the profile does not state "
                  f"({len(all_gaps)}):")
            for g in all_gaps:
                if g["placeholder"]:
                    print(f"  - {g['field']} → "
                          f"{g['placeholder']}")
                else:
                    print(f"  - {g['field']} → set a date")
        else:
            print("GAPS: none — the profile states every "
                  "fact the documents use.")
        if contradictions:
            print(f"CONTRADICTIONS ({len(contradictions)}):")
            for text in contradictions:
                print(f"  - {text}")
        print("")
        if complete:
            print("Verdict: COMPLETE — make will generate "
                  "with no placeholders.")
        else:
            print("Verdict: INCOMPLETE — fill the gaps above "
                  "in the profile; anything left unstated "
                  "ships as a loud [TO FILL: ...] placeholder, "
                  "never as an invented fact.")
    return 0 if complete else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    _JsonAwareParser.json_mode = "--json" in argv
    ap = _JsonAwareParser(
        prog=TOOL,
        description="Generate privacy, terms and cookie "
                    "pages plus a self-hosted consent banner "
                    "from one site-profile JSON (stdlib only, "
                    "local only, templates — not legal "
                    "advice).")
    sub = ap.add_subparsers(dest="command", required=True,
                            parser_class=_JsonAwareParser)

    p_make = sub.add_parser(
        "make", help="generate the pages, consent.js, "
                     "banner.html and manifest.txt into a "
                     "folder (exit 1 if placeholders or "
                     "contradictions remain)")
    p_make.add_argument("--profile", required=True,
                        help="the site-profile JSON file")
    p_make.add_argument("--out", required=True,
                        help="folder to write the generated "
                             "files into (created if missing)")
    p_make.add_argument("--as-of", default=None,
                        help="generation date, YYYY-MM-DD "
                             "(overrides the profile's as_of; "
                             "one of the two is required)")
    _json_arg(p_make)
    p_make.set_defaults(func=cmd_make)

    p_check = sub.add_parser(
        "check", help="report the profile's gaps and "
                      "contradictions without writing "
                      "anything")
    p_check.add_argument("--profile", required=True,
                         help="the site-profile JSON file")
    p_check.add_argument("--as-of", default=None,
                         help="generation date, YYYY-MM-DD "
                              "(only reported; check writes "
                              "nothing)")
    _json_arg(p_check)
    p_check.set_defaults(func=cmd_check)

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


if __name__ == "__main__":
    sys.exit(main())
