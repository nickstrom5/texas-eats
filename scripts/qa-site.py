"""QA for the website in docs/: static checks on every generated page, then every page in headless Chrome at phone and desktop widths.

Static (no browser):
- no "every restaurant" / "all N restaurants"-style overclaims, "worst"/"dirtiest" lists or grades anywhere (text, meta, alt text,
  JSON-LD, the web app's strings)
- a Content-Security-Policy meta on every page whose hashes match each inline <script>/<style>; no inline style or on* attributes
- titles 50-60 and descriptions 140-160 characters, unique across indexable pages; one <h1>; sitemap = the indexable pages
- city pages: the title, h1 and description name only sections the page has
- JSON-LD parses; ItemList items point to an anchor on the same page; no aggregateRating/review; no empty streetAddress
- promotional spots (title, description, og/twitter, h1, kicker, lede, Article headline) never name a place whose latest score is in
  its city's low band (Austin Red, El Paso below 70, Arlington F); the inspections page names no place at all and lists none
- the hand-checked guide pages list only hand-checked places with that guide's tag (matched to core.json by name and address)
- the honors page never calls a finalist or semifinalist a winner; MICHELIN and James Beard trademark lines on every page
- the inspections page says Texas has no statewide grade, names each city's bands and links each city's records
- the web app keeps its localStorage under "txeats-"; its map credits OpenStreetMap and Overture; its Inspections guide doesn't open
  on the lowest-score order (no worst list)
- data: ids unique and as many as places; detail files keyed inside core and in the right county; websites are http(s); no
  Google-derived field (rating, reviews, price) anywhere in the published data; core.json, ids.json, every detail file and the web
  app page carry the same build version (rows only line up within one build)
- every page: the "Part of Eats Ranked" footer line, a #org Organization whose parentOrganization is the eatsranked.com hub, a mailto:
  to nick@eatsranked.com, no web font loaded; work-with-nick@gmail.com and other states' app names and
  repo slugs nowhere in docs/, other states' names nowhere in the site's own copy or code; no domain or URL from
  pipeline/website_blocklist.json (hacked, expired or wrong-business sites) anywhere in docs/, data files included; the privacy policy names every localStorage
  key the web app writes; the landing page shows the app screenshots (docs/img) with alt text, sizes and lazy loading
- 2026-10-13 (Nick's copy decisions): no file in docs/ says "Confirmed listing" (the label is "High-confidence listing"), and none
  promises an invite or a TestFlight link ("we'll send you the TestFlight link", "you'll get an invite"): early access is an ask
Browser (Playwright, channel="chrome"): no horizontal scroll, no console errors, no CSP violations, no broken internal links or
images; the web app loads, searches (dishes, "north lamar" direction words), opens a place with its city's inspection score and
TABC records, Back closes it, the phone panel is a modal dialog, a #p= link opens that place, the map draws, a hostile #g= doesn't
break it, and saved places use the txeats- prefix. Also: AA contrast of every text run (light at both widths, dark on the main pages);
ids.json waits for the first use; a slow county file keeps keyboard focus in the panel; a failed or other-build county file is reported
as missing, never as "no license matched"; and the six family web-app bugs (16px inputs on phones, Back/Forward, the place as a modal
dialog at every width, corrupt localStorage, no "Nearest" without a fix, a fresh location fix on every Near me tap); a tap never
waits for ids.json (the place opens at once, Save and the #p= link follow); ids.json or a core.json from another build or from before
versioning is refused with a reload message, never mixed in; a #p= link whose place isn't there says so. A search the open
guide can't answer offers "Search all restaurants (N matches)", which finds a famous place outside the guide in one click; the search
box's placeholder fits at 375 px, and so do the sort select's choices.

Usage: .venv/bin/python scripts/qa-site.py            (serves docs/ itself on a free localhost port; exits 1 on any problem)
       .venv/bin/python scripts/qa-site.py --static   (static checks only, a few seconds)
Ported from fl-eats/scripts/qa-site.py. Until the custom domain is live the site sits under /texas-eats/ on github.io, so the pages
are served under that same path here (a temporary folder with docs/ linked in as texas-eats/).
"""
import base64
import functools
import glob
import hashlib
import html
import html.parser
import http.server
import json
import os
import re
import sys
import tempfile
import threading
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(__file__), "..")
DOCS = os.environ.get("QA_DOCS") or os.path.join(ROOT, "docs")   # QA_DOCS: check a copy (used to mutation-test these checks)
DOMAIN = open(os.path.join(DOCS, "CNAME")).read().strip() if os.path.exists(os.path.join(DOCS, "CNAME")) else "nickstrom5.github.io"
BASE = re.search(r'data-base="([^"]*)"', open(os.path.join(DOCS, "index.html")).read()).group(1)
STORAGE_PREFIX = "txeats-"
OTHER_PREFIXES = ("coeats-", "ce-", "wieats-", "fleats-")
INS_PAGE = "texas-restaurant-inspections.html"
HON_PAGE = "texas-michelin-james-beard.html"
GUIDE_PAGES = {"texas-barbecue.html": 1, "texas-tex-mex.html": 2, "texas-taquerias.html": 4, "texas-kolaches.html": 8,
               "texas-chicken-fried-steak.html": 16, "texas-oldest-restaurants.html": 32}
LOW_BANDS = {"Red", "Below 70", "F"}
EMAIL = "nick@eatsranked.com"            # Nick, 2026-10-12: the site's contact address
OLD_EMAIL = "work-with-nick@gmail.com"     # must appear nowhere in docs/
# Nick, 2026-10-13: the tier label is "High-confidence listing" (the family's wording), never "Confirmed listing"; and since only his
# internal TestFlight group exists, no page promises an invite or a link ("we'll send you the TestFlight link"): early access is an ask
OLD_LABEL = re.compile(r"confirmed\s+listing", re.I)
PROMISE = re.compile(r"\b(?:we'll|we will|we'd|you'll|you will|you'd)\b[^.!?]{0,60}?\b(?:invit\w*|testflight|beta|early access)\b"
                     r"|\b(?:send|email|e-mail|text)\s+you\s+(?:a|an|the|your)\s+(?:testflight|invit\w*|beta|link)\b"
                     # "Early access by email" states an offer; "ask for early access by email" is an ask, and passes
                     r"|(?<!ask for )(?<!asking for )\bearly access\s+(?:is\s+)?(?:by\s+(?:email|invit\w*)|available)\b", re.I)
HUB_ORG = "https://eatsranked.com/#organization"
# other Eats Ranked states: their app names and repo slugs may not appear anywhere in docs/, and their state names may not appear in the
# site's own copy or code (a place's own name or street, inside its list item or its JSON-LD, may say "New York" or "Washington Ave";
# Washington, Colorado and Florida are also Texas street or river names, so they aren't checked as words)
OTHER_APPS = r"\b(?:Wisconsin|California|Washington|Colorado|Connecticut|Maine|Idaho|New York|Chicago|Illinois|Florida|Hawaii|Pennsylvania) Eats\b|Chicago Restaurants: Ranked|\bChi Ranked\b"
OTHER_SLUGS = r"\b(?:wi|ca|wa|co|ct|me|id|ny|chi|fl|hi|pa)-eats\b|\b(?:wisconsin|california|washington|colorado|connecticut|maine|idaho|new-york|florida|hawaii|pennsylvania)-eats\b|chicago-restaurants-ranked"
OTHER_STATES = r"\b(?:Wisconsin|California|Connecticut|Maine|Idaho|New York|Illinois|Chicago|Florida|Hawaii|Pennsylvania)\b"
TM_MICHELIN = "MICHELIN and the MICHELIN Guide are trademarks of Michelin"
TM_JBF = "James Beard Foundation and James Beard Award are trademarks of the James Beard Foundation"

# claims the lists can't back up: the app lists what was checked or matched, never "every"/"all N" restaurants
OVERCLAIMS = [
    r"\bevery\s+(?:single\s+)?(?:texas\s+|local\s+|licensed\s+)?(?:restaurant|bar|caf[eé]|place to eat|eatery|barbecue joint|taquer[ií]a)",
    r"\bevery\s+place\s+in\s+(?:texas|the\s+state)",
    r"\ball\s+(?:of\s+the\s+)?\d[\d,]*\s+(?:\w+\s+){0,2}(?:restaurants|places|spots|caf[eé]s|bars)\b",
    r"\b(?:all|every)\s+(?:the\s+)?(?:restaurants|places)\s+in\s+(?:the\s+state|texas|town)\b",
    r"\b(?:all|every)\s+(?:of\s+)?texas'?s\s+(?:restaurants|bars)\b",
    r"\b(?:search|browse|see|map)\s+(?:all|every)\s+(?:of\s+)?(?:the\s+)?\d[\d,]*\b",    # "search all 52,573" (no noun, same claim)
    r"\b(?:confirmed|checked|verified)\s+open\b",            # the research dates show when we checked a source, not that it's open now
    r"\b(?:worst|dirtiest|grossest|filthiest)\b",            # no worst lists, anywhere
    # Texas: inspection scores and Arlington's letter grades are the cities' own and are shown as such; a grade of ours never is
    r"\bour\s+(?:own\s+)?(?:grade|score)\b|\bgrade(?:d|s)?\s+by\s+(?:us|texas eats)\b",
]
# city-page words -> the section that backs them
GENERIC = set("""the and of a an at on in by to la el le los las de del da di du restaurant restaurants cafe café cafes grill grille bar bars pub
kitchen local mexican tex mex texmex food foods deli bakery market house fish seafood barbecue bar b q kolache kolaches tavern diner pizza pizzeria taqueria tacos
burger burgers bbq sushi wings coffee tea juice bistro cantina eatery shack hut express company co inn lounge club station dock docks
grill bay beach island lone star texas houston dallas austin san antonio main street corner new old original famous best little big great first
american italian mexican chinese thai japanese indian greek french spanish caribbean haitian sandwich sandwiches subs chicken steak
steakhouse smokehouse pit brisket cafe mama papa joe joes""".split())
CITY_KEYWORDS = [(r"barbecue|\bbbq\b", "bbq"), (r"taquer|\btacos?\b", "taqueria"), (r"tex-mex", "texmex"), (r"kolache", "kolache"),
                 (r"chicken-fried", "cfs"), (r"michelin|james beard|honoree", "honors"), (r"\boldest\b", "oldest"),
                 (r"inspection", "inspections")]


class Page(html.parser.HTMLParser):
    """The facts the static checks need from one HTML file."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.title, self.desc, self.robots, self.canonical, self.csp = "", None, "", None, None
        self.h1s, self.ids, self.section_ids, self.alts, self.metas = [], [], set(), [], []
        self.scripts, self.styles, self.ldjson, self.bad_attrs = [], [], [], []
        self.promo = []        # text of the kicker and lede paragraphs
        self._in, self._buf, self._h1, self._promo = None, [], None, None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for k, v in attrs:
            if k == "style" or k.startswith("on"):
                self.bad_attrs.append(f"<{tag} {k}=…>")
        if "id" in a:
            self.ids.append(a["id"])
            if tag == "section":
                self.section_ids.add(a["id"])
        if tag == "img":
            self.alts.append(a.get("alt"))
        if tag == "meta":
            if a.get("name") == "description":
                self.desc = a.get("content", "")
            elif a.get("name") == "robots":
                self.robots = a.get("content", "")
            elif (a.get("http-equiv") or "").lower() == "content-security-policy":
                self.csp = a.get("content", "")
            if (a.get("property") or a.get("name") or "").startswith(("og:", "twitter:")):
                self.metas.append(a.get("content", ""))
        if tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        if tag in ("script", "style", "title"):
            self._in, self._buf = (tag, a.get("type")), []
        if tag == "h1":
            self._h1 = []
        if tag == "p" and set((a.get("class") or "").split()) & {"lede", "kicker"}:
            self._promo = []

    def handle_endtag(self, tag):
        if self._in and tag == self._in[0]:
            text = "".join(self._buf)
            kind, typ = self._in
            if kind == "title":
                self.title = text
            elif kind == "style":
                self.styles.append(text)
            elif typ == "application/ld+json":
                self.ldjson.append(text)
            elif typ in (None, "", "text/javascript", "module"):
                self.scripts.append(text)
            self._in = None
        if tag == "h1" and self._h1 is not None:
            self.h1s.append("".join(self._h1).strip())
            self._h1 = None
        if tag == "p" and self._promo is not None:
            self.promo.append("".join(self._promo))
            self._promo = None

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)
        if self._h1 is not None:
            self._h1.append(data)
        if self._promo is not None:
            self._promo.append(data)


def sha(s):
    return "'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() + "'"


def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield path + "." + k, k, v
            yield from walk(v, path + "." + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, f"{path}[{i}]")


def _safe_json(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _dicts(o):
    """Every JSON object inside a parsed JSON-LD block, nested ones and @graph members included."""
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _dicts(v)
    elif isinstance(o, list):
        for v in o:
            yield from _dicts(v)


def doc_files():
    return sorted(f for f in glob.glob(os.path.join(DOCS, "**", "*.html"), recursive=True) if "/screenshots/" not in f)


def rel(f):
    return os.path.relpath(f, DOCS)


def page_url(path):
    full = f"https://{DOMAIN}{BASE}" if DOMAIN.endswith("github.io") else f"https://{DOMAIN}"
    return full + "/" + ("" if path == "index.html" else path.removesuffix("index.html"))


def sitemap_paths():
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [e.text for e in ET.parse(os.path.join(DOCS, "sitemap.xml")).getroot().findall("s:url/s:loc", ns)]
    out = []
    for u in locs:
        p = urllib.parse.urlparse(u).path
        if BASE and p.startswith(BASE):
            p = p[len(BASE):]
        p = p.lstrip("/")
        out.append(p + "index.html" if p == "" or p.endswith("/") else p)
    return out


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", s.replace("'", "").replace("’", "")).strip() + " "


def load_core():
    """core.json with its sparse columns expanded and its coordinates and dates decoded: a list of dicts, in core order."""
    core = json.load(open(os.path.join(DOCS, "data", "core.json")))
    n, C = core["n"], dict(core["cols"])
    for k, pairs in (core.get("sparse") or {}).items():
        col = [None] * n
        for i, v in pairs:
            col[i] = v
        C[k] = col
    rows, la, lo = [], 0, 0
    for i in range(n):
        r = {k: C[k][i] for k in C}
        if r.get("dla") is not None:
            la += r["dla"]; lo += r["dlo"]
            r["la"], r["lo"] = la / 10000, lo / 10000
        r["city"] = core["cities"][r["c"]] if r.get("c") is not None else ""
        rows.append(r)
    return core, rows


def blocklist_patterns(problems):
    """pipeline/website_blocklist.json as (label, regex) pairs, case-insensitive: a "domain" entry matches that domain and every
    subdomain (www. included) with or without a scheme; a "url" entry matches that URL with http or https, with or without www. and a
    trailing slash."""
    try:
        entries = json.load(open(os.path.join(ROOT, "pipeline", "website_blocklist.json")))
    except (OSError, ValueError) as ex:
        problems.append(f"pipeline/website_blocklist.json: unreadable ({ex})")
        return []
    if not isinstance(entries, list) or not entries:   # an empty list would let this check pass without checking anything
        problems.append("pipeline/website_blocklist.json: empty (it should hold at least the entries found so far)")
        return []
    out = []
    for b in entries:
        match, target = b.get("match", "domain"), (b.get("url") or b.get("domain") or "").strip().lower()
        if match not in ("domain", "url") or not target:
            problems.append(f"pipeline/website_blocklist.json: bad entry {b}")
            continue
        if match == "domain":
            d = target.rstrip(".").removeprefix("www.")
            out.append((f"{d} ({b.get('place', '')})", re.compile(r"(?<![a-z0-9-])(?:[a-z0-9-]+\.)*" + re.escape(d) + r"(?![a-z0-9-])", re.I)))
        else:
            u = re.sub(r"^(?:https?:)?//(?:www\.)?", "", target).rstrip("/")
            out.append((f"{u} ({b.get('place', '')})", re.compile(r"(?:https?:)?(?://)?(?:www\.)?" + re.escape(u) + r"/?(?=[\s\"'<>\\]|$)", re.I)))
    return out


def static_checks():
    problems = []
    pages = {rel(f): open(f, encoding="utf-8").read() for f in doc_files()}
    parsed = {p: Page(t) for p, t in pages.items()}
    in_sitemap = set(sitemap_paths())
    titles, descs = {}, {}
    try:
        core, rows = load_core()
    except (OSError, ValueError, KeyError) as ex:
        return [f"data: couldn't read core.json ({ex})"], len(pages)
    # names a promotional spot must never carry: places whose latest score is in its city's low band, when no place of the same name is fine
    bad, fine = set(), set()
    res = core.get("results") or []
    for r in rows:
        b = res[r["ib"]] if isinstance(r.get("ib"), int) and 0 <= r["ib"] < len(res) else None
        (bad if b in LOW_BANDS else fine).add(norm(r["n"]))
    # a name made only of everyday words ("Local", "Taqueria Cafe") can't be told from the copy around it, so only distinctive names count
    distinctive = lambda k: len(k.strip()) >= 6 and any(w not in GENERIC for w in k.split())
    promo_bad = sorted(k for k in bad - fine if distinctive(k))
    any_bad = sorted(k for k in bad if distinctive(k))
    by_key = {}
    for r in rows:
        by_key.setdefault((norm(r["n"]), norm(r.get("a")), r.get("z")), []).append(r)
    for path, text in pages.items():
        pg = parsed[path]
        where = path
        indexed = "noindex" not in pg.robots
        # --- overclaims: everything a reader or a crawler sees (CSS aside)
        visible = html.unescape(re.sub(r"<style>.*?</style>", " ", text, flags=re.S))
        visible = re.sub(r"\s+", " ", visible.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&"))
        for rx in OVERCLAIMS:
            for m in re.finditer(rx, visible, re.I):
                problems.append(f"{where}: overclaim \"{m.group(0)}\" (…{visible[max(0, m.start() - 40):m.end() + 20]}…)")
        # --- CSP
        if not pg.csp:
            problems.append(f"{where}: no Content-Security-Policy meta")
        else:
            pol = {d.split()[0]: d.split()[1:] for d in (x.strip() for x in pg.csp.split(";")) if d}
            if pol.get("default-src") != ["'none'"]:
                problems.append(f"{where}: CSP default-src isn't 'none'")
            for name, blocks in (("script-src", pg.scripts), ("style-src", pg.styles)):
                allowed = pol.get(name, [])
                if any(x in allowed for x in ("'unsafe-inline'", "'unsafe-eval'", "*", "https:", "data:")):
                    problems.append(f"{where}: CSP {name} is loose: {allowed}")
                for b in blocks:
                    if sha(b) not in allowed:
                        problems.append(f"{where}: an inline {name.split('-')[0]} block isn't in the CSP (hash {sha(b)[:20]}…)")
            for need in ("base-uri", "form-action", "connect-src", "img-src"):
                if need not in pol:
                    problems.append(f"{where}: CSP has no {need}")
        if pg.bad_attrs:
            problems.append(f"{where}: inline style/event attributes break the CSP: {pg.bad_attrs[:3]}")
        if re.search(r"<script[^>]+src=|<link[^>]+rel=\"stylesheet\"", text):
            problems.append(f"{where}: loads an external script or stylesheet")
        # --- titles, descriptions, headings, sitemap
        if len(pg.h1s) != 1:
            problems.append(f"{where}: {len(pg.h1s)} <h1>")
        if path != "404.html":
            if not 50 <= len(pg.title) <= 60:
                problems.append(f"{where}: title is {len(pg.title)} characters: {pg.title}")
            if pg.desc is None or not 140 <= len(pg.desc) <= 160:
                problems.append(f"{where}: description is {len(pg.desc or '')} characters")
        if indexed and path != "404.html":
            if pg.title in titles:
                problems.append(f"{where}: same title as {titles[pg.title]}")
            if pg.desc in descs:
                problems.append(f"{where}: same description as {descs[pg.desc]}")
            titles[pg.title], descs[pg.desc] = path, path
            if path not in in_sitemap:
                problems.append(f"{where}: indexable but not in sitemap.xml")
            if pg.canonical != page_url(path):
                problems.append(f"{where}: canonical {pg.canonical} != {page_url(path)}")
        elif path in in_sitemap:
            problems.append(f"{where}: noindex page is in sitemap.xml")
        for a in pg.alts:
            if not a:
                problems.append(f"{where}: an <img> has no alt text")
        dup_ids = {i for i in pg.ids if pg.ids.count(i) > 1}
        if dup_ids:
            problems.append(f"{where}: duplicate ids {sorted(dup_ids)[:5]}")
        # --- every page: part of the Eats Ranked family, in Wisconsin's words, and the Organization names its parent (XS-08)
        if not re.search(r'Part of <a href="https://eatsranked\.com/"(?: rel="noopener")?>Eats Ranked</a>, restaurant apps state by state\.', text):
            problems.append(f"{where}: no 'Part of Eats Ranked' footer link")
        orgs = [b for raw in pg.ldjson for b in _dicts(_safe_json(raw)) if b.get("@type") == "Organization" and b.get("@id", "").endswith("/#org")]
        if not orgs or not all((o.get("parentOrganization") or {}).get("@id") == HUB_ORG for o in orgs):
            problems.append(f"{where}: no #org Organization with parentOrganization {HUB_ORG}")
        # --- the contact address (Nick, 2026-10-12)
        if f'href="mailto:{EMAIL}' not in text:
            problems.append(f"{where}: no mailto:{EMAIL} link")
        # --- no web font: the site uses system faces only (the CSP and the privacy policy promise nothing loads from anyone else)
        if re.search(r"@font-face|/fonts/", text):
            problems.append(f"{where}: loads a web font")
        # --- no other state's name in this site's own copy or code (place items and JSON-LD aside), nor its app name or repo (XS-05)
        own = re.sub(r'<li id="[^"]*">.*?</li>|<script type="application/ld\+json">.*?</script>', " ", text, flags=re.S)
        for m in re.finditer(OTHER_STATES, own):
            problems.append(f"{where}: names another state's site (…{own[max(0, m.start() - 40):m.end() + 20]}…)")
        # --- trademark lines (the footer carries them on every page)
        for tm in (TM_MICHELIN, TM_JBF):
            if tm not in visible:
                problems.append(f"{where}: missing the trademark line \"{tm[:40]}…\"")
        # --- promotional spots never name a place with a Follow-Up or Closed latest result
        lds = []
        for raw in pg.ldjson:
            try:
                lds.append(json.loads(raw))
            except ValueError:
                pass
        headlines = [x.get("headline", "") + " " + x.get("description", "") for x in lds if isinstance(x, dict) and x.get("@type") == "Article"]
        promo_text = norm(" ".join([pg.title, pg.desc or ""] + pg.metas + pg.h1s + pg.promo + headlines))
        for k in promo_bad:
            if k in promo_text:
                problems.append(f"{where}: a promotional spot names{k}, whose latest inspection score is in its city's low band")
        # --- city pages: the title, h1 and description promise only what's on the page
        if path.startswith("cities/") and path != "cities/index.html":
            promise = " ".join([pg.title, pg.h1s[0] if pg.h1s else "", pg.desc or ""]).lower()
            for rx, sec in CITY_KEYWORDS:
                if re.search(rx, promise) and sec not in pg.section_ids:
                    problems.append(f"{where}: title/h1/description mention {rx!r} but the page has no #{sec} section")
        # --- a town's total counts every place there, the listed ones included: never framed as extra ("Beyond those", "N more");
        # a town gets a page for hand-checked or honored places, and "checked" means hand-checked only
        if path.startswith("cities/") and re.search(r"\bBeyond those\b|\bplus [\d,]+ more\b", visible):
            problems.append(f"{where}: the town's total is framed as extra places, but it includes the listed ones")
        if re.search(r"enough checked places", visible):
            problems.append(f"{where}: says towns get a page for 'checked places' (the rule is hand-checked or honored places)")
        # --- a self-claim of "Texas's oldest restaurant" is always attributed
        for m in re.finditer(r"texas'?s?'? oldest restaurant(?!s)", visible, re.I):
            before = visible[max(0, m.start() - 40):m.start()].lower()
            if not re.search(r"calls itself|its own|service mark|claim", before):
                problems.append(f"{where}: unattributed \"{m.group(0)}\" (…{visible[max(0, m.start() - 40):m.end() + 10]}…)")
        # --- JSON-LD
        for raw in pg.ldjson:
            try:
                ld = json.loads(raw)
            except ValueError as ex:
                problems.append(f"{where}: bad JSON-LD ({ex})")
                continue
            if "</" in raw:
                problems.append(f"{where}: JSON-LD contains a raw '</'")
            for p, k, v in walk(ld):
                if k in ("aggregateRating", "review", "reviewRating", "ratingValue", "reviewCount"):
                    problems.append(f"{where}: JSON-LD has {k} at {p}")
                if k == "streetAddress" and not str(v).strip():
                    problems.append(f"{where}: empty streetAddress at {p}")
            for block in ([ld] + ld.get("@graph", [])) if isinstance(ld, dict) else []:
                if block.get("@type") != "ItemList":
                    continue
                own_url = pg.canonical or page_url(path)
                items = block.get("itemListElement", [])
                if block.get("numberOfItems") != len(items):
                    problems.append(f"{where}: ItemList numberOfItems {block.get('numberOfItems')} != {len(items)}")
                for li in items:
                    it = li.get("item", {})
                    u = it.get("url", "")
                    if not u.startswith(own_url + "#"):
                        problems.append(f"{where}: ItemList item {it.get('name')!r} url {u!r} isn't on this page")
                    elif u.split("#", 1)[1] not in pg.ids:
                        problems.append(f"{where}: ItemList item {it.get('name')!r} points to #{u.split('#', 1)[1]}, which isn't on the page")
                    s = it.get("sameAs")
                    if s and not re.match(r"https?://", s):
                        problems.append(f"{where}: sameAs {s!r} isn't http(s)")
                # --- a hand-checked guide lists only hand-checked places with its tag
                if path in GUIDE_PAGES:
                    tag = GUIDE_PAGES[path]
                    for li in items:
                        it = li.get("item", {})
                        a = it.get("address", {})
                        key = (norm(it.get("name")), norm(a.get("streetAddress")), a.get("postalCode") or None)
                        hits = by_key.get(key, [])
                        if not any(r.get("hc") == 1 and (r.get("g") or 0) & tag for r in hits):
                            problems.append(f"{where}: lists {it.get('name')!r}, which isn't a hand-checked place with this guide's tag")
        # --- links: only http(s), mailto and tel leave the site
        for href in re.findall(r'href="([^"]*)"', text):
            if re.match(r"\s*(javascript|data|vbscript):", href, re.I) and not href.startswith("data:image/svg+xml"):
                problems.append(f"{where}: unsafe link {href[:40]}")
        # --- the App Store button has no Apple logo until it's Apple's own badge
        for m in re.finditer(r'<a class="btn store-btn"[^>]*>(.*?)</a>', text, re.S):
            if "<svg" in m.group(1):
                problems.append(f"{where}: the early-access button carries an Apple logo")
    # --- the inspections page: no statewide grade, each city's bands, each city's records, and no place named or listed
    ins = pages.get(INS_PAGE)
    if not ins:
        problems.append(f"{INS_PAGE} is missing")
    else:
        vis = norm(html.unescape(re.sub(r"<(script|style)\b.*?</\1>", " ", ins, flags=re.S)))
        for need in ("no statewide restaurant grade", "Green", "Yellow", "Red", "70 or above is passing", "A for 91 to 100"):
            if norm(need) not in vis:
                problems.append(f"{INS_PAGE}: doesn't say \"{need}\"")
        for u in ("data.austintexas.gov", "foodscores.elpasotexas.gov", "opendata.arlingtontx.gov"):
            if u not in ins:
                problems.append(f"{INS_PAGE}: doesn't link {u}")
        if 'class="places"' in ins or '"ItemList"' in ins:
            problems.append(f"{INS_PAGE}: lists places")
        named = [k for k in any_bad if k in vis]
        if named:
            problems.append(f"{INS_PAGE}: names places with a low-band score: {named[:5]}")
    # --- the honors page never calls a finalist or semifinalist a winner
    hon = pages.get(HON_PAGE, "")
    for li in re.findall(r"<li id=\"[^\"]*\">.*?</li>", hon, re.S):
        t = html.unescape(re.sub(r"<[^>]+>", " ", li))
        if "James Beard winner" in t and not re.search(r"James Beard: [^;]*\bwinner\b", t):
            problems.append(f"{HON_PAGE}: a place carries 'James Beard winner' without a winning honor: {t[:80]}")
        if re.search(r"(?:semi)?finalist\s+winner|winner\s+\(?(?:semi)?finalist", t, re.I):
            problems.append(f"{HON_PAGE}: mixes finalist and winner: {t[:80]}")
    # --- the web app
    ex = parsed.get("explore/index.html")
    if ex:
        js = "\n".join(ex.scripts)
        if f'"{STORAGE_PREFIX}"' not in js:
            problems.append(f"explore/index.html: localStorage prefix {STORAGE_PREFIX!r} not found")
        for m in re.finditer(r"""localStorage\.(?:get|set|remove)Item\(\s*(["'`])([^"'`]*)\1""", js):
            if not m.group(2).startswith(STORAGE_PREFIX):
                problems.append(f"explore/index.html: localStorage key {m.group(2)!r} doesn't start with {STORAGE_PREFIX!r}")
        for other in OTHER_PREFIXES:
            if re.search(rf"""["'`]{re.escape(other)}["'`]""", js):
                problems.append(f"explore/index.html: uses another state's storage prefix {other!r}")
        if not re.search(r'id="ex-mapattr"[^>]*>[^<]*© OpenStreetMap contributors, Overture Maps Foundation', pages["explore/index.html"]):
            problems.append("explore/index.html: the map doesn't credit OpenStreetMap contributors and Overture Maps Foundation")
        if re.search(r"""inspections:\s*\{[^}]*sorts:\s*\[\s*["']low["']""", js):
            problems.append("explore/index.html: the Inspections guide opens on the lowest-score order (a worst list)")
    else:
        problems.append("explore/index.html is missing")
    # --- published data
    try:
        idf = json.load(open(os.path.join(DOCS, "data", "ids.json")))
        if not isinstance(idf, dict):
            problems.append("data: ids.json is a bare list with no build version")
            idf = {"ids": ",".join(map(str, idf))}
        ids = idf["ids"].split(",")
        if len(ids) != core["n"] or len(set(ids)) != len(ids):
            problems.append(f"data: ids.json has {len(ids)} ids ({len(set(ids))} unique) for {core['n']} places")
        # --- one build: ids, details and the page all carry core.json's version (rows only line up within a build)
        ver = core.get("ver")
        if not ver or idf.get("v") != ver:
            problems.append(f"data: ids.json version {idf.get('v')!r} != core.json {ver!r}")
        m = re.search(r'id="ex-app"[^>]*data-ver="([^"]*)"', pages.get("explore/index.html", ""))
        if not m or m.group(1) != ver:
            problems.append(f"explore/index.html: data-ver {m and m.group(1)!r} != core.json {ver!r}")
        for i_, f_ in enumerate(core["dfiles"]):
            if f_ and not os.path.exists(os.path.join(DOCS, "data", f"detail-{f_}.json")):
                problems.append(f"data: core.json names detail-{f_}.json, which doesn't exist")
        for f in sorted(glob.glob(os.path.join(DOCS, "data", "detail-*.json"))):
            slug_ = os.path.basename(f)[len("detail-"):-len(".json")]
            co = core["dfiles"].index(slug_) if slug_ in core["dfiles"] else None
            det = json.load(open(f))
            if det.pop("_v", None) != core.get("ver"):
                problems.append(f"data: {os.path.basename(f)} isn't from this build (its _v isn't core.json's ver)")
            for k, d in det.items():
                i = int(k)
                if not 0 <= i < core["n"] or rows[i].get("co") != co:
                    problems.append(f"data: {os.path.basename(f)} has place {k}, which isn't in that county")
                    break
                w = d.get("w")
                if w and not re.match(r"https?://", w):
                    problems.append(f"data: website {w!r} for {rows[i]['n']!r} isn't http(s)")
            for p_, k, v in walk(det):
                if k.lower() in ("rating", "ratings", "reviews", "review_count", "price", "price_level", "gmap_id", "stars"):
                    problems.append(f"data: {os.path.basename(f)} has a Google-style field {k!r}")
                    break
        for k in list(core["cols"]) + list(core.get("sparse") or {}):
            if k.lower() in ("rating", "ratings", "reviews", "rv", "rt", "price", "pr", "gmap_id", "stars"):
                problems.append(f"data: core.json has a Google-style column {k!r}")
    except (OSError, ValueError, KeyError) as ex:
        problems.append(f"data: couldn't read the published data ({ex})")
    # --- the old contact address, other states' apps and repos, and blocklisted (hacked, expired, wrong-business) websites: nowhere in
    # docs/ (pages, the web app's core and every county detail file, sitemap, manifest)
    blocked = blocklist_patterns(problems)
    for f in sorted(glob.glob(os.path.join(DOCS, "**", "*"), recursive=True)):
        if os.path.isdir(f) or "/screenshots/" in f or f.endswith((".png", ".webp", ".woff2", ".ttf", ".jpg")) or os.path.basename(f) == "CNAME":
            continue
        t = open(f, encoding="utf-8", errors="replace").read()
        if OLD_EMAIL in t:
            problems.append(f"{rel(f)}: still shows {OLD_EMAIL}")
        # the old tier label and any invite/TestFlight promise: visible text, attributes, meta, JSON-LD and the web app's strings, with
        # tags out (so a sentence reads whole), entities and curly apostrophes normalized
        raw = html.unescape(t).replace("\u2019", "'")
        plain = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\u2019", "'") if f.endswith(".html") else raw
        m = OLD_LABEL.search(raw) or OLD_LABEL.search(plain)
        if m:
            problems.append(f"{rel(f)}: says {m.group(0)!r} (the label is \"High-confidence listing\")")
        m = PROMISE.search(plain) or PROMISE.search(raw)
        if m:
            problems.append(f"{rel(f)}: promises an invite or a TestFlight link: {m.group(0)!r} (the copy should end at an ask)")
        tu = html.unescape(t.replace("\\/", "/"))   # JSON's escaped slashes and HTML entities read as the URL they spell
        for label, rx in blocked:
            m = rx.search(t) or rx.search(tu)
            if m:
                problems.append(f"{rel(f)}: links a blocklisted website ({label}): …{m.group(0)}…")
        # the web app's data holds place names, and a real restaurant may be called "New York Eats" (Arlington and Irving, 2026-10-21):
        # there, only the repo slugs count
        in_data = rel(f).startswith("data/")
        for m in re.finditer(OTHER_SLUGS if in_data else OTHER_APPS + "|" + OTHER_SLUGS, t, flags=re.I):
            problems.append(f"{rel(f)}: names another state's app or repo: {m.group(0)!r}")
    # --- the privacy policy names every localStorage key the web app writes (XS-12)
    if ex:
        keys = sorted(set(re.findall(r"""store\.set\(\s*["']([^"']+)["']""", "\n".join(ex.scripts))))
        priv = pages.get("privacy.html", "")
        if not keys:
            problems.append("explore/index.html: found no store.set(...) keys to check the privacy policy against")
        for k in keys:
            if STORAGE_PREFIX + k not in priv:
                problems.append(f"privacy.html: doesn't name the web app's localStorage key {STORAGE_PREFIX + k!r}")
    # --- the landing page shows the app (docs/img/screen-*.png from scripts/site-images.sh), each with alt text and a size
    shots = re.findall(r"<img src=\"[^\"]*/img/screen-[a-z]+\.png\"[^>]*>", pages.get("index.html", ""))
    if len(shots) < 3 or any(not re.search(r'alt="[^"]{20,}"', x) or 'width="' not in x or 'loading="lazy"' not in x for x in shots):
        problems.append(f"index.html: the 'Inside the app' screenshots are missing or lack alt/size/lazy ({len(shots)} found)")
    return problems, len(pages)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve():
    root = DOCS
    if BASE:   # serve docs/ at /texas-eats/, the path GitHub Pages will use
        root = tempfile.mkdtemp()
        os.symlink(os.path.abspath(DOCS), os.path.join(root, BASE.strip("/")))
    # QA_PORT: a fixed port (the machine is shared; each session keeps to its own range); default, any free port
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("QA_PORT") or 0)), functools.partial(Quiet, directory=root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def local_exists(path):
    path = urllib.parse.unquote(path.split("#")[0].split("?")[0])
    if BASE and path.startswith(BASE + "/"):
        path = path[len(BASE):]
    f = os.path.join(DOCS, path.lstrip("/"))
    return os.path.isfile(f) or os.path.isfile(os.path.join(f, "index.html"))


def expected_hits(rows, guide_tag, word):
    """Places on a hand-checked guide whose name, dishes, town or address contain the word (what a search for it should list)."""
    return sum(1 for r in rows if r.get("hc") == 1 and (r.get("g") or 0) & guide_tag
               and f" {word}" in norm(" ".join(str(x) for x in (r["n"], r.get("dish"), r.get("a"), r["city"], r.get("z")) if x)))


def expected_bib():
    """Bib Gourmand places (MICHELIN level 2) the web app's box should list (core.json holds restaurants only)."""
    core = json.load(open(os.path.join(DOCS, "data", "core.json")))
    return sum(1 for _, v in core["sparse"]["mi"] if v == 2)     # a mostly-empty column: [[row, value], ...]


def bib_problems(page, ex, width):
    """The Bib Gourmand box keeps every Bib Gourmand and nothing else: the count is core.json's, every row says Bib Gourmand,
    and unticking it brings the whole guide back."""
    want, out = expected_bib(), []
    if not want:
        return [f"explore @{width}: core.json has no Bib Gourmand (mi 2) places"]
    page.goto(ex + "#g=all&bib=1", wait_until="networkidle")
    page.reload(wait_until="networkidle")
    page.wait_for_function("document.querySelectorAll('.ex-row').length > 0", timeout=20000)
    box = page.locator("#ex-bibwrap")
    if not box.is_visible() or box.inner_text().strip() != f"Bib Gourmand ({want:,})" or not page.locator("#ex-bib").is_checked():
        out.append(f"explore @{width}: the Bib Gourmand box isn't shown ticked as 'Bib Gourmand ({want:,})' ({box.inner_text().strip()!r})")
    count = page.locator("#ex-count").inner_text()
    if not count.startswith(f"{want:,} place"):
        out.append(f"explore @{width}: Bib Gourmand lists {count!r}, expected the {want} in core.json")
    tags = page.evaluate("[...document.querySelectorAll('.ex-row')].map(r => [...r.querySelectorAll('.tag-mi')].map(t => t.textContent).join('|'))")
    if len(tags) != min(want, 100):
        out.append(f"explore @{width}: Bib Gourmand shows {len(tags)} rows, expected {min(want, 100)}")
    wrong = [t for t in tags if t != "Bib Gourmand"]
    if wrong:
        out.append(f"explore @{width}: Bib Gourmand lists places that aren't Bib Gourmands: {wrong[:3]}")
    page.locator("#ex-bib").uncheck()
    page.wait_for_timeout(300)
    if page.locator("#ex-count").inner_text().startswith(f"{want:,} place"):
        out.append(f"explore @{width}: unticking Bib Gourmand didn't bring the whole guide back")
    return out


CSP_PROBE = """window.__csp = []; document.addEventListener("securitypolicyviolation",
  e => window.__csp.push(e.violatedDirective + " " + (e.blockedURI || "inline") + " @" + (e.sourceFile || "") + ":" + e.lineNumber));"""


# WCAG AA contrast of every visible text run against the background it actually sits on (opacity included)
CONTRAST_JS = r"""() => {
  const lum = (c) => { const a = c.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126*a[0] + 0.7152*a[1] + 0.0722*a[2]; };
  const parse = (s) => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const bgOf = (el) => { const layers = []; for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } }
    let out = [255, 255, 255]; for (const c of layers.reverse()) out = out.map((v, i) => v * (1 - c[3]) + c[i] * c[3]); return out; };
  const bad = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!['P','A','SPAN','LI','H1','H2','H3','B','SMALL','BUTTON','LABEL','SUMMARY','TD','TH','DIV','STRONG','EM','CODE'].includes(el.tagName)) continue;
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height || el.closest('[hidden],[aria-hidden="true"],.skip')) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden') continue;
    const fg = parse(cs.color), bg = bgOf(el); if (!fg) continue;
    let op = 1; for (let e = el; e; e = e.parentElement) op *= Number(getComputedStyle(e).opacity);
    const f = fg.slice(0, 3).map((v, i) => v * fg[3] * op + bg[i] * (1 - fg[3] * op));
    const ratio = (Math.max(lum(f), lum(bg)) + 0.05) / (Math.min(lum(f), lum(bg)) + 0.05);
    const size = parseFloat(cs.fontSize), large = size >= 24 || (size >= 18.66 && Number(cs.fontWeight) >= 700);
    if (ratio < (large ? 3 : 4.5)) bad.push(el.tagName.toLowerCase() + '.' + el.className + ' "' + el.textContent.trim().slice(0, 30) + '" ' + ratio.toFixed(2));
  }
  return [...new Set(bad)].slice(0, 5);
}"""


def webapp_robustness(browser, base, problems):
    """The web app's data handling: no ids.json until someone uses the page; a slow county file doesn't lose keyboard focus; a county file
    that fails, or comes from another build, is never shown as "no license matched" (or as another place's details)."""
    ex = base + BASE + "/explore/"
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    seen = []
    page.on("request", lambda r: seen.append(r.url))
    page.goto(ex + "#g=bbq", wait_until="networkidle")
    page.wait_for_selector(".ex-row")
    page.wait_for_timeout(1500)
    if any("/data/ids.json" in u for u in seen):
        problems.append("explore @375: ids.json loaded before anyone used the page (it belongs after the first tap, key or scroll)")
    page.mouse.wheel(0, 200)
    page.wait_for_timeout(1500)
    if not any("/data/ids.json" in u for u in seen):
        problems.append("explore @375: ids.json didn't load after the first scroll")
    if any(re.search(r"/data/(core|ids|detail-[a-z-]+)\.json(?!\?v=)", u) for u in seen):
        problems.append(f"explore @375: a data file was fetched without its ?v= build version: {[u for u in seen if '/data/' in u][:3]}")
    if page.evaluate("[getComputedStyle(document.querySelector('#ex-maphint')).pointerEvents, getComputedStyle(document.querySelector('#ex-mapattr')).pointerEvents]") != ["none", "none"]:
        problems.append("explore: the map's hint and credit catch clicks meant for the dots under them")
    # a slow county file: the panel opens, then re-renders with the details, and keyboard focus stays on its close button
    def slow(route):
        page.wait_for_timeout(1200)
        route.continue_()
    page.route("**/data/detail-*.json*", slow)
    page.evaluate("document.querySelector('.ex-row').click()")   # a tap: no hover warm-up first
    page.wait_for_timeout(3000)
    if "Loading details" in page.locator("#ex-panel").inner_text() or page.evaluate("document.activeElement.id") != "ex-close":
        problems.append(f"explore @375: after the details arrived, focus was on {page.evaluate('document.activeElement.id || document.activeElement.tagName')!r}, not the close button")
    page.unroute("**/data/detail-*.json*")
    ctx.close()
    for label, handler in (("unreachable", lambda route: route.abort()),
                           ("from another build", lambda route: route.fulfill(status=200, content_type="application/json",
                                                                             body=json.dumps({"_v": "another-build", "0": {"lic": "XXX"}})))):
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.route("**/data/detail-*.json*", handler)
        page.goto(ex + "#g=bbq", wait_until="networkidle")
        page.wait_for_selector(".ex-row")
        page.locator(".ex-row").first.click()
        page.wait_for_timeout(2000)
        t = page.locator("#ex-panel").inner_text() if page.locator("#ex-panel").is_visible() else ""
        if "didn't load" not in t or "no TABC license matched" in t or "TABC's public inquiry" in t:
            problems.append(f"explore: a county file {label} isn't reported as missing details: {t[:160]!r}")
        ctx.close()


def webapp_family_bugs(browser, base, problems):
    """Six web-app bugs found in other Eats Ranked states (cross-site ADDENDUM-2), checked here so they can't arrive in Texas."""
    ex = base + BASE + "/explore/"
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(ex + "#g=bbq", wait_until="networkidle")
    page.wait_for_selector(".ex-row")
    # 1. phones: the search box and selects at 16px or more (iOS zooms the page under 16px); buttons keep the site's font and size
    sizes = page.evaluate("""[...document.querySelectorAll('#ex-q, #ex-sort, #ex-town, #ex-cuisine')].map(e => [e.id, parseFloat(getComputedStyle(e).fontSize)])""")
    if any(px < 16 for _, px in sizes):
        problems.append(f"explore @375: inputs/selects under 16px (iOS zooms on focus): {sizes}")
    fams = page.evaluate("""[...document.querySelectorAll('.ex-guides button, .ex-view button, #ex-locate, .ex-zoom button')].map(e => [e.textContent.trim(), getComputedStyle(e).fontFamily, parseFloat(getComputedStyle(e).fontSize)])""")
    if any(("system-ui" not in f and "apple-system" not in f) or px < 14 for _, f, px in fams):
        problems.append(f"explore @375: buttons fell back to the browser's default font or size: {[x for x in fams if 'system-ui' not in x[1] or x[2] < 14][:3]}")
    # 4. a corrupt value under one of our keys (any page on the shared github.io origin can write one) doesn't stop the app
    for val in ('{"x":1}', "not json", "[null, 5, {}]"):
        for key in ("saved", "guide"):
            errors.clear()
            page.evaluate(f"localStorage.clear(); localStorage.setItem({json.dumps(STORAGE_PREFIX + key)}, {json.dumps(val)})")
            page.reload(wait_until="networkidle")
            try:
                page.wait_for_selector(".ex-row", timeout=15000)
            except Exception:   # noqa: BLE001
                problems.append(f"explore: localStorage {STORAGE_PREFIX + key}={val!r} stopped the app from loading")
            if errors:
                problems.append(f"explore: localStorage {STORAGE_PREFIX + key}={val!r} threw {errors[:1]}")
    page.evaluate("localStorage.clear()")
    ctx.close()
    # 2 and 3. at desktop width too: the open place is a modal dialog over an inert page; Back closes it and keeps the search, Forward
    # reopens it; Escape and a click on the backdrop close it and focus goes back to the row
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.goto(base + BASE + "/", wait_until="networkidle")
    page.goto(ex + "#g=bbq", wait_until="networkidle")
    page.wait_for_selector(".ex-row")
    page.fill("#ex-q", "franklin barbecue")
    page.wait_for_timeout(500)
    page.locator(".ex-row").first.click()
    page.wait_for_selector("#ex-panel:not([hidden])")
    page.wait_for_timeout(400)
    state = page.evaluate("""(() => { const p = document.querySelector('#ex-panel'); return [p.getAttribute('role'), p.getAttribute('aria-modal'),
        p.getAttribute('aria-labelledby'), document.querySelector('#ex-app').inert, document.activeElement.id]; })()""")
    if state != ["dialog", "true", "ex-pname", True, "ex-close"]:
        problems.append(f"explore @1280: the open place isn't a modal dialog with focus inside and the page inert: {state}")
    page.go_back()
    page.wait_for_timeout(600)
    if page.locator("#ex-panel").is_visible() or not page.url.startswith(ex) or page.input_value("#ex-q") != "franklin barbecue":
        problems.append(f"explore @1280: Back with a place open didn't close it and keep the search ({page.url})")
    page.go_forward()
    page.wait_for_timeout(800)
    if not page.locator("#ex-panel").is_visible():
        problems.append("explore @1280: Forward didn't reopen the place")
    page.mouse.click(40, 400)   # the backdrop, left of the side sheet
    page.wait_for_timeout(500)
    if page.locator("#ex-panel").is_visible() or page.evaluate("document.querySelector('#ex-app').inert"):
        problems.append("explore @1280: a click outside the open place didn't close it")
    page.locator(".ex-row").first.click()
    page.wait_for_selector("#ex-panel:not([hidden])")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    if page.evaluate("document.activeElement.className") != "ex-row":
        problems.append("explore @1280: Escape didn't return focus to the row that opened the place")
    ctx.close()
    # 5 and 6. no "Nearest" before a fix (none yet, or denied); every Near me tap asks for a fresh fix; outside Texas it says so
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, permissions=[])
    page = ctx.new_page()
    page.goto(ex + "#g=bbq&sort=nearest", wait_until="networkidle")
    page.wait_for_selector(".ex-row")
    page.click("#ex-locate")
    page.wait_for_timeout(1200)
    if "Nearest" in page.locator("#ex-count").inner_text():
        problems.append("explore: says 'Nearest' after location was denied")
    ctx.close()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, geolocation={"latitude": 30.2686, "longitude": -97.7428}, permissions=["geolocation"])
    page = ctx.new_page()
    page.goto(ex + "#g=bbq", wait_until="networkidle")
    page.wait_for_selector(".ex-row")
    page.click("#ex-locate")
    page.wait_for_timeout(1000)
    first = page.locator(".ex-row .ex-metric").first.inner_text()
    ctx.set_geolocation({"latitude": 30.694, "longitude": -88.043})   # Mobile, Alabama
    if not page.locator("#ex-locate").is_visible():
        problems.append("explore: Near me disappears after the first fix, so the location can never be refreshed")
    else:
        page.click("#ex-locate")
        page.wait_for_timeout(1000)
        if page.locator(".ex-row .ex-metric").first.inner_text() == first:
            problems.append("explore: a second Near me tap reused the first location fix")
        if "outside Texas" not in page.locator("#ex-locmsg").inner_text():
            problems.append(f"explore: outside Texas, the message doesn't say so: {page.locator('#ex-locmsg').inner_text()!r}")
    ctx.close()


def webapp_ids_and_links(browser, base, problems):
    """ids.json waits for the first use, so a tap must never wait for it: the place opens at once and its Save button and #p= link
    follow. When ids.json or core.json can't be trusted (another build, a cache that ignored ?v=), the page says so instead of looking
    empty or mixing builds; and a #p= link to a place that isn't there says so."""
    ex = base + BASE + "/explore/"
    stale_ids = json.dumps([f"x{i}" for i in range(3)])                  # the live build's shape: a bare list, no version
    # 1. a slow ids.json: the tapped place shows at once, Save waits for the id, then the place gets its link and its Back step
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    def slow(route):
        page.wait_for_timeout(2500)
        route.continue_()
    page.route("**/data/ids.json*", slow)
    page.goto(base + BASE + "/", wait_until="networkidle")
    page.goto(ex + "#g=bbq", wait_until="networkidle")
    page.wait_for_selector(".ex-row")
    page.tap(".ex-row >> nth=0")
    page.wait_for_timeout(700)
    if not page.locator("#ex-panel").is_visible():
        problems.append("explore @375: a tap waited for ids.json before opening the place (no panel 0.7 s after the tap)")
    page.wait_for_timeout(3500)
    if not page.locator("#ex-save:not([disabled])").count() or "&p=" not in page.url:
        problems.append(f"explore @375: after ids.json arrived, the open place has no Save button or #p= link ({page.url})")
    else:
        page.go_back()
        page.wait_for_timeout(700)
        if page.locator("#ex-panel").is_visible() or not page.url.startswith(ex):
            problems.append(f"explore @375: Back didn't close a place opened before ids.json arrived ({page.url})")
    ctx.close()
    # 2. ids.json from another build: the place opens without Save, Escape closes it, Saved and a #p= link say what went wrong
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.route("**/data/ids.json*", lambda route: route.fulfill(status=200, content_type="application/json", body=stale_ids))
    page.goto(ex + "#g=bbq", wait_until="networkidle")
    page.wait_for_selector(".ex-row")
    page.locator(".ex-row").first.click()
    page.wait_for_timeout(1500)
    if not page.locator("#ex-panel").is_visible() or page.locator("#ex-save:not([disabled])").count():
        problems.append("explore: with ids.json from another build, a place didn't open, or offered Save without an id")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    if page.locator("#ex-panel").is_visible():
        problems.append("explore: Escape didn't close a place that has no id (ids.json from another build)")
    page.evaluate(f"localStorage.setItem({json.dumps(STORAGE_PREFIX + 'saved')}, JSON.stringify(['abc123']))")
    page.goto(ex + "#g=saved", wait_until="networkidle")
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1500)
    if "couldn't load" not in page.locator("#ex-list").inner_text():
        problems.append(f"explore: with ids.json from another build, Saved says {page.locator('#ex-list').inner_text()[:80]!r}, not that it couldn't load")
    page.goto(ex + "#g=bbq&p=abc123", wait_until="networkidle")
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1500)
    if "couldn't load" not in page.locator("#ex-locmsg").inner_text():
        problems.append("explore: with ids.json from another build, a #p= link opened nothing and said nothing")
    page.evaluate("localStorage.clear()")
    ctx.close()
    # 3. a #p= link to a place that isn't in this build says so
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.goto(ex + "#g=bbq&p=000000000000", wait_until="networkidle")
    page.wait_for_selector(".ex-row")
    page.wait_for_timeout(1500)
    if "isn't on the list" not in page.locator("#ex-locmsg").inner_text():
        problems.append("explore: a #p= link to a place that isn't here opened nothing and said nothing")
    ctx.close()
    # 5. Back, Forward, then the close button: closing steps back over the place's entry, so the next Back leaves the page
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.goto(base + BASE + "/", wait_until="networkidle")
    page.goto(ex + "#g=bbq", wait_until="networkidle")
    page.wait_for_selector(".ex-row")
    page.locator(".ex-row").first.click()
    page.wait_for_selector("#ex-panel:not([hidden]) #ex-save:not([disabled])")
    page.go_back()
    page.wait_for_timeout(600)
    page.go_forward()
    page.wait_for_timeout(900)
    page.click("#ex-close")
    page.wait_for_timeout(600)
    page.go_back()
    page.wait_for_timeout(900)
    if page.url.startswith(ex):
        problems.append(f"explore: after Back, Forward and the close button, Back stayed on the search page ({page.url}): a dead Back step")
    ctx.close()
    # 4. a core.json with no build version (a cache that ignored ?v=) is refused with the reload message, before any other data file
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    seen = []
    page.on("request", lambda r: seen.append(r.url) if "/data/" in r.url else None)
    def unversioned(route):
        core = json.loads(route.fetch().text())
        core.pop("ver", None)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(core))
    page.route("**/data/core.json*", unversioned)
    page.goto(ex + "#g=bbq", wait_until="networkidle")
    page.wait_for_timeout(1500)
    if page.locator(".ex-row").count() or "couldn't load" not in page.locator("#ex-loading").inner_text():
        problems.append("explore: a core.json without a build version was used (rows would meet another build's ids and county files)")
    ctx.close()


def webapp_search_scope_and_placeholder(browser, base, problems):
    """Typing searches only the open guide: a famous place outside it (Joe T. Garcia's isn't on the barbecue list the page opens on)
    gets a "Search all restaurants (N matches)" button that finds it in one click. And the search box's placeholder fits at 375 px."""
    ex = base + BASE + "/explore/"
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    page.goto(ex + "#g=bbq", wait_until="networkidle")
    page.wait_for_selector(".ex-row")
    fit = page.evaluate("""(() => { const q = document.querySelector('#ex-q'); const ph = q.placeholder; q.value = ph;
        const r = [q.scrollWidth, q.clientWidth, parseFloat(getComputedStyle(q).fontSize), ph]; q.value = ''; return r; })()""")
    if fit[0] > fit[1] or fit[2] < 16:
        problems.append(f"explore @375: the search box's placeholder {fit[3]!r} doesn't fit ({fit[0]}px of text in {fit[1]}px) or is under 16px")
    # every guide's sort choices fit their select at 375 px (a select shows its value cut off, with no way to read the rest)
    for g in ("honors", "inspections"):
        page.goto(ex + f"#g={g}", wait_until="networkidle")
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".ex-row")
        cut = page.evaluate("""(() => { const s = document.querySelector('#ex-sort'), c = s.cloneNode(true);
            c.style.maxWidth = 'none'; c.style.position = 'absolute'; c.style.visibility = 'hidden'; s.parentNode.appendChild(c);
            const need = c.offsetWidth; c.remove(); return need > s.offsetWidth + 0.5 ? [...s.options].map(o => o.textContent) : []; })()""")
        if cut:
            problems.append(f"explore @375: the {g} sort select cuts off {cut}")
    page.goto(ex + "#g=bbq", wait_until="networkidle")
    page.reload(wait_until="networkidle")
    page.wait_for_selector(".ex-row")
    page.fill("#ex-q", "joe t. garcia's")
    page.wait_for_timeout(700)
    btn = page.locator("#ex-all")
    if page.locator(".ex-row").count() or not btn.count() or not re.search(r"Search all restaurants \(\d[\d,]* match", btn.inner_text()):
        problems.append(f"explore @375: a search the barbecue list can't answer ('joe t. garcia's') offers no 'Search all restaurants' button "
                        f"({page.locator('#ex-list').inner_text()[:100]!r})")
    else:
        btn.click()
        page.wait_for_timeout(700)
        first = page.locator(".ex-row b").first.inner_text() if page.locator(".ex-row").count() else ""
        if "joe t. garcia's" not in first.lower() or page.input_value("#ex-q") != "joe t. garcia's" or "g=all" not in page.url:
            problems.append(f"explore @375: 'Search all restaurants' didn't find Joe T. Garcia's with the same words (first row {first!r}, {page.url})")
    ctx.close()


def browser_checks(problems):
    from playwright.sync_api import sync_playwright
    base = serve()
    paths = [rel(f) for f in doc_files()]
    urls = [base + BASE + "/" + ("" if p == "index.html" else p.removesuffix("index.html")) for p in paths]
    core, rows = load_core()
    idf = json.load(open(os.path.join(DOCS, "data", "ids.json")))
    ids = idf["ids"].split(",") if isinstance(idf, dict) else idf
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        for width in (375, 1280):
            ctx = browser.new_context(viewport={"width": width, "height": 900})
            ctx.add_init_script(CSP_PROBE)
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            for url in urls:
                errors.clear()
                page.goto(url, wait_until="networkidle")
                where = f"{urllib.parse.urlparse(url).path} @{width}"
                over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                if over > 1:
                    problems.append(f"{where}: scrolls sideways by {over}px")
                if page.locator("h1").count() != 1:
                    problems.append(f"{where}: {page.locator('h1').count()} <h1>")
                problems += [f"{where}: CSP violation: {v}" for v in page.evaluate("window.__csp || []")]
                if width == 1280:   # links are the same at both widths
                    refs = page.evaluate("""[...document.querySelectorAll('a[href],img[src],link[href],script[src]')]
                        .map(e => e.getAttribute('href') || e.getAttribute('src'))""")
                    for ref in refs:
                        full = urllib.parse.urljoin(url, ref)
                        p = urllib.parse.urlparse(full)
                        if p.scheme in ("mailto", "tel", "data"):
                            continue
                        if p.netloc in (urllib.parse.urlparse(base).netloc, DOMAIN) and not local_exists(p.path):
                            problems.append(f"{where}: broken link {ref}")
                        if p.fragment and "=" not in p.fragment and p.netloc == urllib.parse.urlparse(base).netloc and p.path == urllib.parse.urlparse(url).path:
                            if not page.evaluate("(id) => !!document.getElementById(id)", urllib.parse.unquote(p.fragment)):
                                problems.append(f"{where}: link to missing #{p.fragment}")
                    imgs = page.evaluate("[...document.images].filter(i => i.complete && i.naturalWidth === 0).map(i => i.src)")
                    problems += [f"{where}: image didn't load {s}" for s in imgs]
                problems += [f"{where}: console error: {e}" for e in errors]
                problems += [f"{where}: text under AA contrast: {c}" for c in page.evaluate(CONTRAST_JS)]
            # ------------------------------------------------ the web app
            errors.clear()
            ex = base + BASE + "/explore/"
            page.goto(base + BASE + "/", wait_until="networkidle")             # a page before it, so Back has somewhere to leave to
            page.goto(ex + "#g=bbq", wait_until="networkidle")
            page.wait_for_function("document.querySelectorAll('.ex-row').length > 0", timeout=30000)
            search = page.locator('#ex-q').first
            for word in ("brisket", "sausage"):
                search.fill(word)
                page.wait_for_timeout(500)
                want, got = expected_hits(rows, 1, word), page.locator(".ex-row").count()
                if got != want or not want:
                    problems.append(f"explore @{width}: '{word}' listed {got} barbecue joints, expected the {want} that serve it")
            problems += bib_problems(page, ex, width)
            # direction words: "north lamar" finds N Lamar addresses
            page.goto(ex + "#g=all", wait_until="networkidle")
            page.wait_for_function("document.querySelectorAll('.ex-row').length > 0", timeout=30000)
            search.fill("north lamar")
            page.wait_for_timeout(700)
            nl = sum(1 for r in rows if " n lamar " in norm(r.get("a")))
            count_text = page.locator("#ex-count").inner_text()
            got = int(re.match(r"([\d,]+)", count_text).group(1).replace(",", "")) if re.match(r"[\d,]+", count_text) else 0
            if not nl or got < nl:
                problems.append(f"explore @{width}: 'north lamar' listed {got} places, but {nl} have an N Lamar address")
            page.goto(ex + "#g=inspections", wait_until="networkidle")
            page.wait_for_function("document.querySelectorAll('.ex-row').length > 0", timeout=30000)
            search.fill("franklin barbecue")
            page.wait_for_timeout(500)
            if not page.locator(".ex-row").count():
                problems.append(f"explore @{width}: search 'franklin barbecue' found nothing in Inspection Scores")
            else:
                page.locator(".ex-row").first.click()
                page.wait_for_timeout(1500)
                panel = page.locator("#ex-panel")
                if not panel.is_visible() or not panel.locator("a", has_text="Directions").count():
                    problems.append(f"explore @{width}: opening a place showed no details")
                else:
                    ptxt = panel.inner_text()
                    if "Inspections · Austin".upper() not in ptxt.upper() or not re.search(r"\d+/100", ptxt):
                        problems.append(f"explore @{width}: the panel doesn't show Austin's score: {ptxt[:200]!r}")
                    if not panel.locator('a[href*="data.austintexas.gov"]').count():
                        problems.append(f"explore @{width}: the panel has no link to Austin's records")
                    if width == 375:
                        modal = page.evaluate("""[document.querySelector('#ex-panel').getAttribute('role'),
                            document.querySelector('#ex-panel').getAttribute('aria-modal'), document.querySelector('#ex-app').inert,
                            document.querySelector('footer').inert]""")
                        if modal != ["dialog", "true", True, True]:
                            problems.append(f"explore @{width}: the open place sheet isn't a modal dialog with the page behind it inert: {modal}")
                    page.locator("#ex-save").click()
                    keys = page.evaluate("Object.keys(localStorage)")
                    bad = [k for k in keys if not k.startswith(STORAGE_PREFIX)]
                    if bad or not keys:
                        problems.append(f"explore @{width}: localStorage keys {keys} (want all to start {STORAGE_PREFIX!r})")
                    page.locator("#ex-save").click()
                    page.go_back()
                    page.wait_for_timeout(600)
                    if not page.url.startswith(ex) or panel.is_visible():
                        problems.append(f"explore @{width}: Back with a place open didn't just close it (now at {page.url}, panel visible: {panel.is_visible()})")
                    elif width == 375 and page.evaluate("document.querySelector('#ex-app').inert"):
                        problems.append(f"explore @{width}: the page stayed inert after the sheet closed")
            search.fill("🍕")
            page.wait_for_timeout(400)
            if page.locator(".ex-row").count():
                problems.append(f"explore @{width}: an emoji search listed places")
            # a shared #p= link opens that place
            target = next((i for i, r in enumerate(rows) if r.get("hc") == 1 and (r.get("g") or 0) & 4), None)
            if target is not None:
                page.goto(ex + "#g=taqueria&p=" + ids[target], wait_until="networkidle")
                page.reload(wait_until="networkidle")
                page.wait_for_timeout(1500)
                name = page.locator("#ex-pname").inner_text() if page.locator("#ex-pname").count() else ""
                if norm(name) != norm(rows[target]["n"]):
                    problems.append(f"explore @{width}: #p={ids[target]} opened {name!r}, not {rows[target]['n']!r}")
            # the map draws dots and credits its outlines
            page.goto(ex + "#g=bbq", wait_until="networkidle")
            page.reload(wait_until="networkidle")
            page.wait_for_function("document.querySelectorAll('.ex-row').length > 0", timeout=30000)
            page.locator('.ex-view button[data-v="map"]').click()
            page.wait_for_timeout(1200)
            painted = page.evaluate("""(() => { const c = document.querySelector('#ex-map'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
                let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] > 170 && d[i] < 210 && d[i + 1] < 30 && d[i + 2] > 30 && d[i + 2] < 70) n++; return n; })()""")
            if painted < 20:
                problems.append(f"explore @{width}: the map drew no red dots for the barbecue joints ({painted} pixels)")
            if not page.locator("#ex-mapattr").is_visible():
                problems.append(f"explore @{width}: the map's OpenStreetMap/Overture credit isn't visible")
            for hostile in ("#g=constructor", "#g=__proto__&sort=toString", "#g=all&p=__proto__"):
                errors.clear()
                page.goto(ex + hostile, wait_until="networkidle")
                page.reload(wait_until="networkidle")
                page.wait_for_timeout(700)
                if not page.locator(".ex-row").count() or errors:
                    problems.append(f"explore @{width}: {hostile} broke the list ({errors[:1]})")
            page.goto(ex + "#g=honors&sort=nearest", wait_until="networkidle")
            page.reload(wait_until="networkidle")
            page.wait_for_function("document.querySelectorAll('.ex-row').length > 0", timeout=30000)
            if "Nearest" in page.locator("#ex-count").inner_text():
                problems.append(f"explore @{width}: says 'Nearest' with no location")
            page.goto(ex + "#g=inspections", wait_until="networkidle")
            page.reload(wait_until="networkidle")
            page.wait_for_function("document.querySelectorAll('.ex-row').length > 0", timeout=30000)
            opts = page.locator("#ex-sort option").all_inner_texts()
            if not opts or opts[0].lower().startswith("lowest"):
                problems.append(f"explore @{width}: the Inspections guide opens on {opts[:1]} (no worst list)")
            problems += [f"explore @{width}: CSP violation: {v}" for v in page.evaluate("window.__csp || []")]
            problems += [f"explore @{width}: console error: {e}" for e in errors]
            ctx.close()
        # dark mode: the pages people land on most, plus the web app and the 404 page
        ctx = browser.new_context(viewport={"width": 375, "height": 812}, color_scheme="dark")
        page = ctx.new_page()
        for p in ("index.html", "texas-barbecue.html", "cities/austin.html", "texas-restaurant-inspections.html", "explore/index.html", "404.html", "privacy.html"):
            page.goto(base + BASE + "/" + ("" if p == "index.html" else p.removesuffix("index.html")), wait_until="networkidle")
            if p.startswith("explore"):
                page.wait_for_selector(".ex-row")
            problems += [f"{p} @375 dark: text under AA contrast: {c}" for c in page.evaluate(CONTRAST_JS)]
            if page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") > 1:
                problems.append(f"{p} @375 dark: scrolls sideways")
        ctx.close()
        webapp_robustness(browser, base, problems)
        webapp_family_bugs(browser, base, problems)
        webapp_ids_and_links(browser, base, problems)
        webapp_search_scope_and_placeholder(browser, base, problems)
        browser.close()
    return len(urls)


def main():
    problems, n = static_checks()
    if "--static" in sys.argv:
        print(f"{n} pages, static checks")
    else:
        n = browser_checks(problems)
        print(f"{n} pages × 2 widths + the web app")
    for p in problems:
        print("  ✗", p)
    print("OK" if not problems else f"{len(problems)} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
