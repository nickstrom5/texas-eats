"""Stage 2: the Texas list -> site/texas.json (web leaderboard) or, with TX_APP=1, data/app/places.json (the App Store build)

Ported from co-eats/pipeline/colorado.py (itself from wi-eats). Statewide base: Overture Maps listings (stage1.pkl), kept by the rule
calibrate.py measured against Austin's, El Paso's and Arlington's inspected establishments (data/tx/calibration*.json).
Official records: a listing that matches a TABC license or an Austin / El Paso / Arlington inspected establishment is marked
official, and licensed or inspected restaurants and bars the map data doesn't have are added from the lists. Those three cities'
inspection scores are shown as each city publishes them (score 0-100 and the city's own band or grade), never a grade of ours.
Ratings, reviews and price level (web only): Google, Sep 2021 snapshot (UCSD Google Local).
"""
import os, re, sys, json, math, hashlib, unicodedata, collections, glob, urllib.parse
import numpy as np, pandas as pd
from shapely.geometry import shape, Point
from shapely.prepared import prep
from rapidfuzz import fuzz
from common import (norm_name, nice, name_sim, cuisine, FOOD_COST, MARGIN, MARGIN_CUISINE, SPEND, GENERIC, _stems, DATA, TX, ROOT,
                    canon_city, town_key, FOODCAT)
from brands import brand_of
import official
import tracking_params
from listings_util import official_match, _close_words
from official import street_key, street_nums

APP = os.environ.get("TX_APP") == "1"
SITE = os.environ.get("TX_SITE") or (os.path.join(ROOT, "data", "app") if APP else os.path.join(ROOT, "site"))
GOOD_SOURCES = {"meta", "AllThePlaces", "DAC"}
BASE = {1: 600_000, 2: 1_000_000, 3: 2_200_000, 4: 3_500_000}   # typical yearly sales by price tier (same as Chicago)
B_FIT = 0.764   # review-volume exponent fit on Chicago's published sales (chi-eats meta.model.b)
import datetime
TODAY = datetime.date.today().isoformat()
TAX_CUISINE = {
    "pizza_restaurant": "Pizza", "mexican_restaurant": "Mexican", "taco_restaurant": "Mexican", "texmex_restaurant": "Mexican",
    "sandwich_shop": "Sandwiches & Deli", "delicatessen": "Sandwiches & Deli", "bakery": "Bakery & Sweets", "donut_shop": "Bakery & Sweets",
    "dessert_shop": "Bakery & Sweets", "ice_cream_shop": "Bakery & Sweets", "bagel_shop": "Bakery & Sweets", "cupcake_shop": "Bakery & Sweets",
    "frozen_yogurt_shop": "Bakery & Sweets", "chocolatier": "Bakery & Sweets", "popcorn_shop": "Bakery & Sweets",
    "bar_and_grill_restaurant": "Bar & Pub", "gastropub": "Bar & Pub", "bar": "Bar & Pub", "brewery": "Bar & Pub", "pub": "Bar & Pub",
    "sports_bar": "Bar & Pub", "cocktail_bar": "Bar & Pub", "wine_bar": "Bar & Pub", "dive_bar": "Bar & Pub", "beer_bar": "Bar & Pub",
    "irish_pub": "Bar & Pub", "tiki_bar": "Bar & Pub", "speakeasy": "Bar & Pub", "hookah_bar": "Bar & Pub", "gay_bar": "Bar & Pub",
    "chinese_restaurant": "Chinese", "italian_restaurant": "Italian", "burger_restaurant": "Burgers",
    "breakfast_and_brunch_restaurant": "Breakfast & Diner", "diner": "Breakfast & Diner", "barbecue_restaurant": "BBQ",
    "chicken_restaurant": "Chicken & Wings", "chicken_wings_restaurant": "Chicken & Wings", "sushi_restaurant": "Japanese & Sushi",
    "japanese_restaurant": "Japanese & Sushi", "ramen_restaurant": "Japanese & Sushi", "seafood_restaurant": "Seafood", "poke_restaurant": "Seafood",
    "steakhouse": "Steakhouse", "indian_restaurant": "South Asian", "pakistani_restaurant": "South Asian", "thai_restaurant": "Thai",
    "hot_dog_restaurant": "Hot Dogs & Sausages", "mediterranean_restaurant": "Mediterranean & Middle Eastern",
    "greek_restaurant": "Mediterranean & Middle Eastern", "middle_eastern_restaurant": "Mediterranean & Middle Eastern",
    "korean_restaurant": "Korean", "vietnamese_restaurant": "Vietnamese", "salad_bar": "Healthy & Vegan", "vegan_restaurant": "Healthy & Vegan",
    "vegetarian_restaurant": "Healthy & Vegan", "health_food_restaurant": "Healthy & Vegan", "coffee_shop": "Coffee & Café", "cafe": "Coffee & Café",
    "coffee_roastery": "Coffee & Café", "smoothie_juice_bar": "Healthy & Vegan", "juice_bar": "Healthy & Vegan", "bubble_tea_shop": "Coffee & Café",
    "tea_room": "Coffee & Café", "soul_food": "Soul & Southern", "southern_american_restaurant": "Soul & Southern",
    "cajun_and_creole_restaurant": "Seafood", "caribbean_restaurant": "Latin & Caribbean", "jamaican_restaurant": "Latin & Caribbean",
    "latin_american_restaurant": "Latin & Caribbean", "cuban_restaurant": "Latin & Caribbean", "puerto_rican_restaurant": "Latin & Caribbean",
    "peruvian_restaurant": "Latin & Caribbean", "african_restaurant": "African", "ethiopian_restaurant": "African",
    "french_restaurant": "German & European", "german_restaurant": "German & European", "polish_restaurant": "German & European",
    "spanish_restaurant": "German & European", "tapas_bar": "German & European", "noodles_restaurant": "Chinese",
    "belgian_restaurant": "German & European", "russian_restaurant": "German & European", "fondue_restaurant": "German & European",
    "scandinavian_restaurant": "German & European", "european_restaurant": "German & European", "eastern_european_restaurant": "German & European",
    "hungarian_restaurant": "German & European", "british_restaurant": "German & European", "dutch_restaurant": "German & European",
}


def curated_matcher(frame):
    """A researched place -> row of frame: same street number and street with a similar name; else a near-exact name in the same town;
    else a near-exact name that's unique statewide (the research uses the real municipality, the listings the mailing town)."""
    by_key = {}
    for i, a in enumerate(frame.street):
        sk = street_key(a)[1]
        for n in street_nums(a):
            if sk:
                by_key.setdefault((n, sk), []).append(i)
    towns = [canon_city(c).lower() if isinstance(c, str) else "" for c in frame.city]
    ks = list(frame.k.fillna(""))
    # two listings at the researched address that match equally well: the official or high-confidence one wins (a Foursquare copy of
    # Vin48 sat 3.3 km up the hill)
    srcrank = [3 if s_ == "official" else 2 if s_ == "meta" else 1 if s_ in ("AllThePlaces", "DAC") else 0 for s_ in frame.src]
    lat_ = list(frame.lat) if "lat" in frame else None
    lon_ = list(frame.lon) if "lon" in frame else None

    def match(c):
        # "J-Bar (Hotel Jerome)" is the J-Bar: the words in parentheses say where it is, so they don't count toward a name match
        bare = lambda n: re.sub(r"\s*\([^)]*\)", "", n or "")
        keys = {norm_name(bare(m)) for m in (c.get("match_names") or [])} | {norm_name(bare(c["name"]))}
        keys.discard("")
        if not keys:   # a name that is only a number ("1111" in Houston) has no name key: it can't be matched by name
            return None
        _, sk = street_key(c.get("address") or "")
        cands = set()
        for n in street_nums(c.get("address") or ""):
            cands.update(by_key.get((n, sk), []))
        best, bs = None, 0
        for i in cands:
            s_ = max((fuzz.token_set_ratio(m, ks[i]) for m in keys), default=0)
            if s_ >= 60 and s_ + srcrank[i] > bs:
                best, bs = i, s_ + srcrank[i]
        if best is None and not c.get("chain"):
            ctown = (canon_city(c.get("city") or "") or "").lower()
            sim = [max(fuzz.ratio(m, k) for m in keys) if k else 0 for k in ks]
            hits = [i for i, s_ in enumerate(sim) if s_ >= 90 and towns[i] == ctown] or [i for i, s_ in enumerate(sim) if s_ >= 95]
            if len(hits) == 1:
                best = hits[0]
            elif len(hits) > 1 and lat_ is not None:
                # two records of one business (a TABC row and its map listing) before the duplicate merge: the same spot,
                # so the better-sourced one; two branches far apart stay unmatched until the research gives an address
                la_ = [lat_[i] for i in hits]; lo_ = [lon_[i] for i in hits]
                if (max(la_) - min(la_)) * 111 < 0.4 and (max(lo_) - min(lo_)) * 97 < 0.4:
                    best = max(hits, key=lambda i: srcrank[i])
        return best
    return match




def pct(s):
    return (s.rank(pct=True) * 100).round(1)


o = pd.read_pickle(f"{TX}/stage1.pkl")
G = pd.read_pickle(f"{TX}/google21.pkl")
if APP:   # the App Store build ignores every Google 2021 match
    o["in21"] = False; o["closed21"] = False; o["gi"] = np.nan
F = pd.read_pickle(f"{TX}/official.pkl")
F = F[F.active].reset_index(drop=True)
# a liquor license still on the "active" list a year or more after its expiration (Coohills, 2014) is a stale record, not evidence
# that the business is open; a lapse of under a year is a pending renewal
stale = F.jur.eq("liq") & F.expires.notna() & (F.expires.astype(str) < "2025-10-19")
print("stale liquor licenses ignored (expired a year or more before the list):", int(stale.sum()))
F = F[~stale].reset_index(drop=True)
# Town, neighborhood and company words prove nothing about a name: Madame Ushi's licensee "7908 ASPEN LLC" isn't Jus Aspen, and
# "LB CHERRY CREEK LLC" (Le Bilboquet) isn't Tony P's Cherry Creek. Names are compared on what's left.
NEIGHBORHOODS = set("""DOWNTOWN UPTOWN MIDTOWN MONTROSE HEIGHTS DEEP ELLUM BISHOP ARTS LOWER GREENVILLE KNOX HENDERSON GALLERIA RIVER OAKS
RICE VILLAGE MEMORIAL WASHINGTON EADO EAST END SOUTH CONGRESS SOCO RAINEY CLARKSVILLE MUELLER DOMAIN ZILKER SOUTH LAMAR PEARL
SOUTHTOWN ALAMO HEIGHTS STONE OAK RIVERWALK RIVER WALK STOCKYARDS SUNDANCE NEAR SOUTHSIDE MAGNOLIA LEGACY WEST VICTORY PARK
MARKETPLACE VILLAGE CROSSING MALL CITY CENTRAL PLAZA SQUARE STATION""".split())
LEGAL_W = {"LLC", "INC", "CORP", "CORPORATION", "LTD", "CO", "COMPANY", "GROUP", "HOLDINGS", "HOLDING", "HOSPITALITY", "ENTERPRISES",
           "ENTERPRISE", "INVESTMENTS", "INVESTMENT", "PROPERTIES", "MANAGEMENT", "VENTURES", "PARTNERS", "DBA", "THE"}
NOISE_W = {w for c in o.city.dropna().unique() for w in norm_name(canon_city(c) or c).split()} | NEIGHBORHOODS | LEGAL_W | {"TEXAS", "TX"}


def core(k):
    return " ".join(w for w in (k or "").split() if w not in NOISE_W)


def agree(a, b, need=80):
    """Two normalized names are the same business: compared without town, neighborhood and company words."""
    ca, cb = core(a), core(b)
    if not ca or not cb:
        return bool(a) and a == b
    return name_sim(ca, cb) >= need


# words a neighbor shares without being the same business: a host store, a food everyone sells
SHARED_JUNK = {"WHOLE", "SAFEWAY", "TARGET", "KING", "SOOPERS", "WALMART", "COSTCO", "SPROUTS", "ALBERTSONS", "YOGURT", "FROZEN", "SUSHI",
               "RAMEN", "NOODLE", "NOODLES", "BURRITO", "BURRITOS", "BAGEL", "BAGELS", "CREPE", "CREPES", "BOBA", "SMOOTHIE", "JUICE",
               "SPIRITS", "WINE", "WINES", "LIQUOR", "LIQUORS", "BEER", "BREWING", "BREWERY", "DISTILLERY", "CAKE", "CAKES", "PIE", "PIES"}


def shared_word(a, b):
    """A distinctive word of four letters or more in both names (not a town, neighborhood, company, host-store or food word)."""
    sa = {w for w in _stems(core(a)) if len(w) >= 4 and w not in SHARED_JUNK}
    sb = {w for w in _stems(core(b)) if len(w) >= 4 and w not in SHARED_JUNK}
    return bool(sa & sb)
# a license the geocoders couldn't place (a highway address in the mountains) still matches a listing by street address in its
# town's county: Outer Range Brewing and Eddyline Pub had no county, so their Brew Pub licenses never reached their listings
town_cty = o.dropna(subset=["city", "county"]).groupby("city").county.agg(lambda s_: s_.mode().iat[0]).to_dict()
miss_cty = F.county.isna()
F.loc[miss_cty, "county"] = F.city[miss_cty].map(lambda c: town_cty.get(canon_city(c)))
print("unplaced licenses given their town's county:", int((miss_cty & F.county.notna()).sum()), "of", int(miss_cty.sum()))

# ---------------------------------------------------------------- official records, matched county by county
# (a street address like "100 Main St" exists in dozens of towns, so a match is only tried inside one county)
o["off"] = np.nan
for cty, sel in o.groupby("county").groups.items():
    R = F[F.county == cty]
    if not len(R):
        continue
    L = o.loc[sel].reset_index(drop=True)
    m = official_match(L, R.reset_index(drop=True), town_words=frozenset(NOISE_W))
    for i, j in m.items():
        o.at[sel[i], "off"] = R.index[j]
o["official"] = o.off.notna()
print("listings matched to an official record:", int(o.official.sum()), F.loc[o.off.dropna().astype(int), "jur"].value_counts().to_dict())

# a company register lists the owner ("Irish Investments And Securities"), not the restaurant: show the trade name from the place's own
# TABC license or city record, and drop an entity that holds no license (a restaurant group's office)
ENTITY = re.compile(r"\b(?:LLC|L\.L\.C|INC|GROUP|HOLDINGS?|HOSPITALITY|ENTERPRISES?|INVESTMENTS?|PROPERTIES|DEVELOPMENT|MANAGEMENT|VENTURES|"
                    r"PARTNERS|CORP|CORPORATION|SECURITIES|ASSOCIATES|INDUSTRIES|CONCEPTS)\b", re.I)
FOODISH = re.compile(r"(?i)restaurant|caf[eé]|grill|kitchen|pizz|\bbar\b|pub|tavern|taco|burger|bbq|brew|coffee|bakery|deli|diner|sushi|"
                     r"food|eatery|saloon|lounge|cantina|steak|wings|chicken|bistro|taproom|winery|distill")


def _trade(n):
    n = re.sub(r",?\s+(?:INC|LLC|L\.L\.C|CORP|CORPORATION|LTD)\.?\s*$", "", (n or "").strip(), flags=re.I).strip(" -,&/")
    n = re.sub(r"^(.+?),?\s+THE$", r"THE \1", n, flags=re.I)
    return nice(n) if n.isupper() or n.islower() else n


o["name"] = o.name.str.replace(r"(?i)^.*?\bd\s*/?\s*b\s*/?\s*a\b\.?:?\s+(?=\S)", "", regex=True)
# "Tags Restaurant Group", "Zh Restaurant Investments 3": a company word at the end is a company even with a food word before it
ENTITY_END = re.compile(r"(?i)(?<![&]\s)(?<!\band\s)\b(?:GROUP|INVESTMENTS?|HOLDINGS?|CONCEPTS|MANAGEMENT|VENTURES|PARTNERS|ENTERPRISES?|PROPERTIES|DEVELOPMENT|HOSPITALITY)(?:\s+\d+)?$")
ent_rows = pd.Series([bool(ENTITY.search(n)) and (not FOODISH.search(n) or bool(ENTITY_END.search(n))) for n in o.name.fillna("")], index=o.index)
ent_fixed, ent_drop = 0, []
F_biz_rows = F.groupby("biz").groups
for i in o.index[ent_rows]:
    j = o.off.at[i]
    names = []
    if j == j:
        for jj in F_biz_rows.get(F.biz.iat[int(j)], []):
            nm_ = F["name"].iat[jj]
            if isinstance(nm_, str) and nm_ and not ENTITY.search(nm_):
                names.append(nm_)
    if names:
        o.at[i, "name"] = _trade(names[0]); o.at[i, "k"] = norm_name(o.at[i, "name"]); o.at[i, "st"] = _stems(o.at[i, "k"]) - GENERIC
        ent_fixed += 1
    else:
        ent_drop.append(i)
QA_DEBUG = {"entity_dropped": [f"{o.at[i, 'name']} | {o.at[i, 'street']} | {o.at[i, 'city']} | {o.at[i, 'src']}" for i in ent_drop]}
o = o.drop(index=ent_drop).reset_index(drop=True)
print("company names replaced by the license's trade name:", ent_fixed, "| company rows with no license dropped:", len(ent_drop))


# ---------------------------------------------------------------- hand-checked research (data/research)
def load_curated():
    """MICHELIN Guide Texas and James Beard honors -> curated entries (facts only, each with sources)."""
    out, by = [], {}

    def entry(name, address, city, zip_=None):
        key = (norm_name(name), (canon_city(city) or "").lower())
        if key not in by:
            by[key] = {"name": name, "address": address, "city": city, "zip": zip_, "chain": False, "match_names": [name.upper()],
                       "james_beard": [], "other_honors": [], "tags": [], "open": True, "sources": []}
            out.append(by[key])
        return by[key]
    mpath = f"{DATA}/research/michelin.json"
    if os.path.exists(mpath):
        mj = json.load(open(mpath))
        for r in mj.get("restaurants", []):
            c = entry(r["name"], r.get("address"), r.get("city"), r.get("zip"))
            c["michelin"] = r.get("distinction")
            c["green_star"] = bool(r.get("green_star"))
            c["sources"] += r.get("sources") or []
            if r.get("michelin_url"):
                c["sources"].append(r["michelin_url"])
            if r.get("open") is False:
                c["open"] = False
    jpath = f"{DATA}/research/jbf.json"
    if os.path.exists(jpath):
        for r in json.load(open(jpath)):
            c = entry(r["name"], r.get("address"), r.get("city"), r.get("zip"))
            c["james_beard"] += [h for h in r.get("honors") or [] if h not in c["james_beard"]]
            c["sources"] += r.get("sources") or []
            if r.get("open") is False:
                c["open"] = False
    return out


CUR = load_curated()


# A source on a host that blocks us (robots.txt disallows ClaudeBot, Claude-User or anthropic-ai, or a bot check) is never used:
# pipeline/check_sources.py checks every cited host and caches the answers in data/research/source_hosts.json (ported from ny-eats,
# 2026-10-16: 54 cited URLs on 15 hosts were blocked, among them westword.com, 5280.com and cpr.org)
SOURCE_HOSTS = json.load(open(f"{DATA}/research/source_hosts.json")) if os.path.exists(f"{DATA}/research/source_hosts.json") else {}
UNCHECKED_HOSTS, NO_SOURCE = set(), []


def usable(urls):
    from check_sources import why_not, host, API_HOSTS
    out = []
    for u in urls or []:
        if host(u) in API_HOSTS:
            out.append(u)
        elif host(u) not in SOURCE_HOSTS:
            UNCHECKED_HOSTS.add(host(u)); out.append(u)
        elif why_not(SOURCE_HOSTS, u) is None:
            out.append(u)
    return out


def load_research():
    """data/research/app/*.json: hand-checked BBQ, Tex-Mex, taquerias, kolaches, chicken-fried steak and oldest places
    (facts only, each with a 2025-26 source). An entry for a place already in CUR adds its kinds and notes there."""
    out, by = [], {(norm_name(c["name"]), (canon_city(c.get("city")) or "").lower()): c for c in CUR}
    for f in sorted(glob.glob(f"{DATA}/research/app/*.json")):
        if os.path.basename(f).startswith("closed"):
            continue
        for e in json.load(open(f)):
            if e.get("open") is False or not e.get("name"):
                continue
            ok_src = usable(e.get("sources"))
            if not ok_src or e.get("recheck"):   # a guide entry needs a 2025-26 source we may use; it waits until it has one
                NO_SOURCE.append(f"{e['name']} ({e.get('city') or ''})"); continue
            key = (norm_name(e["name"]), (canon_city(e.get("city")) or "").lower())
            c = by.get(key)
            if c is None:
                c = {"name": e["name"], "address": e.get("address"), "city": e.get("city"), "zip": e.get("zip"), "chain": False,
                     "match_names": [e["name"].upper()] + [m.upper() for m in e.get("match_names") or []], "founded": e.get("founded"),
                     "open": True, "tags": [], "research_only": True}
                by[key] = c; out.append(c)
            c["tags"] = list(dict.fromkeys((c.get("tags") or []) + [k.lower() for k in (e.get("kinds") or [])]))
            c["dishes"] = list(dict.fromkeys((c.get("dishes") or []) + (e.get("dishes") or [])))
            c["rsources"] = list(dict.fromkeys((c.get("rsources") or []) + ok_src))
            for k in ("note", "website", "seasonal", "founded_note", "evidence_date", "display"):
                c[k] = c.get(k) or e.get(k)
            if not c.get("founded") and e.get("founded"):
                c["founded"] = e["founded"]
    return out


CUR = CUR + load_research()
CLOSED = []
for f in [f"{DATA}/research/closed.json"] + sorted(glob.glob(f"{DATA}/research/app/closed_*.json")):
    if os.path.exists(f):
        CLOSED += json.load(open(f))
# a closure still applies while its source waits to be replaced (showing a place we know closed is the worse error), but it's listed
closed_unsourced = [c["name"] for c in CLOSED if not usable(c.get("sources"))]
print("research entries waiting for a source we may use:", len(NO_SOURCE), NO_SOURCE[:20],
      "| closures whose only sources are blocked:", closed_unsourced, "| cited hosts never checked (run check_sources.py):",
      sorted(UNCHECKED_HOSTS)[:8])
print("verified places: honors", sum(1 for c in CUR if not c.get("research_only")), "+ research-only", sum(1 for c in CUR if c.get("research_only")),
      "| verified closed:", len(CLOSED))

# ---------------------------------------------------------------- keep rule (calibrate.py / calibration*.json)
base_ok = ~o.j_junk & ~o.j_closedname & ~o.j_outside & ~o.j_far & ~o.ov_closed & ~(o.nowhere & ~o.in21)
_m = curated_matcher(o[base_ok].reset_index())
_bo = o.index[base_ok]
verified = pd.Series(False, index=o.index)
for c in CUR:
    if c.get("open") is not False:
        j = _m(c)
        if j is not None:
            verified[_bo[j]] = True
conf = o.confidence.fillna(0)
has_web = o.n_web.fillna(0).astype(int) > 0
if APP:
    keep = base_ok & (o.official | verified | ((o.src == "meta") & (conf >= 0.95)) | ((o.src == "meta") & (conf >= 0.9) & has_web)
                      | o.src.isin(["AllThePlaces", "DAC"]))
else:
    keep = base_ok & (~o.closed21 | o.official | verified) & (o.src.isin(GOOD_SOURCES) | o.official | verified)
print("kept listings:", int(keep.sum()), "of", len(o), "| hand-verified kept despite the source rule:",
      int((verified & keep & ~(o.src.isin(GOOD_SOURCES) | o.official)).sum()))
o = o[keep].reset_index(drop=True)

# ---------------------------------------------------------------- duplicate listings of one place
o["biz"] = o.off.map(lambda j: F.biz.iat[int(j)] if j == j else np.nan)
o["rank"] = o.official.astype(int) * 8 + o.in21.astype(int) * 4 + o.src.isin(GOOD_SOURCES).astype(int) * 2 + o.confidence.fillna(0)
o = o.sort_values("rank", ascending=False).reset_index(drop=True)
cell, drop = {}, set()
for i, r in o.iterrows():
    key = (round(r.lat / 0.001), round(r.lon / 0.0013))
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for j in cell.get((key[0] + dy, key[1] + dx), []):
                d_ = math.hypot((o.lat.iat[j] - r.lat) * 111000, (o.lon.iat[j] - r.lon) * 85000)
                same_biz = r.biz == r.biz and r.biz == o.biz.iat[j] and name_sim(r.k, o.k.iat[j]) >= 80
                if same_biz or (d_ < 80 and (r.k == o.k.iat[j] or (fuzz.token_set_ratio(r.k, o.k.iat[j]) >= 92 and r.st & o.st.iat[j]))) or (
                        d_ < 150 and isinstance(r.brand_n, str) and r.brand_n == o.brand_n.iat[j]):
                    drop.add(i); break
            if i in drop: break
        if i in drop: break
    if i not in drop:
        cell.setdefault(key, []).append(i)
o = o.drop(index=list(drop)).reset_index(drop=True)
akey = [(b if isinstance(b, str) else k, n, c) if n and isinstance(c, str) else None for b, k, n, c in zip(o.brand_n, o.k, o.num, o.city)]
seen, dup = set(), []
for a in akey:   # o is sorted best-first, so the better-sourced copy survives
    dup.append(a is not None and a in seen)
    if a is not None:
        seen.add(a)
has_addr = o.num.notna()
for b, grp in o[o.brand_n.notna()].groupby("brand_n"):
    with_a, without = grp[has_addr[grp.index]], grp[~has_addr[grp.index]]
    for i, r in without.iterrows():
        if len(with_a) and (np.hypot((with_a.lat - r.lat) * 111, (with_a.lon - r.lon) * 85) < 1.5).any():
            dup[i] = True
o = o[~np.array(dup)].reset_index(drop=True)
near_dup = set()
for (k, c), grp in o[o.brand_n.isna() & o.k.fillna("").str.len().ge(4) & o.city.notna()].groupby(["k", "city"]):
    if len(grp) < 2 or not (_stems(k) - GENERIC):
        continue
    idx = list(grp.index)   # already best-first
    for a in range(len(idx)):
        for b in range(a + 1, len(idx)):
            if idx[b] in near_dup or idx[a] in near_dup:
                continue
            if math.hypot((o.lat[idx[a]] - o.lat[idx[b]]) * 111000, (o.lon[idx[a]] - o.lon[idx[b]]) * 85000) < 500 and not (o.official[idx[a]] and o.official[idx[b]]):
                near_dup.add(idx[b])
    good = grp[grp.in21 | grp.official]
    for i in grp.index[~(grp.in21 | grp.official)]:
        if i not in near_dup and len(good) and (np.hypot((good.lat - o.lat[i]) * 111, (good.lon - o.lon[i]) * 85) < 1.5).any() and i not in good.index:
            near_dup.add(i)
o = o.drop(index=list(near_dup)).reset_index(drop=True)
print("after merging duplicate listings:", len(o), "(dropped", len(drop) + sum(dup) + len(near_dup), ")")
confirmed = ((o.src == "meta") & (o.confidence.fillna(0) >= 0.95)) if APP else o.in21
o["tier"] = np.where(o.official, "official", np.where(confirmed, "both", "listing"))

# ---------------------------------------------------------------- licensed places the map listings don't have
# Added from the official lists (rules below).
FOODWORD = re.compile(r"\b(?:RESTAURANT|CAFE|CAFFE|GRILL|GRILLE|KITCHEN|PIZZA|PIZZERIA|TAQUERIA|TACOS?|BURRITOS?|BURGERS?|DINER|BISTRO|EATERY|"
                      r"BBQ|BARBECUE|SUSHI|RAMEN|PHO|NOODLES?|DELI|BAKERY|DONUTS?|COFFEE|ESPRESSO|TEA|BOBA|CREPES?|WINGS|CHICKEN|STEAK\w*|"
                      r"SEAFOOD|THAI|CHINESE|MEXICAN|ITALIAN|INDIAN|KOREAN|VIETNAMESE|JAPANESE|GREEK|MEDITERRANEAN|ETHIOPIAN|CANTINA|"
                      r"TAVERN|PUB|BAR|SALOON|LOUNGE|BREWING|BREWERY|TAPROOM|TAPHOUSE|BEER|WINE|COCKTAILS?|SPEAKEASY|CREAMERY|ICE CREAM|"
                      r"GELATO|BAGELS?|SANDWICH\w*|SUBS|POKE|DUMPLINGS?|HOT ?POT|BRUNCH|BREAKFAST|PANCAKE\w*|WAFFLES?|BOWLS?|SALADS?|"
                      r"SMOOTHIES?|JUICE|EMPANADAS?|TAMALES?|PUPUSA\w*|AREPAS?|SHAWARMA|FALAFEL|GYROS?|KABOBS?|KEBABS?|CURRY|DOGS?)\b")
# Texas: a TABC on-premises license (a Food and Beverage Certificate makes it a restaurant), an Arlington establishment inspected as a
# restaurant or bar, or an Austin / El Paso inspected establishment whose name says it's a place to eat (those lists also cover
# groceries, convenience stores and kiosks, and don't say which).
foodname_f = F["name"].fillna("").str.upper().map(lambda n: bool(FOODWORD.search(norm_name(n) or "")))
lic_food = (F.kind.isin(["restaurant", "bar", "brewery"]) & (F.jur == "liq")) \
    | ((F.jur == "arl") & F.kind.isin(["restaurant", "bar"])) \
    | (F.jur.isin(["aus", "elp", "arl"]) & F.kind.isin(["food", "restaurant", "bar"]) & foodname_f)
found = set(o.biz.dropna())
eligible = set(F.biz[lic_food])
add = F[F.biz.isin(eligible) & ~F.biz.isin(found) & F.lat.notna()].copy()
add["pri"] = add.jur.map({"aus": 0, "elp": 0, "arl": 0, "liq": 1}) * 10 + add.kind.map({"restaurant": 0, "bar": 1, "brewery": 2, "food": 3}).fillna(5)
add = add.sort_values("pri").drop_duplicates("biz")
print("licensed restaurants/bars not in the map listings:", len(add), add.jur.value_counts().to_dict())
rows = []
for _, f in add.iterrows():
    rows.append({"id": f.lic, "name": f["name"], "street": f.addr, "city": canon_city(f.city), "zip": f.zip, "lat": f.lat, "lon": f.lon,
                 "cat": "bar" if f.kind in ("bar", "brewery") else "restaurant", "tax": None, "confidence": np.nan, "brand": None, "src": "official",
                 "official": True, "off": f.name, "biz": f.biz, "tier": "official", "in21": False, "closed21": False, "dom": None,
                 "county": f.county, "n_web": 0})
A = pd.DataFrame(rows)


def clean_official(n):
    n = re.split(r"\s*;\s*", n if isinstance(n, str) else "")[0]
    n = re.sub(r"^(.+?),?\s+THE$", r"THE \1", n, flags=re.I)   # license style "MIGHTY BURGER, THE", before the INC/LLC strip
    n = re.sub(r"(?i)^.*?\bd\s*/?\s*b\s*/?\s*a\b\.?:?\s+(?=\S)", "", n)   # "XYZ LLC DBA Metropolis Coffee"
    n = re.sub(r"\s*\((?:MOBILE|MOBILE UNIT|COMMISSARY|CATERING|CP|INSIDE [^)]*)\)\s*$", "", n, flags=re.I)
    n = re.sub(r"\s*#\s*\d+\w*.*$|\s*\(#?[A-Z]?\d+\)|\s+\d{3,}\s*$", "", n or "") if not re.fullmatch(r"(?i)\s*the\s+\d{3,}\s*", n or "") else n
    n = re.sub(r",?\s+(?:INC|LLC|L\.L\.C|CORP|CORPORATION|LTD)\.?\s*$", "", n, flags=re.I)
    n = re.sub(r"^(?:THE\s+)?(?:CITY|TOWN|COUNTY) OF\s+.*$", "", n, flags=re.I) or n
    n = re.split(r"\s*/\s*", n)[0] if len(n) > 34 and "/" in n else n
    n = n.strip(" -,&/")
    n = re.sub(r"^(.+?),?\s+THE$", r"THE \1", n, flags=re.I)   # license style "MIGHTY BURGER, THE"
    return nice(n) if n.isupper() or n.islower() else n


# a record placed more than 30 km from the other places in its own town is a wrong geocode, not a restaurant out there
tmed = o.groupby("city")[["lat", "lon"]].median(); tsize = o.groupby("city").size()
far_a = [isinstance(c, str) and tsize.get(c, 0) >= 5 and math.hypot((la - tmed.lat[c]) * 111, (lo - tmed.lon[c]) * 85) > 30
         for c, la, lo in zip(A.city, A.lat, A.lon)]
print("license rows far from their own town (dropped as bad geocodes):", int(sum(far_a)))
A = A[~np.array(far_a, dtype=bool)].reset_index(drop=True)
A["name"] = A.name.map(clean_official)
A = A[A.name.fillna("").str.len() > 0].reset_index(drop=True)
# a license whose only name is the company's ("DHWW Investments") doesn't say what the place is called
a_ent = pd.Series([bool(ENTITY.search(n)) and (not FOODISH.search(n) or bool(ENTITY_END.search(n))) for n in A.name], index=A.index)
print("license rows named only for a company, dropped:", int(a_ent.sum()), A.name[a_ent].tolist()[:12])
A = A[~a_ent].reset_index(drop=True)
A["k"] = A.name.map(norm_name)
A["st"] = A.k.map(lambda k: _stems(k) - GENERIC if k else set())
A["num"] = A.street.map(lambda a: (re.match(r"\s*(\d+)", a or "") or [None, None])[1])
A["brand_n"] = A.k.map(brand_of)

# Google 2021 listings for the added rows (web only)
taken = set(o.gi.dropna().astype(int))
grid = {}
for i, (la, lo) in enumerate(zip(G.latitude, G.longitude)):
    grid.setdefault((round(la / 0.0015), round(lo / 0.002)), []).append(i)
pairs = []
for ai, r in ([] if APP else A.iterrows()):
    if not r.k:
        continue
    gy, gx = round(r.lat / 0.0015), round(r.lon / 0.002)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for gi in grid.get((gy + dy, gx + dx), []):
                if gi in taken or not G.k.iat[gi] or G.closed21.iat[gi]:
                    continue
                dist = math.hypot((G.latitude.iat[gi] - r.lat) * 111000, (G.longitude.iat[gi] - r.lon) * 85000)
                if dist > 200:
                    continue
                s = name_sim(r.k, G.k.iat[gi])
                same_num = r.num is not None and G.num.iat[gi] == r.num
                if same_num and r.st & G.st.iat[gi]:
                    s = max(s, 80)
                if s < 95 and not r.st & G.st2.iat[gi]:
                    continue
                if (s >= 88 and dist < 150) or (s >= 75 and same_num):
                    pairs.append((s + (10 if same_num else 0) - dist / 25, ai, gi))
A["gi"] = np.nan
ta, tg = set(), set()
for sc, ai, gi in sorted(pairs, key=lambda t: -t[0]):
    if ai in ta or gi in tg:
        continue
    ta.add(ai); tg.add(gi); A.at[ai, "gi"] = gi
A["in21"] = A.gi.notna()
print("added rows matched to Google 2021:", int(A.in21.sum()))
# a licensed place the matching missed can sit on top of its own map listing under a slightly different name: merge it into that listing,
# unless the listing already matched a record of its own
kgrid = {}
for j, (la, lo) in enumerate(zip(o.lat, o.lon)):
    kgrid.setdefault((round(la / 0.0015), round(lo / 0.002)), []).append(j)
merge, same_lic = {}, set()
for ai, r in A.iterrows():
    if not r.k:
        continue
    best, bs = None, -1
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for j in kgrid.get((round(r.lat / 0.0015) + dy, round(r.lon / 0.002) + dx), []):
                if j in merge.values():
                    continue
                dist = math.hypot((o.lat.iat[j] - r.lat) * 111000, (o.lon.iat[j] - r.lon) * 85000)
                s = name_sim(r.k, o.k.iat[j]) if o.k.iat[j] else 0
                if o.official.iat[j]:
                    if dist <= 80 and s >= 95:
                        same_lic.add(ai)
                    continue
                shared = bool(r.st & o.st.iat[j]) or _close_words(r.st, o.st.iat[j])
                if (dist <= 60 and (s >= 88 or (shared and s >= 60))) or (dist <= 25 and s >= 75):
                    if s - dist / 10 > bs:
                        best, bs = j, s - dist / 10
    if best is not None:
        merge[ai] = best
for ai, j in merge.items():
    for c in ("official", "off", "biz", "tier"):
        o.at[o.index[j], c] = A.at[ai, c]
A = A.drop(index=list(set(merge) | same_lic)).reset_index(drop=True)
print("license rows merged into a map listing on the second pass:", len(merge), "| same business's second record:", len(same_lic - set(merge)),
      "| license rows added:", len(A))
akey = [(n, st) for n, st in zip(A.num, A.street.map(lambda a: street_key(a)[1]))]
shared_n = collections.Counter(akey)
A["lic_shared"] = [shared_n[k] >= 5 and not g for k, g in zip(akey, A.in21)]
o = pd.concat([o, A], ignore_index=True)
o["city"] = o.city.map(canon_city)
main = o.city.dropna().groupby(o.city.dropna().map(town_key)).agg(lambda x: x.mode().iat[0])
o["city"] = o.city.map(lambda c: main.get(town_key(c), c) if isinstance(c, str) else c)

# ---------------------------------------------------------------- hand-checked places the map listings don't have as a place to eat
# (a hotel dining room, an on-mountain lodge, a saloon filed as a hotel): placed on Overture's own listing of the business (any
# category), else an address point, else the US Census geocoder's match (geocode_census.py fills the cache). The web build also
# attaches the place's Google 2021 listing when Google filed it as a restaurant (a hotel's listing lends no ratings).
import gzip, duckdb
_m = curated_matcher(o)
missing = [c for c in CUR if c.get("open") is not False and not c.get("chain") and _m(c) is None]
OV = duckdb.connect().execute(f"""SELECT name, street, city, zip, lat, lon, cat, tax FROM '{TX}/overture_tx_bbox.parquet'
                                  WHERE region = 'TX' AND name IS NOT NULL""").df()
OV["k"] = OV.name.map(norm_name); OV["town"] = OV.city.map(lambda c: (canon_city(c) or "").lower())
ov_by_town = {t: g for t, g in OV.groupby("town")}
AP = pd.read_pickle(f"{TX}/ap_index.pkl")
GEOCACHE = json.load(open(f"{TX}/geocode_census.json")) if os.path.exists(f"{TX}/geocode_census.json") else {}
GEO_TODO = []
if not APP:
    FULL = []
    with gzip.open(f"{DATA}/ucsd/meta-Texas.json.gz", "rt") as f:
        for line in f:
            d = json.loads(line)
            if d.get("latitude") and not (d.get("state") or "").startswith("Permanently closed"):
                FULL.append(d)
    fk = [norm_name(d["name"]) for d in FULL]
HOSTCAT = re.compile(r"hotel|inn\b|resort|lodge|motel|bowling|museum|store|shop|market|farm|grocery|bed & breakfast|campground|marina|winery|ski", re.I)
added = []
for c in missing:
    keys = {norm_name(m) for m in (c.get("match_names") or [])} | {norm_name(c["name"])}
    keys.discard("")
    if not keys:
        continue
    nums = street_nums(c.get("address") or "")
    town = (canon_city(c.get("city") or "") or "").lower()
    spot = None
    g = ov_by_town.get(town)
    if g is not None:
        sims = [max(fuzz.ratio(m, k) for m in keys) if isinstance(k, str) and k else 0 for k in g.k]
        j = int(np.argmax(sims)) if len(sims) else -1
        if j >= 0 and sims[j] >= 88:
            h = g.iloc[j]
            spot = (h["lat"], h["lon"], (h["zip"] if isinstance(h["zip"], str) else "")[:5] or c.get("zip"))
    if spot is None:
        _, sk = street_key(c.get("address") or "")
        for n in nums:
            cand = AP[(AP.num == n) & (AP.key == sk)]
            if len(cand):
                same = cand[(cand.town == town) | (cand.ptown == town) | (cand.zip == (c.get("zip") or ""))]
                cand = same if len(same) else cand
                if (cand.lat.max() - cand.lat.min()) < 0.01:
                    spot = (cand.lat.median(), cand.lon.median(), cand.zip.iloc[0] or c.get("zip")); break
    if spot is None:
        a, t = (c.get("address") or "").strip(), (c.get("city") or "").strip()
        gq = f"{a}, {t}, TX {c.get('zip') or ''}".strip() if re.match(r"\s*\d", a) and t else None
        hit = GEOCACHE.get(gq) if gq else None
        if hit:
            spot = (hit["lat"], hit["lon"], c.get("zip"))
        else:
            if gq:
                GEO_TODO.append(gq)
            continue
    la, lo, zp = spot
    gi_ = np.nan
    if not APP:
        best, bs = None, 0
        for i, k in enumerate(fk):
            if not k or not any(fuzz.ratio(m, k) >= 88 or (len(m.split()) >= 2 and fuzz.token_set_ratio(m, k) >= 95) for m in keys):
                continue
            addr = FULL[i].get("address") or ""
            hit_num = any(re.search(rf"\b{n}\b", addr) for n in nums)
            hit_town = bool(town) and town in addr.lower()
            if not (hit_num or hit_town):
                continue
            sc = 2 * hit_num + hit_town + math.log1p(FULL[i].get("num_of_reviews") or 0) / 10
            if sc > bs:
                best, bs = i, sc
        if best is not None:
            d = FULL[best]
            cats = d.get("category") or []
            host = bool(cats) and bool(HOSTCAT.search(cats[0]))
            G.loc[len(G)] = {**{c_: None for c_ in G.columns}, "name": d["name"], "address": d.get("address"), "gmap_id": d.get("gmap_id"),
                             "latitude": d["latitude"], "longitude": d["longitude"], "category": [] if host else cats,
                             "avg_rating": None if host else d.get("avg_rating"), "num_of_reviews": None if host else d.get("num_of_reviews"),
                             "price": None if host else d.get("price"), "state": d.get("state"), "description": d.get("description"),
                             "k": norm_name(d["name"]), "st": set(), "closed21": False}
            gi_ = len(G) - 1
    added.append({"id": "research-" + c["name"], "name": c["name"], "street": c.get("address"), "city": canon_city(c.get("city")), "zip": zp,
                  "lat": la, "lon": lo, "cat": "restaurant", "tax": None, "confidence": np.nan, "brand": None, "src": "research",
                  "official": False, "off": np.nan, "biz": np.nan, "tier": "both", "in21": gi_ == gi_, "closed21": False, "dom": None,
                  "gi": gi_, "k": norm_name(c["name"]), "st": _stems(norm_name(c["name"])) - GENERIC,
                  "num": (re.match(r"\s*(\d+)", c.get("address") or "") or [None, None])[1], "brand_n": None, "web": c.get("website"), "n_web": 1})
if added:
    o = pd.concat([o, pd.DataFrame(added)], ignore_index=True)
json.dump(sorted(set(GEO_TODO)), open(f"{DATA}/research/geocode_todo.json", "w"), indent=1)
print("hand-verified places added (not in the map listings as a place to eat):", len(added), "of", len(missing),
      "| waiting for the Census geocoder:", len(set(GEO_TODO)), "| not placed:",
      [c["name"] for c in missing if not any(a["name"] == c["name"] for a in added)][:20])

# counties for every row; towns that share a name in far-apart counties are two towns
CTY = {n: prep(shape(g).buffer(0.002)) for n, g in json.load(open(f"{TX}/tx_counties_detail.geojson")).items()}
miss_c = o.county.isna() & o.lat.notna()
o.loc[miss_c, "county"] = [next((n for n, p in CTY.items() if p.contains(Point(lo, la))), None) for la, lo in zip(o.lat[miss_c], o.lon[miss_c])]
split = 0
for c, grp in o[o.city.notna() & o.county.notna()].groupby("city"):
    if grp.county.nunique() < 2:
        continue
    med = grp.groupby("county")[["lat", "lon"]].median()
    big = grp.county.value_counts().index[0]
    far = {n for n, m in med.iterrows() if math.hypot((m.lat - med.lat[big]) * 111, (m.lon - med.lon[big]) * 85) > 40}
    if far:   # only the far-away county's places get the county label ("Fort Morgan" stays Fort Morgan)
        sel = grp.index[grp.county.isin(far)]
        o.loc[sel, "city"] = [f"{c} ({n.replace(' County', '')} Co.)" for n in grp.county[grp.county.isin(far)]]
        split += 1
print("same-name towns split by county:", split)
res_rows = o.index[o.src.eq("research") & o.off.isna()]
n_res_off = 0
for cty, sel in o.loc[res_rows].groupby("county").groups.items():
    R = F[F.county == cty]
    if not len(R):
        continue
    L = o.loc[sel].reset_index(drop=True)
    for i_, j_ in official_match(L, R.reset_index(drop=True), town_words=frozenset(NOISE_W)).items():
        ix = sel[i_]
        o.at[ix, "off"] = R.index[j_]; o.at[ix, "official"] = True; o.at[ix, "biz"] = F.biz.iat[int(R.index[j_])]; o.at[ix, "tier"] = "official"
        n_res_off += 1
print("hand-checked places added from research, matched to their official records:", n_res_off, "of", len(res_rows))

# ---------------------------------------------------------------- fields
gi = [int(v) if v == v and v is not None else None for v in o.gi]
o["rating"] = [G.avg_rating.iat[i] if i is not None else np.nan for i in gi]
o["reviews"] = [G.num_of_reviews.iat[i] if i is not None else np.nan for i in gi]
o["gprice"] = [len(G.price.iat[i]) if i is not None and isinstance(G.price.iat[i], str) else np.nan for i in gi]
o["gcats"] = ["|".join(G.category.iat[i] or []) if i is not None else "" for i in gi]
o["gmap_id"] = [G.gmap_id.iat[i] if i is not None else None for i in gi]
o["name_out"] = [b if isinstance(b, str) and fuzz.ratio(norm_name(n), norm_name(b)) >= 88 else nice(n) if n.isupper() or n.islower() else n
                 for n, b in zip(o.name, o.brand_n)]
from common import CUISINE_RULES


def pick_cuisine(tax, k, gcats, raw):
    for c, pat in CUISINE_RULES[:-1]:          # a specific word in the name wins ("Mickey-Lu Bar-B-Q", "Paul's Pelmeni")
        if pat.search(k or ""):
            return c
    if isinstance(tax, str) and tax in TAX_CUISINE:
        return TAX_CUISINE[tax]
    return cuisine(k, gcats, raw)              # "bar"-type names, then Google's categories


o["cuisine"] = [pick_cuisine(t, k, gc, n) for t, k, gc, n in zip(o.tax, o.k, o.gcats, o.name)]
first_cat = o.gcats.str.split("|").str[0].fillna("")
cafe_tax = o.tax.isin(["cafe", "coffee_shop"]) & o.cuisine.eq("Coffee & Café") & first_cat.ne("") & ~first_cat.str.contains(r"Coffee|Cafe|Café|Espresso|Tea|Bakery|Donut|Dessert|Ice cream|Juice|Breakfast")
o.loc[cafe_tax, "cuisine"] = [cuisine(k, g, "") for k, g in zip(o.loc[cafe_tax, "k"], o.loc[cafe_tax, "gcats"])]
o.loc[o.cat.isin(["bar", "brewery"]) & (o.cuisine == "American & Other"), "cuisine"] = "Bar & Pub"
o.loc[o.cat.isin(["coffee_shop", "cafe"]) & (o.cuisine == "American & Other"), "cuisine"] = "Coffee & Café"
o.loc[o.city.fillna("") == "", "city"] = None


# brand sanity: a brand rule that matched a name prefix must agree with the listing's website, Overture's brand feed, or its kind of food
def mode(x):
    return x.mode().iat[0]


bdom = {}
for b, grp in o[o.brand_n.notna()].groupby("brand_n"):
    d = grp.dom.dropna()
    if len(d) >= 3:
        top, n = collections.Counter(d).most_common(1)[0]
        if n >= 0.5 * len(d):
            bdom[b] = top
FAMILY = {"Chicken & Wings": "quick", "Burgers": "quick", "Hot Dogs & Brats": "quick", "Sandwiches & Deli": "cafe", "Pizza": "pizza",
          "Mexican": "mex", "Latin & Caribbean": "mex", "Coffee & Café": "cafe", "Bakery & Sweets": "cafe", "Frozen Custard": "cafe",
          "Breakfast & Diner": "cafe", "Healthy & Vegan": "cafe", "Steakhouse": "sitdown", "Supper Club": "sitdown", "Seafood": "sea",
          "Bar & Pub": "bar", "Italian": "italian", "Chinese": "asian", "Japanese & Sushi": "asian", "Thai": "asian", "Korean": "asian",
          "Vietnamese": "asian", "South Asian": "sasian", "Mediterranean & Middle Eastern": "med", "German & European": "sitdown", "BBQ": "bbq",
          "Soul & Southern": "soul", "African": "african"}
brand_cuisine = o[o.brand_n.notna()].groupby("brand_n").cuisine.agg(mode)


def core(k):
    w = [x for x in k.split() if x not in GENERIC and x not in ("RESTAURANT", "RESTAURANTS", "CAFE", "STORE")]
    return " ".join(w) or k


def brand_ok(b, dm, cu, tax, obrand, name, src):
    if not isinstance(b, str):
        return None
    dm = dm if isinstance(dm, str) else None
    nk, bk = norm_name(name), norm_name(b)
    if src not in ("AllThePlaces", "DAC") and brand_of(nk) != b:
        return None                                 # only Overture's label says so ("Golden Chicken" labeled Golden Chick)
    ob = norm_name(obrand) if isinstance(obrand, str) else ""
    brand_feed = src in ("AllThePlaces", "DAC")
    label = bool(ob) and fuzz.token_set_ratio(ob, bk) >= 80
    related = brand_feed or fuzz.partial_ratio(bk, nk) >= 60 or (label and fuzz.partial_ratio(ob, nk) >= 60)
    if not related:
        return None
    squashed = re.sub(r"[^a-z]", "", b.lower())
    own_site = dm and (bdom.get(b) == dm or dm.split(".")[0].replace("-", "") in (squashed, squashed + "s"))
    exact = fuzz.ratio(core(nk), core(bk)) >= 90 or (label and fuzz.ratio(core(nk), core(ob)) >= 90) \
        or (len(bk) >= 6 and (nk == bk or nk.startswith(bk + " ")))
    if exact or own_site or (label and brand_feed):
        return b
    if dm and b in bdom and src != "BrightQuery":
        return None
    want = brand_cuisine.get(b)
    if isinstance(tax, str) and tax in TAX_CUISINE and want and FAMILY.get(cu) and FAMILY.get(want) and FAMILY[cu] != FAMILY[want]:
        return None
    return b


old_brand = o.brand_n.copy()
o["brand_n"] = [brand_ok(b, dm, cu, t, ob, n, sr) for b, dm, cu, t, ob, n, sr in zip(o.brand_n, o.dom, o.cuisine, o.tax, o.brand, o.name, o.src)]
rej = o[old_brand.notna() & o.brand_n.isna()]
print("brand matches rejected:", len(rej), collections.Counter(old_brand[rej.index]).most_common(10))
o.loc[o.brand_n.notna(), "name_out"] = [b if fuzz.ratio(norm_name(n), norm_name(b)) >= 80 or len(norm_name(n)) <= len(norm_name(b)) + 2 else n
                                        for n, b in zip(o.loc[o.brand_n.notna(), "name_out"], o.loc[o.brand_n.notna(), "brand_n"])]


def chain_mode(x):
    real = x[x != "American & Other"]
    return (real if len(real) else x).mode().iat[0]


CHAIN_CUISINE = {"Culver's": "Burgers", "Freddy's": "Burgers", "Noodles & Company": "Healthy & Vegan", "Pizza Ranch": "Pizza",
                 "Perkins": "Breakfast & Diner", "Village Inn": "Breakfast & Diner", "Snooze": "Breakfast & Diner", "Lucile's": "Breakfast & Diner",
                 "Dairy Queen": "Bakery & Sweets", "Cold Stone Creamery": "Bakery & Sweets", "Baskin-Robbins": "Bakery & Sweets", "Sweet Cow": "Bakery & Sweets",
                 "Einstein Bros. Bagels": "Bakery & Sweets", "Panera Bread": "Sandwiches & Deli", "Caribou Coffee": "Coffee & Café",
                 "Taco John's": "Mexican", "Illegal Pete's": "Mexican", "Santiago's": "Mexican", "Hardee's": "Burgers", "Carl's Jr.": "Burgers",
                 "Good Times": "Burgers", "Smashburger": "Burgers", "Bad Daddy's Burger Bar": "Burgers", "Larkburger": "Burgers",
                 "HuHot Mongolian Grill": "Chinese", "Tokyo Joe's": "Japanese & Sushi", "Famous Dave's": "BBQ", "Dickey's Barbecue Pit": "BBQ",
                 "Brothers BBQ": "BBQ", "Texas Roadhouse": "Steakhouse", "Tropical Smoothie Cafe": "Healthy & Vegan", "Jamba": "Healthy & Vegan",
                 "Smoothie King": "Healthy & Vegan", "Mad Greens": "Healthy & Vegan", "Modern Market": "Healthy & Vegan",
                 "Garbanzo": "Mediterranean & Middle Eastern", "Snarf's": "Sandwiches & Deli", "Cheba Hut": "Sandwiches & Deli", "Smiling Moose": "Sandwiches & Deli",
                 "Starbucks": "Coffee & Café", "Dunkin'": "Coffee & Café", "Dutch Bros": "Coffee & Café", "Ziggi's Coffee": "Coffee & Café",
                 "Cracker Barrel": "American & Other", "Golden Corral": "American & Other", "Rock Bottom": "Bar & Pub", "Old Chicago": "Pizza",
                 "Beau Jo's": "Pizza", "Anthony's Pizza & Pasta": "Pizza", "Blackjack Pizza": "Pizza", "Abo's Pizza": "Pizza",
                 "Whataburger": "Burgers", "Shipley Do-Nuts": "Bakery & Sweets", "Kolache Factory": "Bakery & Sweets", "Rudy's": "BBQ",
                 "Bill Miller Bar-B-Q": "BBQ", "Pappas Bar-B-Q": "BBQ", "Pappadeaux": "Seafood", "Pappasito's": "Mexican",
                 "Pappas Bros. Steakhouse": "Steakhouse", "Saltgrass Steak House": "Steakhouse", "Taco Cabana": "Mexican",
                 "Taco Palenque": "Mexican", "Torchy's Tacos": "Mexican", "Velvet Taco": "Mexican", "Fuzzy's Taco Shop": "Mexican",
                 "Chuy's": "Mexican", "Mi Cocina": "Mexican", "El Chico": "Mexican", "Lupe Tortilla": "Mexican", "Rosa's Café": "Mexican",
                 "Tumbleweed TexMex": "Mexican", "Tacodeli": "Mexican", "Tacos Tu Madre": "Mexican", "Taqueria Arandas": "Mexican",
                 "Freebirds": "Mexican", "Pluckers": "Chicken & Wings", "Babe's Chicken Dinner House": "Soul & Southern",
                 "Pollo Regio": "Chicken & Wings", "Layne's Chicken Fingers": "Chicken & Wings", "Golden Chick": "Chicken & Wings",
                 "Bush's Chicken": "Chicken & Wings", "Black Walnut Cafe": "Breakfast & Diner", "Kerbey Lane": "Breakfast & Diner",
                 "P. Terry's": "Burgers", "Hopdoddy": "Burgers", "Rodeo Goat": "Burgers", "Schlotzsky's": "Sandwiches & Deli",
                 "Jason's Deli": "Sandwiches & Deli", "Cotton Patch Cafe": "Soul & Southern", "James Coney Island": "Hot Dogs & Sausages",
                 "Cane Rosso": "Pizza", "Grimaldi's": "Pizza", "Mama's Pizza": "Pizza", "Dodie's Cajun Diner": "Seafood", "Pok-e-Jo's": "BBQ"}
allc = o.loc[o.brand_n.notna(), ["brand_n", "cuisine"]]
all_brand_cuisine = allc.groupby("brand_n").cuisine.agg(chain_mode)
o.loc[o.brand_n.notna(), "cuisine"] = o.loc[o.brand_n.notna(), "brand_n"].map(lambda b: CHAIN_CUISINE.get(b) or all_brand_cuisine.get(b))

# price: Google price level, else the chain's usual level, else the cuisine's usual level (both from Texas' own Google data)
o["price"] = o.gprice
o["price_est"] = o.price.isna().astype(int)
bp = o[o.gprice.notna()].groupby("brand_n").gprice.median()
o.loc[o.price.isna() & o.brand_n.notna(), "price"] = o.brand_n.map(bp)
cp = o[o.gprice.notna()].groupby("cuisine").gprice.median()
o.loc[o.price.isna(), "price"] = o.cuisine.map(cp)
o["price"] = o.price.fillna(2).round().clip(1, 4).astype(int)

# chain size statewide. Unbranded same-name places count as one chain only when they share a website ("Corner Tap" x5 isn't a chain)
bc = o.brand_n.value_counts()
o["chain_n"] = o.brand_n.map(lambda b: int(bc.get(b, 0)) if isinstance(b, str) else 1)
STORE_DOMS_ALL = {"caseys.com", "kingsoopers.com", "citymarket.com", "safeway.com", "albertsons.com", "walmart.com", "samsclub.com", "target.com",
                  "costco.com", "sprouts.com", "naturalgrocers.com", "wholefoodsmarket.com", "kumandgo.com", "maverik.com", "loves.com", "pilotflyingj.com",
                  "7-eleven.com", "circlek.com", "conoco.com", "sinclairoil.com", "phillips66.com", "shell.us", "safeway.com",
                  "heb.com", "kroger.com", "tomthumb.com", "randalls.com", "fiestamart.com", "allsups.com", "stripesstores.com", "buc-ees.com"}
first_stem = o.k.fillna("").map(lambda k: next((w for w in k.split() if w not in GENERIC and len(w) >= 3), None))
grpkey = pd.Series([(d, s) if isinstance(d, str) and isinstance(s, str) and not isinstance(b, str) and d not in STORE_DOMS_ALL else None for d, s, b in zip(o.dom, first_stem, o.brand_n)], index=o.index)
gsize = grpkey.dropna().value_counts()
member = [g is not None and gsize.get(g, 0) >= 2 for g in grpkey]
o.loc[member, "chain_n"] = [int(gsize[g]) for g, m in zip(grpkey, member) if m]
o["ckey"] = grpkey.map(lambda g: "|".join(g) if g else None)
chain_dom = set(o.ckey[member])
grp_cuisine = o[member].groupby("ckey").cuisine.agg(chain_mode)
o.loc[member, "cuisine"] = [grp_cuisine.get(k) for k in o.loc[member, "ckey"]]
sib = o.gprice.notna()
for key, sel in (("brand_n", o.brand_n.notna()), ("ckey", pd.Series(member, index=o.index))):
    med = o[sel & sib].groupby(key).gprice.median()
    fill = sel & (o.price_est == 1) & o[key].isin(med.index)
    o.loc[fill, "price"] = o.loc[fill, key].map(med).round().clip(1, 4).astype(int)
print("name-based chains:", len(chain_dom), "|", int(sum(member)), "locations")

o["bar"] = o.cat.isin(["bar", "brewery"]) | (o.cuisine == "Bar & Pub")
o["name_out"] = o.name_out.map(lambda n: re.sub(r"\b(?:Tcby|Ihop|Bj's|Bjs)\b", lambda m: {"tcby": "TCBY", "ihop": "IHOP"}.get(m.group(0).lower(), "BJ's"), n))
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]+")
CJK = r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]"
TAILWORDS = re.compile(r"^(?:best|award|voted|magazine|official|order|delivery|takeout|take out|catering|now open|open|to go|curbside|franchise|inside .*|"
                       r"(?:(?:ice cream|chocolates?|fudge|coffee|cafe|café|restaurant|bar|grill|pizza|shawarma|hookah lounge|juicy seafood|latin tavern|"
                       r"bakery|deli|sandwiches|tacos|gifts?|shopping|treats|sweets|full bar|food|game room|drinks|spirits|live music|events|patio|"
                       r"lodging|rooms|resort|motel|campground|cocktails|beer|wine|burgers|wings|craft beer|sports bar|and|&|,|-|\s)+))$", re.I)


def tidy(n, brand):
    """Emoji and non-Latin duplicates of an English name, LLC in the middle, marketing tails, notes in parentheses."""
    n = unicodedata.normalize("NFKC", n)   # "𝗖𝗼𝘄𝗹𝗶𝗰𝗸𝘀" (math bold letters) -> "Cowlicks"
    if re.search(r"[ÃÂâð][\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013-\u203a\u20ac\u2122]", n):
        for enc in ("cp1252", "latin-1"):   # UTF-8 read as Windows-1252 ("COLOMBIANAðŸ‡¨ðŸ‡´")
            try:
                n = n.encode(enc).decode("utf-8"); break
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
    n = re.sub(r"[®™©]", "", EMOJI.sub("", n))
    if re.search(r"[A-Za-z]{3,}", re.sub(CJK, "", n)):
        n = re.sub(r"\s*\([^()]*" + CJK + r"[^()]*\)", "", n)   # "Red Maple MKE (赤いカエデMKE)"
    latin = re.sub(CJK + "+", " ", n)
    if re.search(r"[A-Za-z]{3,}", latin) and re.search(CJK, n):
        n = re.sub(r"\(\s*\)", "", latin)
    m = re.match(r"^(.*?)[,\s]+(?:LLC|Inc)\.?\s*-{1,2}\s*(.+)$", n, flags=re.I)
    if m:
        n = m.group(2) if len(m.group(2).split()) >= 2 and len(m.group(1).split()) <= 2 else m.group(1)
    n = re.sub(r"[,\s]+(?:LLC|L\.L\.C|LLP|L\.L\.P|Inc|Corp)\.?(?=\s|$|,)", "", n, flags=re.I)
    n = re.sub(r"\s*\([^()]*\)\s*$", "", n) if re.sub(r"\s*\([^()]*\)\s*$", "", n).strip() else n   # "(Official Page)", "(Seasonal ...)", "(To-Go)"
    if not re.search(r"\b(?:of|in|de|at)\s+(?:TX|Tex\.?|Texas)\s*$", n, flags=re.I):   # keep "Taste of Texas"
        n = re.sub(r",?\s+(?:TX|Tex\.?|Texas)\s*$", "", n)                                                 # "Joe's BBQ, TX"
    n = re.sub(r"^(.+?),?\s+the$", r"The \1", n, flags=re.I)                                                    # license style "KITCHEN, THE"
    parts = re.split(r"\s+[-–]{1,2}\s+|--", n)
    if len(parts) > 1:
        tail = " ".join(parts[1:])
        if TAILWORDS.match(tail.strip()) or re.search(r"\b(?:Best|Award|Magazine|Voted|20\d\d)\b", tail):
            n = parts[0]
    if isinstance(brand, str):
        n = re.sub(r"\s*#\s*\d+\s*$", "", n)
    n = re.sub(r"^\d{3,}\s*-\s*", "", n) or n                                      # "8487 - Nekter Juice Bar"
    n = re.sub(r"^[A-Z][a-z]+(?: [A-Z][a-z]+)?,\s*TX\s*-\s*", "", n) or n               # "Katy, TX - Fox's Pizza"
    n = re.sub(r"(?i)\s*,?\s*L ?td\.?$", "", n) or n                                   # "Caribou Club , L Td"
    n = re.sub(r"(?<=[a-z]{3})\.$", "", n)                                             # "Rosy Rings."
    n = re.sub(r"\s+", " ", n).strip(" -–,") or n
    n = re.sub(r"(?i)\s+(?:at|of|de|@|&|and)$", "", n) or n   # a name cut off at the source ("The Deli At")
    return nice(n) if n.isupper() and len(n) > 4 else n


o["name_out"] = [tidy(n, b) for n, b in zip(o.name_out, o.brand_n)]
# a chain location labeled with its town or mall ("Snooze Denver, Colorado - Union Station") shows the brand
o.loc[o.brand_n.notna(), "name_out"] = [b if norm_name(n).startswith(norm_name(b)) and len(norm_name(b)) >= 3 else n
                                        for n, b in zip(o.loc[o.brand_n.notna(), "name_out"], o.loc[o.brand_n.notna(), "brand_n"])]
o["spell"] = o.name_out.map(lambda n: re.sub(r"[^a-z0-9]", "", n.lower()))
o["name_out"] = o.groupby("spell").name_out.transform(lambda s: s.mode().iat[0] if len(s) > 1 else s.iat[0])
# names that aren't a business: a street address, "closed"/"retired", a town or "Village of X", a lone generic word, no Latin letters
towns_l = set(o.city.dropna().str.lower())
nm = o.name_out.fillna("")
junk = (nm.str.match(r"(?i)^\d+\s+(?:[NSEW]\.?\s+)?[\w.' ]+?\b(?:St|Street|Ave|Avenue|Dr|Drive|Rd|Road|Blvd|Ln|Lane|Way|Ct|Pl|Hwy|Pkwy|Trl)\b\.?(?:\s*#\s*\w+)?(?:\s*,.*|\s+[A-Z][a-z]+,\s*TX\b.*)?$")
        | nm.str.contains(r"(?i)(?:\bclosed|\bretired)\s*\)?\s*$") \
        | nm.str.contains(r"(?i)\bmua b[aá]n\b|to[aà]n qu[oố]c|\bcasino online\b|\bpayday\b|\bloans?\b|\bseo services?\b") \
        | nm.str.contains(r"(?i)\blocation closed\b|\bnow operated by\b|\bvisit our\b|\bpermanently closed\b|\btemporarily closed\b|\bhas moved\b|\bwe(?:'ve| have)? moved\b") | (nm.str.lower().str.strip().isin(towns_l) & o.brand_n.isna())
        | nm.str.match(r"(?i)^(?:village|city|town) of ") | nm.str.strip().str.lower().isin(["kitchen", "bar", "pub", "tavern", "grill", "deli", "pizza", "bakery", "coffee", "diner", "restaurant", "cafe", "café"])
        | ~nm.str.contains(r"[A-Za-z]"))
print("junk names dropped:", int(junk.sum()), nm[junk].head(12).tolist())
o = o[~junk].reset_index(drop=True)
# ---------------------------------------------------------------- not restaurants (hidden unless "include non-restaurants" is on)
# Checked on the cleaned display name, so a street in a store label ("Barriques University Ave") doesn't hide a café.
STORE = re.compile(r"^(?:CASEYS(?: GENERAL STORE)?|KING SOOPERS?|CITY MARKET|SAFEWAY|ALBERTSONS|SPROUTS(?: FARMERS MARKET)?|NATURAL GROCERS|"
                   r"WHOLE FOODS(?: MARKET)?|WALMART\b.*|COSTCO\b.*|TARGET|SAMS CLUB|ALDI|TRADER JOES|LOAF N JUG|KUM (?:AND )?GO|MAVERIK|"
                   r"CIRCLE K|CONOCO|SINCLAIR|SHELL|PHILLIPS 66|EXXON|CHEVRON|VALERO|CENEX|ALTA CONVENIENCE|WESTERN CONVENIENCE|"
                   r"DASHMART|7 ELEVEN|BIG O TIRES|H E B|HEB|H E B PLUS|KROGER|TOM THUMB|RANDALLS|FIESTA MART|EL RANCHO SUPERMERCADO|"
                   r"FOOD TOWN|BROOKSHIRE BROTHERS|BROOKSHIRES|UNITED SUPERMARKETS|MARKET STREET|ALLSUPS|STRIPES|TOOT N TOTUM|"
                   r"MURPHY USA|RACETRAC|QUIKTRIP|VALERO|BUC EES|CEFCO|TIME WISE|SPEC S|SPECS)$|\b(?:SAMS CLUB|BIMBO BAKERIES|BAKERY OUTLET|THRIFT STORE|HUNT BROTHERS|"
                   r"HOT STUFF (?:PIZZA|FOODS|KITCHEN)|KRISPY KRUNCHY|CHESTERS (?:FRIED )?CHICKEN|GAS STATION|"
                   r"TRAVEL (?:CENTER|PLAZA|STOP)|TRUCK STOP|TRUCKSTOP|PILOT FLYING J|FLYING J|LOVES TRAVEL|FARMERS FRIDGE|MRBEAST|MR BEAST|"
                   r"ITS JUST WINGS|WOW BAO|GHOST KITCHEN|VIRTUAL KITCHEN|LIQUORS? (?:STORE|MART|DEPOT|OUTLET|BARN|WAREHOUSE)|LIQUORS?$|"
                   r"WINE AND SPIRITS|AND SPIRITS$|GENTLEM[AE]NS CLUB|SHOWGIRLS|BABY DOLLS|PT S (?:SHOWCLUB|GOLD)|DIAMOND CABARET|RICKS CABARET|XTC CABARET|"
                   r"SPECS WINES|"
                   r"TRAMPOLINE|INDOOR PLAYGROUND|DISPENSARY|CANNABIS|MARIJUANA|NATIVE ROOTS|LIVWELL|LIGHTSHADE|"
                   r"MEAT MARKET|MEATS$|BUTCHER|JERKY|VENDING|COMMISSARY|FOOD PANTRY|FOOD BANK|"
                   r"WINE (?:MERCHANTS?|SHOP|STORE|DEPOT|OUTLET)|ROCKY MOUNTAIN CHOCOLATE|JELLY BELLY|LINDT)\b")
STORE_DOMS = {"caseys.com", "kingsoopers.com", "citymarket.com", "safeway.com", "albertsons.com", "walmart.com", "samsclub.com", "target.com",
              "costco.com", "sprouts.com", "naturalgrocers.com", "wholefoodsmarket.com", "kumandgo.com", "maverik.com", "loves.com",
              "pilotflyingj.com", "7-eleven.com", "circlek.com", "huntbrotherspizza.com", "hotstuffpizza.com", "krispykrunchy.com",
              "farmersfridge.com", "mrbeastburger.com", "rmcf.com", "heb.com", "kroger.com", "tomthumb.com",
              "randalls.com", "fiestamart.com", "allsups.com", "stripesstores.com", "buc-ees.com", "murphyusa.com", "racetrac.com", "quiktrip.com",
              "valero.com", "specsonline.com"}
REALFOOD = re.compile(r"\b(?:RESTAURANT|GRILL|BAR|PUB|TAVERN|PIZZA|CAFE|KITCHEN|STEAK|BISTRO|DINER|BREWING|BREWERY|TAP|SALOON|"
                      r"TAPROOM|LOUNGE|INN|EATERY|BURGERS?|BBQ|TACOS?|DRIVE IN|DELI|COFFEE|ICE CREAM|CREAMERY|BAKERY|MALT|SODA FOUNTAIN|DONUTS?|"
                      r"CANTINA|TAQUERIA|BURRITOS?|CHILE)\b")
# retail candy, fudge and popcorn shops and shake-and-tea "nutrition" clubs (not the parlors and cafés that also sell candy)
CANDY = re.compile(r"\b(?:CANDY|CANDIES|FUDGE|POPCORN|CONFECTION\w*|CHOCOLATES?|CHOCOLATIER|TRUFFLES?|SWEETS? SHOPPE?|KETTLE CORN|NUTRITION)\b")
CHEESY = re.compile(r"\bCHEESE (?:SHOP|STORE|MONGER|COMPANY)\b")
CHEESE_OK = re.compile(r"\b(?:MACARONI|GRILLED|STEAK|BURGER)\b")
# a company that runs the kitchen, a stadium or airport, a campus: hidden whatever the name says
HARD = re.compile(r"\b(?:AIRPORT|TERMINAL|CONCOURSE|AT AND T STADIUM|COWBOYS STADIUM|NRG STADIUM|NRG PARK|MINUTE MAID PARK|DAIKIN PARK|GLOBE LIFE FIELD|ALAMODOME|"
                  r"AMERICAN AIRLINES CENTER|TOYOTA CENTER|FROST BANK CENTER|MOODY CENTER|KYLE FIELD|Q2 STADIUM|TOYOTA FIELD|"
                  r"FAIRGROUNDS?|STATE FAIR|NATIONAL WESTERN|LEVY|AVIANDS|SODEXO|ARAMARK|DELAWARE NORTH|CENTERPLATE|COMPASS GROUP|CHARTWELLS|"
                  r"BON APPETIT|HMSHOST|EUREST|GUCKENHEIMER|SSP AMERICA|DELTA SKY CLUB|UNITED CLUB|CENTURION LOUNGE|COMMISSARY|DINING HALL|"
                  r"UNIVERSITY DINING|CORRECTIONAL|PRISON|DETENTION|CATHOLIC HOME|SENIOR DINING|CAREERS|FORT CAVAZOS|FORT HOOD|FORT BLISS|"
                  r"LACKLAND|RANDOLPH AFB|DYESS|SHEPPARD AFB|LAUGHLIN AFB|GOODFELLOW|NAS CORPUS CHRISTI|NAS KINGSVILLE|JBSA|"
                  r"TDCJ|STATE FAIR OF TEXAS|RODEO HOUSTON|HOUSTON LIVESTOCK SHOW)\b")
# words that usually mean a venue, unless the place is plainly a bar, café or restaurant or has a real following
SOFT = re.compile(r"\b(?:STADIUM|ARENA|FESTIVAL|CONCESSIONS?|FOOD ?SERVICES?|UNIVERSITY|COLLEGE|SCHOOL|ACADEMY|ELEMENTARY|STUDENT|CAMPUS|"
                  r"HOSPITAL|MEDICAL CENTER|CLINIC|HEALTH CENTER|SENIOR|RETIREMENT|ASSISTED LIVING|NURSING|CARE CENTER|REHAB|CHURCH|PARISH|"
                  r"PAVILION|AMPHITHEAT(?:ER|RE)|CONCESSION COMPANY|STADIUM CLUB|CONGREGATION|TEMPLE|SYNAGOGUE|MOSQUE|MINISTR(?:Y|IES)|VFW|AMERICAN LEGION|AMVETS|EAGLES CLUB|FRATERNAL ORDER|ELKS LODGE|"
                  r"MOOSE LODGE|KNIGHTS OF COLUMBUS|COUNTRY CLUB|GOLF CLUB|GOLF COURSE|YACHT CLUB|ATHLETIC CLUB|SOCIAL CLUB|"
                  r"CATERING|CATERERS?|BANQUETS?|BANQUET HALL|EVENT (?:CENTER|VENUE|SPACE)|CONVENTION CENTER|CONFERENCE CENTER|MUSEUM|ZOO|"
                  r"THEATER|THEATRE|CINEMAS?|ALAMO DRAFTHOUSE|BOWLING|LANES|CASINO|KICKAPOO LUCKY EAGLE|NASKILA|SPEAKING ROCK|HOTEL|MOTEL|INN AND SUITES|SUITES|"
                  r"MARRIOTT|HILTON|HYATT|SHERATON|WESTIN|HOLIDAY INN|HAMPTON INN|FAIRFIELD INN|RESIDENCE INN|COURTYARD|SPRINGHILL|RADISSON|"
                  r"BEST WESTERN|COMFORT INN|SUPER 8|RED ROOF|DAYS INN|LA QUINTA|CORPORATE|EMPLOYEE|CAFETERIA|MOBILE|FOOD TRUCK|KIOSK|GYM|"
                  r"FITNESS|YMCA|YWCA|BOYS AND GIRLS CLUB|DAYCARE|DAY CARE|CHILD CARE|CHILDCARE|LEARNING CENTER|JAIL|MILITARY|NATIONAL GUARD|BUILDING)\b")
kd = o.name_out.map(norm_name).fillna("")
k_ = o.k.fillna("")
busy = o.reviews.fillna(0) >= 200
gfirst = o.gcats.fillna("").str.split("|").str[0]
plainly_food = kd.str.contains(REALFOOD) | o.cat.isin(["bar", "brewery", "coffee_shop", "cafe"]) \
    | gfirst.str.contains(r"\b(?:Bar|Pub|Restaurant|Cafe|Café|Coffee|Tavern|Grill|Brewery|Diner|Bakery)\b", regex=True)
brand_store = o.brand_n.isin(["Casey's", "7-Eleven", "Hunt Brothers Pizza", "Hot Stuff Pizza", "Krispy Krunchy Chicken", "MrBeast Burger",
                              "It's Just Wings", "Kum & Go", "Maverik", "Loaf 'N Jug", "Love's", "Rocky Mountain Chocolate Factory",
                              "Buc-ee's", "H-E-B", "Kroger", "Tom Thumb", "Stripes", "Valero", "Shell", "Mi Tienda"])
store = kd.str.contains(STORE) | k_.str.contains(r"\b(?:GAS STATION)\b") | brand_store \
    | (o.dom.isin(STORE_DOMS) & ~plainly_food) \
    | (kd.str.contains(CANDY) & ~kd.str.contains(REALFOOD) & ~busy) \
    | (kd.str.contains(CHEESY) & ~kd.str.contains(CHEESE_OK) & ~kd.str.contains(REALFOOD) & ~o.cat.isin(["bar", "brewery"]))
venue = kd.str.contains(HARD) | k_.str.contains(HARD) | o.name.fillna("").str.upper().str.contains(r"\(T-?\d|\bGATE [A-Z]?\d|\bCONCOURSE [ABC]\b", regex=True) \
    | (kd.str.contains(SOFT) & ~(busy | plainly_food))
LICENSE_ONLY_NONREST = re.compile(r"\b(?:APARTMENTS?|POOLS?|SWIM|AQUATIC|ARCHERY|BOWHUNTERS|SPORTSM[AE]NS?|GUN CLUB|ASSOCIATION|ATTN|C O|EVENTS?|STUDIOS?|"
                                  r"BOATS|SPORTS CENTER|HOSPITALITY GROUP|KNIGHTS|HEALTH|ECONO|CABELAS|CONDOMINIUMS?|HOMEOWNERS|NEIGHBORHOOD|COMMUNITY|"
                                  r"PARKS AND REC|RECREATION|CAMP|BIBLE|FOUNDATION|SOCIETY|COUNCIL|LEAGUE|UNION|INSTITUTE|CENTER$|FARMS?|AMUSEMENT|PREP|"
                                  r"EDUCATIONAL|ENTERTAINMENT|SERVICE AMERICA|CORPORATION|HOLDINGS|MANAGEMENT|VENTURES|FIELD|GOLF|COUNTRY CLUB|"
                                  r"RACQUET|SKI AREA|SKI RESORT|LODGING|HOTEL|MOTEL|SUITES|THEATRE|THEATER|CINEMA|BOWL|LANES|STADIUM|ARENA)\b")
lic_only = o.src.eq("official")
club = kd.str.contains(r"\bCLUB\b") & ~kd.str.contains(r"SUPPER ?CLUB|NIGHT ?CLUB|CLUB 51|CLUB TAVERN")
venue |= lic_only & (kd.str.contains(LICENSE_ONLY_NONREST) | club) & ~busy

# airports and stadiums: DFW, Love Field, IAH, Hobby, Austin-Bergstrom, San Antonio, El Paso; AT&T Stadium, NRG
VENUE_ADDR = {("2400", "AVIATION"), ("8008", "HERB KELLEHER"), ("2800", "N TERMINAL"), ("2800", "TERMINAL"), ("7800", "AIRPORT"),
              ("3600", "PRESIDENTIAL"), ("9800", "AIRPORT"), ("6701", "CONVAIR")}
vaddr = pd.Series([bool(street_nums(a) & {n for n, s2 in VENUE_ADDR if s2 == s_}) for a, s_ in
                   zip(o.street, o.street.map(lambda a: street_key(a)[1]))], index=o.index)
# a stadium's year-round restaurant with a real following stays; airport and concourse stands don't
airport = o.street.fillna("").str.upper().str.contains(r"^(?:2400 AVIATION|8008 HERB KELLEHER|2800 N(?:ORTH)? TERMINAL|7800 AIRPORT|3600 PRESIDENTIAL|9800 AIRPORT|6701 CONVAIR)")
vaddr &= ~((o.reviews.fillna(0) >= 300) & ~airport)
venue |= vaddr
print("stadium / airport / fairground addresses:", int(vaddr.sum()))
o["venue"] = store | venue | o.get("lic_shared", pd.Series(False, index=o.index)).fillna(False).astype(bool)
print("non-restaurants flagged:", int(o.venue.sum()), "| stores:", int(store.sum()), "| venues:", int((venue & ~store).sum()))




# ---------------------------------------------------------------- honors and hand-checked facts (data/research)
for col in ("jbf", "michelin", "green_star", "founded", "founded_note", "cur_tags", "dishes", "rnote", "rsite", "seasonal", "evidence"):
    o[col] = None
match_curated = curated_matcher(o)
o["hc"] = False   # hand-checked: matched to an open entry in data/research (each has a 2025-26 source)
o["rname"] = None
matched_cur, unmatched = 0, []
for c in CUR:
    if c.get("open") is False:
        continue
    best = match_curated(c)
    if best is None:
        unmatched.append(c["name"] + " (" + (c.get("city") or "") + ")")
        continue
    matched_cur += 1
    i = o.index[best]
    o.at[i, "hc"] = True
    if not o.at[i, "rname"]:   # the checked name, without a branch or host hotel note: "Savina's Mexican Kitchen (Downtown)"
        o.at[i, "rname"] = c.get("display") or re.sub(r"\s*\([^()]*\)\s*$", "", c["name"]).strip()
    for col, vals in (("jbf", c.get("james_beard")), ("cur_tags", c.get("tags")), ("dishes", c.get("dishes"))):
        if vals:
            have = [x for x in (o.at[i, col] or "").split("; ") if x]
            o.at[i, col] = "; ".join(have + [v for v in dict.fromkeys(vals) if v not in have])
    for col, v in (("michelin", c.get("michelin")), ("green_star", c.get("green_star") or None), ("founded", c.get("founded")),
                   ("founded_note", c.get("founded_note")), ("rnote", c.get("note")), ("rsite", c.get("website")), ("seasonal", c.get("seasonal")),
                   ("evidence", c.get("evidence_date"))):
        if v and not o.at[i, col]:
            o.at[i, col] = v
renamed = o.hc & o.rname.notna() & (o.rname != o.name_out)
print("hand-checked places shown under the checked name:", int(renamed.sum()), list(zip(o.name_out[renamed], o.rname[renamed]))[:12])
o.loc[o.hc & o.rname.notna(), "name_out"] = o.rname
print(f"verified entries matched: {matched_cur}/{sum(1 for c in CUR if c.get('open') is not False)}; unmatched ({len(unmatched)}): {unmatched[:30]}")
# places the research verified as closed (with a source) come off the list, whatever the map listings say
gone = [(c["name"], o.name_out.iat[b]) for c in CLOSED for b in [match_curated(c)] if b is not None]
drop_closed = {o.index[b] for c in CLOSED for b in [match_curated(c)] if b is not None}
o = o.drop(index=list(drop_closed)).reset_index(drop=True)
print("verified closed, removed:", len(drop_closed), gone[:20])

# ---------------------------------------------------------------- Texas tags (hand-checked guides: data/research/app/*.json)
tags_c = o.cur_tags.fillna("").str.lower()
o["t_bbq"] = o.hc & tags_c.str.contains(r"\bbbq\b|barbecue|brisket")
o["t_texmex"] = o.hc & tags_c.str.contains(r"tex-?mex")
o["t_taqueria"] = o.hc & tags_c.str.contains(r"taquer")
o["t_kolache"] = o.hc & tags_c.str.contains(r"kolach")
o["t_cfs"] = o.hc & tags_c.str.contains(r"chicken[- ]fried")
o["t_oldest"] = o.hc & pd.to_numeric(o.founded, errors="coerce").le(1960)
# official: the business holds a state Brew Pub or Distillery Pub license; liquor license types per business
# One address can hold several businesses (a Subway next to a liquor store, a brewery's old and new names), so a place shows only the
# license it was matched to and those whose name it shares, never its neighbor's.
F_biz_rows = F.groupby("biz").groups
F_stems = [set().union(*[(_stems(kk) - GENERIC) for kk in ks]) if ks else set() for ks in F["keys"]]


TOWN_WORDS = {w for c in o.city.dropna().unique() for w in _stems(norm_name(c))}


def place_lics(off_, b, k, st_):
    if b != b:
        return []
    nums = street_nums(st_) if isinstance(st_, str) else set()
    out = []
    for j in F_biz_rows.get(b, []):
        same_num = not nums or F.num.iat[j] in nums
        if any(agree(k, kk, 80 if same_num else 90) or (same_num and bool(nums) and shared_word(k, kk)) for kk in F["keys"].iat[j]):
            out.append(j)
    return out


o["k_out"] = o.name_out.map(norm_name)
o["lic_ix"] = [place_lics(a, b, k, st_) for a, b, k, st_ in zip(o.off, o.biz, o.k_out, o.street)]
# GAP-3: a place named for its license holder ("Amy Vu", "A & J Refrigeration", "Eaten Path" next to Bosq) takes the license's trade
# name, or goes when the place under that trade name is right there
PERSON = re.compile(r"^[A-Z][a-z]+ [A-Z]\.? (?:[A-Z][a-z]+|Mc[A-Z][a-z]+)$")
# a license in a person's own name ("Ken S Fukayama", "Clifford Lee Bautsch") says who owns the place, not what it's called
FIRST_NAMES = set("""james john robert michael william david richard joseph thomas charles christopher daniel matthew anthony mark donald steven
paul andrew joshua kenneth kevin brian george timothy ronald edward jason jeffrey ryan jacob gary nicholas eric jonathan stephen larry
justin scott brandon benjamin samuel gregory alexander frank patrick raymond jack dennis jerry tyler aaron jose adam nathan henry douglas
zachary peter kyle ethan walter noah jeremy christian keith roger terry gerald harold sean austin carl arthur lawrence dylan jesse jordan
bryan billy joe bruce gabriel logan albert willie alan juan wayne elijah randy roy vincent ralph eugene russell bobby mason philip louis
clifford ken ken kenny mike jim bob tom bill steve dave rick dan chris tony mary patricia jennifer linda elizabeth barbara susan jessica
sarah karen lisa nancy betty margaret sandra ashley kimberly emily donna michelle carol amanda dorothy melissa deborah stephanie rebecca
sharon laura cynthia kathleen amy angela shirley anna brenda pamela emma nicole helen samantha katherine christine debra rachel carolyn
janet catherine maria heather diane ruth julie olivia joyce virginia victoria kelly lauren christina joan evelyn judith megan andrea cheryl
hannah jacqueline martha gloria teresa ann sara madison frances kathryn janice jean abigail alice judy sophia grace denise amber doris
marilyn danielle beverly isabella theresa diana natalie brittany charlotte marie kayla alexis lori pak yi""".split())


def is_person(n):
    w = n.replace(".", "").split()
    return 2 <= len(w) <= 3 and w[0].lower() in FIRST_NAMES and all(x[:1].isupper() and x.isalpha() for x in w)
cellk = collections.defaultdict(list)
for i_, (la_, lo_) in enumerate(zip(o.lat, o.lon)):
    if la_ == la_:
        cellk[(round(la_ / 0.001), round(lo_ / 0.0013))].append(i_)
holder_drop, holder_renamed = [], 0
o["renamed"] = False
for i_ in range(len(o)):
    ix = o.lic_ix.iat[i_]
    if not ix:
        continue
    k = o.k_out.iat[i_]
    best_dba, best_holder, dba_name = 0, 0, None
    for j in ix:
        dba, holder = F["dba"].iat[j], F["holder"].iat[j]
        if isinstance(dba, str) and dba.strip():
            sd = name_sim(core(k), core(norm_name(dba))) if core(norm_name(dba)) and core(k) else 0
            if sd >= best_dba:
                best_dba, dba_name = sd, dba
        if isinstance(holder, str) and holder.strip() and core(norm_name(holder)) and core(k):
            best_holder = max(best_holder, name_sim(core(k), core(norm_name(holder))))
    if o.hc.iat[i_] or o.honored.iat[i_] if "honored" in o.columns else o.hc.iat[i_]:
        continue
    if best_holder >= 85 and best_dba <= 60 and dba_name and norm_name(dba_name) != norm_name(F["holder"].iat[ix[0]] or ""):
        la_, lo_ = o.lat.iat[i_], o.lon.iat[i_]
        key = (round(la_ / 0.001), round(lo_ / 0.0013)) if la_ == la_ else None
        twin = key is not None and any(j_ != i_ and math.hypot((o.lat.iat[j_] - la_) * 111000, (o.lon.iat[j_] - lo_) * 85000) < 100
                                       and agree(o.k_out.iat[j_], norm_name(dba_name), 85)
                                       for dy in (-1, 0, 1) for dx in (-1, 0, 1) for j_ in cellk.get((key[0] + dy, key[1] + dx), []))
        if twin:
            holder_drop.append(i_)
        else:
            o.at[o.index[i_], "name_out"] = _trade(dba_name); o.at[o.index[i_], "k_out"] = norm_name(o.name_out.iat[i_])
            o.at[o.index[i_], "k"] = o.k_out.iat[i_]; o.at[o.index[i_], "renamed"] = True; holder_renamed += 1
    elif best_holder >= 85 and not FOODISH.search(o.name_out.iat[i_] or "") and is_person(o.name_out.iat[i_] or ""):
        holder_drop.append(i_)   # the license names only a person: the place's own name is unknown
QA_DEBUG["holder_named_dropped"] = [o.name_out.iat[i_] for i_ in holder_drop]
print("places named for the license holder: renamed to the trade name", holder_renamed, "| dropped (the trade-name place is right there, or a person's name)", len(holder_drop))
o = o.drop(index=o.index[holder_drop]).reset_index(drop=True)
# a renamed row can be a place the research found closed ("Q House" came back under its license's trade name): check the list again
_mc = curated_matcher(o)
closed_again = {o.index[b] for c in CLOSED for b in [_mc(c)] if b is not None and bool(o.renamed.iat[b])}
print("verified closed, removed after renaming:", len(closed_again), o.name_out[list(closed_again)].tolist()[:10])
o = o.drop(index=list(closed_again)).reset_index(drop=True)
# an "official" place must show the record that makes it official: a listing matched by address alone to a differently named business
# (a company-register listing for Coma Mexican Grill at Pony M Cake's address) loses that status, and goes when its own source
# wouldn't keep it (the app's keep rule without the official match)
no_rec = o.official & o.lic_ix.map(len).eq(0) & ~o.src.eq("official")
conf_ = o.confidence.fillna(0)
web_ = o.get("web", pd.Series(None, index=o.index)).notna() | o.rsite.notna()
own_ok = o.hc | o.src.isin(["AllThePlaces", "DAC", "research"]) | ((o.src == "meta") & ((conf_ >= 0.95) | ((conf_ >= 0.9) & web_)))
o.loc[no_rec, ["official", "off", "biz"]] = [False, np.nan, np.nan]
o.loc[no_rec, "tier"] = np.where((o.src[no_rec] == "research") | ((o.src[no_rec] == "meta") & (conf_[no_rec] >= 0.95)), "both", "listing")
print("official only by address to another business: demoted", int((no_rec & own_ok).sum()), "| dropped", int((no_rec & ~own_ok).sum()))
QA_DEBUG["no_record_dropped"] = (o.name_out[no_rec & ~own_ok] + " | " + o.street[no_rec & ~own_ok].fillna("")).tolist()
o = o[~(no_rec & ~own_ok)].reset_index(drop=True)
QA_DEBUG["license_trace"] = [f"{o.name_out.iat[i_]} | {o.street.iat[i_]} | off={F.lic.iat[int(o.off.iat[i_])] if o.off.iat[i_] == o.off.iat[i_] else None}"
                              f" ({F['name'].iat[int(o.off.iat[i_])] if o.off.iat[i_] == o.off.iat[i_] else ''}) | lic={[F.lic.iat[j] for j in o.lic_ix.iat[i_]]}"
                              for i_ in range(len(o)) if re.match(r"(?i)jus aspen|boulder cafe$|castle rock beer|eaten path|amy vu|a & j refrig|aspen kitchen|oni aspen|betula", o.name_out.iat[i_] or "")]
o["liq_types"] = [sorted({F.ltype.iat[j] for j in ix if F.jur.iat[j] == "liq"}) or None for ix in o.lic_ix]
# a Brew Pub or Distillery Pub license marks one place: at the license's house number, the best name match
bp_best = {}
for i, (ix, k, st_, off_) in enumerate(zip(o.lic_ix, o.k_out, o.street, o.off)):
    nums = street_nums(st_) if isinstance(st_, str) else set()
    for j in ix:
        if F.jur.iat[j] == "liq" and "Brewpub" in str(F.ltype.iat[j]) and F.num.iat[j] in nums:
            dba = F["dba"].iat[j]
            sc = (name_sim(core(k), core(norm_name(dba))) if isinstance(dba, str) and core(k) and core(norm_name(dba)) else 0) \
                + max((name_sim(k or "", kk) for kk in F["keys"].iat[j]), default=0) / 1000
            if sc > bp_best.get(j, (-1, None))[0]:
                bp_best[j] = (sc, i)
o["t_brewpub"] = False
o.loc[o.index[[i for _, i in bp_best.values()]], "t_brewpub"] = True
print("brewpub licenses on a place:", len(bp_best), "of", int(F[F.jur.eq("liq")].ltype.astype(str).str.contains("Brewpub").sum()))
# licenses that allow drinking on the premises: bars and restaurants, and the tasting rooms of breweries, wineries and distilleries
ONPREM_T = ("Mixed Beverage Permit", "Wine and Beer Retailer's Permit", "Beer Retailer's On-Premise License", "Private Club",
            "Brewer's License", "Winery Permit", "Distiller's and Rectifier's Permit")
o["liq"] = o.liq_types.map(lambda t: next((x for p in ONPREM_T for x in (t or []) if x.startswith(p)), None))
o["honored"] = o.jbf.notna() | o.michelin.notna() | o.t_oldest
# a MICHELIN restaurant isn't a pub because its map listing says "bar"; starred places are $$$$ unless Google gave a price level
o.loc[o.michelin.notna() & o.cuisine.eq("Bar & Pub"), "cuisine"] = "American & Other"
o.loc[o.michelin.isin(["1 Star", "2 Stars"]) & o.price_est.eq(1), "price"] = 4
shop = pd.Series(False, index=o.index)
store_only = o.liq_types.map(lambda t: bool(t) and all(official.liq_kind(x) == "retail" for x in t))
campus = o.name.fillna("").str.contains(r"^\(CU\)|@ .*\bHall\b", case=False, regex=True) \
    | (o.name_out.fillna("").str.contains(r"\b(?:Day Spa|Salon|Aesthetics|Barber(?:shop)?|Tattoo|Jewel(?:ry|ers)|Center for the Arts|Ice Arena)\b",
                                          case=False, regex=True) & ~o.name_out.fillna("").str.contains(r"Bookcase", case=False, regex=True))
# Python's re, not pandas' (its pyarrow engine has ASCII-only word boundaries, so "Café" never matched)
FOODWORDS = re.compile(r"(?i)\b(?:bar|pub|tavern|saloon|lounge|social club|caf[eé]|coffee|diner|pizza|grill|kitchen|bistro|taco|sushi|deli|subs?|"
                       r"bakery|pasteler[ií]a|panader[ií]a|restaurante?|taquer[ií]a|cocina|trattoria|italian|peep)\b")
foodname = pd.Series([bool(REALFOOD.search(norm_name(n) or "")) or bool(FOODWORDS.search(n or "")) for n in o.name_out], index=o.index)
# a store is a place whose own name is on the package-store license, not a café that shares a word with the liquor store next door
own_retail = pd.Series([any(F.jur.iat[j] == "liq" and official.liq_kind(F.ltype.iat[j]) == "retail"
                            and any(name_sim(k or "", kk) >= 80 for kk in F["keys"].iat[j]) for j in ix)
                        for ix, k in zip(o.lic_ix, o.k_out)], index=o.index)
store_only &= own_retail & ~foodname
campus &= ~(foodname & ~o.name.fillna("").str.contains(r"^\(CU\)", case=False, regex=True))
o.loc[store_only | campus, "venue"] = True
NONFOOD = re.compile(r"(?i)\bnails?\b|nail ?bar|\blash(?:es)?\b|beauty (?:bar|lounge)|\bspa\b|scissors|grooming|\bsenior\b|\bliving\b|assisted|"
                     r"memory care|retirement|\bpaint(?:ing)?\b|\bsip\b|\bglaze\b|\baxes?\b|tomahawk|escap(?:e|ology)|pickle ?ball|picklr|soccer|"
                     r"volleyball|softball|\bskate\b|roller|climbing|trampoline|bounce|\bkids?\b|kidz|planetarium|tramway|raceway|marina|nordic|"
                     r"rentals?\b|lockers|anglers|cyclery|mountaineering|booksellers|bridal|apparel|boutique|nursery|petroleum|\bshell\b|"
                     r"sinclair|conoco|phillips 66|mini-?mart|country stores?|bait shop|flea market|\bguns?\b|firearms|eye ?pieces|kemo sabe|"
                     r"gorsuch|living spaces|\brh\b|trading post|sports cards|collectibles|workspace|coworking|car wash|real estate|insurance|"
                     r"\bbank\b|credit union|dental|\bclinic\b|chiropract|urgent care|\bvet(?:erinary)?\b|kennel|storage|\bmotel\b|"
                     r"marriott|hilton|hyatt|doubletree|residence inn|courtyard by|staybridge|holiday inn|hampton inn|aloft|moxy|kimpton|ritz-carlton|"
                     r"\bthe gant\b|viceroy|inspirato|bed (?:&|and) breakfast|\bb&b\b|parking")
FOODMORE = re.compile(r"(?i)cuisine|baguette|bistro|brew|spirits|distill|winery|wines?\b|cellars?|cider|meadery|tap ?(?:room|house)|"
                      r"tasting|eats|kitchen|cantina|cocina|taqueria|pupuser|mariscos|panader|pasteler|dumpling|noodle|ramen|poke|boba|"
                      r"creamery|gelato|donut|bagel|crepe|waffle|biscuit|smokehouse|bbq|barbecue|chophouse|steak|seafood|oyster|sushi|pho\b")
foodword = pd.Series([bool(REALFOOD.search(norm_name(n) or "")) or bool(FOODWORDS.search(n or "")) or bool(FOODMORE.search(n or ""))
                      for n in o.name_out], index=o.index)
# a nail bar's "Bar" or a salon's "Lounge" is no food word: these hide whatever else the name says
STRONG_NONFOOD = re.compile(r"(?i)\bnails?\b|\blash(?:es)?\b|\bsalon\b|\bsenior\b|assisted living|memory care|\bguns?\b|firearms|"
                            r"petroleum|\bsinclair\b|\bconoco\b|living spaces|barber")
nonfood = pd.Series([bool(NONFOOD.search(n or "")) for n in o.name_out], index=o.index) & ~foodword \
    | pd.Series([bool(STRONG_NONFOOD.search(n or "")) for n in o.name_out], index=o.index)
REST_T = ONPREM_T
rest_lic = o.liq_types.map(lambda t: bool(t) and any(x.startswith(REST_T) for x in t))
license_only = o.src.eq("official") & ~foodword & ~rest_lic
# a license-only row named only with initials or a company word ("HRHC", "Salc", "DFB Capital") is a company, not a place to eat
license_only |= o.src.eq("official") & ~foodword & o.name_out.fillna("").str.fullmatch(r"(?:[A-Z]{2,5}|[A-Z][a-z]{2,4}|.*\b(?:Capital|Concessions?|Pavilion|Amphitheat(?:er|re)|Stadium|Arena|Club Level)\b.*)")
# Overture's own category for the same business: a nail salon, senior home, gas station or hotel listing at this spot, and no
# restaurant listing under the same name
OVNF = re.compile(r"beauty|nail|salon|barber|\bspa\b|senior|retirement|assisted|nursing|gas station|convenience|\bhotel\b|motel|lodging|"
                  r"gun|firearm|clothing|apparel|furniture|sporting goods|school|real estate|bank|insurance|dentist|doctor|clinic|church|"
                  r"religious|auto|car dealer|car wash|storage|art studio|paint|escape room|trampoline|climbing|bowling|golf|marina|museum")
ovc = collections.defaultdict(list)
for r_ in OV.itertuples():
    if r_.lat == r_.lat:
        ovc[(round(r_.lat / 0.001), round(r_.lon / 0.0013))].append(r_)


def ov_nonfood(k, la, lo):
    if la != la or not k:
        return False
    key = (round(la / 0.001), round(lo / 0.0013)); hits = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for r_ in ovc.get((key[0] + dy, key[1] + dx), []):
                if math.hypot((r_.lat - la) * 111000, (r_.lon - lo) * 85000) < 100 and agree(k, r_.k, 85):
                    hits.append(" ".join(str(x or "").replace("_", " ") for x in (r_.cat, r_.tax)))
    return bool(hits) and any(OVNF.search(h) for h in hits) and not any(FOODCAT.search(h) for h in hits)


ovnf = pd.Series([ov_nonfood(k, la, lo) for k, la, lo in zip(o.k_out, o.lat, o.lon)], index=o.index) & ~foodword
o.loc[nonfood | license_only | ovnf, "venue"] = True
QA_DEBUG["nonfood_hidden"] = o.name_out[nonfood | ovnf].tolist(); QA_DEBUG["license_only_hidden"] = o.name_out[license_only].tolist()
print("non-food businesses hidden: by name", int(nonfood.sum()), "| license-only rows without a food word", int(license_only.sum()),
      "| by Overture's category", int(ovnf.sum()))
print("liquor-store-only places hidden as stores:", int(store_only.sum()), "| campus dining halls:", int(campus.sum()))
QA_DEBUG["store_only"] = o.name_out[store_only].tolist(); QA_DEBUG["campus_nonfood"] = o.name_out[campus].tolist()
o.loc[o.honored | o.hc, "venue"] = False
o["t_fb"] = o.liq_types.map(lambda t: bool(t) and any("Food and Beverage Certificate" in x for x in t))
# reported alcohol sales: the Comptroller's mixed beverage gross receipts for the place's own Mixed Beverage permit, last 12 complete
# months. One permit reports for one location: it goes to the place whose name best matches the license's trade name.
MIX, MIX_FROM, MIX_TO = official.mixbev_receipts()
mb_best = {}
for i, (ix, k) in enumerate(zip(o.lic_ix, o.k_out)):
    for j in ix:
        if F.jur.iat[j] != "liq" or not str(F.ltype.iat[j]).startswith("Mixed Beverage"):
            continue
        rec = next((MIX[p] for p in (F.permits.iat[j] or []) if p in MIX), None)
        if rec is None:
            continue
        dba = F["dba"].iat[j]
        sc = name_sim(core(k), core(norm_name(dba))) if isinstance(dba, str) and core(k) and core(norm_name(dba)) else 0
        if sc > mb_best.get(j, (-1, None, None))[0]:
            mb_best[j] = (sc, i, rec)
o["alc"] = np.nan; o["alc_n"] = np.nan
for sc, i, rec in mb_best.values():
    ix_ = o.index[i]
    o.at[ix_, "alc"] = (0 if o.alc.iat[i] != o.alc.iat[i] else o.alc.iat[i]) + rec["total"]
    o.at[ix_, "alc_n"] = max(rec["n"], 0 if o.alc_n.iat[i] != o.alc_n.iat[i] else o.alc_n.iat[i])
print("places with reported mixed-beverage receipts:", int(o.alc.notna().sum()), f"({MIX_FROM} to {MIX_TO})")
print("tags:", {t_: int(o["t_" + t_].sum()) for t_ in ("bbq", "texmex", "taqueria", "kolache", "cfs", "oldest", "brewpub", "fb")},
      "| on-premises alcohol", int(o.liq.notna().sum()))

# ---------------------------------------------------------------- city inspections (each city's own score and band), last 3 years
# Austin: 0-100 and the dataset's own category (Green 90+, Yellow 70-89, Red under 70). El Paso: 0-100, "70 or above is passing" (the city's
# portal). Arlington: the latest score and the city's letter grade (A 91-100, B 81-90, C 71-80, F under 70, per the city).
INS = pd.concat([official.austin_inspections().assign(jur="aus"), official.elpaso_inspections().assign(jur="elp"),
                 official.arlington_inspections().assign(jur="arl")], ignore_index=True)
INS = INS[INS.score.notna() & INS.d.notna()]
INS_BY = {b_: g for b_, g in INS.groupby("lic", sort=False)}


def band(jur, score, b_=None):
    if jur == "aus":
        return {"Green": "Green", "Yellow": "Yellow", "Red": "Red"}.get(b_) or ("Green" if score >= 90 else "Yellow" if score >= 70 else "Red")
    if jur == "elp":
        return "Passing" if score >= 70 else "Below 70"
    return "A" if score >= 91 else "B" if score >= 81 else "C" if score >= 71 else "F"


RES = ["Green", "Yellow", "Red", "Passing", "Below 70", "A", "B", "C", "F"]
LOW = {"Red", "Below 70", "F"}
INS_COUNTY = {"aus": {"Travis County", "Williamson County", "Hays County"}, "elp": {"El Paso County"}, "arl": {"Tarrant County"}}
F_keys = dict(zip(F.lic, F["keys"]))
cols_i = ["in_res", "in_pts", "in_date", "in_type", "in_n", "in_rr", "in_cl", "in_hist", "in_items", "in_jur"]
recs = []
F_kind = dict(zip(F.lic, F.kind)); F_num = dict(zip(F.lic, F.num)); F_jur = dict(zip(F.lic, F.jur))
for off_, b, k, cty, st_ in zip(o.off, o.biz, o.k, o.county, o.street):
    if not any(cty in v for v in INS_COUNTY.values()):
        recs.append([None] * len(cols_i)); continue
    own = F.lic.iat[int(off_)] if off_ == off_ else None
    pnums = street_nums(st_) if isinstance(st_, str) else set()

    def agrees(x):
        jn = F_num.get(x)
        return cty in INS_COUNTY.get(F_jur.get(x), ()) and any(agree(k or "", kk, 85) or (bool(pnums) and jn in pnums and shared_word(k or "", kk))
                                                              for kk in F_keys.get(x, []))
    ok_ = lambda x: isinstance(x, str) and F_jur.get(x) in INS_COUNTY and F_kind.get(x) != "other" and agrees(x)
    cand = [own] if ok_(own) else []
    if not cand and b == b:
        cand = [x for x in F.lic[F.biz == b] if ok_(x)]
    g = None
    for x in cand:
        h = INS_BY.get(x)
        if h is not None and (g is None or len(h) > len(g)):
            g = h
    if g is None:
        recs.append([None] * len(cols_i)); continue
    last = g.iloc[-1]
    j_ = last.jur
    bands = [band(j_, r_.score, r_.band) for r_ in g.itertuples()]
    recs.append([bands[-1], int(round(last.score)), last.d, last.typ, len(g), int(sum(b_ in LOW for b_ in bands)),
                 int(sum("Closed" in str(getattr(r_, "result", "") or "") for r_ in g.itertuples())),
                 [[r_.d, b_, int(round(r_.score)), r_.typ] for r_, b_ in zip(g.itertuples(), bands)][::-1], None, j_])
o[cols_i] = pd.DataFrame(recs, index=o.index, columns=cols_i)
INS_THROUGH = {j_: INS.d[INS.jur == j_].max() for j_ in ("aus", "elp", "arl")}
print("places with city inspection scores:", o.in_jur.value_counts().to_dict(), "| latest band:", o.in_res.value_counts().to_dict(),
      "| records through", INS_THROUGH)

def own_jbf(jb):
    return "; ".join(h for h in (jb or "").split("; ") if "Restaurateur" not in h)


# ---------------------------------------------------------------- sales / profit: the Chicago model (web only)
auv = {a["brand"]: a for a in json.load(open(f"{DATA}/chain_auv.json")) if a.get("auv_usd")}
for mine, theirs in {"Freddy's": "Freddy's Frozen Custard & Steakburgers", "A&W": "A&W Restaurants"}.items():
    if theirs in auv and mine not in auv:
        auv[mine] = auv[theirs]
med_rev = o[o.reviews.notna() & (o.chain_n < 5)].groupby("price").reviews.median()
rel = (o.reviews + 10) / (o.price.map(med_rev) + 10)
bump = np.where(o.bar, 1.15, 1.0)
o["rev"] = (o.price.map(BASE) * bump * rel.fillna(0.6) ** B_FIT).clip(100_000, 40_000_000)
o["rev_src"] = np.where(o.reviews.notna(), "model", "model-low")
n_auv = 0
for b, a in auv.items():
    sel = o.brand_n == b
    if not sel.any():
        continue
    n_auv += 1
    med = o.loc[sel, "reviews"].median()
    r_ = (o.loc[sel, "reviews"] / med) ** 0.35 if med == med else pd.Series(np.nan, index=o.index[sel])
    o.loc[sel, "rev"] = a["auv_usd"] * r_.fillna(0.85).clip(0.6, 1.5)
    o.loc[sel, "rev_src"] = "chain"
o.loc[o.venue & o.rev_src.isin(["model", "model-low"]), "rev_src"] = "venue"
m_rat = o.rating.mean()
o["bayes"] = (o.reviews * o.rating + 40 * m_rat) / (o.reviews + 40)
margin = o.price.map(MARGIN)
margin = o.cuisine.map(MARGIN_CUISINE).fillna(margin) * (0.8 + 0.4 * pct(o.bayes).fillna(40) / 100)
o["margin"] = margin.round(4)
o["profit"] = o.rev * o.margin
o["food_cost"] = o.cuisine.map(FOOD_COST).fillna(30)
o["value_raw"] = o.bayes - 0.18 * (o.price - 1)
# iconic points: honors + history (verified founding year) + how many people know it (web only; the app has no review counts)
jb = o.jbf.map(lambda v: own_jbf(v) if isinstance(v, str) else "")
# Texas has a MICHELIN Guide, so honors carry most of the weight: 2 stars 62, 1 star 52, Bib 36, Recommended 22, America's Classics 40,
# a James Beard win 26; verified history adds up to 24 (80 years at one address) and popularity up to 14
MI_PTS = {"2 Stars": 62, "1 Star": 52, "Bib Gourmand": 36, "Recommended": 22}
acc = (jb.str.contains("America's Classic") * 40 + jb.str.contains(r"\bwinner\b") * 26
       + (jb.str.contains(r"(?<!semi)finalist") & ~jb.str.contains(r"\bwinner\b")) * 14 + (jb.str.contains("semifinalist") & ~jb.str.contains(r"(?<!semi)finalist|\bwinner\b")) * 6
       + o.michelin.map(MI_PTS).fillna(0) + o.t_oldest * 16).clip(upper=62)
years = (2026 - pd.to_numeric(o.founded, errors="coerce")).clip(lower=0)
o["s_icon"] = np.where(o.honored, (acc + years.fillna(0).clip(upper=80) / 80 * 24 + pct(np.log1p(o.reviews)).fillna(0) / 100 * 14).clip(upper=100), np.nan)


def r(x, n=0):
    if x is None or (isinstance(x, float) and x != x):
        return None
    return int(round(float(x))) if n == 0 else round(float(x), n)


def own_jbf(jb):
    """James Beard lines about the restaurant or its chef; an Outstanding Restaurateur honor belongs to the owners' whole group."""
    return "; ".join(h for h in (jb or "").split("; ") if "Restaurateur" not in h)


def hon_flags(x):
    jb = own_jbf(x.jbf)
    return ((1 if "America's Classic" in jb else 0) | (2 if re.search(r"\bwinner\b", jb) else 0) | (4 if re.search(r"(?<!semi)finalist", jb) else 0)
            | (8 if "semifinalist" in jb else 0) | (16 if x.t_oldest else 0))


MI_LEVEL = {"Recommended": 1, "Bib Gourmand": 2, "1 Star": 3, "2 Stars": 4, "3 Stars": 5}
TAGS = ["bbq", "texmex", "taqueria", "kolache", "cfs", "oldest", "brewpub", "fb"]
o = o[o.lat.notna()].reset_index(drop=True)

# ---------------------------------------------------------------- the same place twice (both builds): same name at the same street
# address, or (not a chain) the same name in one town within 400 m. The official record wins, then a hand-checked one, then more facts;
# the kept copy inherits what the dropped one knew, so a hand-checked green chile spot can't lose its check to a license record.
rank = o.tier.map({"official": 2, "both": 1, "listing": 0}).fillna(0) * 10 + o.hc.astype(int) * 5 + o.get("web", pd.Series(None, index=o.index)).notna().astype(int)
keyname = o.name_out.map(norm_name)
keyaddr = ["|".join(k) if all(k := street_key(s_)) else None for s_ in o.street]
drop, merged, seen = set(), [], {}
for pos, i in enumerate(o.index):
    if keyaddr[pos] and keyname[i]:
        k = (keyname[i], keyaddr[pos], o.city[i])
        if k in seen:
            j = seen[k]
            lose = i if rank[i] <= rank[j] else j
            drop.add(lose); seen[k] = j if lose == i else i
            merged.append((seen[k], lose))
        else:
            seen[k] = i
single = o[(o.chain_n.fillna(1) < 2) & ~o.index.isin(drop)]
for (nm, town), g in single.groupby([keyname[single.index], single.city]):
    if len(g) < 2 or not nm:
        continue
    idx = list(g.index)
    for a_ in range(len(idx)):
        for b_ in range(a_ + 1, len(idx)):
            i, j = idx[a_], idx[b_]
            if i in drop or j in drop:
                continue
            if math.hypot((o.at[j, "lat"] - o.at[i, "lat"]) * 111, (o.at[j, "lon"] - o.at[i, "lon"]) * 85) < 0.4:
                lose = i if rank[i] <= rank[j] else j
                drop.add(lose); merged.append((j if lose == i else i, lose))
NAMEFILL = re.compile(r"\b(?:THE|AND|CO|COMPANY|INC|LLC)\b")
TOWN_W = {w for c in o.city.dropna().unique() for w in _stems(norm_name(c))}
loose = {i: re.sub(r"\s+", " ", NAMEFILL.sub(" ", keyname[i] or "")).strip() for i in o.index}
cellp = collections.defaultdict(list)
for i in o.index:
    if i not in drop and o.at[i, "lat"] == o.at[i, "lat"]:
        cellp[(round(o.at[i, "lat"] / 0.0012), round(o.at[i, "lon"] / 0.0016))].append(i)
near_pairs = 0
for (cy_, cx_), ids in list(cellp.items()):
    nb = [j for dy in (-1, 0, 1) for dx in (-1, 0, 1) for j in cellp.get((cy_ + dy, cx_ + dx), [])]
    for i in ids:
        for j in nb:
            if j <= i or i in drop or j in drop:
                continue
            if isinstance(o.at[i, "brand_n"], str) or isinstance(o.at[j, "brand_n"], str):
                continue   # two Starbucks a block apart are two Starbucks
            if math.hypot((o.at[j, "lat"] - o.at[i, "lat"]) * 111000, (o.at[j, "lon"] - o.at[i, "lon"]) * 85000) > 120:
                continue
            a_, b_ = loose[i], loose[j]
            short = a_ if len(a_) <= len(b_) else b_
            same_num = bool(street_nums(o.at[i, "street"] or "") & street_nums(o.at[j, "street"] or "")) if isinstance(o.at[i, "street"], str) and isinstance(o.at[j, "street"], str) else False
            prefix = same_num and (a_.startswith(b_ + " ") or b_.startswith(a_ + " ")) and bool(_stems(short) - GENERIC - TOWN_W)
            if a_ and b_ and len(a_) >= 4 and (a_ == b_ or fuzz.ratio(a_, b_) >= 92 or prefix):
                lose = i if rank[i] <= rank[j] else j
                drop.add(lose); merged.append((j if lose == i else i, lose)); near_pairs += 1
print("same business within 120 m under a name variant, merged:", near_pairs)
QA_DEBUG["near_merged"] = [f"{o.at[k_, 'name_out']} | {o.at[k_, 'street']} <= {o.at[l_, 'name_out']} | {o.at[l_, 'street']}" for k_, l_ in merged[-near_pairs:]] if near_pairs else []
for keep_, lose in merged:
    if o.at[lose, "lic_ix"]:
        o.at[keep_, "lic_ix"] = list(dict.fromkeys(list(o.at[keep_, "lic_ix"] or []) + list(o.at[lose, "lic_ix"])))
    for col in [c for c in o.columns if c.startswith("t_")] + ["hc", "honored"]:
        if bool(o.at[lose, col]) and not bool(o.at[keep_, col]):
            o.at[keep_, col] = o.at[lose, col]
    for col in ("jbf", "michelin", "green_star", "founded", "founded_note", "cur_tags", "dishes", "rnote", "rsite", "seasonal", "evidence", "web",
                "phone", "s_icon", "liq", "alc", "alc_n", "in_res", "in_pts", "in_date", "in_type", "in_n", "in_rr", "in_cl", "in_hist", "in_items", "in_jur"):
        if col in o.columns and (o.at[keep_, col] is None or (isinstance(o.at[keep_, col], float) and o.at[keep_, col] != o.at[keep_, col])):
            v = o.at[lose, col]
            if v is not None and not (isinstance(v, float) and v != v):
                o.at[keep_, col] = v
print("same place twice, merged:", len(drop))
o = o.drop(index=list(drop)).reset_index(drop=True)
# adult clubs aren't restaurants and don't belong in a 13+ app at all; smoke, vape and cannabis shops are hidden with non-restaurants
webs = o.get("web", pd.Series("", index=o.index)).fillna("").astype(str) + " " + o.rsite.fillna("").astype(str)
# Texas: "cabaret" alone is no sign (Deep Eddy Cabaret is an Austin dive bar, The St. James a supper club), so only these words count
adult = o.name_out.str.contains(r"gentlem[ae]n['’]?s club|exotic dancer|strip club|adult entertainment|showclub|baby dolls|"
                                r"rick'?s cabaret|xtc cabaret|\bmen'?s club|bikini bar|showgirls|showclub|centerfolds", case=False, regex=True) \
    | webs.str.contains(r"centerfolds|gentlemensclub|stripclub|babydolls|diamondcabaret", case=False, regex=True)
# most clubs hold a plain Tavern license under a plain trade name ("PT's After Dark", "Glendale Restaurants"), so names alone miss them:
# every place at a checked club address goes (data/research/adult_venues.json), and so does a place near an Overture adult venue
# that shares its name
AV = json.load(open(f"{DATA}/research/adult_venues.json"))["venues"]
av_keys = {}
for v in AV:
    n_, s_ = street_key(v["address"])
    av_keys.setdefault(n_, []).append((s_, {t.lower() for t in v["towns"]}))
adult_addr = pd.Series([any(official.street_compat(s_, sk) and (c_ or "").lower() in towns for sk, towns in av_keys.get(n_, []))
                        if n_ and s_ else False
                        for (n_, s_), c_ in zip(o.street.map(street_key), o.city)], index=o.index)
OVA = duckdb.connect().execute(f"""SELECT name, lat, lon FROM '{TX}/overture_tx_bbox.parquet'
                                   WHERE cat IN ('adult_entertainment_venue', 'strip_club') OR tax IN ('adult_entertainment_venue', 'strip_club')""").df()
OVA["k"] = OVA.name.map(norm_name)
# a shared word counts only if it isn't a town's name ("Rick's Cabaret Denver" and "Embassy Suites Denver" share only "Denver")
TOWNW = {w for c in o.city.dropna().unique() for w in _stems(norm_name(c))}
# words every club shares ("The St. James Restaurant & Cabaret" isn't "Latina's Cabaret"); Overture's adult category also files
# adult day cares, game rooms and cigar lounges, so their words don't count either
ADULT_W = {"CABARET", "MEN", "MENS", "GENTLEMEN", "GENTLEMENS", "GENTLEMAN", "GENTLEMANS", "LOUNGE", "GAME", "GAMEROOM", "ROOM",
           "ROOMS", "SPORT", "SPORTS", "SHOWCLUB", "SHOW", "CLUB", "CUMBIA", "CUMBIAS", "ADULT", "DAY", "CARE", "CIGAR", "WHISKEY", "VIP", "PALACE", "PARTY", "DREAM", "DREAMS"}
adult_near = pd.Series([any(math.hypot((la - a.lat) * 111000, (lo - a.lon) * 85000) < 150 and (name_sim(k or "", a.k) >= 80
                            or bool((_stems(k or "") - GENERIC - TOWNW - ADULT_W) & (_stems(a.k) - GENERIC - TOWNW - ADULT_W))) for a in OVA.itertuples())
                        for k, la, lo in zip(o.name_out.map(norm_name), o.lat, o.lon)], index=o.index)
adult = adult | adult_addr | adult_near
print("adult clubs removed:", int(adult.sum()), "(by checked address", int(adult_addr.sum()), "| near an Overture adult venue", int(adult_near.sum()), ")",
      o.name_out[adult].tolist()[:30])
QA_DEBUG["adult"] = o.name_out[adult].tolist()
json.dump(QA_DEBUG, open(f"{TX}/qa_debug{'_app' if APP else ''}.json", "w"), indent=1, ensure_ascii=False, default=str)
o = o[~adult].reset_index(drop=True)
smoke = o.name_out.str.contains(r"\bvape\b|hookah|smoke ?shop|\btobacco\b|cigar lounge|\bcbd\b|dispensary|head shop|cannabis|marijuana", case=False, regex=True)
o.loc[smoke, "venue"] = True
if APP:
    fixes = json.load(open(f"{DATA}/research/name_fixes.json")) if os.path.exists(f"{DATA}/research/name_fixes.json") else []
    for fx in fixes:
        hit = (o.name_out.str.upper() == fx["name"].upper()) & (o.city == fx["town"]) & o.street.fillna("").str.startswith(fx["street_number"] + " ")
        o.loc[hit, "name_out"] = fx["fixed"]
        print("name fix:", fx["name"], "->", fx["fixed"], int(hit.sum()))


def clean_url(u):
    """Website links without tracking parameters (Reserve with Google tokens, utm_*, click ids)."""
    base, _, q = u.partition("?")
    keep_q = [kv for kv in q.split("&") if kv and not re.match(r"(rwg_token|utm_[a-z]+|fbclid|gclid|y_source)=", kv)]
    return base + ("?" + "&".join(keep_q) if keep_q else "")


LIQ_UPDATED = official.LIST_DATE


# pipeline/website_blocklist.json (hacked, taken-over, parked or wrong-business sites, confirmed by hand in the 2026-10-12 sweep):
# the place stays, its link goes, in the app as on the site (scripts/make-site.py applies the same list)
WEB_BLOCK = json.load(open(f"{ROOT}/pipeline/website_blocklist.json", encoding="utf-8"))


def site_blocked(w):
    pr = urllib.parse.urlsplit(w if "//" in w else "https://" + w)
    host, path = pr.netloc.lower().rstrip(".").removeprefix("www."), pr.path.rstrip("/")
    for b in WEB_BLOCK:
        if b.get("match", "domain") == "domain":
            d = re.sub(r"^[a-z]+://", "", str(b.get("domain") or "").lower()).split("/")[0].removeprefix("www.")
            if d and (host == d or host.endswith("." + d)):
                return True
        else:
            bu = urllib.parse.urlsplit(str(b.get("url") or ""))
            if host == bu.netloc.lower().removeprefix("www.") and path == bu.path.rstrip("/") and (not bu.query or pr.query == bu.query):
                return True
    return False


def lic_list(ix):
    out = []
    for j in ix:
        jur, lic, lt = F.jur.iat[j], F.lic.iat[j], F.ltype.iat[j]
        exp = F["expires"].iat[j] if "expires" in F.columns else None
        if jur == "liq":
            # the list is TABC's active licenses: a past date only means the renewal is pending, so it isn't shown
            out.append({"src": "TABC license", "id": lic[5:], "type": lt,
                        "exp": exp if isinstance(exp, str) and exp >= LIQ_UPDATED else None})
    return out


COUNTIES = sorted(o.county.dropna().unique().tolist())
JUR = {"aus": 1, "elp": 2, "arl": 3, "liq": 4}
o["jur_n"] = [JUR.get(F.jur.iat[int(j)], 0) if j == j else 0 for j in o.off]
SRCS = ["official", "meta", "AllThePlaces", "DAC", "research", "BrightQuery", "Foursquare", "Microsoft"]
meta_common = {"generated": TODAY, "overture_release": "2026-09-23.1", "inspections_through": INS_THROUGH,
               "inspections_published": {"aus": "2026-10-15", "elp": "2026-10-19", "arl": "2026-10-17"},
               "brewpub_licenses": int(F[F.jur.eq("liq")].ltype.astype(str).str.contains("Brewpub").sum()),
               "liquor_updated": LIQ_UPDATED, "mixbev_from": MIX_FROM, "mixbev_to": MIX_TO, "counties": COUNTIES, "tags": TAGS, "srcs": SRCS, "results": RES, "ins_jur": ["aus", "elp", "arl"]}

if APP:
    nv = o[~o.venue]
    CITIES = sorted(o.city.dropna().unique().tolist()); CUIS = sorted(o.cuisine.unique().tolist()); BRANDS = sorted(o.brand_n.dropna().unique().tolist())
    ci, cu, br, cy = ({c: i for i, c in enumerate(L)} for L in (CITIES, CUIS, BRANDS, COUNTIES))
    TIER = {"listing": 0, "both": 1, "official": 2}
    # Texas is ~80,000 places: the app ships a statewide core file (lists, search, map) and one detail file per region (inspection
    # history, TABC licenses, reported alcohol sales, phone, website), read only when a place opens (Florida's model).
    # Regions only split the files: each county goes to the nearest of nine anchor cities, by county centre.
    ANCHORS = {"Houston & Gulf Coast": (29.76, -95.37), "Dallas–Fort Worth": (32.78, -97.05), "Austin & Central Texas": (30.27, -97.74),
               "San Antonio & Hill Country": (29.42, -98.49), "El Paso & West Texas": (31.0, -104.5), "Rio Grande Valley & Border": (26.6, -98.3),
               "Coastal Bend": (27.8, -97.4), "East Texas": (32.0, -94.6), "Panhandle & Plains": (34.2, -101.8)}
    REGIONS = list(ANCHORS)
    _cn = json.load(open(f"{TX}/tx_counties_detail.geojson"))
    REGION_OF = {}
    for n_, g_ in _cn.items():
        c_ = shape(g_).centroid
        REGION_OF[n_] = min(ANCHORS, key=lambda k: math.hypot((ANCHORS[k][0] - c_.y) * 111, (ANCHORS[k][1] - c_.x) * 96))
    RG = {r_: i for i, r_ in enumerate(REGIONS)}
    INSJ = ["aus", "elp", "arl"]
    ITYPES = sorted({h_[3] for hs in o.in_hist.dropna() for h_ in hs})
    places, seen_ids = [], set()
    details = collections.defaultdict(dict)
    LINKS = json.load(open(f"{TX}/website_check.json")) if os.path.exists(f"{TX}/website_check.json") else None
    link_drops, link_cands, nan_keys = collections.Counter(), {}, collections.Counter()
    for i, x in o.iterrows():
        # a stable id (normalized name + ~100 m cell) so saved places survive a data refresh
        idsrc = f"{norm_name(x.name_out)}|{round(float(x.lat), 3)}|{round(float(x.lon), 3)}"
        p = {"id": hashlib.md5(idsrc.encode()).hexdigest()[:12], "n": x.name_out, "c": ci.get(x.city) if isinstance(x.city, str) else None,
             "cu": cu[x.cuisine], "t": TIER[x.tier], "s": SRCS.index(x.src) if x.src in SRCS else 1}
        dt_ = {}
        if isinstance(x.county, str): p["co"] = cy[x.county]
        rg = RG.get(REGION_OF.get(x.county)) if isinstance(x.county, str) else None
        if rg is not None: p["rg"] = rg
        if isinstance(x.street, str): p["a"] = re.sub(r"(?:,\s*|\s+)(?:TX|Texas)(?:\s+7\d{4})?$", "", nice(x.street, addr=True)) or nice(x.street, addr=True)
        if isinstance(x.zip, str) and re.match(r"^(?:7[5-9]\d{3}|885\d\d)", x.zip): p["z"] = x.zip[:5]
        p["la"], p["lo"] = round(float(x.lat), 5), round(float(x.lon), 5)
        if isinstance(x.brand_n, str): p["b"] = br[x.brand_n]
        if x.chain_n and int(x.chain_n) > 1: p["ch"] = int(x.chain_n)
        if x.venue: p["v"] = 1
        if x.bar: p["bar"] = 1
        tg = sum(1 << bi for bi, t_ in enumerate(TAGS) if bool(x["t_" + t_]))
        if tg: p["g"] = tg
        if x.hc: p["hc"] = 1
        if x.honored:
            p["h"] = hon_flags(x)
            if isinstance(x.michelin, str): p["mi"] = MI_LEVEL.get(x.michelin, 0)
            if isinstance(x.jbf, str): p["jbf"] = x.jbf
            p["ip"] = round(float(x.s_icon), 1)
        if x.founded == x.founded and x.founded is not None: p["f"] = int(float(x.founded))
        for k, col in (("fn", "founded_note"), ("note", "rnote"), ("dish", "dishes"), ("seas", "seasonal")):
            if isinstance(x[col], str) and x[col]: p[k] = x[col]
        if isinstance(x.liq, str): p["liq"] = 1
        # reported alcohol sales (Comptroller), thousands of dollars over the 12 months in the header: core, so a guide can sort by it
        if x.alc == x.alc and x.alc is not None: p["al"] = int(round(x.alc / 1000))
        web = x.rsite if isinstance(x.rsite, str) else (x.web if isinstance(x.get("web"), str) and not x.hc else None)
        if web:
            w_ = clean_url(web)
            c_ = link_cands.setdefault(w_, {"name": x.brand_n if isinstance(x.brand_n, str) else x.name_out, "chain": isinstance(x.brand_n, str),
                                            "towns": [], "zips": [], "phones": [], "streets": []})
            for k_, v_ in (("towns", x.city), ("zips", x.zip), ("phones", x.get("phone")), ("streets", x.street)):
                if isinstance(v_, str) and v_ and v_ not in c_[k_] and len(c_[k_]) < 8:
                    c_[k_].append(v_)
            # only links pipeline/check_websites.py verified; unchecked ones wait
            if LINKS is not None and LINKS.get(w_, {}).get("ok") and not site_blocked(LINKS[w_].get("ship") or w_):
                dt_["w"] = LINKS[w_].get("ship") or w_
            else:
                link_drops[(LINKS or {}).get(w_, {}).get("why", "not checked yet") if LINKS is not None else "not checked yet"] += 1
        if isinstance(x.get("phone"), str) and x.phone: dt_["ph"] = x.phone
        ls = lic_list(x.lic_ix)
        if ls: dt_["lic"] = [[l_["id"], l_["type"], l_.get("exp")] for l_ in ls]
        if x.alc == x.alc and x.alc is not None: dt_["aln"] = int(x.alc_n)
        if isinstance(x.in_res, str):
            # core: [city, band, score, date] of the latest inspection; detail: the history, latest first
            p["in"] = [INSJ.index(x.in_jur), RES.index(x.in_res), int(x.in_pts), x.in_date]
            dt_["in"] = {"n": int(x.in_n), "h": [[d, RES.index(b_), int(sc), ITYPES.index(t_)] for d, b_, sc, t_ in x.in_hist[:8]]}
        if p["la"] != p["la"] or p["lo"] != p["lo"]:
            nan_keys["no coordinates (skipped)"] += 1
            continue
        for k_ in [k_ for k_, v_ in p.items() if isinstance(v_, float) and v_ != v_]:
            nan_keys[k_] += 1; del p[k_]
        while p["id"] in seen_ids:
            p["id"] = p["id"] + "x"
        seen_ids.add(p["id"])
        places.append(p)
        if dt_:
            details[REGIONS[rg] if rg is not None else "Other"][p["id"]] = dt_
    print("website links dropped:", sum(link_drops.values()), link_drops.most_common(8), "| empty numbers dropped:", dict(nan_keys))
    # tracking tags (ref=google, utm_*, cn_channel …) off every outbound link; the store's own parameters stay (tracking_params.py)
    tp_changes = tracking_params.scrub(places)
    tracking_params.scrub(details, tp_changes)
    print("tracking tags stripped:", dict(tp_changes) if isinstance(tp_changes, dict) else tp_changes)
    json.dump(link_cands, open(f"{TX}/website_candidates.json", "w"), indent=0, ensure_ascii=False)
    calib_app = json.load(open(f"{TX}/calibration_app.json"))
    out = {"v": 1, **meta_common, "regions": REGIONS, "itypes": ITYPES, "cities": CITIES, "cuisines": CUIS, "brands": BRANDS,
           "count": len(places), "count_restaurants": int(len(nv)), "calibration": calib_app, "places": places}
    os.makedirs(SITE, exist_ok=True)
    json.dump(out, open(f"{SITE}/places.json", "w"), separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str)
    for f_ in glob.glob(f"{SITE}/detail-*.json"):
        os.remove(f_)
    for reg, dd in details.items():
        json.dump(dd, open(f"{SITE}/detail-{re.sub(r'[^a-z]+', '-', reg.lower().replace('–', '-')).strip('-')}.json", "w"),
                  separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str)
    json.dump(json.load(open(f"{TX}/tx_shapes.json")), open(f"{SITE}/tx_shapes.json", "w"), separators=(",", ":"))
    sizes = {os.path.basename(f_): os.path.getsize(f_) // 1024 for f_ in sorted(glob.glob(f"{SITE}/detail-*.json"))}
    print("APP: wrote", len(places), "places (", len(nv), "restaurants ) | core", os.path.getsize(f"{SITE}/places.json") // 1024, "KB | details (KB):", sizes,
          "| tiers:", nv.tier.value_counts().to_dict(), "| tags:", {t_: int(nv["t_" + t_].sum()) for t_ in TAGS}, "| hand-checked:", int(nv.hc.sum()),
          "| honored:", int(nv.honored.sum()), "| inspections:", int(nv.in_res.notna().sum()), "| alcohol sales:", int(nv.alc.notna().sum()))
    sys.exit(0)

# ---------------------------------------------------------------- web leaderboard export (columnar; Google 2021 ratings labeled as such)
CITIES = sorted(o.city.dropna().unique().tolist()); CUIS = sorted(o.cuisine.unique().tolist()); BRANDS = sorted(o.brand_n.dropna().unique().tolist())
ci, cu, br, cy = ({c: i for i, c in enumerate(L)} for L in (CITIES, CUIS, BRANDS, COUNTIES))
SRC = {"model": 0, "model-low": 1, "chain": 2, "reported": 3, "venue": 4}
TIER = {"listing": 0, "both": 1, "official": 2}
LIQT = [None] + sorted(o.liq.dropna().unique().tolist())
SCALE = {"lat": 10000, "lon": 10000, "rating": 10, "margin": 1000, "value_raw": 1000}
C = collections.OrderedDict((c, []) for c in ["name", "addr", "city", "county", "zip", "lat", "lon", "cuisine", "brand", "chain_n", "rating", "reviews",
                                               "price", "price_est", "rev_k", "rev_src", "margin", "value_raw", "tier", "jur", "bar", "venue", "tags",
                                               "src", "liq", "hc", "alc_k"])
SP = {"hon": [], "insp": []}
extra = {}
for i, x in o.iterrows():
    tg = sum(1 << b for b, t_ in enumerate(TAGS) if bool(x["t_" + t_]))
    z = int(x.zip[:5]) if isinstance(x.zip, str) and re.match(r"^(?:7[5-9]\d{3}|885\d\d)", x.zip) else None
    vals = {"name": x.name_out, "addr": nice(x.street, addr=True) if isinstance(x.street, str) else None,
            "city": ci.get(x.city) if isinstance(x.city, str) else None, "county": cy.get(x.county) if isinstance(x.county, str) else None,
            "zip": z, "lat": x.lat, "lon": x.lon, "cuisine": cu[x.cuisine],
            "brand": br.get(x.brand_n) if isinstance(x.brand_n, str) else None, "chain_n": int(x.chain_n), "rating": x.rating, "reviews": r(x.reviews),
            "price": int(x.price), "price_est": int(x.price_est), "rev_k": int(round(x.rev / 1000)), "rev_src": SRC[x.rev_src], "margin": x.margin,
            "value_raw": x.value_raw, "tier": TIER[x.tier], "jur": int(x.jur_n), "bar": int(bool(x.bar)), "venue": int(bool(x.venue)), "tags": tg,
            "src": SRCS.index(x.src) if x.src in SRCS else 1, "liq": LIQT.index(x.liq) if isinstance(x.liq, str) else 0, "hc": int(bool(x.hc)),
            "alc_k": int(round(x.alc / 1000)) if x.alc == x.alc and x.alc is not None else None}
    if x.honored:
        SP["hon"].append([i, int(round(x.s_icon * 10)), hon_flags(x), MI_LEVEL.get(x.michelin, 0) if isinstance(x.michelin, str) else 0,
                          1 if x.green_star else 0])
    if isinstance(x.in_res, str):
        SP["insp"].append([i, RES.index(x.in_res), int(x.in_pts), x.in_date if isinstance(x.in_date, str) else None, int(x.in_n), int(x.in_rr), int(x.in_cl),
                           ["aus", "elp", "arl"].index(x.in_jur)])
    for c, v in vals.items():
        if c in SCALE:
            v = None if v is None or v != v else int(round(float(v) * SCALE[c]))
        elif isinstance(v, float):
            v = None if v != v else v
        C[c].append(v.item() if hasattr(v, "item") else v)
    e = {k: v for k, v in (("jbf", x.jbf), ("michelin", x.michelin), ("founded", r(x.founded) if x.founded == x.founded and x.founded is not None else None),
                           ("founded_note", x.founded_note), ("note", x.rnote), ("dishes", x.dishes), ("seasonal", x.seasonal),
                           ("web", x.rsite if isinstance(x.rsite, str) else None)) if isinstance(v, (str, int)) and v != ""}
    ls = lic_list(x.lic_ix)
    if ls: e["lic"] = ls
    if isinstance(x.in_res, str):
        e["insp"] = x.in_hist[:8]
        if x.in_items: e["items"] = x.in_items[:12]
    if e:
        extra[i] = e
nv = o[~o.venue]
meta = {**meta_common, "cities": CITIES, "cuisines": CUIS, "brands": BRANDS, "src": list(SRC), "tiers": list(TIER), "liqt": LIQT,
        "food_cost": dict(FOOD_COST), "spend": SPEND, "count": len(o), "count_restaurants": int(len(nv)),
        "count_official": int(nv.official.sum()), "count_both": int((nv.tier == "both").sum()), "count_listing": int((nv.tier == "listing").sum()),
        "n_cities": int(nv.city.nunique()), "rating_mean": round(float(m_rat), 3), "model": {"b": B_FIT, "n_chains": n_auv},
        "calibration": json.load(open(f"{TX}/calibration.json")), "n_honored": int(o.honored.sum())}
for _k, _v in list(C.items()) + list(SP.items()):
    _bad = [j for j, x in enumerate(_v) if (isinstance(x, float) and x != x) or (isinstance(x, list) and any(isinstance(y, float) and y != y for y in x))]
    if _bad: print("NaN in", _k, len(_bad), _v[_bad[0]])
os.makedirs(SITE, exist_ok=True)
json.dump({"n": len(o), "scale": SCALE, "cols": C, "sparse": SP, "meta": meta}, open(f"{SITE}/texas.json", "w"), separators=(",", ":"), allow_nan=False, default=str)
json.dump({"n": len(o), "extra": {str(k): v for k, v in extra.items()}}, open(f"{SITE}/tx_detail.json", "w"), separators=(",", ":"), allow_nan=False, default=str)
json.dump(json.load(open(f"{TX}/tx_shapes.json")), open(f"{SITE}/tx_shapes.json", "w"), separators=(",", ":"))
o.to_pickle(f"{TX}/stage2.pkl")
print("wrote", len(o), "places (", int(len(nv)), "restaurants ) in", nv.city.nunique(), "towns;", os.path.getsize(f"{SITE}/texas.json") // 1024,
      "KB | tiers:", nv.tier.value_counts().to_dict(), "| top towns:", nv.city.value_counts().head(8).to_dict())
