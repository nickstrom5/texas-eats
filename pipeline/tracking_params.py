"""Strips tracking query parameters from outbound links before they ship (QA 2026-10-19, P1 #13).

Map listings carry the tags a business's listing manager or Google's ordering feed added ("?ref=google",
"referrer=google_food_ordering", "cn_channel=cn_google", utm_*, Yext's "cid=RF:YXT…"). They tell the destination the visitor came
from Google, which isn't true for our app and site, and they track. Only parameters that are tracking by name (or a known tracking
value) go; everything else in the query stays, because store pages need theirs (store ids, locations, Olo/Toast restaurant ids).
scrub() rewrites every bare URL anywhere in the data, in place; the app's unit test fails if a tracking parameter is bundled.
Since QA 2026-10-28 (P1 #4) the same rules also cover tags after "#" (Yext's "…/las-vegas/#utm_source=rest_of_network…"), tags
written into the path ("…/alpharetta/utm_source=Facebook&utm_medium=BusinessListing") and links stored without a scheme
("instagram.com/x?igshid=…"), which the website shows with https:// added.

The same file is in every state's pipeline/; keep the copies identical.
"""
import collections
import re
import urllib.parse

# a whole string that is one link: with a scheme, or a bare host and path ("instagram.com/x?igshid=…", "www.x.com")
BARE_URL = re.compile(r"(?i)^\s*(?:https?://|www\.|(?:[a-z0-9-]+\.)+[a-z]{2,}/)\S*\s*$")
LINKS = re.compile(r"""(?i)https?://[^\s"'<>\\]+|(?<![\w/.:@-])(?:[a-z0-9-]+\.)+[a-z]{2,}/[^\s"'<>\\]*""")
# tracking by name, whatever the value
TRACKING_KEYS = re.compile(r"^(?:utm[_-].*|gclid|gbraid|wbraid|dclid|fbclid|msclkid|mc_cid|mc_eid|_ga|_gl|_kx|igsh|igshid|mibextid|"
                           r"srsltid|cn_channel|y_source|rwg_token|olonwp|ost_redirect_attribution|cmpid|yext_?.*)$", re.I)
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


def _drop(params):
    """"k=v&k2=v2" without its tracking pairs, or None when none of them is tracking."""
    parts = params.split("&")
    keep = []
    for p in parts:
        k, _, v = p.partition("=")
        if not _tracking(urllib.parse.unquote_plus(k), urllib.parse.unquote_plus(v)):
            keep.append(p)
    if len(keep) == len(parts):
        return None
    return "&".join(p for p in keep if p)


def clean(url):
    """The link without its tracking parameters, in the query, after "#" or written into the path. Anything else (the rest of the
    path, a page anchor or a single-page app's route, other parameters, their order) is unchanged."""
    s = url.strip()
    try:
        u = urllib.parse.urlsplit(s)
    except ValueError:
        return url
    query, path, frag = u.query, u.path, u.fragment
    if query:
        q = _drop(query)
        query = query if q is None else q
    if "=" in frag:
        # "#utm_source=…" or a route's own query ("#/menu?utm_source=…&table=4": the route stays)
        head, sep, tail = frag.rpartition("?")
        f = _drop(tail)
        if f is not None:
            frag = head + sep + f if f else head
    if "=" in path:
        segs = path.split("/")
        out = []
        for i, seg in enumerate(segs):
            d = _drop(seg) if "=" in seg else None
            if d is None:
                out.append(seg)
            elif d or i == len(segs) - 1:
                out.append(d)      # a dropped last segment leaves the trailing slash: ".../alpharetta/"
        path = "/".join(out)
    if (query, path, frag) == (u.query, u.path, u.fragment):
        return url
    return urllib.parse.urlunsplit(u._replace(query=query, path=path, fragment=frag))


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
    return [u for u in LINKS.findall(t) if clean(u) != u]


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
        # after "#", in the path, without a scheme (QA 2026-10-28)
        "https://cafe.hardrock.com/las-vegas/#utm_source=rest_of_network&utm_medium=Yext&utm_campaign=Listings":
            "https://cafe.hardrock.com/las-vegas/",
        "https://order.example.com/#/menu?utm_source=fb&table=4": "https://order.example.com/#/menu?table=4",
        "https://www.snoozeeatery.com/restaurant/georgia/alpharetta/utm_source=Facebook&utm_medium=BusinessListing":
            "https://www.snoozeeatery.com/restaurant/georgia/alpharetta/",
        "https://x.example/menu/utm_source=fb/item-4": "https://x.example/menu/item-4",
        "instagram.com/sharks1413_macon?igshid=NjNlMDhmYTc%3D": "instagram.com/sharks1413_macon",
        "https://paulthomaschocolates.com/pages/free-tasting-event?_kx=aSsBlo5n7gs8XtzVMZqf49qCxiL8_rle28VLXim4X1o.V26kig%3Futm_source%3Dfacebook":
            "https://paulthomaschocolates.com/pages/free-tasting-event",
        # kept: a store's own parameters
        "https://order.example.com/menu?restaurantId=51&location=7": "https://order.example.com/menu?restaurantId=51&location=7",
        "https://shop.example.com/?cid=12": "https://shop.example.com/?cid=12",
        "https://www.goldbelly.com/restaurants/x?ref=gs": "https://www.goldbelly.com/restaurants/x?ref=gs",
        "https://example.com/": "https://example.com/",
        "https://example.com/#menu": "https://example.com/#menu",
        "https://togoorder.com/web/1754#/": "https://togoorder.com/web/1754#/",
        "https://order.example.com/#/store?id=9": "https://order.example.com/#/store?id=9",
        "https://example.com/p/id=5": "https://example.com/p/id=5",
        "www.example.com/menu?page=2": "www.example.com/menu?page=2",
    }
    bad = 0
    for a, want in cases.items():
        got = clean(a)
        bad += got != want
        print("ok  " if got == want else "FAIL", a, "->", got)
    d = {"w": "https://a.example/?fbclid=1", "links": ["https://b.example/?x=1&gclid=2"], "n": "not a url ?utm_source=x",
         "ig": "instagram.com/x?igshid=1", "t": "Dr. J's/Main St ?utm_source=x"}
    ch = scrub(d)
    ok = d == {"w": "https://a.example/", "links": ["https://b.example/?x=1"], "n": "not a url ?utm_source=x",
               "ig": "instagram.com/x", "t": "Dr. J's/Main St ?utm_source=x"} and sum(ch.values()) == 3
    bad += not ok
    print("ok  " if ok else "FAIL", "scrub rewrites nested links only")
    ok = tracked('{"w":"https:\\/\\/a.example\\/?ref=google"}') == ["https://a.example/?ref=google"] and tracked('"https://a.example/"') == []
    bad += not ok
    print("ok  " if ok else "FAIL", "tracked() finds escaped JSON links")
    ok = tracked('{"w":"instagram.com\\/x?igshid=1","h":"https://h.example/#utm_source=y","k":"https://k.example/a#top"}') == [
        "instagram.com/x?igshid=1", "https://h.example/#utm_source=y"]
    bad += not ok
    print("ok  " if ok else "FAIL", "tracked() finds scheme-less links and tags after #")
    print("failures:", bad)
    raise SystemExit(1 if bad else 0)
