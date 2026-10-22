"""Geocode addresses Overture's address points can't place (rural counties have few) with the US Census
Bureau's public batch geocoder, and cache the answers in data/tx/geocode_census.json.

Inputs: official records still without a point (data/tx/official.pkl) and, when present, data/research/geocode_todo.json (verified
research addresses the app build couldn't place). Only exact Texas matches are kept. One batch request at a time, honest UA.
Usage: python geocode_census.py   (then re-run geocode_official.py's consumers: calibrate.py / colorado.py read the cache)
"""
import csv, io, json, os, time
import pandas as pd
import requests
from common import TX, DATA

cache_path = f"{TX}/geocode_census.json"
cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
misses = set(cache.pop("_misses", []))
F = pd.read_pickle(f"{TX}/official.pkl")
todo = []
_need = F.lat.isna() & F.kind.isin(["restaurant", "bar", "brewery", "food"])   # Texas: only food and drink records (not 28k stores)
for a, c, z in zip(F.loc[_need, "addr"], F.loc[_need, "city"], F.loc[_need, "zip"]):
    if isinstance(a, str) and a.strip():
        todo.append((a.strip(), (c or "").strip().title() if isinstance(c, str) else "", z or ""))
rt = f"{DATA}/research/geocode_todo.json"
if os.path.exists(rt):
    for q in json.load(open(rt)):
        parts = [p.strip() for p in q.split(",")]
        if len(parts) >= 3:
            todo.append((parts[0], parts[1], parts[2].replace("TX", "").strip()))


def qkey(a, c, z):
    return f"{a}, {c}, TX {z}".strip()


todo = [t for t in dict.fromkeys(todo) if qkey(*t) not in cache and qkey(*t) not in misses]
print("to geocode:", len(todo))
URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
UA = {"User-Agent": "TexasEatsBuild/1.0 (+nick@eatsranked.com)"}
for start in range(0, len(todo), 2500):
    chunk = todo[start:start + 2500]
    buf = io.StringIO()
    w = csv.writer(buf)
    for i, (a, c, z) in enumerate(chunk):
        w.writerow([i, a, c, "TX", z])
    for attempt in range(3):
        try:
            r = requests.post(URL, files={"addressFile": ("a.csv", buf.getvalue(), "text/csv")},
                              data={"benchmark": "Public_AR_Current"}, headers=UA, timeout=600)
            r.raise_for_status()
            break
        except Exception as e:
            print("retry", attempt, e); time.sleep(10)
    else:
        continue
    got = 0
    for row in csv.reader(io.StringIO(r.text)):
        if len(row) < 3:
            continue
        i = int(row[0]); q = qkey(*chunk[i])
        a_, c_, z_ = chunk[i]
        mt = row[4].upper() if len(row) > 4 else ""
        agrees = (z_ and mt.rstrip().endswith(z_)) or (c_ and f", {c_.upper()}, TX" in mt)
        if row[2] == "Match" and len(row) >= 6 and row[3] in ("Exact", "Non_Exact") and ", TX," in row[4] and agrees:
            lon, lat = map(float, row[5].split(","))
            cache[q] = {"lat": round(lat, 6), "lon": round(lon, 6), "matched": row[4], "exact": row[3] == "Exact"}
            got += 1
        else:
            misses.add(q)
    print(f"batch {start // 2500 + 1}: {got}/{len(chunk)} matched", flush=True)
    cache["_misses"] = sorted(misses)
    json.dump(cache, open(cache_path, "w"), indent=0, sort_keys=True)
    cache.pop("_misses")
    time.sleep(3)
cache["_misses"] = sorted(misses)
json.dump(cache, open(cache_path, "w"), indent=0, sort_keys=True)
print(len(cache) - 1, "cached,", len(misses), "unmatched")
# apply to official.pkl
F["geo"] = F.geo.astype(object)
for i in F.index[F.lat.isna()]:
    a, c, z = F.at[i, "addr"], F.at[i, "city"], F.at[i, "zip"]
    if not isinstance(a, str):
        continue
    h = cache.get(qkey(a.strip(), c.strip().title() if isinstance(c, str) else "", z if isinstance(z, str) else ""))
    zz = z if isinstance(z, str) else ""; cc = c.strip().upper() if isinstance(c, str) else ""
    if h and ((zz and h["matched"].upper().rstrip().endswith(zz)) or (cc and f", {cc}, TX" in h["matched"].upper())):
        F.at[i, "lat"], F.at[i, "lon"], F.at[i, "geo"] = h["lat"], h["lon"], "census"
F.to_pickle(f"{TX}/official.pkl")
print("still without a point:", F[F.lat.isna()].groupby("jur").size().to_dict())
