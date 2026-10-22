"""How often is a map listing a real, inspected or licensed food business? Measured where official lists exist -> data/tx/calibration*.json

Adapted from co-eats/pipeline/calibrate.py.
- Austin: listings with an Austin address in Travis County against every facility Austin Public Health inspected in the last 3 years
  (ecmv-9xxi) plus TABC licenses there. APH inspects every food business in its jurisdiction, so this is the full test.
- El Paso County: against every permit the City of El Paso inspected in 3 years (city plus county towns) plus TABC.
- Arlington: against the city's food establishment list (latest inspection per place) plus TABC.
- Statewide, county by county: against TABC on-premises licenses only. Many restaurants don't serve alcohol, so these rates are lower
  bounds; they compare listing sources, they don't measure them.
A match is the same business name nearby, or the same street address with a distinctive name word in common.
"""
import json
import numpy as np, pandas as pd
from shapely.geometry import shape, Point
from shapely.prepared import prep
from common import TX
from listings_util import official_match

o = pd.read_pickle(f"{TX}/stage1.pkl")
F = pd.read_pickle(f"{TX}/official.pkl")
from shapely import STRtree
_CN = json.load(open(f"{TX}/tx_counties_detail.geojson"))
_NAMES = list(_CN)
_GEOMS = [shape(_CN[n]).buffer(0.0003) for n in _NAMES]
_TREE = STRtree(_GEOMS)


def county_of(la, lo):
    if la != la:
        return None
    p = Point(lo, la)
    for i in _TREE.query(p):
        if _GEOMS[i].contains(p):
            return _NAMES[i]
    return None


o["county"] = [county_of(la, lo) for la, lo in zip(o.lat, o.lon)]
# TABC rows carry their county; the city inspection lists have no county field (El Paso: the county's own program)
F["county"] = [county_of(la, lo) or (f"{c} County" if isinstance(c, str) and c else None) or
               {"aus": "Travis County", "elp": "El Paso County", "arl": "Tarrant County"}.get(j)
               for la, lo, c, j in zip(F.lat, F.lon, F.get("county", pd.Series([None] * len(F))), F.jur)]
o.to_pickle(f"{TX}/stage1.pkl")
F.to_pickle(f"{TX}/official.pkl")
base = ~o.j_junk & ~o.j_outside
print("listings with a county:", int(o.county.notna().sum()), "of", len(o))


def groups(L, app=False):
    s = L.src.fillna("none")
    if app:
        conf = L.confidence.fillna(0)
        return np.select([L.ov_closed | L.j_closedname, (s == "meta") & (conf >= 0.95), (s == "meta") & (conf >= 0.9),
                          s.isin(["AllThePlaces", "DAC"]), (s == "BrightQuery") & (conf >= 0.95), s == "meta"],
                         ["closed per Overture/name", "meta_high", "meta_mid", "brand_feed", "bq_high", "meta_low"], "other_sources")
    return np.select([L.closed21, L.ov_closed, (s == "meta") & L.in21, s == "meta", s.isin(["AllThePlaces", "DAC"]) & L.in21,
                      s.isin(["AllThePlaces", "DAC"]), L.in21, s == "Foursquare", s == "BrightQuery", s == "Microsoft"],
                     ["Google 2021 says closed", "Overture says closed", "Meta + open in Google 2021", "Meta only",
                      "brand feed + Google 2021", "brand feed only", "Foursquare/BrightQuery/Microsoft + Google 2021",
                      "Foursquare only", "BrightQuery only", "Microsoft only"], "other")


AREAS = {"Austin": ("Travis County", F.jur.isin(["aus", "liq"]) & F.active, "aus"),
         "El Paso County": ("El Paso County", F.jur.isin(["elp", "liq"]) & F.active, "elp"),
         "Arlington": ("Tarrant County", F.jur.isin(["arl", "liq"]) & F.active, "arl")}
res, app = {}, {}
for label, (cty, sel, own) in AREAS.items():
    L = o[base & (o.county == cty)].reset_index(drop=True)
    R = F[sel & (F.county == cty)].reset_index(drop=True)
    if own == "aus":   # Austin Public Health: the City of Austin (listings in Austin and its unincorporated edges)
        L = L[L.city.isin(["Austin", "Del Valle", "Manchaca"])].reset_index(drop=True)
    if own == "arl":
        L = L[L.city.eq("Arlington")].reset_index(drop=True); R = R[R.city.eq("Arlington")].reset_index(drop=True)
    m = official_match(L, R)
    L["hit"] = L.index.map(lambda i: i in m)
    L["hit_food"] = L.index.map(lambda i: i in m and R.kind.iat[m[i]] in ("restaurant", "bar", "brewery", "food"))
    for mode, store in ((False, res), (True, app)):
        L["grp"] = groups(L, mode)
        t = L.groupby("grp").agg(n=("id", "size"), official=("hit", "mean"), food=("hit_food", "mean")).sort_values("n", ascending=False)
        print(f"\n== {label} ({'app grouping' if mode else 'web grouping'}): {len(L)} listings, {len(R)} official records")
        print(t.assign(official=(t.official * 100).round(1), food=(t.food * 100).round(1)).to_string())
        store[label] = {"listings": int(len(L)), "official_records": int(len(R)),
                        "groups": {g: {"n": int(r.n), "official": round(float(r.official), 3), "food": round(float(r.food), 3)} for g, r in t.iterrows()}}
    # the other direction: how many official restaurants/bars do the (cleaned, open) map listings hold?
    keepish = ~(L.ov_closed | L.j_closedname | L.closed21)
    got = set(R.biz.iloc[[m[i] for i in L.index[keepish] if i in m]])
    Rr = R[(R.jur == own) & R.kind.isin(["restaurant", "bar", "food"])].drop_duplicates("biz")
    cover = float(np.mean([b in got for b in Rr.biz])) if len(Rr) else None
    print(f"{label}: official food businesses found among open map listings: {cover*100:.1f}% of {len(Rr)}")
    res[label]["coverage"] = round(cover, 3)
    res[label]["official_food"] = int(len(Rr))

# statewide, per county: share of open, cleaned listings matched to an on-premises state liquor license (a lower bound)
LQ = F[(F.jur == "liq") & F.kind.isin(["restaurant", "bar", "brewery"])].reset_index(drop=True)
L = o[base & o.county.notna() & ~o.ov_closed & ~o.j_closedname].reset_index(drop=True)
m = official_match(L, LQ)
L["liq"] = L.index.map(lambda i: i in m)
L["grp"] = groups(L, True)
per = L.groupby("county").agg(listings=("id", "size"), liq_match=("liq", "mean"))
per["liq_onprem_records"] = LQ.groupby("county").size().reindex(per.index).fillna(0).astype(int)
got_l = L[L.liq].index.map(lambda i: LQ.biz.iat[m[i]])
per["liq_found"] = [float(np.mean([b in set(got_l) for b in LQ[LQ.county == c].drop_duplicates("biz").biz])) if (LQ.county == c).any() else None
                    for c in per.index]
bygrp = L.groupby("grp").liq.agg(["size", "mean"])
print("\n== statewide, matched to an on-premises liquor license, by app grouping\n" + bygrp.assign(mean=(bygrp["mean"] * 100).round(1)).to_string())
print("\n== per county\n" + per.sort_values("listings", ascending=False).round(3).to_string())
json.dump({"areas": res, "statewide_liquor_by_group": {g: {"n": int(r["size"]), "liq": round(float(r["mean"]), 3)} for g, r in bygrp.iterrows()},
           "per_county": {c: {k: (round(float(v), 3) if isinstance(v, float) else int(v)) for k, v in r.items() if v == v}
                          for c, r in per.iterrows()},
           "unplaced_liquor_records": int((F.jur.eq("liq") & F.lat.isna()).sum())},
          open(f"{TX}/calibration.json", "w"), indent=1)
json.dump(app, open(f"{TX}/calibration_app.json", "w"), indent=1)
