"""Place official records that have no coordinates (TABC licenses, El Paso inspections) on Overture address points.

Match: same house number and street key, then the same zip (else the same town, else a single unambiguous point cluster).
-> data/tx/official.pkl (official.load() plus lat/lon/geo columns), data/tx/ap_index.pkl (address-point index, cached)
"""
import os, re, time, pickle
import numpy as np, pandas as pd
from common import TX, canon_city
import official
from official import street_key

t = time.time()
idx_path = f"{TX}/ap_index.pkl"
if os.path.exists(idx_path):
    AP = pd.read_pickle(idx_path)
else:
    AP = pd.read_parquet(f"{TX}/addresses_tx.parquet", columns=["number", "street", "postcode", "postal_city", "state", "muni", "lat", "lon"])
    AP = AP[AP.state.isin(["TX", None]) | AP.state.isna()]
    keys = [street_key(f"{n} {s}") for n, s in zip(AP.number.astype(str), AP.street.fillna(""))]
    AP["num"] = [k[0] for k in keys]
    AP["key"] = [k[1] for k in keys]
    AP["zip"] = AP.postcode.fillna("").astype(str).str[:5]
    AP["town"] = [(canon_city(re.sub(r"^(?:City|Town) of ", "", m)) or "").lower() if isinstance(m, str) else "" for m in AP.muni]
    AP["ptown"] = AP.postal_city.map(lambda c: (canon_city(c) or "").lower() if isinstance(c, str) else "")
    AP = AP[AP.num.notna() & AP.key.notna()][["num", "key", "zip", "town", "ptown", "lat", "lon"]].reset_index(drop=True)
    AP.to_pickle(idx_path)
print("address points:", len(AP), round(time.time() - t), "s", flush=True)
F = official.load()
# Texas has 11.5M address points: group only those at a house number and street some record needs (millions of tiny groups
# took longer than the whole build)
need = set(zip(F.num, F.street))
APn = AP[pd.Series(list(zip(AP.num, AP.key))).isin(need).values]
by = {k: g for k, g in APn.groupby(["num", "key"])}
print("indexed", len(by), "of", len(need), "needed addresses", round(time.time() - t), "s", flush=True)


def place(num, key, zip5, city):
    g = by.get((num, key))
    if g is None:
        return None
    town = (canon_city(city) or "").lower() if isinstance(city, str) else ""
    for sel, how in ((g.zip == zip5, "zip"), ((g.town == town) | (g.ptown == town), "town")):
        h = g[sel] if (zip5 if how == "zip" else town) else g.iloc[0:0]
        if len(h) and (h.lat.max() - h.lat.min()) < 0.01 and (h.lon.max() - h.lon.min()) < 0.013:
            return float(h.lat.median()), float(h.lon.median()), how
    return None


F["geo"] = np.where(F.lat.notna(), "source", None)
miss = F.lat.isna() & F.num.notna() & F.street.notna()
hits = [place(n, k, z, c) for n, k, z, c in zip(F.loc[miss, "num"], F.loc[miss, "street"], F.loc[miss, "zip"], F.loc[miss, "city"])]
for i, h in zip(F.index[miss], hits):
    if h:
        F.at[i, "lat"], F.at[i, "lon"], F.at[i, "geo"] = h
F.to_pickle(f"{TX}/official.pkl")
print("placed:", F.geo.value_counts(dropna=False).to_dict(), "| by source still without a point:",
      F[F.lat.isna()].groupby("jur").size().to_dict(), round(time.time() - t), "s")
