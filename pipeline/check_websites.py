"""Checks every website link the app ships before it ships, because map listings carry stale and hijacked domains.

Chicago found about 3% of its listing websites redirected to gambling, betting or adult sites, including a starred restaurant's.
A link survives only if:
  - the final response is 2xx,
  - it stays on the same registered domain (or the page plainly belongs to the place),
  - the page mentions a distinctive word of the place's name (or, for a name with none, the domain spells the name),
  - the page shows where the place is: its town, zip, phone number or house number and street (a namesake elsewhere doesn't),
  - it isn't a news story, a directory, a site-builder preview or a client-side redirect to another site,
  - and nothing looks like gambling spam, adult content, a parked or for-sale domain, an expired account or "coming soon".
A site that blocks the check, times out or errors is dropped too: no link beats a wrong link. The one exception is a chain's own
domain (mcdonalds.com for McDonald's): when its sample pages refuse the check (403, 429, connection refused), the links stay, because
the domain plainly belongs to the brand.

Polite by design: an honest user agent, one request at a time per host, and three sample pages for a chain's own domain (5+ places,
80%+ one brand). Shared hosts (Square, Wix, Linktree, Instagram) carry many unrelated places, so every link there is checked on its own.
Never bypasses bot protection.

Copied from co-eats (location rules) with wi-eats' injection.py hacked-page detector (planted casino/adult links).
Usage: ../.venv/bin/python check_websites.py   (reads data/tx/website_candidates.json) → data/tx/website_check.json
({url: {"ok": bool, "why": str, "final": str, "ship": str, "at": "YYYY-MM-DD", "v": RULES}})
The app export (texas.py, TX_APP=1) drops every link that isn't ok and ships "ship" (https when the site answers on https).
A verdict is reused for MAX_AGE days at most, and never across a change of the rules (RULES): a domain can be hijacked after it passed.
Re-run before each App Store submission.
"""
import collections
import datetime
import json
import os
import re
import threading
import time
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests

import injection

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = f"{ROOT}/data/tx/website_check.json"
UA = "TexasEatsLinkCheck/1.0 (+https://texas.eatsranked.com/; nick@eatsranked.com)"
RULES = 2          # bump when a rule changes: every cached verdict is checked again
MAX_AGE = 45       # days a verdict is trusted
GENERIC = set("""the and of a an at on in restaurant restaurants bar bars grill grille cafe caffe coffee pizza pizzeria pub tavern house
inn lounge kitchen bistro eatery diner bakery deli market express food foods co company inc llc ltd corp texas tx
houston dallas austin antonio paso worth springs family original new old north south east west st saint mt sports place spot shop shoppe taproom brewing brewery
tap taps bbq barbecue burger burgers chicken subs sub sandwich sandwiches tacos taco mexican chinese thai sushi asian italian
american cuisine catering events""".split())
# Hijacked domains carry Indonesian slot and lottery spam, Turkish betting pages or porn links: any of these marks a page.
SPAM = re.compile(r"slot ?gacor|situs (?:slot|judi|togel)|slot online|\bslot ?88\b|\btogel\b|judi (?:online|bola|slot|qq|poker)|perjudian|"
                  r"bandar ?(?:slot|qq|togel)|\bmaxwin\b|\brtp slot|\bsbobet\b|\bbahis|casino siteleri|\b1win\b|watch porn|free porn|"
                  r"porn videos?|\bpornhub\b|\bxvideos\b|\bxnxx\b|escort service|adult dating|sex cam|camgirl", re.I)
BLOBS = re.compile(r"[A-Za-z0-9+/=_-]{100,}")   # base64 images and tokens: random letters spell anything
# Words a real casino's restaurant or a brewery near the sportsbook uses too: they count only in the page title or description,
# or repeated in the body, and never on a casino's own page.
BETTING = re.compile(r"online casino|casino online|deposit bonus|sportsbook|\bbaccarat\b|bet365|no deposit", re.I)
HEAD = re.compile(r"<title[^>]*>(.*?)</title>|<meta[^>]+name=.description.[^>]+content=\"([^\"]*)", re.S)
CASINO_PLACE = re.compile(r"casino|gaming|ameristar|monarch|black hawk|blackhawk|central city|cripple creek|bronco billy|"
                          r"ute mountain|sky ute|isle of capri|golden gates|saratoga|lodge casino|century casino", re.I)
PARKED = re.compile(r"domain (?:is|may be) for sale|buy this domain|this domain is parked|parked free|sedoparking|hugedomains|"
                    r"afternic|domain has expired|this domain name has expired|account (?:has been )?suspended|website coming soon|"
                    r"site (?:is )?coming soon|future home of|launching soon|godaddy\.com/domainsearch|dan\.com", re.I)
# directories, listings, review sites, shorteners and fundraisers: not the place's own page
BAD_HOSTS = ("business.site", "negocio.site", "google.com", "goo.gl", "g.co/", "share.google", "yelp.com", "tripadvisor.",
             "facebook.com/pages", "doordash.com", "grubhub.com", "ubereats.com", "seamless.com", "allmenus.com", "menupix.com",
             "zmenu.com", "restaurantji.com", "yellowpages.com", "superpages.com", "whitepages.com", "chamberofcommerce.com",
             "cortera.com", "dandb.com", "bizapedia.com", "city-data.com", "mapquest.com", "citysearch.com", "yahoo.com", "hub.biz",
             "edan.io", "poi.place", "placeweb.site", "jany.io", "lany.io", "keeq.io", "restoguides.com", "dinehere.us", "foodspot.com",
             "gastrobars.com", "indulgery.com", "clubplanet.com", "restaurant.com", "groupon.com", "seatgeek.com", "opentable.com",
             "menuism.com", "barfinder.com", "friendseat.com", "local.com", "usplaces.com", "foodeist.com", "jmaps.net", "kwickmenu.com",
             "tinyurl.com", "bit.ly", "forms.gle", "gofund.me", "gofundme.com", "cash.app", "tiktok.com", "reverbnation.com",
             "buzzfile.com", "usdirectory.com", "findaliquorstore.com", "companymap.xyz", "wheresweed.com", "manta.com", "loc8nearme.com",
             "nicelocal.com", "waze.com", "foursquare.com", "zomato.com", "sirved.com", "menupages.com", "beyondmenu.com", "slicelife.com",
             "toasttab.com/local", "linktr.ee", "homesnap.com", "vrbo.com", "airbnb.", "expedia.", "booking.com", "hotels.com",
             "preview=true", "insitepreview", "editor.wix.com", "sites.google.com/view/untitled")
# news and magazines write about a place; a story is never its website (one shipped as an RT article about a giveaway)
NEWS = ("texasmonthly.com", "chron.com", "houstonchronicle.com", "dallasnews.com", "star-telegram.com", "expressnews.com", "mysanantonio.com",
        "statesman.com", "austinchronicle.com", "elpasotimes.com", "dallasobserver.com", "houstonpress.com", "culturemap.com", "khou.com",
        "kxan.com", "wfaa.com", "ksat.com", "kens5.com", "texastribune.org", "westword.com", "eater.com", "dailycamera.com", "denverpost.com", "5280.com", "coloradoan.com", "gazette.com", "rt.com",
        "chieftain.com", "gjsentinel.com", "summitdaily.com", "vaildaily.com", "aspentimes.com", "aspendailynews.com", "steamboatpilot.com",
        "durangoherald.com", "postindependent.com", "timescall.com", "reporterherald.com", "greeleytribune.com", "coloradosun.com",
        "denverite.com", "cpr.org", "9news.com", "kdvr.com", "thedenverchannel.com", "koaa.com", "krdo.com", "kktv.com", "cbsnews.com",
        "nbcnews.com", "axios.com", "patch.com", "nytimes.com", "wikipedia.org", "reddit.com", "yellowscene.com", "bizjournals.com",
        "outtherecolorado.com", "uncovercolorado.com", "coloradohometownweekly.com", "craftbeer.com", "beeradvocate.com", "untappd.com",
        "thrillist.com", "timeout.com", "infatuation.com", "michelin.com", "jamesbeard.org", "eatthis.com", "onlyinyourstate.com")
ARTICLE = re.compile(r"/20\d\d/\d{1,2}/|/ci_\d+|[-/]\d{7,}(?:[/?#]|$)|/(?:news|story|stories|article|articles|blog/20\d\d)/|[?&]p=\d+", re.I)
REFRESH = re.compile(r"<meta[^>]+http-equiv=[\"']?refresh[^>]+url=([^\"'>\s;]+)|(?:window\.)?location(?:\.href)?\s*=\s*[\"'](https?://[^\"']+)|"
                     r"location\.replace\(\s*[\"'](https?://[^\"']+)", re.I)
# town names that are everyday words prove nothing on their own
COMMON_TOWNS = {"golden", "center", "eagle", "parker", "brush", "security", "rye", "grant", "boone", "como", "hasty", "lewis", "otis",
                "pierce", "rush", "julesburg", "victor", "nucla", "avon", "carbondale", "minturn", "ward", "manzanola", "hotchkiss", "kremmling",
                "aurora", "lafayette", "louisville", "littleton", "englewood", "berthoud", "evans", "erie", "dacono", "johnstown", "monument",
                "salida", "paonia", "olathe", "delta", "mancos", "dolores", "ridgway", "rico", "springfield", "holly", "granada", "lamar",
                "wellington", "windsor", "milliken", "fountain", "florence", "gardner", "bayfield", "silverton", "creede", "ouray"}
SHADY = re.compile(r"(?:^|\.)food\d+\.com$|\.top$")   # food73.com-style listing farms, .top redirect farms
# a brand that moved its stores to a short domain
ALIASES = {"burgerking.com": "bk.com"}
BLOCKED = re.compile(r"^(?:http 40[39]|http 429|error: (?:ConnectionError|ConnectTimeout|ReadTimeout))$")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s.replace("'", "")).strip()


def regdom(host):
    parts = host.lower().removeprefix("www.").split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def bad_host(url):
    """A directory, listing site, shortener or preview link. Domains match whole ("restaurant.com" is the coupon site, not
    joesrestaurant.com: the substring test once rejected 235 real sites); entries with a path, query or trailing dot match anywhere."""
    pr = urllib.parse.urlparse(url if "//" in url else "https://" + url)
    host = pr.netloc.lower().removeprefix("www.")
    full = (host + pr.path + ("?" + pr.query if pr.query else "")).lower()
    for b in BAD_HOSTS:
        if any(ch in b for ch in "/=") or b.endswith(".") or b in ("insitepreview",):
            if b in full:
                return True
        elif host == b or host.endswith("." + b):
            return True
    return bool(SHADY.search(regdom(pr.netloc)))


def news_page(url):
    pr = urllib.parse.urlparse(url if "//" in url else "https://" + url)
    return regdom(pr.netloc) in NEWS or bool(ARTICLE.search(pr.path + ("?" + pr.query if pr.query else "")))


def located(text, final, ctx):
    """The page says where the place is: its town (unless the town's name is an everyday word), zip, phone or house number + street."""
    hay = " " + text + " " + norm(final) + " "
    dom = norm(urllib.parse.urlparse(final).netloc).replace(" ", "")
    for t in ctx.get("towns", []):
        t = norm(t)
        if len(t) >= 4 and t not in COMMON_TOWNS and (f" {t} " in hay or (len(t) >= 6 and t.replace(" ", "") in dom)):
            return "town"
    for z in ctx.get("zips", []):
        if re.search(rf"\b{re.escape(str(z)[:5])}\b", hay):
            return "zip"
    digits = {re.sub(r"\D", "", m)[-10:] for m in re.findall(r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}", text)}
    for ph in ctx.get("phones", []):
        d = re.sub(r"\D", "", ph)[-10:]
        if len(d) == 10 and d in digits:
            return "phone"
    for st in ctx.get("streets", []):
        m = re.match(r"\s*(\d+)\s+(.*)", norm(st))
        if m:
            core = [w for w in m.group(2).split() if len(w) >= 3 and w not in STREET_WORDS]
            if core and f" {m.group(1)} " in hay and re.search(rf"\b{m.group(1)}\s+(?:\w+\s+){{0,2}}{re.escape(core[0])}\b", hay):
                return "street"
    return None


GENERAL_TLD = {"com", "net", "org", "co", "us", "biz", "info", "restaurant", "restaurants", "bar", "cafe", "pizza", "coffee", "kitchen",
               "menu", "beer", "wine", "bio", "site", "online", "store", "shop", "rest", "food", "pub", "bistro", "life", "page"}


def label(url):
    host = urllib.parse.urlparse(url if "//" in url else "https://" + url).netloc.lower().removeprefix("www.")
    parts = host.split(".")
    return (parts[-2] if len(parts) >= 2 else host), parts[-1]


SUFFIXES = ("", "co", "company", "inc", "llc", "restaurant", "restaurants", "bar", "grill", "cafe", "pizza", "pizzeria", "kitchen", "eatery",
            "bbq", "tavern", "pub", "coffee", "foods", "deli", "bakery", "brewing", "brewery", "wines", "winery", "online", "texas", "tx")


def spells_name(url, name):
    """The domain is the place's name spelled out (stonefishsushi.com for Stonefish Sushi, zerodegreescompany.com), with at most a business
    word after it: a namesake elsewhere adds its town (greatwallbedford.com) or uses another ending (hound.vet). Names under 8 letters
    and names with no distinctive word don't count."""
    lab, tld = label(url)
    lab = lab.replace("-", "")
    full = "".join(w for w in norm(name.replace("&", " and ")).split() if w not in ("the", "a", "of"))
    full_noand = full.replace("and", "")
    ws = words(name)
    if tld not in GENERAL_TLD or not ws or len(full) < 8 or not (len(ws) >= 2 or len(ws[0]) >= 7):   # "Pete's Cafe" has namesakes
        return False
    for f in {full, full_noand}:
        for pre in ("", "the", "eat"):
            if lab.startswith(pre + f) and lab[len(pre + f):] in SUFFIXES:
                return True
    return False


def town_site(url, ctx):
    """A town's own or tourism site (manitousprings.org, visitestespark.com) or a chamber's is about the town, not the restaurant."""
    lab, _ = label(url)
    lab = lab.replace("-", "")
    towns = {norm(t).replace(" ", "") for t in ctx.get("towns", [])}
    nm = norm(ctx.get("name") or "").replace(" ", "")
    return (lab in towns and lab not in nm) or lab.startswith("visit") or "chamber" in lab or lab.startswith(("cityof", "townof"))


STREET_WORDS = set("st street ave avenue blvd boulevard rd road dr drive ln lane way pkwy parkway hwy highway us co state route ct court "
                   "pl place cir circle ter trl trail sq unit ste suite north south east west n s e w ne nw se sw".split())


def words(name):
    return [w for w in norm(name).split() if len(w) >= 4 and w not in GENERIC]


TODAY = datetime.date.today().isoformat()
host_locks = collections.defaultdict(threading.Lock)
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept": "text/html,*/*;q=0.5", "Accept-Language": "en-US"})


def check(url, ctx):
    ctx = ctx if isinstance(ctx, dict) else {"name": ctx}
    name = ctx.get("name") or ""
    u = url if url.startswith("http") else "https://" + url
    host = urllib.parse.urlparse(u).netloc.lower()
    if bad_host(u):
        return {"ok": False, "why": "directory or Google link", "final": u}
    if news_page(u):
        return {"ok": False, "why": "news story or article", "final": u}
    with host_locks[regdom(host)]:
        try:
            r = session.get(u, timeout=(8, 15), allow_redirects=True, stream=True)
            body = r.raw.read(400_000, decode_content=True).decode(r.encoding or "utf-8", "ignore") if r.ok else ""
            final = r.url
            r.close()
        except Exception as e:
            return {"ok": False, "why": "error: " + type(e).__name__, "final": u}
        finally:
            time.sleep(0.3)
    if not r.ok:
        return {"ok": False, "why": f"http {r.status_code}", "final": final}
    text = BLOBS.sub(" ", body).lower()
    head = " ".join(a or b for a, b in HEAD.findall(text[:60_000]))
    casino = CASINO_PLACE.search(name) or CASINO_PLACE.search(urllib.parse.urlparse(final).netloc)
    if SPAM.search(text) or SPAM.search(final) or (not casino and (BETTING.search(head) or len(BETTING.findall(text)) >= 2)):
        return {"ok": False, "why": "gambling or adult content", "final": final}
    # planted links and spam (casino, betting, adult, pharma, link farms; visible, hidden or off-screen): injection.py
    reasons = injection.scan(body, urllib.parse.urlparse(final).netloc, final, name)
    if reasons:
        rule, evidence = reasons[0]
        return {"ok": False, "why": "hacked: " + rule, "final": final, "evidence": evidence[:300]}
    pk = injection.parked(body, final)
    if pk:
        return {"ok": False, "why": "parked, expired or coming soon", "final": final, "evidence": pk[1][:300]}
    if PARKED.search(text[:60_000]):
        return {"ok": False, "why": "parked, expired or coming soon", "final": final}
    if bad_host(final):
        return {"ok": False, "why": "redirects to a directory", "final": final}
    if news_page(final):
        return {"ok": False, "why": "news story or article", "final": final}
    for m in REFRESH.finditer(body[:60_000]):   # a page that sends the visitor elsewhere with a meta refresh or a script
        to = next(g for g in m.groups() if g)
        if to.startswith("http") and regdom(urllib.parse.urlparse(to).netloc) not in (regdom(host), regdom(urllib.parse.urlparse(final).netloc)):
            return {"ok": False, "why": "redirects to another site", "final": to}
    ws = words(name)
    page = norm(re.sub(r"<script.*?</script>|<style.*?</style>", " ", body, flags=re.S)) + " " + norm(final)
    dom = norm(urllib.parse.urlparse(final).netloc.removeprefix("www.").rsplit(".", 1)[0]).replace(" ", "")
    if any(len(w) >= 5 for w in ws):
        mentions = any(f" {w} " in f" {page} " or w in dom for w in ws if len(w) >= 5)
    elif ws:   # only short words ("G Mart"): the whole name, not "mart" on H Mart's page
        phrase = " ".join(w for w in norm(name).split() if w not in ("the", "and", "of", "a"))
        mentions = f" {phrase} " in f" {page} " or phrase.replace(" ", "") in dom
    else:   # "The Fort", "Pho 555": no distinctive word, so the domain has to spell the name
        allw = [w for w in norm(name).split() if w not in ("the", "and", "of", "a")]
        mentions = bool(allw) and "".join(allw)[:12] in dom
    same = regdom(urllib.parse.urlparse(final).netloc) in (regdom(host), ALIASES.get(regdom(host)))
    if not mentions:
        return {"ok": False, "why": "page doesn't mention the place", "final": final}
    if not same and not any(w in dom for w in ws):
        return {"ok": False, "why": "moved to another domain", "final": final}
    if town_site(final, ctx):
        return {"ok": False, "why": "town, tourism or chamber site", "final": final}
    # a chain's own domain (chipotle.com) names no single store's town; the chain check samples its store pages instead
    brand_dom = ctx.get("chain") and any(w in dom for w in ws)
    where = "brand's own domain" if brand_dom else "domain spells the name" if spells_name(final, name) else \
        located(norm(BLOBS.sub(" ", body)), final, ctx)
    if not where:
        return {"ok": False, "why": "page doesn't show the place's town, address or phone", "final": final}
    ship = url
    if final.startswith("https://") and not u.startswith("https://") and regdom(urllib.parse.urlparse(final).netloc) == regdom(host):
        ship = "https://" + re.sub(r"^(?:https?://)?", "", url)
    return {"ok": True, "why": "ok", "final": final, "ship": ship, "where": where}


def save(results, indent=None):
    """Write the verdicts atomically: the export may read the file while a long check is still running."""
    with open(OUT + ".tmp", "w") as f:
        json.dump(results, f, indent=indent)
    os.replace(OUT + ".tmp", OUT)


def main():
    # every link the export considered (written by texas.py, TX_APP=1), so a link dropped last time gets another chance
    cands = json.load(open(f"{ROOT}/data/tx/website_candidates.json"))
    jobs = collections.defaultdict(list)   # registered domain -> [(url, name)]
    ctx_of = {w: (c if isinstance(c, dict) else {"name": c}) for w, c in cands.items()}
    for w, c in ctx_of.items():
        u = w if w.startswith("http") else "https://" + w
        jobs[regdom(urllib.parse.urlparse(u).netloc)].append((w, c["name"]))
    prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
    # chain verdicts are recomputed every run; host rules may have grown since a page was fetched; a verdict from older rules
    # or older than MAX_AGE days is checked again (a domain that passed can be hijacked later)
    oldest = (datetime.date.today() - datetime.timedelta(days=MAX_AGE)).isoformat()
    prev = {u: v for u, v in prev.items() if not v["why"].startswith(("chain domain", "brand's own"))
            and v["why"] not in ("moved to another domain", "gambling or adult content", "page doesn't show the place's town, address or phone")
            and v.get("v") == RULES and v.get("at", "") >= oldest}
    todo, chain_hosts, brand_of = [], {}, {}
    for dom, items in jobs.items():
        uniq = list(dict.fromkeys(items))
        top, n = collections.Counter(name for _, name in uniq).most_common(1)[0]
        if len(uniq) >= 5 and n >= 0.8 * len(uniq):   # a chain's own domain: three samples stand for all
            chain_hosts[dom] = [u for u, _ in uniq]
            brand_of[dom] = top
            todo += uniq[:3]
        else:
            todo += uniq
    for u, v in prev.items():   # host rules apply to cached pages too, no request needed
        if v["ok"] and (bad_host(u) or bad_host(v["final"])):
            prev[u] = {**v, "ok": False, "why": "redirects to a directory"}
        if v["ok"] and (news_page(u) or news_page(v["final"])):
            prev[u] = {**v, "ok": False, "why": "news story or article"}
    todo = [(u, ctx_of[u]) for u, n in todo if u not in prev]
    print(f"{sum(len(v) for v in jobs.values())} links, {len(jobs)} domains, {len(chain_hosts)} chain domains; checking {len(todo)}")
    results, done = dict(prev), 0
    lock = threading.Lock()

    def run(item):
        nonlocal done
        try:
            verdict = check(*item)
        except ValueError as e:   # a malformed URL on the page or in the listing: dropped, never a crash of the whole run
            verdict = {"ok": False, "why": "error: " + type(e).__name__, "final": item[0]}
        res = {**verdict, "at": TODAY, "v": RULES}
        with lock:
            results[item[0]] = res
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(todo)}", flush=True)
                save(results)

    with ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(run, todo))
    for dom, urls in chain_hosts.items():
        samples = [results.get(u) for u in urls[:3] if results.get(u)]
        verdict = bool(samples) and sum(s["ok"] for s in samples) >= 2
        why = "chain domain " + ("ok" if verdict else "failed its samples")
        own = any(w in norm(dom) for w in words(brand_of[dom]))
        if not verdict and own and samples and all(s["ok"] or BLOCKED.match(s["why"]) for s in samples):
            verdict, why = True, "brand's own site (blocked the check)"
            for u in urls[:3]:
                results[u] = {**results[u], "ok": True, "why": why}
        for u in urls[3:]:
            results[u] = {"ok": verdict, "why": why, "final": u, "ship": u, "at": TODAY, "v": RULES}
    save(results, indent=0)
    c = collections.Counter(v["why"] if not v["ok"] else "ok" for v in results.values())
    print("results:", c.most_common())


if __name__ == "__main__":
    main()
