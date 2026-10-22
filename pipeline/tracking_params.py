"""Strips tracking query parameters from outbound links before they ship (QA 2026-10-19, P1 #13).

Map listings carry the tags a business's listing manager or Google's ordering feed added ("?ref=google",
"referrer=google_food_ordering", "cn_channel=cn_google", utm_*, Yext's "cid=RF:YXT…"). They tell the destination the visitor came
from Google, which isn't true for our app and site, and they track. Only parameters that are tracking by name (or a known tracking
value) go; everything else in the query stays, because store pages need theirs (store ids, locations, Olo/Toast restaurant ids).
scrub() rewrites every bare URL anywhere in the data, in place; the app's unit test fails if a tracking parameter is bundled.

The same file is in every state's pipeline/; keep the copies identical.
"""
import collections
import re
import urllib.parse

BARE_URL = re.compile(r"(?i)^\s*https?://\S+\s*$")
# tracking by name, whatever the value
TRACKING_KEYS = re.compile(r"^(?:utm[_-].*|gclid|gbraid|wbraid|dclid|fbclid|msclkid|mc_cid|mc_eid|_ga|_gl|igsh|igshid|mibextid|srsltid|"
                           r"cn_channel|y_source|rwg_token|olonwp|ost_redirect_attribution|cmpid|yext_?.*)$", re.I)
# tracking only with these values: a source tag that names Google or a listing manager (ref=google, referrer=google_food_ordering,
# source=google), Yext's campaign ids on chains' links (cid=RF:YXT:…), Disney's listing campaigns (CMP=OKC-…)
TRACKING_VALUES = {
    "ref": re.compile(r"^(?:google|gmb|gbp|yext|bookmarks)\b", re.I),
    "referrer": re.compile(r"^google", re.I),
    "source": re.compile(r"^(?:google|gmb|gbp|yext)\b", re.I),
    "cid": re.compile(r"^RF:YXT", re.I),
    "cmp": re.compile(r"^OKC-", re.I),
}


def _tracking(k, v):
    k = k.strip()
    if TRACKING_KEYS.match(k):
        return True
    rx = TRACKING_VALUES.get(k.lower())
    return bool(rx and rx.match(v.strip()))


def clean(url):
    """The link without its tracking parameters. Anything else (path, fragment, other parameters, their order) is unchanged."""
    s = url.strip()
    try:
        u = urllib.parse.urlsplit(s)
    except ValueError:
        return url
    if not u.query:
        return url
    parts = u.query.split("&")
    keep = []
    for p in parts:
        k, _, v = p.partition("=")
        if not _tracking(urllib.parse.unquote_plus(k), urllib.parse.unquote_plus(v)):
            keep.append(p)
    if len(keep) == len(parts):
        return url
    return urllib.parse.urlunsplit(u._replace(query="&".join(p for p in keep if p)))


def scrub(obj, changed=None):
    """Clean, in place, every bare URL anywhere in obj (dicts and lists, any depth). Returns a Counter of rewrites by field."""
    changed = collections.Counter() if changed is None else changed
    if isinstance(obj, dict):
        items = obj.items()
    elif isinstance(obj, list):
        items = enumerate(obj)
    else:
        return changed
    for k, v in list(items):
        if isinstance(v, str) and BARE_URL.match(v):
            c = clean(v)
            if c != v:
                obj[k] = c
                changed[k if isinstance(k, str) else "[list]"] += 1
        else:
            scrub(v, changed)
    return changed


def tracked(text):
    """Links in a text (JSON, HTML) that still carry a tracking parameter; for QA scripts and tests."""
    t = text.replace("\\/", "/").replace("&amp;", "&")
    return [u for u in re.findall(r"""https?://[^\s"'<>\\]+""", t) if clean(u) != u]


if __name__ == "__main__":   # self-test: python3 tracking_params.py
    cases = {
        "http://places.singleplatform.com/havana-spice/menu?ref=google": "http://places.singleplatform.com/havana-spice/menu",
        "https://pos.chowbus.com/online-ordering/store/The-Copper-Q/23380?referrer=google_food_ordering":
            "https://pos.chowbus.com/online-ordering/store/The-Copper-Q/23380",
        "https://direct.chownow.com/order/41979/locations/63500?cn_channel=cn_google": "https://direct.chownow.com/order/41979/locations/63500",
        "https://www.kekes.com/locations/kekes-mandarin?utm_source": "https://www.kekes.com/locations/kekes-mandarin",
        "https://x.example/?utm_source=gmb&utm_medium=organic&store=12#menu": "https://x.example/?store=12#menu",
        "https://www.eventbrite.com/e/1?utm-campaign=social&aff=ebdsshios": "https://www.eventbrite.com/e/1?aff=ebdsshios",
        "https://www.mcdonalds.com/?cid=RF%3AYXT%3AFB%3A%3AClicks": "https://www.mcdonalds.com/",
        "https://www.jaleo.com/location/jaleo-disney-springs/?CMP=OKC-19063652_GM_WDW": "https://www.jaleo.com/location/jaleo-disney-springs/",
        # kept: a store's own parameters
        "https://order.example.com/menu?restaurantId=51&location=7": "https://order.example.com/menu?restaurantId=51&location=7",
        "https://shop.example.com/?cid=12": "https://shop.example.com/?cid=12",
        "https://www.goldbelly.com/restaurants/x?ref=gs": "https://www.goldbelly.com/restaurants/x?ref=gs",
        "https://example.com/": "https://example.com/",
    }
    bad = 0
    for a, want in cases.items():
        got = clean(a)
        bad += got != want
        print("ok  " if got == want else "FAIL", a, "->", got)
    d = {"w": "https://a.example/?fbclid=1", "links": ["https://b.example/?x=1&gclid=2"], "n": "not a url ?utm_source=x"}
    ch = scrub(d)
    ok = d == {"w": "https://a.example/", "links": ["https://b.example/?x=1"], "n": "not a url ?utm_source=x"} and sum(ch.values()) == 2
    bad += not ok
    print("ok  " if ok else "FAIL", "scrub rewrites nested links only")
    ok = tracked('{"w":"https:\\/\\/a.example\\/?ref=google"}') == ["https://a.example/?ref=google"] and tracked('"https://a.example/"') == []
    bad += not ok
    print("ok  " if ok else "FAIL", "tracked() finds escaped JSON links")
    print("failures:", bad)
    raise SystemExit(1 if bad else 0)
