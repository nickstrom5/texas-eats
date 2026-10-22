"""Writes the public website in docs/ from the same data the app ships (data/app/places.json plus the data/app/detail-*.json files that
hold TABC licenses, reported alcohol sales, phones, websites and inspection histories).

Pages: the landing page; six statewide hand-checked guides (barbecue joints, Tex-Mex, taquerías, kolaches, chicken-fried steak, the
oldest places); MICHELIN & James Beard; an explainer of the inspection scores Austin, El Paso and Arlington publish (counts only, no
place named); one page per big city or town with enough hand-checked or honored places to say something real, plus a cities index; the
web app (/explore/); privacy; terms; 404; sitemap.xml, robots.txt, site.webmanifest and playbook/site-numbers.json. Everything listed
is hand-checked research or public records; nothing comes from Google, Yelp or any ratings site, and nothing is ranked by ratings.
Ported from fl-eats/scripts/make-site.py.

Rules the copy keeps (scripts/qa-site.py checks them):
- Every number is counted from the data here, never typed in. Texas has no statewide restaurant list, so our lists are "places we
  list": no sentence claims "every" or "all N" restaurants.
- "Checked" only for the hand-checked lists (`hc`, a 2025-26 source for each place).
- Texas has no statewide inspection grade and we compute none: the site shows each city's own score and band (Austin's Green /
  Yellow / Red, El Paso's passing line of 70, Arlington's letter grade), with the date, labeled as the city's.
- A place whose latest score is in its city's low band (Austin Red, El Paso below 70, Arlington F) is never named in a title,
  description, lede or other promotional spot. The inspections page names no place at all and has no "worst" list.
- Every page carries a hash-pinned Content-Security-Policy; inline scripts and styles are hashed after the page is final.

Usage (from tx-eats/): .venv/bin/python scripts/make-site.py           (github.io address, BASE /texas-eats)
                       TX_DOMAIN=texas.eatsranked.com .venv/bin/python scripts/make-site.py   (once Nick's CNAME resolves)
Re-run it after every data rebuild, then check the pages with scripts/qa-site.py. Never hand-edit docs/*.html.
"""
import base64
import datetime as dt
import glob
import gzip
import hashlib
import html
import json
import math
import os
import re
import struct
import urllib.parse
from collections import Counter, defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS = f"{ROOT}/docs"
# Where the site lives. Until Nick's Cloudflare record (CNAME texas -> nickstrom5.github.io, DNS only) resolves, GitHub Pages serves
# the project address. When `dig texas.eatsranked.com` shows the CNAME, run with TX_DOMAIN=texas.eatsranked.com and push: this
# writes docs/CNAME, and GitHub then forwards the old github.io links (the ones inside shipped app builds).
CUSTOM_DOMAIN = os.environ.get("TX_DOMAIN", "").strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
REPO = "texas-eats"
DOMAIN = f"https://{CUSTOM_DOMAIN}" if CUSTOM_DOMAIN else f"https://nickstrom5.github.io/{REPO}"
BASE = "" if CUSTOM_DOMAIN else f"/{REPO}"     # path prefix for root-relative links
BRAND = "Texas Eats"
APP_NAME = "Texas Eats: Restaurants"
TAGLINE = "BBQ, Tex-Mex & taquerías"
EMAIL = "nick@eatsranked.com"   # Nick, 2026-10-12: the site's contact address (Cloudflare Email Routing)
PUBLISHED = "2026-10-21"        # the site's first publication (Article datePublished)
SITE_REV = "2026-10-21"         # the last change to this generator's own copy or code: bump it when you change the words
POLICY_UPDATED = "2026-10-21"   # privacy policy and terms: bump only when their text changes
CHECKED = "fall 2026"
STORAGE_PREFIX = "txeats-"      # the web app's localStorage keys (other state sites share the nickstrom5.github.io origin)
# Texas Eats is one of the Eats Ranked state sites: the hub (eatsranked.com) lists it as a subOrganization, and every page says so
# from this side too (the footer line and the Organization's parentOrganization), in Wisconsin's words.
HUB = {"@type": "Organization", "@id": "https://eatsranked.com/#organization", "name": "Eats Ranked", "url": "https://eatsranked.com/"}
ORG_ID = f"{DOMAIN}/#org"
# the site's Organization as other pages name it (author, publisher): the same @id as the full node on the landing page
ORG_REF = {"@type": "Organization", "@id": ORG_ID, "name": BRAND, "url": f"{DOMAIN}/",
           "logo": {"@type": "ImageObject", "url": f"{DOMAIN}/icon-512.png", "width": 512, "height": 512}, "parentOrganization": HUB}

# ---------------------------------------------------------------- data: the core file plus the region detail files
D = json.load(open(f"{ROOT}/data/app/places.json"))
assert D.get("generated"), "data/app/places.json has no 'generated' field: the pipeline hasn't finished writing it"
DETAIL_SRC = {}
for _f in sorted(glob.glob(f"{ROOT}/data/app/detail-*.json")):
    DETAIL_SRC.update(json.load(open(_f)))
assert DETAIL_SRC, "data/app/detail-*.json are missing"


def merged(r):
    """One place with its detail fields put back: the core's "in" is [city, band, score, date]; the detail's "in" is {n, h}."""
    det = DETAIL_SRC.get(r["id"]) or {}
    out = dict(r)
    ins = r.get("in")
    if isinstance(ins, list) and len(ins) >= 4:
        out["in"] = {"j": ins[0], "b": ins[1], "s": ins[2], "d": ins[3]}
    for k, v in det.items():
        if k == "in" and isinstance(v, dict):
            out["in"] = {**(out.get("in") or {}), **v}
        else:
            out[k] = v
    return out


RECS = [merged(r) for r in D["places"]]
TODAY = max(str(D.get("generated") or SITE_REV)[:10], SITE_REV)   # sitemap lastmod and dateModified move with the data or the copy
INS_THROUGH = D.get("inspections_through") or {}
LIQ_UPDATED = D.get("liquor_updated") or ""
MIX_FROM, MIX_TO = D.get("mixbev_from") or "", D.get("mixbev_to") or ""
CITIES, CUISINES, COUNTIES = D["cities"], D["cuisines"], D["counties"]
RESULTS, ITYPES = D.get("results") or [], D.get("itypes") or []
BBQ, TEXMEX, TAQUERIA, KOLACHE, CFS, OLDEST, BREWPUB, FB = 1, 2, 4, 8, 16, 32, 64, 128
MI = ["", "MICHELIN Recommended", "Bib Gourmand", "1 MICHELIN Star", "2 MICHELIN Stars", "3 MICHELIN Stars"]
INS_CITY = ["Austin", "El Paso", "Arlington"]
INS_KEY = ["aus", "elp", "arl"]
INS_AGENCY = ["Austin Public Health", "the City of El Paso Department of Public Health", "the City of Arlington"]
INS_URL = ["https://data.austintexas.gov/Health-and-Community-Services/Food-Establishment-Inspection-Scores/ecmv-9xxi",
           "https://foodscores.elpasotexas.gov/", "https://opendata.arlingtontx.gov/datasets/food-establishments"]
LOW_BANDS = {"Red", "Below 70", "F"}
TABC_SEARCH = "https://www.tabc.texas.gov/public-information/tabc-public-inquiry/"
TABC_DATA = "https://data.texas.gov/d/7hf9-qc9f"
MIXBEV_DATA = "https://data.texas.gov/d/naix-2893"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
NUM_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def hdate(iso):
    """2026-09-24 -> September 24, 2026"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    return f"{MONTHS[int(m[2]) - 1]} {int(m[3])}, {m[1]}" if m else str(iso or "")


def hmonth(iso):
    m = re.match(r"(\d{4})-(\d{2})", str(iso or ""))
    return f"{MONTHS[int(m[2]) - 1]} {m[1]}" if m else str(iso or "")


def plural(n, one, many=None):
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def words_num(n):
    return NUM_WORDS[n] if 0 <= n < len(NUM_WORDS) else f"{n:,}"


def safe_url(u):
    """Only http(s) links leave the site; a bare host ("example.com/menu") gets https://. Anything else is dropped."""
    u = str(u or "").strip()
    if re.fullmatch(r"https?://[^\s\"'<>\\]+", u, re.I):
        return u
    if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}(?:[/?#][^\s\"'<>\\]*)?", u, re.I):
        return "https://" + u
    return ""


# Websites we must not link (pipeline/website_blocklist.json): hacked, expired or another business's site. A blocked link is
# dropped, never the place. qa-site.py fails if a blocked domain or URL appears anywhere in docs/.
BLOCKLIST = json.load(open(f"{ROOT}/pipeline/website_blocklist.json"))
for _b in BLOCKLIST:
    assert _b.get("match", "domain") in ("domain", "url") and (_b.get("url") or _b.get("domain")), f"bad blocklist entry {_b}"
BLOCKED_LINKS = []   # (place, link) pairs the blocklist dropped from this build


def url_key(u):
    """A URL compared without its scheme, a leading www., a trailing slash or letter case."""
    return re.sub(r"^(?:https?:)?//(?:www\.)?", "", str(u or "").strip().lower()).rstrip("/")


def blocked_site(u):
    host = (urllib.parse.urlsplit(u).hostname or "").rstrip(".").removeprefix("www.")
    for b in BLOCKLIST:
        if b.get("match", "domain") == "url":
            if url_key(u) == url_key(b.get("url") or b["domain"]):
                return b
        else:
            d = b["domain"].strip().lower().rstrip(".").removeprefix("www.")
            if host == d or host.endswith("." + d):
                return b
    return None


class P:
    """One place, with the same meaning the app gives each field (TexasEats/Models/Place.swift)."""

    def __init__(self, r):
        self.r = r
        self.name = str(r["n"])
        self.city = CITIES[r["c"]] if r.get("c") is not None else ""
        self.county = COUNTIES[r["co"]] if r.get("co") is not None else None
        self.cuisine = CUISINES[r["cu"]] if r.get("cu") is not None else ""
        self.addr = (r.get("a") or "").strip().rstrip(",").strip()
        self.zip = str(r.get("z") or "")
        self.lat, self.lon = r.get("la"), r.get("lo")
        self.tags = r.get("g") or 0
        self.chain = (r.get("ch") or 0) >= 5
        self.venue = r.get("v") == 1
        self.ip = r.get("ip")
        self.founded = r.get("f") if isinstance(r.get("f"), int) else None
        self.fn = r.get("fn") or ""
        self.dishes = (r.get("dish") or "").replace("; ", ", ")
        self.season = r.get("seas") or ""
        self.note = r.get("note") or ""
        self.site = safe_url(r.get("w"))
        if self.site and blocked_site(self.site):
            BLOCKED_LINKS.append((self.name, self.site))
            self.site = ""   # the link goes, the place stays
        self.jbf = r.get("jbf") or ""
        self.h = r.get("h") or 0
        self.mi = r.get("mi") if r.get("mi") in range(1, len(MI)) else 0
        self.hc = r.get("hc") == 1   # hand-checked against a 2025-26 source; the only places the themed guides list
        self.lic = r.get("lic") or []   # TABC licenses: [[id, type, expires]]
        self.al = r.get("al")           # reported alcohol sales, $K over the header's 12 months
        ins = r.get("in")
        self.ins = ins if isinstance(ins, dict) and ins.get("d") else None
        self.band = RESULTS[self.ins["b"]] if self.ins and 0 <= self.ins.get("b", -1) < len(RESULTS) else None
        self.ins_city = self.ins["j"] if self.ins else None

    def featured_key(self):
        # the app's "Featured first": honored places, then documented founding year, then name
        return (-(self.ip if self.ip is not None else -1), self.founded or 9999, self.name.lower())

    def jb_label(self):
        return ("America's Classic" if self.h & 1 else "James Beard winner" if self.h & 2 else "James Beard finalist" if self.h & 4
                else "James Beard semifinalist" if self.h & 8 else None)

    def promo_ok(self):
        """Never name a place whose latest score is in its city's low band in a title, description, lede or other promotional spot."""
        return self.band not in LOW_BANDS

    def in_guide(self, tag):
        return self.hc and bool(self.tags & tag)


PLACES = [P(r) for r in RECS]
REST = [p for p in PLACES if not p.venue]

GUIDE_TAGS = [("bbq", BBQ), ("texmex", TEXMEX), ("taqueria", TAQUERIA), ("kolache", KOLACHE), ("cfs", CFS)]
L = {k: sorted([p for p in REST if p.in_guide(t)], key=P.featured_key) for k, t in GUIDE_TAGS}
HON_L = sorted([p for p in REST if p.mi or p.jbf], key=P.featured_key)
OLD_L = sorted([p for p in REST if p.founded and p.in_guide(OLDEST)], key=lambda p: (p.founded, p.name.lower()))
HC_ANY = [p for p in REST if p.hc and (p.tags & (BBQ | TEXMEX | TAQUERIA | KOLACHE | CFS | OLDEST))]   # on at least one hand-checked guide
INS_L = [p for p in REST if p.ins]

# ---------------------------------------------------------------- regions: the app's nine (each county to the nearest anchor city)
REGIONS = list(D.get("regions") or [])
REGION_NAME = {r: r for r in REGIONS}
REGION_ORDER = ["Houston & Gulf Coast", "Dallas–Fort Worth", "Austin & Central Texas", "San Antonio & Hill Country", "El Paso & West Texas",
                "Rio Grande Valley & Border", "Coastal Bend", "East Texas", "Panhandle & Plains"]
assert set(REGION_ORDER) == set(REGIONS), REGIONS
for p in PLACES:
    rg = p.r.get("rg")
    p.region = REGIONS[rg] if isinstance(rg, int) and 0 <= rg < len(REGIONS) else None


def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------- html helpers
e = html.escape


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("'", "").replace("&", "and")).strip("-")


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


def join_words(xs, conj="and"):
    xs = [x for x in xs if x]
    if len(xs) <= 1:
        return "".join(xs)
    return ", ".join(xs[:-1]) + f" {conj} " + xs[-1]


def fit(cands, lo, hi, what=""):
    seen = []
    # a description that misses the window by a few characters gets a fixed tail (Texas counts vary more than Florida's did)
    more = [c.rstrip(".") + t for c in cands for t in (", with addresses and websites.", ". Free iPhone app coming soon.", ", with addresses.",
                                                         ". Free iPhone app.", ", with maps.")] if lo >= 100 else []
    for o in list(cands) + more:
        if lo <= len(o) <= hi:
            return o
        seen.append(o)
    raise ValueError(f"nothing fits {lo}-{hi} for {what}: {[(len(o), o) for o in seen[:12]]}")


# The app icon in miniature (scripts/make-brand.swift, same geometry): three brisket slices on pink butcher paper, on flag blue.
LOGO = ('<svg viewBox="0 0 64 64" width="30" height="30" aria-hidden="true"><defs><clipPath id="lg-r"><rect width="64" height="64" rx="14"/></clipPath><clipPath id="lg-s1"><rect x="12.16" y="21.12" width="17.92" height="21.76" rx="3.2"/></clipPath><clipPath id="lg-s2"><rect x="23.04" y="21.12" width="17.92" height="21.76" rx="3.2"/></clipPath><clipPath id="lg-s3"><rect x="33.92" y="21.12" width="17.92" height="21.76" rx="3.2"/></clipPath></defs><g clip-path="url(#lg-r)"><rect width="64" height="64" fill="#002868"/><rect x="8.64" y="16.64" width="46.72" height="30.08" fill="#E7B9A6"/><rect x="12.16" y="21.12" width="17.92" height="21.76" rx="3.2" fill="none" stroke="#E7B9A6" stroke-width="1.6"/><g clip-path="url(#lg-s1)"><rect x="12.16" y="21.12" width="17.92" height="21.76" fill="#C98A5E"/><rect x="12.16" y="36.79" width="17.92" height="6.09" fill="#A9683F"/><rect x="12.16" y="21.12" width="17.92" height="5.44" fill="#D9574A"/><rect x="12.16" y="21.12" width="17.92" height="3.2" fill="#3A2318"/></g><rect x="23.04" y="21.12" width="17.92" height="21.76" rx="3.2" fill="none" stroke="#E7B9A6" stroke-width="1.6"/><g clip-path="url(#lg-s2)"><rect x="23.04" y="21.12" width="17.92" height="21.76" fill="#C98A5E"/><rect x="23.04" y="36.79" width="17.92" height="6.09" fill="#A9683F"/><rect x="23.04" y="21.12" width="17.92" height="5.44" fill="#D9574A"/><rect x="23.04" y="21.12" width="17.92" height="3.2" fill="#3A2318"/></g><rect x="33.92" y="21.12" width="17.92" height="21.76" rx="3.2" fill="none" stroke="#E7B9A6" stroke-width="1.6"/><g clip-path="url(#lg-s3)"><rect x="33.92" y="21.12" width="17.92" height="21.76" fill="#C98A5E"/><rect x="33.92" y="36.79" width="17.92" height="6.09" fill="#A9683F"/><rect x="33.92" y="21.12" width="17.92" height="5.44" fill="#D9574A"/><rect x="33.92" y="21.12" width="17.92" height="3.2" fill="#3A2318"/></g></g></svg>')
FAVICON = "data:image/svg+xml," + LOGO.replace('width="30" height="30" ', "").replace(' aria-hidden="true"', "").replace("<svg ", "<svg xmlns='http://www.w3.org/2000/svg' ").replace('"', "'").replace("#", "%23").replace("<", "%3C").replace(">", "%3E")

# Nick's palette (2026-10-20): the Texas flag. Old Glory blue #002868 for text and accents (14.6:1 on white), flag red #BF0A30 as
# a fill under white text (6.4:1) and for small accents, butcher-paper pink #E7B9A6 (the icon's) as a fill under ink, a warm paper
# #F7F3EC as the page tint. Lettering: condensed heavy system faces for headings, the system monospaced face for numbers; no web
# fonts are loaded (the CSP allows only this site, and the site loads nothing from anyone else).
CSS = """
  :root {
    --bg: #f7f3ec; --surface: #fff; --surface2: #efe9df; --rule: #e3dbcf;
    --ink: #0e1a30; --ink2: #28385a; --muted: #55627a;
    --accent: #002868; --accent2: #1c3f86; --on-accent: #fff; --orange: #bf0a30; --on-orange: #fff; --lime: #e7b9a6; --soft: #f8dce2; --limesoft: #f6e7e0;
    --focus: #bf0a30;
    --radius: 16px;
    --display: "Avenir Next Condensed", "Helvetica Neue Condensed", "Roboto Condensed", "Arial Narrow", system-ui, sans-serif;
    --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #0b1426; --surface: #111e38; --surface2: #172747; --rule: #263a63; --ink: #eef2fa; --ink2: #d3dcef; --muted: #a9b6d0; --accent: #9fb8ff; --accent2: #c0d0ff; --on-accent: #0b1426; --focus: #ff8aa0; }
  }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  @media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
  @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 17px/1.55 -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif; -webkit-font-smoothing: antialiased; }
  a { color: var(--accent); text-underline-offset: 2px; }
  a:focus-visible, summary:focus-visible, button:focus-visible, select:focus-visible, input:focus-visible, [tabindex]:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; border-radius: 6px; }
  .skip { position: absolute; left: -9999px; top: 0; background: var(--orange); color: var(--on-orange); padding: 10px 14px; font-weight: 700; z-index: 10; }
  .skip:focus { left: 8px; top: 8px; }
  .wrap { max-width: 760px; margin: 0 auto; padding: 0 20px; }
  header.site { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 18px 0 14px; }
  .stripes { display: grid; grid-template-columns: 36px 1fr; grid-template-rows: 9px 9px; margin: 0 0 4px; border-radius: 4px; overflow: hidden; }
  .stripes i { display: block; }
  .stripes i:nth-child(1) { grid-row: 1 / span 2; background: var(--accent); }
  .stripes i:nth-child(2) { background: var(--surface2); }
  .stripes i:nth-child(3) { background: var(--orange); }
  .logo { display: flex; align-items: center; gap: 10px; font: 800 24px/1 var(--display); text-transform: uppercase; letter-spacing: .01em; color: var(--accent); text-decoration: none; }
  .logo svg { flex: 0 0 auto; border-radius: 7px; }
  header.site nav { display: flex; flex-wrap: wrap; gap: 4px 16px; justify-content: flex-end; }
  header.site nav a { color: var(--ink2); text-decoration: none; font-size: 15px; }
  header.site nav a:hover { color: var(--accent); text-decoration: underline; }
  h1, h2 { font-family: var(--display); font-weight: 800; color: var(--accent); letter-spacing: -.005em; }
  h1 { font-size: clamp(40px, 8.5vw, 64px); line-height: .95; margin: 0 0 18px; text-transform: uppercase; overflow-wrap: break-word; text-shadow: 3px 3px 0 var(--orange); }
  .kicker { font: 600 13px/1.4 var(--mono); letter-spacing: .04em; text-transform: uppercase; color: var(--accent); margin: 0 0 12px; }
  .kicker::before { content: ""; display: inline-block; width: 9px; height: 9px; border-radius: 50%; background: var(--orange); margin: 0 8px 1px 0; }
  h2 { font-size: 34px; line-height: 1.02; margin: 0 0 10px; text-transform: uppercase; }
  h3 { font-size: 18px; margin: 0; line-height: 1.3; }
  .lede { font-size: 19px; color: var(--ink2); margin: 0 0 26px; }
  .hero { padding: 44px 0 28px; }
  section { padding: 36px 0; border-top: 1px solid var(--rule); }
  section.hero { border: 0; }
  .sub { color: var(--ink2); margin: 0 0 22px; }
  .cta-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
  .btn { display: inline-flex; align-items: center; gap: 10px; background: var(--orange); color: var(--on-orange); font-weight: 700; padding: 14px 20px; border-radius: 14px; text-decoration: none; font-size: 17px; }
  .btn-ghost { background: transparent; color: var(--accent); border: 2px solid var(--accent); }
  .pill { font-size: 14px; color: var(--muted); }
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 28px 0 0; padding: 0; list-style: none; }
  .stats li { background: var(--surface); border: 1px solid var(--rule); border-radius: 14px; padding: 14px; }
  .stats b { display: block; font: 600 28px/1 var(--mono); color: var(--accent); }
  .stats span { font-size: 14px; color: var(--muted); }
  .steps { display: grid; gap: 12px; list-style: none; margin: 0; padding: 0; }
  .step { display: flex; gap: 14px; background: var(--surface); border: 1px solid var(--rule); border-radius: var(--radius); padding: 18px; }
  .step .n { flex: 0 0 32px; height: 32px; border-radius: 50%; background: var(--orange); color: var(--on-orange); font-weight: 800; display: grid; place-items: center; }
  .step p { margin: 4px 0 0; color: var(--ink2); }
  .shots { display: flex; gap: 14px; overflow-x: auto; margin: 0 -20px; padding: 4px 20px 14px; scroll-snap-type: x proximity; list-style: none; }
  .shots li { flex: 0 0 auto; width: 210px; scroll-snap-align: start; }
  .shots img { display: block; width: 210px; height: auto; border-radius: 24px; border: 1px solid var(--rule); background: var(--surface2); }
  .shots p { font-size: 14px; color: var(--muted); margin: 8px 2px 0; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .card { background: var(--surface); border: 1px solid var(--rule); border-radius: var(--radius); padding: 18px; }
  .card h3 { font: 800 21px/1.1 var(--display); text-transform: uppercase; letter-spacing: .01em; }
  a.card.gc { display: flex; flex-direction: column; gap: 6px; border: 0; border-radius: 18px; min-height: 150px; }
  a.card.gc b { font: 600 32px/1 var(--mono); margin-bottom: auto; }
  a.card.gc p, a.card.gc h3 { color: inherit; }
  a.card.gc p { opacity: .92; }
  a.card.gc.gc-bbq, a.card.gc.gc-texmex, a.card.gc.gc-taqueria, a.card.gc.gc-kolache, a.card.gc.gc-cfs { background: #bf0a30; color: #fff; }
  a.card.gc.gc-oldest, a.card.gc.gc-honors { background: #002868; color: #fff; }
  .card p { margin: 6px 0 0; color: var(--ink2); }
  a.card { display: block; text-decoration: none; color: var(--ink); }
  a.card:hover h3 { text-decoration: underline; color: var(--accent); }
  .cities { display: flex; flex-wrap: wrap; gap: 8px; list-style: none; padding: 0; margin: 0; }
  .cities a { display: inline-block; padding: 8px 12px; border-radius: 999px; border: 1px solid var(--rule); background: var(--surface); text-decoration: none; color: var(--ink); font-size: 15px; }
  .cities a:hover { border-color: var(--accent); }
  .cities a[aria-current] { border-color: var(--accent); font-weight: 700; }
  details { background: var(--surface); border: 1px solid var(--rule); border-radius: 14px; padding: 2px 18px; margin-bottom: 10px; }
  summary { cursor: pointer; padding: 14px 0; font-weight: 600; list-style: none; display: flex; justify-content: space-between; gap: 12px; }
  summary::-webkit-details-marker { display: none; }
  summary::after { content: "+"; color: var(--accent); font-weight: 800; }
  details[open] summary::after { content: "\\2013"; }
  details p { margin: 0 0 16px; color: var(--ink2); }
  .final { text-align: center; }
  .final .cta-row { justify-content: center; }
  nav.crumbs { font-size: 14px; color: var(--muted); padding: 16px 0 0; }
  nav.crumbs ol { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 6px; }
  nav.crumbs li + li::before { content: "/"; margin-right: 6px; color: var(--rule); }
  nav.crumbs a { color: var(--muted); }
  .places { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
  .places li { background: var(--surface); border: 1px solid var(--rule); border-radius: 14px; padding: 14px 16px; min-width: 0; overflow-wrap: anywhere; scroll-margin-top: 12px; }
  .places li:target { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent); }
  .places .where { margin: 2px 0 0; font-size: 15px; color: var(--muted); }
  .places .facts { margin: 8px 0 0; font-size: 15px; color: var(--ink2); }
  .places .facts b { color: var(--ink); font-weight: 600; }
  .places .note { margin: 6px 0 0; font-size: 15px; color: var(--ink2); }
  .places .fine { margin: 6px 0 0; }
  .places .link { font-size: 14px; margin: 6px 0 0; }
  .tag { display: inline-block; font-size: 12px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; background: var(--lime); color: #0e1a30; border-radius: 6px; padding: 1px 6px; margin: 0 4px 2px 0; }
  .tag-mi { background: #bf0a30; color: #fff; }
  .tag-jb { background: #002868; color: #fff; }
  .tag-plain { background: var(--soft); color: #0e1a30; }
  .toc { columns: 2; padding-left: 20px; margin: 0; }
  table { border-collapse: collapse; width: 100%; font-size: 15px; }
  th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--rule); vertical-align: top; }
  td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
  .tbl { overflow-x: auto; }
  .res { display: inline-block; font: 800 12px/1.4 -apple-system, system-ui, sans-serif; letter-spacing: .04em; text-transform: uppercase; padding: 2px 6px; border-radius: 6px; }
  .res-ok { background: #ddefe3; color: #0e5a2b; } .res-mid { background: #ffe9c2; color: #6b3a00; } .res-low { background: #f9d5db; color: #7a0019; }
  .groups { list-style: none; padding: 0; margin: 0 0 18px; display: grid; gap: 12px; }
  .groups > li { background: var(--surface); border: 1px solid var(--rule); border-radius: 14px; padding: 14px 16px; }
  .groups ul { margin: 8px 0 0; padding-left: 20px; color: var(--ink2); font-size: 15px; }
  .groups .count { margin: 8px 0 0; font-weight: 600; }
  .fine { font-size: 14px; color: var(--muted); }
  .legal h2 { font-size: 26px; margin-top: 28px; }
  .legal p, .legal li { color: var(--ink2); }
  footer { padding: 32px 0 56px; color: var(--muted); font-size: 14px; border-top: 1px solid var(--rule); margin-top: 20px; }
  footer nav { display: flex; flex-wrap: wrap; gap: 8px 16px; }
  footer a { color: var(--muted); }
  footer p { margin: 12px 0 0; }
  @media (max-width: 600px) {
    .grid2 { grid-template-columns: 1fr; }
    .stats { grid-template-columns: 1fr 1fr; }
    .toc { columns: 1; }
    .toc a { display: inline-block; padding: 3px 0; }
    header.site { flex-direction: column; align-items: flex-start; }
    header.site nav { justify-content: flex-start; }
    header.site nav a, footer nav a, nav.crumbs a { display: inline-block; padding: 10px 0; }
    footer nav { gap: 0 18px; }
    th, td { padding: 8px 4px; font-size: 14px; }
    .tbl th, .tbl td { padding: 8px 3px; font-size: 13px; }
    .res { font-size: 11px; letter-spacing: .02em; padding: 2px 4px; }
    nav.crumbs ol { align-items: center; }
  }
"""


def jsonld(obj):
    big = obj.get("@type") == "ItemList"
    raw = json.dumps(obj, ensure_ascii=False, indent=None if big else 1, separators=(",", ":") if big else None)
    return '<script type="application/ld+json">\n' + raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026") + "\n</script>"


def crumbs(trail):
    """trail: [(name, url)] ending with the current page."""
    items = "".join(f'<li><a href="{u}">{e(n)}</a></li>' if i < len(trail) - 1 else f'<li aria-current="page">{e(n)}</li>'
                    for i, (n, u) in enumerate(trail))
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": DOMAIN + u} for i, (n, u) in enumerate(trail)]}
    return f'<nav class="crumbs" aria-label="Breadcrumb"><ol>{items}</ol></nav>', ld


def store_button(label="Ask for early access"):
    # A plain mailto button until launch: no Apple logo (Apple's marketing rules allow it only in the official badge). When
    # APP_STORE_URL is set in page() below, swap this for Apple's "Download on the App Store" badge artwork. Only Nick's internal
    # TestFlight group exists (2026-10-13): the mailto asks, and no page copy promises an invite or a link.
    return (f'<a class="btn store-btn" href="mailto:{EMAIL}?subject=Texas%20Eats%20early%20access&amp;body=Send%20me%20the%20TestFlight%20link.">'
            f'<span class="store-label">{label}</span></a>')


STORE_NOTE = "The free Texas Eats app for iPhone and iPad is on its way to the App Store."


def sha256_src(s):
    return "'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() + "'"


def csp_for(doc):
    """A strict policy for one finished page: only its own inline <script>/<style> blocks (by hash), same-origin data and images."""
    scripts = re.findall(r"<script>(.*?)</script>", doc, re.S)          # executable inline scripts (JSON-LD blocks are data, not run)
    styles = re.findall(r"<style>(.*?)</style>", doc, re.S)
    return ("default-src 'none'; "
            f"script-src {' '.join(sha256_src(s) for s in scripts) or chr(39) + 'none' + chr(39)}; "
            f"style-src {' '.join(sha256_src(s) for s in styles) or chr(39) + 'none' + chr(39)}; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'")


CSP_SLOT = "__CSP__"
written, noindexed = [], []
NAV = [("/texas-barbecue.html", "Barbecue"), ("/texas-taquerias.html", "Taquerías"), ("/texas-kolaches.html", "Kolaches"),
       ("/cities/", "Cities"), ("/explore/", "Search")]


def page(path, title, desc, body, lds=(), robots="index,follow,max-image-preview:large", og_alt=None, extra_css="", og_type="article"):
    assert 50 <= len(title) <= 60 or path == "404.html", (path, len(title), title)
    assert 140 <= len(desc) <= 160 or path == "404.html", (path, len(desc), desc)
    assert body.count("<h1") == 1, path
    assert 'style="' not in body, f"{path}: inline style attributes break the CSP"
    url = DOMAIN + "/" + ("" if path == "index.html" else path.removesuffix("index.html"))
    indexed = "noindex" not in robots
    if not any("parentOrganization" in json.dumps(x) for x in lds):   # every page names its publisher and the Eats Ranked parent
        lds = list(lds) + [{"@context": "https://schema.org", **ORG_REF}]
    og_alt = og_alt or f"{BRAND}: {TAGLINE}. Texas restaurants, with hand-checked barbecue joints, Tex-Mex, taquerías, kolaches and the state's oldest places."
    ld = "\n".join(jsonld(x) for x in lds)
    canon = f'<link rel="canonical" href="{url}">\n' if indexed else ""
    og_url = f'<meta property="og:url" content="{url}">\n' if indexed else ""
    nav = "\n".join(f'      <a href="{u}">{t}</a>' for u, t in NAV)
    doc = f"""<!DOCTYPE html>
<html lang="en" data-base="{BASE}">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{CSP_SLOT}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
{canon}<meta name="robots" content="{robots}">
<meta name="theme-color" content="#002868">
<!-- Smart App Banner: once the App Store Connect record exists, replace APP_ID with the numeric Apple ID and uncomment.
<meta name="apple-itunes-app" content="app-id=APP_ID">
-->
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
{og_url}<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="{BRAND}">
<meta property="og:locale" content="en_US">
<meta property="og:image" content="{DOMAIN}/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{e(og_alt)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{DOMAIN}/og.png">
<link rel="icon" type="image/svg+xml" href="{FAVICON}">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<style>{CSS}{extra_css}</style>
{ld}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<div class="wrap">
  <header class="site">
    <a class="logo" href="/" aria-label="{BRAND} home">{LOGO}{BRAND}</a>
    <nav aria-label="Main">
{nav}
    </nav>
  </header>
  <div class="stripes" aria-hidden="true"><i></i><i></i><i></i></div>
{body}
  <footer>
    <nav aria-label="Footer">
      <a href="/">{BRAND} app</a>
      <a href="/explore/">Search Texas restaurants</a>
{chr(10).join(f'      <a href="{u}">{e(t)}</a>' for u, t in GUIDE_LINKS)}
      <a href="/cities/">Cities and towns</a>
      <a href="/privacy.html">Privacy policy</a>
      <a href="/terms.html">Terms of use</a>
      <a href="mailto:{EMAIL}">Email us</a>
    </nav>
    <p>{SOURCES_LINE}</p>
    <p>© 2026 {BRAND}. Part of <a href="{HUB['url']}" rel="noopener">Eats Ranked</a>, restaurant apps state by state.</p>
    <p>Created by <a href="https://work-with-nick.com/" rel="author">Nick Soderstrom</a>.</p>
  </footer>
</div>
<script>
  // Once the App Store listing exists, paste its URL here (looks like https://apps.apple.com/app/id123456789).
  // Every button switches from "Ask for early access" to "Download on the App Store" automatically (then use Apple's badge artwork,
  // see store_button() in scripts/make-site.py). Also fill in the apple-itunes-app meta tag in <head> on every page, and put the
  // MobileApplication "offers" back in the landing page's JSON-LD (re-run scripts/make-site.py after editing it there).
  var APP_STORE_URL = "";
  if (APP_STORE_URL) {{
    document.querySelectorAll(".store-btn").forEach(function (b) {{ b.href = APP_STORE_URL; b.rel = "noopener"; }});
    document.querySelectorAll(".store-label").forEach(function (l) {{ l.textContent = "Download on the App Store"; }});
    document.querySelectorAll(".store-note").forEach(function (n) {{ n.textContent = "Free for iPhone and iPad."; }});
  }}
</script>
</body>
</html>
"""
    if BASE:   # served under /texas-eats/: every root-relative link and asset gets the prefix
        doc = re.sub(r'(href|src|srcset)="/', rf'\1="{BASE}/', doc)
    doc = doc.replace(CSP_SLOT, csp_for(doc), 1)   # hashed last, over the exact bytes the browser will see
    os.makedirs(os.path.dirname(f"{DOCS}/{path}"), exist_ok=True)
    open(f"{DOCS}/{path}", "w").write(doc)
    (written if indexed else noindexed).append(path)
    return path


class Anchors:
    """Gives each place an id (name-zip) the first time it appears on a page, so ItemList items can point to page#id."""
    RESERVED = {"main", "about", "list", "honors", "oldest", "inspections", "cuisines", "more", "towns", "how", "what", "guides", "cities",
                "faq", "download", "screens", "pricing", "privacy", "groups", "counties", "lookup", "closures", "tiers", "lg-r", "lg-f", "lg-p",
                "cities-list", "lg-s1", "lg-s2", "lg-s3", "alcohol"} | {k for k, _ in GUIDE_TAGS}

    def __init__(self, page_url):
        self.page_url, self.used, self.of = page_url, set(self.RESERVED), {}

    def take(self, p):
        if id(p) in self.of:
            return None
        base = slug(p.name + (" " + p.zip if p.zip else "")) or "place"
        a, n = base, 2
        while a in self.used:
            a, n = f"{base}-{n}", n + 1
        self.used.add(a)
        self.of[id(p)] = a
        return a

    def url(self, p):
        return f"{self.page_url}#{self.of[id(p)]}"


CHIPS = [(BBQ, "Barbecue"), (TEXMEX, "Tex-Mex"), (TAQUERIA, "Taquería"), (KOLACHE, "Kolaches"), (CFS, "Chicken-fried steak")]


def place_item(p, anchors=None, show_fn=False, honors=False):
    facts = []
    if p.dishes:
        facts.append(f"<b>On the menu:</b> {e(p.dishes)}")
    if p.founded:
        facts.append(f"<b>Since</b> {e(str(p.founded))}")
    if p.season:
        facts.append(f"<b>Season:</b> {e(p.season)}")
    kinds = []
    if p.mi:
        kinds.append(('<span class="tag tag-mi">', e(MI[p.mi])))
    if p.jb_label():
        kinds.append(('<span class="tag tag-jb">', e(p.jb_label())))
    if p.hc:
        kinds += [('<span class="tag">', k) for t, k in CHIPS if p.tags & t]
    where = ", ".join(x for x in (p.addr, p.city) if x)
    aid = anchors.take(p) if anchors else None
    out = [f'<li id="{e(aid)}">' if aid else "<li>", f"<h3>{e(p.name)}</h3>", f'<p class="where">{e(where)}</p>']
    if kinds or facts:
        out.append('<p class="facts">' + "".join(f"{tag}{k}</span>" for tag, k in kinds) + (" " + " · ".join(facts) if facts else "") + "</p>")
    if p.note:
        out.append(f'<p class="note">{e(p.note)}</p>')
    if show_fn and p.fn:
        out.append(f'<p class="fine">{e(p.fn)}</p>')
    if honors and p.jbf:   # restaurateur-level honors have no chip, so say what the honor is
        out.append('<p class="fine">' + e("; ".join("James Beard: " + x for x in p.jbf.split("; "))) + "</p>")
    if p.site:
        host = re.sub(r"^https?://(www\.)?", "", p.site, flags=re.I).split("/")[0]
        out.append(f'<p class="link"><a href="{e(p.site)}" rel="noopener nofollow">{e(host)}</a></p>')
    out.append("</li>")
    return "".join(out)


def restaurant_ld(p, item_url):
    addr = {"@type": "PostalAddress"}
    if p.addr:
        addr["streetAddress"] = p.addr
    if p.city:
        addr["addressLocality"] = p.city
    addr["addressRegion"] = "TX"
    if p.zip:
        addr["postalCode"] = p.zip
    addr["addressCountry"] = "US"
    x = {"@type": "Restaurant", "name": p.name, "url": item_url, "address": addr}
    if p.lat is not None and p.lon is not None:
        x["geo"] = {"@type": "GeoCoordinates", "latitude": p.lat, "longitude": p.lon}
    if p.site:
        x["sameAs"] = p.site
    if p.founded:
        x["foundingDate"] = str(p.founded)
    if p.cuisine and p.cuisine not in ("Other", "Restaurant", "American & Other"):
        x["servesCuisine"] = p.cuisine
    return x


def item_list(name, places, url, anchors):
    """An all-on-one-page list: each item's url is its anchor on this page; the restaurant's own site goes in sameAs."""
    return {"@context": "https://schema.org", "@type": "ItemList", "name": name, "url": url, "numberOfItems": len(places),
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "item": restaurant_ld(p, anchors.url(p))} for i, p in enumerate(places)]}


def article_ld(url, headline, desc):
    return {"@context": "https://schema.org", "@type": "Article", "headline": headline, "description": desc,
            "datePublished": PUBLISHED, "dateModified": TODAY, "inLanguage": "en", "mainEntityOfPage": url,
            "image": f"{DOMAIN}/og.png", "author": ORG_REF, "publisher": ORG_REF}


# ---------------------------------------------------------------- counts shared by several pages
N_REST = len(REST)
N_TOWNS = len({p.city for p in REST if p.city})
N_COUNTIES = len({p.county for p in REST if p.county})
N_OFFICIAL = sum(1 for p in REST if p.r.get("t") == 2)
N_LIQ = sum(1 for p in REST if p.r.get("liq") == 1)
N_ALC = sum(1 for p in REST if p.al is not None)
N_HC = len(HC_ANY)
MI_N = Counter(p.mi for p in HON_L if p.mi)
MI_COUNT = {MI[k]: v for k, v in sorted(MI_N.items())}
N_JBF = sum(1 for p in HON_L if p.jbf)
N_CLASSICS = sum(1 for p in HON_L if p.h & 1)
INS_BY_CITY = {j: [p for p in INS_L if p.ins_city == j] for j in range(3)}
BAND_N = {j: Counter(p.band for p in INS_BY_CITY[j]) for j in range(3)}
INS_PATH = "texas-restaurant-inspections.html"
HON_PATH = "texas-michelin-james-beard.html"
OLD_PATH = "texas-oldest-restaurants.html"
GUIDE_PATH = {"bbq": "texas-barbecue.html", "texmex": "texas-tex-mex.html", "taqueria": "texas-taquerias.html",
              "kolache": "texas-kolaches.html", "cfs": "texas-chicken-fried-steak.html"}
GUIDE_NAME = {"bbq": "Barbecue joints", "texmex": "Tex-Mex", "taqueria": "Taquerías", "kolache": "Kolaches", "cfs": "Chicken-fried steak"}
GUIDE_LINKS = ([("/" + GUIDE_PATH[k], GUIDE_NAME[k]) for k, _ in GUIDE_TAGS]
               + [("/" + OLD_PATH, "Oldest restaurants"), ("/" + HON_PATH, "MICHELIN & James Beard"), ("/" + INS_PATH, "Restaurant inspections")])
INS_DATES = {j: hdate(INS_THROUGH.get(INS_KEY[j], "")) for j in range(3)}

SOURCES_LINE = (f"Place data: hand-checked research by {BRAND} ({CHECKED}); Texas Alcoholic Beverage Commission license information and the Texas "
                "Comptroller's mixed beverage gross receipts (data.texas.gov); inspection scores from Austin Public Health (data.austintexas.gov), "
                "the City of El Paso Department of Public Health and the City of Arlington; Overture Maps Foundation places (CDLA Permissive 2.0) "
                "and addresses (open address sources under permissive licenses, docs.overturemaps.org/attribution); map outlines © OpenStreetMap "
                "contributors, Overture Maps Foundation (ODbL); U.S. Census Bureau Geocoder (public domain). Not affiliated with or endorsed by "
                "the State of Texas, TABC, the Comptroller, any city, any restaurant or chain, the MICHELIN Guide or the James Beard Foundation. "
                "MICHELIN and the MICHELIN Guide are trademarks of Michelin; James Beard Foundation and James Beard Award are trademarks of the "
                "James Beard Foundation. Places open and close, so check before you go.")


def by_region(places, key=lambda p: (p.city, p.name.lower())):
    groups = defaultdict(list)
    for p in places:
        groups[p.region or "Elsewhere"].append(p)
    order = REGION_ORDER + ["Elsewhere"]
    return [(REGION_NAME.get(r, "Elsewhere in Texas"), sorted(groups[r], key=key)) for r in order if groups.get(r)]


def region_sections(places, noun, plural_noun, anchors, **item_kw):
    toc = '<ul class="toc">' + "".join(f'<li><a href="#{slug(r)}">{e(r)}</a> ({len(ps)})</li>' for r, ps in by_region(places)) + "</ul>"
    secs = []
    for r, ps in by_region(places):
        anchors.used.update({slug(r), "h-" + slug(r)})
        secs.append(f'<section id="{slug(r)}" aria-labelledby="h-{slug(r)}"><h2 id="h-{slug(r)}">{e(r)}</h2>'
                    f'<p class="sub">{plural(len(ps), noun, plural_noun)}, by town.</p><ol class="places">'
                    + "".join(place_item(p, anchors, **item_kw) for p in ps) + "</ol></section>")
    return toc, "\n".join(secs)


# ---------------------------------------------------------------- city pages: which towns get one
CITY_WANTED = ["Houston", "Dallas", "Austin", "San Antonio", "Fort Worth", "El Paso", "Arlington", "Corpus Christi", "Plano", "Lubbock",
               "Waco", "Lockhart", "McAllen", "Brownsville", "Amarillo", "Galveston", "Fredericksburg", "Denton", "Laredo", "Spring",
               "New Braunfels", "Taylor", "West", "Bellaire", "Irving", "Garland", "Frisco", "Round Rock"]
MIN_LISTED = 5   # hand-checked, honored or oldest places in the town itself: fewer, and the town gets no page yet


def town_listed(c):
    return [p for p in REST if p.city == c and ((p.hc and p.tags) or p.mi or p.jbf)]


CITY_PAGES = [c for c in CITY_WANTED if any(p.city == c and p.lat is not None for p in REST) and len(town_listed(c)) >= MIN_LISTED]
CITY_SKIPPED = {c: len(town_listed(c)) for c in CITY_WANTED if c not in CITY_PAGES}


def city_url(c):
    return f"/cities/{slug(c)}.html"


def city_links(current=None):
    return '<ul class="cities">' + "".join(f'<li><a href="{city_url(c)}"{" aria-current=" + chr(34) + "page" + chr(34) if c == current else ""}>{e(c)}</a></li>'
                                           for c in CITY_PAGES) + "</ul>"


def other_guides(skip):
    return "Other guides: " + ", ".join(f'<a href="{u}">{e(t)}</a>' for u, t in GUIDE_LINKS if u != skip) + "."


def guide_page(path, h1, kicker, title_opts, desc_opts, lede, about_html, places, noun, plural_noun, list_name, region=True, **item_kw):
    url = f"{DOMAIN}/{path}"
    # Texas counts are small or large enough that the written lengths can miss the 140-160 window: each option also gets fixed tails
    tails = (", with addresses and websites.", ", with each place's address and website.", ". Free iPhone app coming soon.", ", with addresses.",
             ". Free iPhone app.", ", with maps.")
    desc_opts = list(desc_opts) + [d.rstrip(".") + t for d in desc_opts for t in tails]
    title_opts = list(title_opts) + [t + f" | {BRAND}" for t in title_opts if BRAND not in t]
    title, desc = fit(title_opts, 50, 60, path + " title"), fit(desc_opts, 140, 160, path + " description")
    nav, bc = crumbs([("Home", "/"), (h1, "/" + path)])
    anchors = Anchors(url)
    if region:
        toc, secs = region_sections(places, noun, plural_noun, anchors, **item_kw)
        jump = f"<h2>Jump to a region</h2>\n    {toc}"
    else:
        secs = (f'<section id="list" aria-labelledby="h-list"><h2 id="h-list">Oldest first</h2><ol class="places">'
                f'{"".join(place_item(p, anchors, **item_kw) for p in places)}</ol></section>')
        jump = ""
    body = f"""{nav}
  <main id="main">
  <section class="hero">
    <p class="kicker">{kicker}</p>
    <h1>{e(h1)}</h1>
    <p class="lede">{lede}</p>
    <div class="cta-row">{store_button()}<span class="pill store-note">{STORE_NOTE}</span></div>
  </section>
  <section id="about">
    {about_html}
    <p class="fine">{other_guides("/" + path)} City pages: {", ".join(f'<a href="{city_url(c)}">{e(c)}</a>' for c in CITY_PAGES)}.</p>
    {jump}
  </section>
{secs}
  </main>"""
    page(path, title, desc, body, [article_ld(url, h1, desc), bc, item_list(list_name, places, url, anchors)])


def towns_text(places, k):
    return join_words([t for t, _ in Counter(p.city for p in places).most_common(k)])


def towns_counts(places, k=8):
    return ", ".join(f"{t} ({n})" for t, n in Counter(p.city for p in places).most_common(k))


def top_dishes(places, k=6, skip=()):
    c = Counter()
    for p in places:
        # sorted: a set's order changes from run to run, and ties in most_common() would reorder the copy on every rebuild
        for d in sorted({x.strip().lower() for x in re.split(r"[;,]", p.r.get("dish") or "") if x.strip()}):
            if d not in skip:
                c[d] += 1
    return ", ".join(f"{d} ({n})" for d, n in c.most_common(k) if n > 1)


HOW_BUILT = ("Our method: a place made the list only if a 2025 or 2026 source backed it up (its own site or menu, a dated local news "
             "story or an official tourism listing) and its street address matched. No current source, or a website gone dark, and it "
             "stayed off. Review sites played no part, and places run by region and town rather than by anybody's score. Barbecue joints "
             "sell out and keep short hours, so check before you drive.")
APP_LINE = (f"On your phone, {BRAND} orders this list by how far each place is from you, and a tap opens Apple Maps' live card with "
            "hours, photos and directions.")


def checked_kicker():
    return f"{BRAND} · checked by hand, {CHECKED}"


def seasonal_line(places):
    n = sum(1 for p in places if p.season)
    return f" {plural(n, 'place')} on this list {'notes a season' if n == 1 else 'note a season'}; seasonal is not closed." if n else ""


# ---------------------------------------------------------------- the five themed guides
assert all(len(v) > 1 for v in L.values()), "the guide copy writes plural nouns"


def guide(k, h1, titles, descs, lede, about, list_name, noun="place"):
    G = L[k]
    plural_noun = noun[:-1] + "ies" if noun.endswith("y") else noun + "s"
    guide_page(GUIDE_PATH[k], h1, checked_kicker(), titles, descs, lede, about + f"""
    <h2>The list at a glance</h2>
    <p>Towns with the most: {e(towns_counts(G))}.{(" The dishes we found most often: " + e(top_dishes(G)) + ".") if top_dishes(G) else ""}</p>
    <p>{HOW_BUILT}</p>
    <p>{APP_LINE}</p>""", G, noun, plural_noun, list_name)


G = L["bbq"]
guide("bbq", "Texas barbecue joints",
      [f"Texas Barbecue Joints: {len(G)} Checked BBQ Places | {BRAND}", f"Texas Barbecue: {len(G)} Hand-Checked BBQ Joints | {BRAND}",
       f"Texas Barbecue: {len(G)} Checked Joints, Brisket to Sausage"],
      [f"{plural(len(G), 'Texas barbecue joint')} for brisket, ribs and sausage, each checked in {CHECKED} against a 2025–26 source, listed by region and town.",
       f"{plural(len(G), 'Texas barbecue joint')}, from Central Texas brisket to East Texas ribs, checked in {CHECKED} against a 2025–26 source, by region and town.",
       f"{plural(len(G), 'Texas barbecue joint')} for brisket, ribs and sausage, hand-checked in {CHECKED} against a 2025–26 source, by region."],
      f"{plural(len(G), 'barbecue joint')} across Texas for smoked brisket, beef ribs, pork ribs and sausage, each checked in {CHECKED} against a 2025–26 source: its own site or menu, recent local news or an official tourism listing.",
      """<h2>Smoke, salt and pepper</h2>
    <p>Central Texas barbecue is beef brisket rubbed with salt and black pepper and smoked for hours over post oak, sold by the pound on butcher paper with white bread, pickles and onions. Beef ribs, pork ribs, turkey and house-made sausage share the cutting board. East Texas leans to chopped beef and sauce; South Texas has barbacoa on Sunday mornings. Many joints open a few days a week and close when the meat runs out.</p>""",
      "Texas barbecue joints", "joint")
G = L["texmex"]
guide("texmex", "Texas Tex-Mex",
      [f"Texas Tex-Mex Restaurants: {len(G)} Checked Places | {BRAND}", f"Tex-Mex in Texas: {len(G)} Hand-Checked Restaurants | {BRAND}",
       f"Texas Tex-Mex: {len(G)} Checked Restaurants by Region"],
      [f"{plural(len(G), 'Texas Tex-Mex restaurant')} for enchiladas, fajitas, queso and combination plates, checked in {CHECKED} against a 2025–26 source, by region.",
       f"{plural(len(G), 'Tex-Mex restaurant')} in Texas, from cheese enchiladas to sizzling fajitas, each checked in {CHECKED} against a 2025–26 source, by region and town."],
      f"{plural(len(G), 'restaurant')} across Texas for Tex-Mex: cheese enchiladas in chili gravy, fajitas, queso, puffy tacos and the combination plate, each checked in {CHECKED} against a 2025–26 source.",
      """<h2>The combination plate</h2>
    <p>Tex-Mex is the Texas cooking that grew from Tejano kitchens: yellow cheese enchiladas under chili con carne gravy, crispy tacos, rice and refried beans on one hot plate, chips with salsa and a bowl of queso. Fajitas came out of the South Texas ranch country, and San Antonio claims the puffy taco.</p>""",
      "Texas Tex-Mex restaurants", "restaurant")
G = L["taqueria"]
guide("taqueria", "Texas taquerías",
      [f"Texas Taquerías: {len(G)} Hand-Checked Taco Spots | {BRAND}", f"Taquerías in Texas: {len(G)} Checked Places | {BRAND}",
       f"Texas Taquerías & Breakfast Tacos: {len(G)} Checked Places"],
      [f"{plural(len(G), 'Texas taquería')} for tacos al pastor, barbacoa, guisados and breakfast tacos, checked in {CHECKED} against a 2025–26 source, by region.",
       f"{plural(len(G), 'Texas taquería')} and breakfast taco spots, each checked in {CHECKED} against a 2025–26 source, listed by region and town."],
      f"{plural(len(G), 'taquería')} and taco spots across Texas, from trompo al pastor and Sunday barbacoa to breakfast tacos on flour tortillas, each checked in {CHECKED} against a 2025–26 source.",
      """<h2>Tortillas first</h2>
    <p>A Texas taquería runs on its tortillas: corn for al pastor off the trompo, carnitas, barbacoa and guisados, flour for the breakfast tacos of egg, potato, bacon and chorizo that Austin and San Antonio argue over. Many are counters, trucks and drive-throughs open early in the morning.</p>""",
      "Texas taquerías", "taquería")
G = L["kolache"]
guide("kolache", "Texas kolaches",
      [f"Texas Kolaches: {len(G)} Hand-Checked Bakeries | {BRAND}", f"Kolaches in Texas: {len(G)} Checked Czech Bakeries | {BRAND}",
       f"Texas Kolache Bakeries: {len(G)} Checked Places by Town"],
      [f"{plural(len(G), 'Texas bakery', 'Texas bakeries')} for fruit kolaches and klobasniky, each checked in {CHECKED} against a 2025–26 source, by region and town.",
       f"{plural(len(G), 'Texas kolache bakery', 'Texas kolache bakeries')} and Czech-Texan stops, checked in {CHECKED} against a 2025–26 source, listed by region and town."],
      f"{plural(len(G), 'bakery', 'bakeries')} and roadside stops across Texas for kolaches, the Czech pastry of sweet dough around fruit or cream cheese, each checked in {CHECKED} against a 2025–26 source.",
      """<h2>Czech Texas</h2>
    <p>Czech immigrants brought the kolache to Central Texas in the 1800s: soft yeast dough with a well of apricot, prune, poppy seed, cream cheese or fruit, often under a crumb topping. The sausage roll that Texas also calls a kolache is properly a klobasnek. West, Caldwell, Hallettsville, Shiner and the stops along I-35 and US 290 keep the tradition.</p>""",
      "Texas kolache bakeries", "bakery")
G = L["cfs"]
guide("cfs", "Texas chicken-fried steak",
      [f"Texas Chicken-Fried Steak: {len(G)} Checked Places | {BRAND}", f"Chicken-Fried Steak in Texas: {len(G)} Checked Places",
       f"Texas Chicken-Fried Steak & Cream Gravy | {BRAND}"],
      [f"{plural(len(G), 'Texas place')} for chicken-fried steak with cream gravy, each checked in {CHECKED} against a 2025–26 source, listed by region and town.",
       f"{plural(len(G), 'Texas café')} and steakhouses for chicken-fried steak, each checked in {CHECKED} against a 2025–26 source, by region and town."],
      f"{plural(len(G), 'café')}, diners and steakhouses across Texas for chicken-fried steak, a tenderized beef cutlet battered, fried and covered in cream gravy, each checked in {CHECKED} against a 2025–26 source.",
      """<h2>The state plate</h2>
    <p>Chicken-fried steak is round steak pounded thin, dredged in seasoned flour, fried crisp like fried chicken and smothered in peppery cream gravy, usually with mashed potatoes and Texas toast. Small-town cafés and old steakhouses make it best, and many serve it at lunch only.</p>""",
      "Texas chicken-fried steak", "place")

# ---------------------------------------------------------------- MICHELIN & James Beard
MI_SHORT = {5: "3-Star", 4: "2-Star", 3: "1-Star", 2: "Bib Gourmand", 1: "Recommended"}
mi_parts = [f"{words_num(MI_N[k])} {MI_SHORT[k]}" for k in (5, 4, 3, 2, 1) if MI_N.get(k)]
N_MI = sum(MI_N.values())
mi_line = (join_words(mi_parts) + (" restaurants" if N_MI != 1 else " restaurant")) if mi_parts else ""
guide_page(HON_PATH, "Texas MICHELIN & James Beard restaurants", f"{BRAND} · honors current as of {CHECKED}",
           [f"Texas MICHELIN & James Beard Restaurants | {BRAND}", "Texas MICHELIN Guide & James Beard Restaurants List",
            f"MICHELIN & James Beard Restaurants in Texas | {BRAND}"],
           [f"{plural(len(HON_L), 'Texas restaurant')} in the MICHELIN Guide Texas or honored by the James Beard Foundation in 2025 and 2026, listed by region and town.",
            f"{plural(len(HON_L), 'Texas restaurant')} with a MICHELIN Guide Texas distinction or a James Beard honor, from Houston to El Paso, listed by region and town."],
           f"{plural(len(HON_L), 'Texas restaurant')} recognized by MICHELIN or the James Beard Foundation. The MICHELIN Guide Texas selection accounts for {plural(N_MI, 'place')} ({e(mi_line)}); {plural(N_JBF, 'place')} hold a James Beard award or finalist nod from 2025 or 2026, or an America's Classics award.",
           f"""<h2>What counts as an honor here</h2>
    <p>Two sources, both reported as facts rather than scores. One is the MICHELIN Guide Texas selection as MICHELIN lists it. The other is the James Beard Foundation: its 2025 and 2026 awards and finalists, plus America's Classics awards from any year ({plural(N_CLASSICS, 'place')}). Finalists are labeled as exactly that, not as winners. A restaurant that has closed since it was honored is off the list, and where an honor went to a chef or a restaurant group instead of the restaurant, the line under the place says so. Reader polls, "best of" roundups and review-site stars don't count.</p>
    <p class="fine">MICHELIN and the MICHELIN Guide are trademarks of Michelin. James Beard Foundation and James Beard Award are trademarks of the James Beard Foundation. {BRAND} is not affiliated with either.</p>""",
           HON_L, "restaurant", "restaurants", "Texas MICHELIN Guide and James Beard restaurants", honors=True)

# ---------------------------------------------------------------- oldest
oldest_named = next((p for p in OLD_L if p.promo_ok()), None)
assert all(p.founded <= 1960 for p in OLD_L), "the oldest-places copy says 'since 1960 or earlier'"
from_line = f" The oldest, {e(oldest_named.name)} in {e(oldest_named.city)}, goes back to {oldest_named.founded}." if oldest_named else ""
guide_page(OLD_PATH, "Texas's oldest restaurants", checked_kicker(),
           [f"Texas's Oldest Restaurants: {len(OLD_L)} Places, Oldest First", f"Oldest Restaurants in Texas: {len(OLD_L)} Places | {BRAND}",
            "Texas's Oldest Restaurants, Year by Year | Texas Eats"],
           [f"{plural(len(OLD_L), 'Texas restaurant')} open at the same address since 1960 or earlier, oldest first, each with a note on what its founding year rests on.",
            f"Texas's oldest restaurants: {plural(len(OLD_L), 'place')} open at the same address since 1960 or earlier, oldest first, with the source behind each year."],
           f"Restaurants, barbecue joints and cafés that have fed Texas from the same address since 1960 or before: {plural(len(OLD_L), 'place')} in all, oldest first, each checked in {CHECKED} against a 2025–26 source.{from_line} The note under each place names what its year rests on.",
           f"""<h2>Which year counts</h2>
    <p>We count from the year a place opened at its current address in its current form, going by the place's own history or a published one. A brand's earlier start somewhere else doesn't count, and neither do the years before a move; if two sources give different years, the later one wins. Know a Texas place from 1960 or earlier that's missing? Send us the source.</p>""",
           OLD_L, "place", "places", "Texas's oldest restaurants", region=False, show_fn=True)

# ---------------------------------------------------------------- the inspections explainer (counts only: no place is named here)
url = f"{DOMAIN}/{INS_PATH}"
n_ins = len(INS_L)
nav, bc = crumbs([("Home", "/"), ("Texas restaurant inspections", "/" + INS_PATH)])
title = fit(["Texas Restaurant Inspections, Explained: City Scores", "Texas Restaurant Inspection Scores, Explained | Texas Eats"], 50, 60, "inspections title")
desc = fit([f"How Austin, El Paso and Arlington score restaurant inspections, what their bands mean, and the latest scores for {n_ins:,} places. Texas has no state grade.",
            f"Austin, El Paso and Arlington publish restaurant inspection scores: how each city scores, what its bands mean, and the latest for {n_ins:,} places."],
           140, 160, "inspections description")
BANDS = {0: ["Green", "Yellow", "Red"], 1: ["Passing", "Below 70"], 2: ["A", "B", "C", "F"]}
BAND_CLS = {"Green": "ok", "Passing": "ok", "A": "ok", "B": "ok", "Yellow": "mid", "C": "mid", "Red": "low", "Below 70": "low", "F": "low"}
city_cards = []
SCALE = ["Austin Public Health scores each inspection out of 100 under the Texas Food Establishment Rules, and its open data sorts every score into a band: Green for 90 and above, Yellow for 70 to 89, and Red below 70. The data covers the last three years.",
         "The City of El Paso scores inspections out of 100 for the city and the county towns it inspects. In the city's words, a score of 70 or above is passing, a score of 60 or below starts a closure, and a violation that poses an imminent threat to public health can close a place whatever the score. The city calls its online scores a summary; full reports are by open-records request.",
         "The City of Arlington scores inspections out of 100 and gives each establishment a letter grade it must post: A for 91 to 100, B for 81 to 90, C for 71 to 80, and F below 70. Its open data has each establishment's latest inspection."]
for j in range(3):
    bn = BAND_N[j]
    lis = "".join(f'<li><span class="res res-{BAND_CLS[b]}">{e(b)}</span> {plural(bn.get(b, 0), "place")}</li>' for b in BANDS[j])
    city_cards.append(f'<li><h3>{INS_CITY[j]}</h3><p>{e(SCALE[j])}</p><ul>{lis}</ul><p class="count">{plural(len(INS_BY_CITY[j]), "place")} in our data, latest score through {e(INS_DATES[j])}. <a href="{e(INS_URL[j])}" rel="noopener">The city\'s records</a>.</p></li>')
body = f"""{nav}
  <main id="main">
  <section class="hero">
    <p class="kicker">{BRAND} guide · city records</p>
    <h1>Texas restaurant inspections, explained</h1>
    <p class="lede">Texas has no statewide restaurant grade. Cities and counties inspect their own restaurants under the Texas Food Establishment Rules, and only a few publish the scores in bulk: Austin, El Paso and Arlington. Here is how each one scores, what its bands mean, and where the {n_ins:,} places in our data with one of those scores stood at their latest inspection.</p>
  </section>
  <section id="groups">
    <h2>Three cities, three scales</h2>
    <p class="sub">All three score out of 100, higher is better, and each has its own way of reading the number. We show each score with the city's own band, as the city published it, and compute no grade of our own.</p>
    <ul class="groups">{"".join(city_cards)}</ul>
    <p>One inspection is a snapshot of one day, and conditions can change quickly. We don't list places by their scores here; the web search can sort a list by each city's latest score, as published.</p>
  </section>
  <section id="lookup">
    <h2>The rest of Texas</h2>
    <p>Houston's open data stops in 2015. Dallas, Fort Worth, San Antonio and Plano publish inspection results one search at a time, and the Dallas and Fort Worth search pages block automated access, so their scores aren't here. Look a place up in the <a href="/explore/">{BRAND} web app</a> for its TABC licenses and, in the three cities above, its latest score and recent history.</p>
    <p class="fine">{other_guides("/" + INS_PATH)}</p>
  </section>
  </main>"""
page(INS_PATH, title, desc, body, [article_ld(url, "Texas restaurant inspections, explained", desc), bc])

# ---------------------------------------------------------------- city pages
city_stats = {}
SEC_DEFS = [  # key, long title phrase, short title phrase, h1 phrase, description phrase builder
    ("bbq", "Barbecue Joints", "Barbecue", "barbecue", lambda n: plural(n, "hand-checked barbecue joint")),
    ("taqueria", "Taquerías", "Tacos", "taquerías", lambda n: plural(n, "taquería")),
    ("texmex", "Tex-Mex", "Tex-Mex", "Tex-Mex", lambda n: plural(n, "Tex-Mex restaurant")),
    ("kolache", "Kolaches", "Kolaches", "kolaches", lambda n: plural(n, "kolache bakery", "kolache bakeries")),
    ("cfs", "Chicken-Fried Steak", "Chicken-Fried Steak", "chicken-fried steak", lambda n: plural(n, "chicken-fried steak spot")),
]
SEC_ORDER = [k for k, *_ in SEC_DEFS] + ["hon", "oldest"]
CITY_INFO = {}
for c in CITY_PAGES:
    here = [p for p in REST if p.city == c]
    info = {k: sorted([p for p in L[k] if p.city == c], key=P.featured_key) for k, _ in GUIDE_TAGS}
    info["hon"] = sorted([p for p in HON_L if p.city == c], key=P.featured_key)
    info["oldest"] = [p for p in OLD_L if p.city == c]
    info["insp"] = Counter(p.band for p in INS_L if p.city == c)
    info["n_ins"] = sum(1 for p in INS_L if p.city == c)
    info["cuis"] = Counter(p.cuisine for p in here if p.cuisine and p.cuisine not in ("Other", "American & Other")).most_common(10)
    info["n_town"] = len(here)
    listed, seen = [], set()
    for k in SEC_ORDER:
        for p in info[k]:
            if id(p) not in seen:
                seen.add(id(p)); listed.append(p)
    info["listed"] = listed
    CITY_INFO[c] = info
    city_stats[c] = {"restaurants": len(here), "listed": len(listed), **{k: len(info[k]) for k in SEC_ORDER},
                     "inspection_scores": info["n_ins"], "inspection_bands": dict(info["insp"])}


def city_sections(info):
    """The sections a city page has, biggest first: (key, long, short, h1 phrase, description phrase)."""
    out = [(k, lt, st, h1p, dp(len(info[k]))) for k, lt, st, h1p, dp in SEC_DEFS if info[k]]
    if info["hon"]:
        has_mi, has_jb = any(p.mi for p in info["hon"]), any(p.jbf for p in info["hon"])
        long = "MICHELIN & James Beard" if has_mi and has_jb else "MICHELIN" if has_mi else "James Beard"
        out.append(("hon", long, "MICHELIN" if has_mi else "James Beard", long if long != "James Beard" else "James Beard honorees",
                    plural(len(info["hon"]), "MICHELIN or James Beard honoree")))
    if info["oldest"]:
        k_old = len(info["oldest"])   # "1 of Texas's oldest restaurants", not "the oldest restaurants" (one place isn't the town's all)
        out.append(("oldest", "Oldest Restaurants", "Oldest Places", "oldest restaurants",
                    f"1 of Texas's oldest restaurants (from {info['oldest'][0].founded})" if k_old == 1
                    else f"{k_old} of Texas's oldest restaurants (back to {info['oldest'][0].founded})"))
    return sorted(out, key=lambda s: (-len(info[s[0]]), SEC_ORDER.index(s[0])))


def tjoin(xs):
    if len(xs) == 1:
        return xs[0]
    conj = " and " if any("&" in x for x in xs) else " & "
    return ", ".join(xs[:-1]) + conj + xs[-1]


def city_title(c, secs):
    cands = []
    for k in range(min(len(secs), 3), 0, -1):
        for col in (1, 2):
            J = tjoin([s[col] for s in secs[:k]])
            # "<town> restaurants" is what people search, so those forms come first
            forms = ([f"{c} Restaurants: {J}", f"{c}, TX Restaurants: {J}", f"{c} Restaurants: {J} | {BRAND}", f"{c}, Texas Restaurants: {J}"]
                     if "Restaurant" not in J else [])
            forms += [f"{c} {J} | {BRAND}", f"{c}, TX {J} | {BRAND}", f"{c}, Texas {J}", f"{c}, TX {J}", f"{c} {J}"]
            if "Restaurant" not in J:
                forms += [f"{c} {J} & Restaurants", f"{c} {J} & Restaurants | {BRAND}", f"{c}, Texas {J} & Restaurants"]
            cands += forms
    cands += [f"{c} Restaurants: What {c} Eats | {BRAND}", f"{c}, Texas Restaurants by Kind | {BRAND}", f"{c}, TX Restaurants, Cafés & Bars | {BRAND}",
              f"{c}, Texas Restaurants, Cafés and Bars", f"{c} Restaurants, Cafés & Bars | {BRAND}", f"{c}, Texas: Restaurants, Barbecue & More | {BRAND}",
              f"{c}, TX: Barbecue, Tacos & Restaurants | {BRAND}"]
    return fit(cands, 50, 60, c + " title")


def city_desc(c, info, secs):
    n_town = info["n_town"]
    leads = [f"In {c}, Texas", f"{c}, Texas", f"{c}, TX"]
    tails = [f". Search {n_town:,} {c} restaurants, cafés and bars", f". Search {n_town:,} local places to eat",
             f", plus {n_town:,} local places to eat on a searchable map", f", plus {n_town:,} more local places to eat", ""]
    extras = ["", f" Checked in {CHECKED}.", " Free iPhone app coming soon.", f" Checked in {CHECKED}. Free iPhone app coming soon."]

    def gen():
        for k in range(len(secs), 0, -1):
            J = join_words([s[4] for s in secs[:k]])
            for lead in leads:
                for tail in tails:
                    for x in extras:
                        yield f"{lead}: {J}{tail}.{x}"
    return fit(list(dict.fromkeys(s.replace("..", ".") for s in gen())), 140, 160, c + " description")


SEC_HEAD = {"bbq": ("Barbecue joints", "bbq"), "taqueria": ("Taquerías", "taqueria"), "texmex": ("Tex-Mex", "texmex"),
            "kolache": ("Kolaches", "kolache"), "cfs": ("Chicken-fried steak", "cfs")}
GUIDE_COUNT_NOUN = {"bbq": "Texas barbecue joints", "taqueria": "Texas taquerías", "texmex": "Texas Tex-Mex restaurants",
                    "kolache": "Texas kolache bakeries", "cfs": "Texas chicken-fried steak spots"}
SINGULAR = {"Texas kolache bakeries": "Texas kolache bakery"}

for c in CITY_PAGES:
    info = CITY_INFO[c]
    path = f"cities/{slug(c)}.html"
    url = DOMAIN + "/" + path
    anchors = Anchors(url)
    secs = city_sections(info)
    title = city_title(c, secs)
    desc = city_desc(c, info, secs)
    k = 3
    while k > 1 and len(join_words([s[3] for s in secs[:k]])) > 48:   # a heading, not the whole table of contents
        k -= 1
    h1_bits = [s[3] for s in secs[:k]]
    h1 = f"{c} restaurants" + (": " + join_words(h1_bits + (["more"] if len(secs) > k else [])) if secs else "")
    nav, bc = crumbs([("Home", "/"), ("Cities", "/cities/"), (c, "/" + path)])
    counts = [s[4] for s in secs]
    n_hc = sum(1 for p in info["listed"] if p.hc and p.tags)
    lede = (f"What {e(c)} has on our lists: {e(join_words(counts))}. "
            + (f"Each hand-checked place had a 2025 or 2026 source when we looked in {CHECKED}. " if n_hc else "")
            + f"In all, {BRAND} maps {info['n_town']:,} restaurants, cafés, bars and bakeries in {e(c)}, nearest first on your phone.")
    parts = [f"""{nav}
  <main id="main">
  <section class="hero">
    <p class="kicker">{BRAND} · {e(c)}, Texas</p>
    <h1>{e(h1)}</h1>
    <p class="lede">{lede}</p>
    <div class="cta-row">{store_button()}<span class="pill store-note">{STORE_NOTE}</span></div>
  </section>"""]
    for s in secs:
        key = s[0]
        if key in SEC_HEAD:
            head, gk = SEC_HEAD[key]
            parts.append(f'<section id="{key}" aria-labelledby="h-{key}"><h2 id="h-{key}">{e(head)} in {e(c)}</h2><p class="sub">Each one checked in {CHECKED} against a 2025–26 source. For all of Texas: <a href="/{GUIDE_PATH[gk]}">{plural(len(L[gk]), SINGULAR.get(GUIDE_COUNT_NOUN[gk], GUIDE_COUNT_NOUN[gk][:-1]), GUIDE_COUNT_NOUN[gk])}</a>.</p><ol class="places">'
                         + "".join(place_item(p, anchors) for p in info[key]) + "</ol></section>")
        elif key == "hon":
            parts.append(f'<section id="honors" aria-labelledby="h-honors"><h2 id="h-honors">MICHELIN &amp; James Beard in {e(c)}</h2><p class="sub">Restaurants in the MICHELIN Guide Texas or named by the James Beard Foundation, reported as facts rather than scores. Across Texas: <a href="/{HON_PATH}">{plural(len(HON_L), "Texas MICHELIN and James Beard restaurant")}</a>.</p><ol class="places">'
                         + "".join(place_item(p, anchors, honors=True) for p in info["hon"]) + "</ol></section>")
        elif key == "oldest":
            parts.append(f'<section id="oldest" aria-labelledby="h-oldest"><h2 id="h-oldest">Oldest restaurants in {e(c)}</h2><p class="sub">In business at this address since 1960 or before, going by the place itself or a published history, listed from the oldest. Each note gives the source of the year. Across Texas: <a href="/{OLD_PATH}">Texas\'s oldest restaurants</a>.</p><ol class="places">'
                         + "".join(place_item(p, anchors, show_fn=True) for p in info["oldest"]) + "</ol></section>")
    if info["n_ins"]:
        ig = info["insp"]
        jj = Counter(p.ins_city for p in INS_L if p.city == c).most_common(1)[0][0]
        ins_bits = join_words([f"{plural(n, 'place')} {b}" for b, n in sorted(ig.items(), key=lambda x: -x[1])])
        parts.append(f'<section id="inspections" aria-labelledby="h-inspections"><h2 id="h-inspections">Inspections in {e(c)}</h2><p class="sub">{e(INS_AGENCY[jj][0].upper() + INS_AGENCY[jj][1:])} publishes an inspection score for {plural(info["n_ins"], "place")} we list in {e(c)}. At their latest inspection, by the city\'s own bands: {e(ins_bits)}. Texas has no statewide grade, and we add none. Records through {e(INS_DATES[jj])}. Each place\'s scores are in the <a href="/explore/#g=inspections&amp;town={e(urllib.parse.quote(c))}">web search</a>; what the scores mean: <a href="/{INS_PATH}">Texas restaurant inspections, explained</a>.</p></section>')
    if info["cuis"]:
        rows = "".join(f'<tr><td>{e(k)}</td><td class="n">{n:,}</td></tr>' for k, n in info["cuis"])
        parts.append(f'<section id="cuisines" aria-labelledby="h-cuisines"><h2 id="h-cuisines">What {e(c)} eats</h2><p class="sub">Kinds of food among the {info["n_town"]:,} places we list in {e(c)}, counted from open map data, TABC licenses and city inspection lists.</p><table><thead><tr><th scope="col">Kind of place</th><th scope="col" class="n">Places</th></tr></thead><tbody>{rows}</tbody></table></section>')
    parts.append(f'<section id="more" aria-labelledby="h-more"><h2 id="h-more">Other Texas towns with a page</h2>{city_links(current=c)}<p class="fine"><a href="/cities/">The cities and towns index</a></p></section>\n  </main>')
    lds = [article_ld(url, h1, desc), bc]
    if info["listed"]:
        lds.append(item_list(f"{c}: " + join_words([s[3] for s in secs]), info["listed"], url, anchors))
    page(path, title, desc, "\n".join(parts), lds)


# ---------------------------------------------------------------- cities index
url = f"{DOMAIN}/cities/"
nav, bc = crumbs([("Home", "/"), ("Cities", "/cities/")])
cards = []
for c in CITY_PAGES:
    info = CITY_INFO[c]
    bits = [f"{s[3]} ({len(info[s[0]])})" for s in city_sections(info)]
    line = (join_words(bits) + ". " if bits else "") + f"{info['n_town']:,} places to eat in all."
    cards.append(f'<a class="card" href="{city_url(c)}"><h3>{e(c)}</h3><p>{e(line[0].upper() + line[1:])}</p></a>')
first, last = CITY_PAGES[:2], CITY_PAGES[-2:]
title = fit([f"Texas Cities & Towns: Restaurant Guides | {BRAND}", f"Texas City Restaurant Guides: {len(CITY_PAGES)} Towns | {BRAND}"], 50, 60, "cities title")
desc = fit([f"Restaurant guides for {len(CITY_PAGES)} Texas cities and towns, from {join_words(first)} to {join_words(last)}: barbecue, tacos, Tex-Mex and honors.",
            f"City-by-city Texas restaurant guides for {len(CITY_PAGES)} cities and towns: barbecue joints, taquerías, Tex-Mex, kolaches, MICHELIN and the oldest places.",
            f"Restaurant guides for {len(CITY_PAGES)} Texas cities and towns: barbecue joints, taquerías, Tex-Mex, kolaches, MICHELIN and James Beard honors and more."],
           140, 160, "cities description")
skipped_line = (f" Other towns get a page once they have at least {MIN_LISTED} hand-checked or honored places; until then, "
                f'<a href="/explore/">search them</a>.')
body = f"""{nav}
  <main id="main">
  <section class="hero">
    <p class="kicker">{BRAND} · cities and towns</p>
    <h1>Texas cities and towns</h1>
    <p class="lede">A page for Texas cities and towns that have enough hand-checked or honored places to say something real: the barbecue joints, taquerías, Tex-Mex, kolaches, MICHELIN and James Beard honorees and oldest restaurants that are actually there, and, in Austin, El Paso and Arlington, the city's own inspection scores.{skipped_line}</p>
  </section>
  <section id="cities-list">
    <h2>Pick a town</h2>
    <div class="grid2">{"".join(cards)}</div>
  </section>
  </main>"""
page("cities/index.html", title, desc, body, [bc], og_type="website")

# ---------------------------------------------------------------- web app (docs/explore/): data split + page
# The web app lists restaurants only (the venues the app hides by default, such as stadium stands and gas-station counters, stay out).
# Three kinds of file, to keep the first load small for ~79,000 places:
# - core.json: the list, search and map columns. Places are ordered by region, county, town, zip and street, so neighbouring rows
#   share their town, zip and street words and gzip well; coordinates are integer steps of 0.0001° from the previous row ("dla"/"dlo"),
#   and the latest inspection is [city, band, score] plus a day number from 2000-01-01 ("idn").
# - ids.json: each place's stable id (the app's id), in core order. Fetched right after the list renders; saved places and shared
#   #p= links wait for it.
# - detail-<county>.json: phones, websites, notes, TABC licenses, alcohol-sales months and inspection histories, keyed by core index,
#   one file per county (Harris's is the biggest), fetched when someone opens (or points at) a place there.
os.makedirs(f"{DOCS}/data", exist_ok=True)
DFILES = [slug(c) for c in COUNTIES] + ["other"]   # detail file per county index; "other" for a place with no county
CAL = {a: {"groups": {g: {"n": v.get("n"), "official": v.get("official")} for g, v in (c.get("groups") or {}).items()}}
       for a, c in (D.get("calibration") or {}).items() if isinstance(c, dict)}
DAY0 = "2000-01-01"


def day_num(iso):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    return (dt.date(int(m[1]), int(m[2]), int(m[3])) - dt.date(2000, 1, 1)).days if m else None


def street_key(a):
    m = re.match(r"\s*(\d+)\s*(.*)", a or "")
    return (m[2].lower(), int(m[1]) if len(m[1]) < 9 else 0) if m else ((a or "").lower(), 0)


def web_order(p):
    rg = REGION_ORDER.index(p.region) if p.region else len(REGION_ORDER)
    return (rg, p.county or "", p.city or "", p.zip, street_key(p.addr), p.name.lower(), p.r["id"])


WEB = sorted(REST, key=web_order)
CORE_KEYS = ["n", "c", "co", "cu", "t", "s", "a", "z", "b", "ch", "g", "hc", "ip", "f", "h", "mi", "dish", "al", "liq"]
cols = {k: [] for k in CORE_KEYS + ["dla", "dlo", "jb", "ij", "ib", "isc", "idn"]}
ids, shards = [], defaultdict(dict)
prev = [0, 0]
for i, p in enumerate(WEB):
    r = p.r
    ids.append(r["id"])
    for k in CORE_KEYS:
        v = r.get(k)
        if k == "a" and v:
            v = p.addr
        cols[k].append(v)
    for k, j, v in (("dla", 0, p.lat), ("dlo", 1, p.lon)):
        if v is None:
            cols[k].append(None)
        else:
            q = round(v * 10000)
            cols[k].append(q - prev[j])
            prev[j] = q
    dk = r["co"] if r.get("co") is not None else len(COUNTIES)   # the detail file this place's extras go in
    if r.get("co") is None:
        cols["co"][-1] = len(COUNTIES)
    cols["jb"].append(1 if r.get("jbf") else None)
    ins = p.ins or {}
    cols["ij"].append(ins.get("j"))
    cols["ib"].append(ins.get("b"))
    cols["isc"].append(ins.get("s"))
    cols["idn"].append(day_num(ins.get("d")))
    d = {k: r[k] for k in ("ph", "note", "seas", "fn", "jbf", "lic", "aln") if r.get(k)}
    if p.site:
        d["w"] = p.site
    if ins.get("h"):
        d["in"] = {"n": ins.get("n"), "h": ins["h"]}
    if d:
        shards[dk][str(i)] = d
assert len(set(ids)) == len(ids), "place ids must be unique (saved places and #p= links use them)"
for f in glob.glob(f"{DOCS}/data/detail*.json"):   # files from an older layout or a region that emptied
    os.remove(f)
# columns that are mostly empty (hand-checked and honored facts) go as [[index, value], ...] instead of 79,000 nulls
sparse = {k: [[i, v] for i, v in enumerate(cols.pop(k)) if v is not None]
          for k in list(cols) if sum(v is not None for v in cols[k]) < len(WEB) * 0.05}
core = {"generated": D["generated"], "inspections_through": INS_THROUGH, "liquor_updated": LIQ_UPDATED, "mixbev_from": MIX_FROM,
        "mixbev_to": MIX_TO, "day0": DAY0, "n": len(WEB), "cities": CITIES, "cuisines": CUISINES, "counties": COUNTIES + ["Texas"],
        "brands": D["brands"], "srcs": D["srcs"], "results": RESULTS, "itypes": ITYPES, "calibration": CAL, "cols": cols, "sparse": sparse,
        "dfiles": [f if dk in shards else None for dk, f in enumerate(DFILES)]}   # null: that county has no extras, so no file
assert all("," not in x for x in ids)
# ids and details are keyed by row, so a file from one build must never meet another build's core.json (a browser cache can outlive a
# deploy by GitHub's 10 minutes): every file carries the build's version, the page fetches with ?v=, and the web app refuses a mismatch
DATA_VER = hashlib.sha256(json.dumps([core, ids, shards], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
DETAIL_FILES = {}
for dk, d in sorted(shards.items()):
    fn = f"detail-{DFILES[dk]}.json"
    json.dump({"_v": DATA_VER, **d}, open(f"{DOCS}/data/{fn}", "w"), separators=(",", ":"), ensure_ascii=False)
    DETAIL_FILES[fn] = len(d)
json.dump({"ver": DATA_VER, **core}, open(f"{DOCS}/data/core.json", "w"), separators=(",", ":"), ensure_ascii=False)
json.dump({"v": DATA_VER, "ids": ",".join(ids)}, open(f"{DOCS}/data/ids.json", "w"), separators=(",", ":"))   # one string: smaller than an array
json.dump(json.load(open(f"{ROOT}/data/tx/tx_shapes.json")), open(f"{DOCS}/data/tx_shapes.json", "w"), separators=(",", ":"))


def sizes(path):
    raw = open(path, "rb").read()
    return len(raw), len(gzip.compress(raw, 9))


SIZES = {os.path.relpath(f, DOCS): sizes(f) for f in sorted(glob.glob(f"{DOCS}/data/*.json"))}

EXPLORE_CSS = """
  [hidden] { display: none !important; }
  .ex-hero { padding: 28px 0 8px; }
  .ex-hero h1 { font-size: clamp(30px, 6vw, 44px); }
  .ex-controls { background: var(--bg); padding: 10px 0 8px; border-bottom: 1px solid var(--rule); }
  .ex-guides { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 8px; scrollbar-width: none; }
  @media (min-width: 601px) { .ex-guides { flex-wrap: wrap; overflow: visible; } }
  @media (max-width: 600px) { .ex-guides { padding-right: 32px; -webkit-mask-image: linear-gradient(to right, #000 calc(100% - 32px), transparent); mask-image: linear-gradient(to right, #000 calc(100% - 32px), transparent); } }
  .ex-guides button, .ex-view button, .ex-small { flex: 0 0 auto; border: 1px solid var(--rule); background: var(--surface); color: var(--accent); border-radius: 999px; padding: 7px 12px; font: 600 14px/1.2 system-ui, sans-serif; font-family: inherit; cursor: pointer; }
  .ex-guides button[aria-pressed="true"], .ex-view button[aria-pressed="true"] { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }
  .ex-row1 { display: flex; gap: 8px; align-items: center; }
  .ex-row1 input[type=search] { flex: 1; min-width: 0; font: 16px/1.3 system-ui, sans-serif; font-family: inherit; padding: 10px 12px; border: 2px solid var(--accent); border-radius: 12px; background: var(--surface); color: var(--ink); }
  .ex-row2 { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 8px; font-size: 14px; }
  .ex-row2 select { font: 14px system-ui, sans-serif; font-family: inherit; padding: 6px 8px; border: 1px solid var(--rule); border-radius: 8px; background: var(--surface); color: var(--ink); max-width: 46vw; }
  .ex-view { margin-left: auto; display: flex; gap: 4px; }
  #ex-count { margin: 8px 0 0; font-size: 14px; color: var(--muted); }
  #ex-sub { margin: 4px 0 0; font-size: 14px; color: var(--ink2); }
  #ex-locmsg { font-size: 13px; color: var(--muted); margin: 4px 0 0; }
  .ex-list { list-style: none; padding: 0; margin: 10px 0; }
  .ex-list li + li { border-top: 1px solid var(--rule); }
  .ex-row { width: 100%; display: flex; gap: 12px; align-items: center; text-align: left; background: none; border: 0; padding: 12px 4px; cursor: pointer; color: var(--ink); font: inherit; }
  .ex-row:hover { background: var(--surface2); }
  .ex-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; overflow-wrap: anywhere; }
  .ex-main b { font-weight: 650; }
  .ex-town { font-size: 14px; color: var(--muted); }
  .tag-dash { background: transparent; color: var(--muted); border: 1px dashed var(--rule); }
  .ex-metric { text-align: right; display: flex; flex-direction: column; align-items: flex-end; max-width: 46%; }
  .ex-metric b { font: 800 22px/1 var(--display); color: var(--accent); }
  .ex-metric small { font-size: 11px; color: var(--muted); }
  .ex-rank { flex: 0 0 34px; height: 34px; display: grid; place-items: center; font: 800 20px var(--display); color: var(--accent); border-radius: 8px; }
  .ex-rank.top { background: var(--orange); color: var(--on-orange); }
  .ex-empty { padding: 24px 4px; color: var(--muted); }
  #ex-more { display: block; margin: 8px auto 24px; }
  #ex-mapwrap { position: relative; height: min(72vh, 720px); margin: 10px 0 20px; border: 1px solid var(--rule); border-radius: 16px; overflow: hidden; background: #dfe6f2; }
  #ex-map { width: 100%; height: 100%; display: block; touch-action: none; cursor: grab; }
  .ex-zoom { position: absolute; right: 10px; top: 10px; display: flex; flex-direction: column; gap: 6px; }
  .ex-zoom button { width: 44px; height: 44px; border-radius: 10px; border: 1px solid #e3dbcf; background: #fff; color: #002868; font: 700 22px/1 system-ui, sans-serif; cursor: pointer; }
  #ex-maphint { position: absolute; left: 10px; top: 10px; margin: 0; font-size: 13px; background: #fff; padding: 3px 8px; border-radius: 999px; color: #28385a; pointer-events: none; }
  #ex-mapattr { position: absolute; right: 0; bottom: 0; margin: 0; font-size: 11px; background: rgba(255,255,255,.85); padding: 2px 6px; border-radius: 6px 0 0 0; color: #28385a; pointer-events: none; }
  .ex-panel { position: fixed; z-index: 20; right: 0; top: 0; bottom: 0; width: min(440px, 100%); overflow-y: auto; background: var(--surface); border-left: 1px solid var(--rule); box-shadow: -8px 0 24px rgba(0,0,0,.12); padding: 18px 20px 40px; }
  @media (max-width: 600px) { .ex-panel { top: auto; height: 86vh; border-left: 0; border-top: 4px solid var(--orange); border-radius: 18px 18px 0 0; } }
  .ex-close { position: sticky; top: 0; float: right; width: 44px; height: 44px; border-radius: 50%; border: 1px solid var(--rule); background: var(--surface); font-size: 24px; line-height: 1; cursor: pointer; color: var(--ink); }
  .ex-kicker { margin: 0; font-size: 12px; font-weight: 700; letter-spacing: .1em; color: var(--accent2); }
  .ex-panel h2 { font-size: 34px; margin: 4px 0 6px; text-transform: uppercase; overflow-wrap: anywhere; }
  .ex-addr, .ex-dist { margin: 0 0 4px; color: var(--ink2); font-size: 15px; }
  .ex-actions { margin: 14px 0 8px; display: grid; gap: 8px; }
  .ex-apple { justify-content: center; }
  .ex-act-row { display: flex; gap: 8px; flex-wrap: wrap; }
  .ex-act-row a, .ex-act-row button { flex: 1; min-width: 88px; text-align: center; padding: 10px; border: 1px solid var(--rule); border-radius: 12px; text-decoration: none; color: var(--accent); font: 600 14px system-ui, sans-serif; font-family: inherit; background: var(--surface); cursor: pointer; }
  .ex-act-row button[aria-pressed="true"] { background: var(--soft); color: #0e1a30; }
  .ex-sec { margin-top: 18px; }
  .ex-sec h3 { font-size: 12px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); border-bottom: 1px solid var(--rule); padding-bottom: 6px; margin-bottom: 8px; }
  .ex-sec p, .ex-sec li { font-size: 15px; color: var(--ink2); margin: 6px 0; }
  .ex-sec ul { padding-left: 18px; }
  .ex-kv { display: flex; justify-content: space-between; gap: 12px; font-size: 15px; padding: 3px 0; }
  .ex-kv span { color: var(--ink2); flex: 0 0 auto; max-width: 40%; }
  .ex-kv b { text-align: right; overflow-wrap: anywhere; }
  .ex-fine { font-size: 13px !important; color: var(--muted) !important; }
  .ex-result { display: flex; align-items: center; gap: 10px; font-weight: 600; flex-wrap: wrap; }
  .ex-app { margin-top: 22px; font-size: 14px; color: var(--muted); }
  body.ex-open { overflow: hidden; }
  .ex-backdrop { position: fixed; inset: 0; z-index: 19; background: rgba(14, 26, 48, .32); }
  /* phones: 16px or more in the search box and the selects, or iOS Safari zooms the page when one gets focus */
  @media (max-width: 600px) { .ex-row1 input[type=search], .ex-row2 select { font-size: 16px; } }
  /* the sort's longest choice ("Lowest inspection score") at 16px: wider than 46vw, so on phones it may use the row */
  @media (max-width: 600px) { #ex-sort { max-width: calc(100vw - 100px); } }
  .ex-res { display: inline-block; font: 800 12px/1.4 -apple-system, system-ui, sans-serif; letter-spacing: .04em; text-transform: uppercase; padding: 3px 8px; border-radius: 6px; text-align: center; }
  .ex-res-ok { background: #ddefe3; color: #0e5a2b; } .ex-res-mid { background: #ffe9c2; color: #6b3a00; } .ex-res-low { background: #f9d5db; color: #7a0019; } .ex-res-x { background: var(--surface2); color: var(--ink2); }
"""
url = f"{DOMAIN}/explore/"
N_HC_GUIDES = len(HC_ANY)
title = fit(["Texas Restaurant Search: Map, Barbecue & Inspection Scores", "Search Texas Restaurants: Barbecue, Tacos & Inspections"], 50, 60, "explore title")
desc = fit([f"Look up {N_REST:,} Texas restaurants by name, town, street, zip or dish, map {N_HC_GUIDES} hand-checked places and see city inspection scores.",
            f"Search {N_REST:,} Texas restaurants by name, town, street or dish, map {N_HC_GUIDES} hand-checked places, TABC licenses and city inspection scores.",
            f"Search {N_REST:,} Texas restaurants by name, town, street or dish, browse {N_HC_GUIDES} hand-checked places on a map and see inspection scores."],
           140, 160, "explore description")
nav, bc = crumbs([("Home", "/"), ("Search", "/explore/")])
guide_buttons = "".join(f'<button type="button" data-g="{k}" aria-pressed="false">{e(t)}</button>' for k, t in
                        (("bbq", "Barbecue"), ("texmex", "Tex-Mex"), ("taqueria", "Taquerías"), ("kolache", "Kolaches"),
                         ("cfs", "Chicken-fried steak"), ("honors", "MICHELIN & James Beard"), ("oldest", "Oldest"),
                         ("brewpubs", "Brewpubs"), ("alcohol", "Bar sales"), ("inspections", "Inspection scores"),
                         ("all", "All restaurants"), ("saved", "Saved")))
explore_js = open(f"{ROOT}/scripts/explore.js").read()
JS_KEYS = sorted(set(re.findall(r'store\.set\("([a-z]+)"', explore_js)))   # the keys the web app writes, each under STORAGE_PREFIX
assert JS_KEYS and "localStorage.setItem(PREFIX + k" in explore_js and len(re.findall(r"localStorage\.setItem", explore_js)) == 1
assert "</script" not in explore_js.lower()
assert f'"{STORAGE_PREFIX}"' in explore_js, "explore.js must keep its localStorage keys under " + STORAGE_PREFIX
body = f"""{nav}
  <main id="main">
  <section class="ex-hero">
    <p class="kicker">{BRAND} · on the web</p>
    <h1>Search Texas restaurants</h1>
    <p class="sub">Pick a list, or type a name, a town, a street or a dish. Behind the search: {N_REST:,} Texas restaurants, cafés, bars and bakeries; {N_HC_GUIDES} hand-checked places on the barbecue, Tex-Mex, taquería, kolache, chicken-fried steak and oldest-places lists; {len(HON_L)} MICHELIN and James Beard honorees; TABC licenses; and the inspection scores Austin, El Paso and Arlington publish. It's the data the iPhone and iPad app will ship with, and what you save stays in this browser.</p>
  </section>
  <p id="ex-loading" hidden>Loading the restaurant list…</p>
  <noscript><p>The search needs JavaScript. The guides work without it: <a href="/{GUIDE_PATH['bbq']}">barbecue joints</a>, <a href="/{GUIDE_PATH['taqueria']}">taquerías</a>, <a href="/{GUIDE_PATH['kolache']}">kolaches</a>, <a href="/{INS_PATH}">inspections explained</a>.</p></noscript>
  <div id="ex-app" hidden data-ver="{DATA_VER}">
    <div class="ex-controls">
      <div class="ex-guides" role="group" aria-label="Guides">{guide_buttons}</div>
      <div class="ex-row1">
        <label class="skip" for="ex-q">Search</label>
        <input id="ex-q" type="search" placeholder="Name, town, street or dish" autocomplete="off" enterkeyhint="search">
        <button type="button" id="ex-locate" class="ex-small">Near me</button>
      </div>
      <div class="ex-row2">
        <label>Sort <select id="ex-sort" aria-label="Sort"></select></label>
        <select id="ex-town" aria-label="Town"></select>
        <select id="ex-cuisine" aria-label="Kind of place"></select>
        <label><input type="checkbox" id="ex-chains"> Hide chains</label>
        <label id="ex-bibwrap" hidden><input type="checkbox" id="ex-bib"> <span>Bib Gourmand <span id="ex-bibn"></span></span></label>
        <button type="button" id="ex-clear" class="ex-small" hidden>Clear filters</button>
        <div class="ex-view" role="group" aria-label="View"><button type="button" data-v="list" aria-pressed="true">List</button><button type="button" data-v="map" aria-pressed="false">Map</button></div>
      </div>
      <p id="ex-sub"></p>
      <p id="ex-count" aria-live="polite"></p>
      <p id="ex-locmsg"></p>
    </div>
    <div id="ex-listwrap"><ol id="ex-list" class="ex-list"></ol><button type="button" id="ex-more" class="ex-small" hidden></button></div>
    <div id="ex-mapwrap" hidden>
      <canvas id="ex-map" aria-label="Map of Texas with a dot for each place in the list. The list view has the same places."></canvas>
      <div class="ex-zoom"><button type="button" id="ex-zin" aria-label="Zoom in">+</button><button type="button" id="ex-zout" aria-label="Zoom out">−</button></div>
      <p id="ex-maphint"></p>
      <p id="ex-mapattr">Outlines © OpenStreetMap contributors, Overture Maps Foundation</p>
    </div>
  </div>
  <div id="ex-backdrop" class="ex-backdrop" hidden></div>
  <aside id="ex-panel" class="ex-panel" hidden aria-labelledby="ex-pname"></aside>
  </main>
<script>
{explore_js}
</script>"""
webapp_ld = {"@context": "https://schema.org", "@type": "WebApplication", "name": f"{BRAND} web app", "url": url,
             "applicationCategory": "TravelApplication", "operatingSystem": "Any", "browserRequirements": "Requires JavaScript",
             "description": desc, "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
             "publisher": ORG_REF}
page("explore/index.html", title, desc, body, [webapp_ld, bc], extra_css=EXPLORE_CSS, og_type="website")

# ---------------------------------------------------------------- landing page
# alt text says what each capture shows (docs/screenshots, made by scripts/capture-screenshots.sh; copies by scripts/site-images.sh)
shots = [("home", "The Texas Eats home screen: a search box and guide cards for Barbecue Joints, Tex-Mex, Taquerías and Kolaches, each with its count of places.", "A guide for each Texas craving."),
         ("bbq", "The hand-checked barbecue list in Texas Eats, nearest first, with each joint's town, kind and distance.", "Barbecue joints nearest you."),
         ("detail", "Micklethwait Craft Meats in Texas Eats: its address, Bib Gourmand and barbecue tags, a button for Apple Maps' ratings, hours and photos, Directions and Call buttons, a small map and the hand-checked notes on what to order.", "Each place, hand-checked notes and all."),
         ("map", "The Texas Eats map around Austin, with pins and numbered clusters for hand-checked places and filter buttons for barbecue, inspections and honors.", "The map, by guide."),
         ("honors", "The MICHELIN and James Beard list in Texas Eats.", "MICHELIN Guide and James Beard honorees.")]
shot_html = []
for i, (name, alt, cap) in enumerate(shots):
    png = f"{DOCS}/img/screen-{name}.png"
    if not os.path.exists(png):
        continue
    w, h = png_size(png)
    lazy = ' loading="lazy"'   # the section sits below the fold at every width
    webp = os.path.exists(f"{DOCS}/img/screen-{name}.webp")
    src = (f'<source srcset="/img/screen-{name}.webp" type="image/webp">' if webp else "")
    shot_html.append(f'<li><picture>{src}<img src="/img/screen-{name}.png" alt="{e(alt)}" width="{w}" height="{h}"{lazy} decoding="async"></picture><p>{e(cap)}</p></li>')

BBQ_L = L["bbq"]
n_bbq_towns = len({p.city for p in BBQ_L if p.city})
faq = [
    ("Is Texas Eats free?", "Completely: no price, no ads, no in-app purchases and no account to create. It's an iPhone and iPad app on its way to the App Store, with no Android version yet; until it's out, the web search here works in any browser."),
    ("Where do the lists come from?", f"Two kinds of source. The barbecue, Tex-Mex, taquería, kolache, chicken-fried steak and oldest-places lists are our own research from {CHECKED}, with a 2025 or 2026 source behind each place: its website or menu, a dated local news story or an official tourism listing. The wider directory of {N_REST:,} restaurants starts from Overture Maps' open place data, keeps the kinds of listing that proved reliable against Austin's, El Paso's and Arlington's inspection lists, and adds restaurants and bars from TABC's license list and those cities' inspection lists."),
    ("Where's good barbecue in Texas?", f"Our barbecue list has {len(BBQ_L)} hand-checked joints in {plural(n_bbq_towns, 'town')}. In the web search, the Barbecue list puts the nearest first once you share your location. Many joints open only a few days a week and close when the brisket runs out, so check before you drive."),
    ("How do I check a Texas restaurant's inspection?", f"Texas has no statewide grade. Austin, El Paso and Arlington publish their inspection scores, and for places there the app and this site show the latest score out of 100 with the city's own band (Austin's Green, Yellow or Red; El Paso's passing line of 70; Arlington's letter grade). Houston, Dallas, San Antonio and Fort Worth don't publish scores in bulk; their search pages are the place to look."),
    ("What are the bar sales numbers?", f"Every Texas business with a Mixed Beverage permit reports its liquor, wine, beer and cover-charge receipts to the Texas Comptroller each month, and the state publishes them. We add up the latest twelve months for each place. They're reported figures, not estimates, and places with only a beer-and-wine license don't report."),
    ("Does it show ratings and reviews?", "Not from us. Tapping a place opens Apple Maps' own card inside the app, with Apple's current ratings, hours, photos and directions. None of our lists is sorted by anyone's rating."),
    ("Does it need my location?", "No. Location only matters for putting the nearest places first. If you share it, it stays on your iPhone or iPad and never reaches us, and the app works fine without it. On this website, Near me reads your location inside your browser and nowhere else."),
    ("A place has closed, or something's wrong. How do I tell you?", f"Write to {EMAIL} with the place's name, its town and what changed. Corrections ship with the next data update."),
]
faq_html = "".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in faq)
faq_ld = {"@context": "https://schema.org", "@type": "FAQPage", "@id": f"{DOMAIN}/#faq",
          "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}
app_ld = {"@context": "https://schema.org", "@graph": [
    # No "offers" until the app is on the App Store (put it back with the listing URL: price 0, USD).
    {"@type": "MobileApplication", "@id": f"{DOMAIN}/#app", "name": APP_NAME,
     "alternateName": ["Texas Eats", "TX Eats", "Texas Eats: BBQ, Tex-Mex & Taquerías"],
     "description": f"A free guide to {N_REST:,} Texas restaurants, with hand-checked lists of barbecue joints, Tex-Mex, taquerías, kolache bakeries, chicken-fried steak and the state's oldest places, {len(HON_L)} MICHELIN and James Beard honorees, TABC licenses, reported bar sales and the inspection scores Austin, El Paso and Arlington publish. Sort by distance, open Apple Maps' live place card for hours and photos, and save places for your next trip.",
     "url": f"{DOMAIN}/", "image": f"{DOMAIN}/og.png", "operatingSystem": "iOS, iPadOS", "applicationCategory": "TravelApplication",
     "applicationSubCategory": "Food & Drink", "inLanguage": "en", "publisher": {"@id": ORG_ID}},
    {"@type": "Organization", "@id": ORG_ID, "name": BRAND, "url": f"{DOMAIN}/",
     "logo": {"@type": "ImageObject", "url": f"{DOMAIN}/icon-512.png", "width": 512, "height": 512}, "email": EMAIL,
     "contactPoint": {"@type": "ContactPoint", "contactType": "customer support", "email": EMAIL, "availableLanguage": "en"},
     # the Eats Ranked hub lists this site as a subOrganization; say so from this side too
     "parentOrganization": HUB},
    {"@type": "WebSite", "@id": f"{DOMAIN}/#website", "name": BRAND, "alternateName": ["TX Eats", "Texas Eats app"], "url": f"{DOMAIN}/",
     "inLanguage": "en", "publisher": {"@id": ORG_ID}}]}
if shot_html:
    app_ld["@graph"][0]["screenshot"] = f"{DOMAIN}/img/screen-{next(n for n, *_ in shots if os.path.exists(f'{DOCS}/img/screen-{n}.png'))}.png"
title = fit(["Texas Eats: BBQ, Tex-Mex, Taquerías & Restaurant App", "Texas Eats: Barbecue, Tacos & Texas Restaurant Guide App"], 50, 60, "landing title")
desc = fit([f"Brisket, breakfast tacos, kolaches and Tex-Mex: a free iPhone and iPad guide to {N_REST:,} Texas restaurants, with hand-checked lists and inspections.",
            f"A free iPhone and iPad guide to {N_REST:,} Texas restaurants, with hand-checked barbecue joints, taquerías, Tex-Mex, kolaches and city inspection scores.",
            f"Free iPhone and iPad guide to {N_REST:,} Texas restaurants: hand-checked barbecue, taquerías, Tex-Mex and kolaches, plus MICHELIN and James Beard."],
           140, 160, "landing description")
city_cards = "".join(f'<li><a href="{city_url(c)}">{e(c)}</a></li>' for c in CITY_PAGES)
screens = f"""
  <section id="screens">
    <h2>Inside the app</h2>
    <ul class="shots" tabindex="0" aria-label="Texas Eats app screenshots">
      {"".join(shot_html)}
    </ul>
  </section>""" if shot_html else ""
guide_cards = "".join(f'<a class="card gc gc-{k}" href="/{GUIDE_PATH[k]}"><b>{len(L[k])}</b><h3>{e(GUIDE_NAME[k])}</h3><p>{plural(len(L[k]), "hand-checked place")}{line}.</p></a>'
                      for k, line in (("bbq", ", brisket to sausage"), ("taqueria", ", trompo to breakfast tacos"), ("texmex", ", enchiladas to fajitas"),
                                      ("kolache", " for kolaches and klobasniky"), ("cfs", " with cream gravy")))
body = f"""  <main id="main">
  <section class="hero">
    <p class="kicker">{BRAND}: {TAGLINE} for iPhone and iPad</p>
    <h1>Texas restaurants, brisket to breakfast tacos</h1>
    <p class="lede">Looking for brisket on butcher paper, a breakfast taco on a flour tortilla, a kolache on the drive down I-35 or a plate of cheese enchiladas? {BRAND} starts with lists we checked place by place, adds the MICHELIN Guide and James Beard honorees, the state's alcohol licenses and the inspection scores three cities publish, and maps {N_REST:,} restaurants, cafés, bars and bakeries in {N_TOWNS:,} Texas towns.</p>
    <div class="cta-row">{store_button()}<a class="btn btn-ghost" href="/explore/">Search on the web</a><span class="pill store-note">No charge, no ads, no sign-in. The App Store release is on its way.</span></div>
    <ul class="stats" aria-label="What's in the app">
      <li><b>{N_HC_GUIDES}</b><span>hand-checked places</span></li>
      <li><b>{len(HON_L)}</b><span>MICHELIN &amp; James Beard</span></li>
      <li><b>{len(INS_L):,}</b><span>with a city inspection score</span></li>
      <li><b>{N_REST:,}</b><span>restaurants</span></li>
    </ul>
  </section>

  <section id="what">
    <h2>Built around how Texas eats</h2>
    <p class="sub">Star ratings won't tell you which joint sells out of brisket by noon, or where the trompo turns. {BRAND} is organized the way people here eat: barbecue, Tex-Mex, taquerías, kolaches and chicken-fried steak, each place checked in {CHECKED} against a 2025–26 source. Where a city publishes inspection scores, you see the latest one with the city's own band, never a grade from us, and Apple Maps' live card supplies ratings, hours and photos.</p>
  </section>

  <section id="how">
    <h2>How it works</h2>
    <ol class="steps">
      <li class="step"><div class="n" aria-hidden="true">1</div><div><h3>Start with a craving.</h3><p>Barbecue Joints, Tex-Mex, Taquerías, Kolaches, Chicken-Fried Steak, MICHELIN &amp; James Beard, Oldest Places, Brewpubs, Bar Sales or Inspection Scores. Or type a name, a town, a street or a dish to search the {N_REST:,} we list.</p></div></li>
      <li class="step"><div class="n" aria-hidden="true">2</div><div><h3>Find the closest one.</h3><p>Put the nearest first, narrow it to one town or one kind of food, or pan the map from El Paso to Beaumont.</p></div></li>
      <li class="step"><div class="n" aria-hidden="true">3</div><div><h3>Head out.</h3><p>Check today's hours and photos on Apple Maps' card, call ahead, get directions, or save the place for the next road trip.</p></div></li>
    </ol>
  </section>
{screens}
  <section id="guides">
    <h2>Texas food guides</h2>
    <p class="sub">Each of the app's lists has its own page here, free to read.</p>
    <div class="grid2">
      {guide_cards}
      <a class="card gc gc-oldest" href="/{OLD_PATH}"><b>{len(OLD_L)}</b><h3>Texas's oldest restaurants</h3><p>{plural(len(OLD_L), "place")} open at the same address since 1960 or earlier.</p></a>
      <a class="card gc gc-honors" href="/{HON_PATH}"><b>{len(HON_L)}</b><h3>MICHELIN &amp; James Beard</h3><p>{plural(len(HON_L), "honored Texas restaurant")}.</p></a>
      <a class="card" href="/{INS_PATH}"><h3>Restaurant inspections, explained</h3><p>How Austin, El Paso and Arlington score restaurants, and the latest scores for {plural(len(INS_L), "place")}.</p></a>
    </div>
  </section>

  <section id="cities">
    <h2>Barbecue, tacos and more by city</h2>
    <p class="sub">From El Paso to Galveston, the towns with enough hand-checked or honored places for a page of their own. The <a href="/cities/">cities and towns index</a> sums up what's on each.</p>
    <ul class="cities">{city_cards}</ul>
  </section>

  <section id="pricing">
    <h2>Free, with no catch</h2>
    <p class="sub">The app costs nothing, shows no ads and sells nothing inside, and there's no account to make. The lists ship inside the app, so they open right away and keep working when the signal drops out on a farm road.</p>
  </section>

  <section id="privacy">
    <h2>What stays on your phone</h2>
    <p class="sub">{BRAND} collects nothing about you: no sign-in, no analytics, no ads. Location, if you turn it on, only puts the nearest places first, and your saved places are kept on the phone or iPad. The website has no cookies and no trackers. <a href="/privacy.html">The privacy policy</a> has the details.</p>
  </section>

  <section id="faq">
    <h2>Questions</h2>
    {faq_html}
  </section>

  <section id="download" class="final">
    <h2>Find your next brisket</h2>
    <p class="sub">The iPhone and iPad app is almost here, and it's free. Ask for early access.</p>
    <div class="cta-row">{store_button()}</div>
  </section>
  </main>"""
page("index.html", title, desc, body, [app_ld, faq_ld], og_type="website")

# ---------------------------------------------------------------- privacy and terms
nav, bc = crumbs([("Home", "/"), ("Privacy policy", "/privacy.html")])
body = f"""{nav}
  <main id="main" class="legal">
  <section class="hero">
    <h1>Privacy policy</h1>
    <p class="lede">Short version: the {BRAND} app collects nothing about you, and this website doesn't track you. Last updated {POLICY_UPDATED}.</p>
  </section>
  <section>
    <h2>The app</h2>
    <ul>
      <li><b>No account, no analytics, no ads.</b> The app has no sign-in, no advertising and no analytics or crash-reporting code. We receive no data from it.</li>
      <li><b>Location.</b> If you allow it, your location is used on your device to sort places by distance and show where you are on the map. It is never sent to us. You can turn it off in Settings at any time.</li>
      <li><b>Saved places and filters</b> are stored only on your device and are deleted when you delete the app.</li>
      <li><b>Apple Maps.</b> When you open a place's ratings, hours and photos, or ask for directions, the app asks Apple Maps for that place. Apple handles that request under <a href="https://www.apple.com/legal/privacy/" rel="noopener">Apple's privacy policy</a>, as it does for any app that shows a map.</li>
      <li><b>Spotlight.</b> The app adds its hand-checked and honored places to your device's search index so you can find them from Spotlight. That index stays on your device.</li>
      <li><b>Calls, websites and email</b> you start from a place open in the Phone app, your browser or Mail, and are handled by them.</li>
    </ul>
    <p>When the app is on the App Store, its privacy label will be "Data Not Collected".</p>
    <h2>This website</h2>
    <p>The site is static pages hosted on GitHub Pages. It sets no cookies and loads no analytics, fonts or scripts from anyone else.</p>
    <ul>
      <li><b>Saved places and your last guide.</b> The search page (<a href="/explore/">/explore/</a>) keeps the places you save and the last guide you opened in your browser's local storage, on this device only, under the keys {join_words([f"<code>{STORAGE_PREFIX}{k}</code>" for k in JS_KEYS])}. Nothing is sent to us. Clearing this site's data in your browser removes them.</li>
      <li><b>Location.</b> If you tap Near me or choose the Nearest sort, your browser asks whether to share your location. If you allow it, the location is used only inside your browser to sort places by distance and is never sent to us or anyone else.</li>
    </ul>
    <p>GitHub may keep standard server logs, such as IP addresses, for security; see <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" rel="noopener">GitHub's privacy statement</a>.</p>
    <h2>Email</h2>
    <p>If you email us, we use your message and address only to reply and to fix the listing you told us about. We don't add you to a mailing list or share your address. Mail to {EMAIL} reaches our inbox through Cloudflare Email Routing; see <a href="https://www.cloudflare.com/privacypolicy/" rel="noopener">Cloudflare's privacy policy</a>.</p>
    <h2>Children</h2>
    <p>The app collects no personal information from anyone, including children.</p>
    <h2>Changes and contact</h2>
    <p>If this policy changes, the new version will be posted here with a new date. Questions: <a href="mailto:{EMAIL}">{EMAIL}</a>.</p>
  </section>
  </main>"""
page("privacy.html", "Texas Eats Privacy Policy: No Tracking, No Accounts",
     fit(["How Texas Eats treats your data: the iPhone app collects none, your location and saved places stay on your device, and this site uses no cookies or trackers.",
          "How Texas Eats treats your data: the app collects none, your location and saved places stay on your device, and this website uses no cookies or trackers."], 140, 160),
     body, [bc])

nav, bc = crumbs([("Home", "/"), ("Terms of use", "/terms.html")])
body = f"""{nav}
  <main id="main" class="legal">
  <section class="hero">
    <h1>Terms of use</h1>
    <p class="lede">The plain-language terms for the {BRAND} app and this website. Last updated {POLICY_UPDATED}.</p>
  </section>
  <section>
    <h2>What the app is</h2>
    <p>{BRAND} is a free guide to restaurants in Texas. It is provided as is, for personal use, without charge and without warranties of any kind.</p>
    <h2>Check before you go</h2>
    <p>Restaurants open, close, change their hours and change their menus, and many barbecue joints sell out early. Dishes and founding years are what each place or a named source said when we checked in {CHECKED}. We work to keep the lists right, but we can't promise that any listing is current or complete. Call the restaurant before you make the trip.</p>
    <h2>Inspection scores and public records</h2>
    <p>The app and this site show the inspection scores Austin Public Health, the City of El Paso and the City of Arlington publish, each with the city's own band or grade and its date. Texas has no statewide grade, and we compute none. An inspection is a snapshot of one day. Alcohol licenses come from the Texas Alcoholic Beverage Commission's license list, and bar sales are the receipts Mixed Beverage permit holders report to the Texas Comptroller. For official records, use each agency's own site (<a href="{e(TABC_SEARCH)}" rel="noopener">TABC's public inquiry</a>).</p>
    <h2>Other people's content</h2>
    <p>Ratings, reviews, hours and photos in each place card come from Apple Maps and are Apple's and its providers', under Apple's terms. Restaurant names and trademarks belong to their owners. MICHELIN and the MICHELIN Guide are trademarks of Michelin; James Beard Foundation and James Beard Award are trademarks of the James Beard Foundation. {BRAND} is not affiliated with any restaurant, chain, award body or government agency.</p>
    <h2>Data sources and licenses</h2>
    <ul>
      <li>Texas Alcoholic Beverage Commission, TABC License Information, and the Texas Comptroller of Public Accounts, Mixed Beverage Gross Receipts (both on data.texas.gov), modified for use here.</li>
      <li>Austin Public Health, Food Establishment Inspection Scores (data.austintexas.gov, public domain); the City of El Paso's Food Establishment Scores; the City of Arlington's Food Establishments open data.</li>
      <li>Overture Maps Foundation places data, under the Community Data License Agreement, Permissive 2.0, including data from Meta, Microsoft, DAC, BrightQuery, AllThePlaces (CC0 1.0) and Foursquare (Apache 2.0).</li>
      <li>Overture Maps Foundation divisions, used for the state and county outlines on the map, under the Open Database License: © OpenStreetMap contributors, Overture Maps Foundation.</li>
      <li>Overture Maps Foundation addresses data, compiled from open address sources under permissive licenses (see docs.overturemaps.org/attribution), used to place records on the map.</li>
      <li>U.S. Census Bureau Geocoder (public domain), used for addresses Overture's address points don't cover.</li>
      <li>The MICHELIN Guide Texas selection and the James Beard Foundation's awards, finalists and America's Classics: honors reported as facts.</li>
      <li>Barbecue joints, Tex-Mex, taquerías, kolaches, chicken-fried steak and founding years: our own research, with a source recorded for every place.</li>
    </ul>
    <h2>Corrections</h2>
    <p>If a listing is wrong, or you own a restaurant and want something fixed, email <a href="mailto:{EMAIL}">{EMAIL}</a>. We fix mistakes in the next update.</p>
    <h2>Liability</h2>
    <p>To the extent the law allows, we are not liable for any loss arising from use of the app or site, including a wasted drive to a closed restaurant.</p>
    <h2>Changes</h2>
    <p>We may update these terms; the current version and its date are always on this page. See also the <a href="/privacy.html">privacy policy</a>.</p>
  </section>
  </main>"""
page("terms.html", "Texas Eats Terms of Use: A Free Guide, Provided As Is",
     fit(["The terms for Texas Eats and this site: a free restaurant guide provided as is, public records shown as the agencies published them, and how to report a mistake.",
          "The terms for Texas Eats and this website: a free guide provided as is, public records shown as the agencies published them, and how to report a mistake.",
          "The terms for Texas Eats and this website: a free guide provided as is, city and state records shown as published, and how to report a mistake."], 140, 160),
     body, [bc])

body = f"""  <main id="main">
  <section class="hero">
    <h1>Page not found</h1>
    <p class="lede">No page lives at this address. Head back to the <a href="/">{BRAND} home page</a>, the <a href="/{GUIDE_PATH['bbq']}">barbecue list</a> or the <a href="/explore/">Texas restaurant search</a>.</p>
  </section>
  </main>"""
page("404.html", f"Not found: {BRAND}", "No page lives at this address.", body, robots="noindex,follow")
noindexed.remove("404.html")


# ---------------------------------------------------------------- plumbing
for f in os.listdir(f"{DOCS}/cities"):   # a city the data lost: drop its old page instead of leaving it live and stale
    if f.endswith(".html") and f"cities/{f}" not in written + noindexed:
        os.remove(f"{DOCS}/cities/{f}")
        print("removed stale", f"cities/{f}")
urls = ["" if w == "index.html" else w.replace("index.html", "") for w in written]
urls.sort(key=lambda u: (u != "", u.startswith("cities/"), u))
open(f"{DOCS}/sitemap.xml", "w").write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                       + "".join(f"  <url><loc>{DOMAIN}/{u}</loc><lastmod>{TODAY}</lastmod></url>\n" for u in urls) + "</urlset>\n")
open(f"{DOCS}/robots.txt", "w").write(f"User-agent: *\nAllow: /\n\nSitemap: {DOMAIN}/sitemap.xml\n")
json.dump({"name": BRAND, "short_name": "TX Eats", "description": f"{TAGLINE[0].upper() + TAGLINE[1:]}: a guide to {N_REST:,} Texas restaurants.",
           "start_url": f"{BASE}/", "display": "browser", "background_color": "#f7f3ec", "theme_color": "#002868",
           "icons": [{"src": f"{BASE}/icon-192.png", "sizes": "192x192", "type": "image/png"}, {"src": f"{BASE}/icon-512.png", "sizes": "512x512", "type": "image/png"}]},
          open(f"{DOCS}/site.webmanifest", "w"), indent=2)
if CUSTOM_DOMAIN:
    open(f"{DOCS}/CNAME", "w").write(CUSTOM_DOMAIN + "\n")
elif os.path.exists(f"{DOCS}/CNAME"):
    os.remove(f"{DOCS}/CNAME")   # no custom domain yet: GitHub serves the project address
open(f"{DOCS}/.nojekyll", "w").write("")
os.makedirs(f"{ROOT}/playbook", exist_ok=True)
json.dump({"generated": TODAY, "domain": DOMAIN, "restaurants": N_REST, "places_incl_hidden": len(PLACES), "towns": N_TOWNS, "counties": N_COUNTIES,
           "on_an_official_list": N_OFFICIAL, "serves_alcohol_tabc": N_LIQ, "reported_alcohol_sales": N_ALC, "hand_checked_on_a_guide": N_HC,
           **{"guide_" + k: len(v) for k, v in L.items()}, "oldest": len(OLD_L), "honors": len(HON_L), "michelin": MI_COUNT, "james_beard": N_JBF,
           "americas_classics": N_CLASSICS, "inspection_scores": len(INS_L),
           "inspection_bands": {INS_CITY[j]: dict(BAND_N[j]) for j in range(3)}, "inspections_through": INS_THROUGH,
           "liquor_updated": LIQ_UPDATED, "mixbev_months": [MIX_FROM, MIX_TO],
           "city_pages": city_stats, "cities_without_a_page": CITY_SKIPPED, "noindex_pages": noindexed,
           "web_app_data_bytes": {k: {"raw": r, "gzip": g} for k, (r, g) in SIZES.items()}},
          open(f"{ROOT}/playbook/site-numbers.json", "w"), indent=1, ensure_ascii=False)
print("wrote", len(written) + len(noindexed) + 1, "pages:", ", ".join(written))
if noindexed:
    print("noindex:", ", ".join(noindexed))
print(f"restaurants {N_REST:,} in {N_TOWNS} towns | official {N_OFFICIAL:,} | hand-checked on a guide {N_HC} | "
      + " | ".join(f"{k} {len(v)}" for k, v in L.items()) + f" | oldest {len(OLD_L)} | honors {len(HON_L)} | inspection scores {len(INS_L):,}")
print("city pages:", ", ".join(CITY_PAGES), "| no page (listed places):", CITY_SKIPPED)
print(f"website blocklist: {len(BLOCKLIST)} entries, {len(BLOCKED_LINKS)} links dropped:", "; ".join(f"{n} {u}" for n, u in BLOCKED_LINKS) or "none")
for k, (r, g) in SIZES.items():
    print(f"  {k}: {r / 1024:,.0f} KB raw, {g / 1024:,.0f} KB gzip")
