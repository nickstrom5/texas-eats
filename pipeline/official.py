"""Official records for Texas -> one table of licensed / inspected food and drink businesses.

Sources (see playbook/12-sources.md):
- "liq": Texas Alcoholic Beverage Commission, "TABC License Information" (data.texas.gov 7hf9-qc9f, daily): every primary license,
         statewide, with its type, status, trade name, owner, address and subordinate flags (FB = Food and Beverage Certificate,
         BP = brewpub, LH = late hours). Only businesses with an alcohol license, and no coordinates.
- "aus": Austin Public Health, "Food Establishment Inspection Scores" (data.austintexas.gov ecmv-9xxi, bi-weekly, last 3 years).
- "elp": City of El Paso Department of Public Health, Food Establishment Scores (foodscores.elpasotexas.gov CSV export, last 3 years;
         the city and the county towns it inspects).
- "arl": City of Arlington, "Food Establishments" (opendata.arlingtontx.gov, ArcGIS; latest inspection per establishment).

load() returns: jur, lic (our id), name, keys (name keys), addr, city, zip, num, street, lat, lon, kind, active.
kind: restaurant | bar | brewery | retail | venue | food | other.
"""
import os, re, json
import numpy as np, pandas as pd
from common import norm_name, RAW, name_sim, _stems, GENERIC, canon_city

OFF = os.path.join(RAW, "official")
DIRS = {"N": "N", "S": "S", "E": "E", "W": "W", "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}
TYPES = set("ST STREET AVE AV AVENUE BLVD BOULEVARD RD ROAD DR DRIVE LN LANE CT COURT PL PLACE PKWY PARKWAY TER TRL TRAIL WAY HWY CIR "
            "CIRCLE PLZ SQ MALL BND PASS XING RUN ROW WALK RDG LOOP FWY FREEWAY EXPY EXPRESSWAY".split())


def road(a):
    """One spelling for numbered roads: 'US HIGHWAY 290' = 'US-290' = 'US 290'; 'STATE HIGHWAY 71' = 'TX-71' = 'SH 71';
    'N INTERSTATE 35' = 'IH 35' = 'I-35'; 'FARM TO MARKET 1960' = 'FM 1960'; 'RANCH ROAD 620' = 'RR 620' = 'RM 620'; 'COUNTY ROAD 5' = 'CR 5'."""
    a = re.sub(r"(\d)\s*&\s*(\d)", r"\1-\2", a.upper())
    a = re.sub(r"\b(US|TX|SH|CR|I|IH|FM|RM|RR)-(\w)", r"\1 \2", a)
    a = re.sub(r"\b(?:INTERSTATE(?: HIGHWAY| HWY)?|IH|I H)\s*(?=\d)", "I ", a)
    a = re.sub(r"\b(?:US|U S)\s+(?:HIGHWAY|HWY)\b", "US", a)
    a = re.sub(r"\b(?:FARM[- ]TO[- ]MARKET(?: ROAD| RD)?|FARM (?:ROAD|RD)|F M)\b", "FM", a)
    a = re.sub(r"\b(?:RANCH[- ]TO[- ]MARKET(?: ROAD| RD)?|RANCH (?:ROAD|RD)|RR|RM)\b(?=\s*\d)", "RM", a)
    a = re.sub(r"\b(?:STATE (?:HIGHWAY|HWY|ROAD|RD)|SH|TEXAS (?:HIGHWAY|HWY|STATE HIGHWAY)|TX (?:HIGHWAY|HWY)|TX)\b(?=\s*\d)", "SH", a)
    a = re.sub(r"\b(?:COUNTY (?:HIGHWAY|HWY|ROAD|RD)|CO RD|CTY (?:HWY|RD)|CR)\b", "CR", a)
    a = re.sub(r"\bHIGHWAY\b", "HWY", a)
    return re.sub(r"\b(US|SH|CR|HWY|FM|RM|I) (\w+)\s*-\s*\w+", r"\1 \2", a)


ORD = {"FIRST": "1ST", "SECOND": "2ND", "THIRD": "3RD", "FOURTH": "4TH", "FIFTH": "5TH", "SIXTH": "6TH", "SEVENTH": "7TH",
       "EIGHTH": "8TH", "NINTH": "9TH", "TENTH": "10TH", "ELEVENTH": "11TH", "TWELFTH": "12TH"}


def street_key(a):
    """'2505 Monroe St' -> ('2505', 'MONROE'); '1000 OSAGE STREET' -> ('1000', 'OSAGE'); 'E Colfax Ave' keeps 'COLFAX'."""
    if not isinstance(a, str):
        return None, None
    a = re.sub(r"[.,#]", " ", road(a))
    m = re.match(r"^\s*(\d+)[A-Z]?(?:\s*-\s*\d+[A-Z]?)?\s+(.*)$", a)
    if not m:
        return None, None
    words = [w for w in m.group(2).split() if w]
    if len(words) > 1 and words[0] in DIRS:
        words = words[1:]
    core = []
    for w in words:
        if w in TYPES and core:
            break
        core.append(w)
    core = [ORD.get(w, w) for w in core]
    return m.group(1), " ".join(core[:3]) or None


def street_compat(a, b):
    """Same street, or one is a whole-word prefix of the other: Boulder's 2025 set sometimes truncates ("1206 CENTAUR" = Centaur Village Dr)."""
    if not isinstance(a, str) or not isinstance(b, str) or not a or not b:
        return False
    return a == b or a.startswith(b + " ") or b.startswith(a + " ")


def street_nums(a):
    """'157-159 W Main St' -> {'157', '159'}; '2505 Monroe St' -> {'2505'}."""
    if not isinstance(a, str):
        return set()
    a = road(a)
    m = re.match(r"^\s*(\d+)[A-Z]?(?:\s*-\s*(\d+)[A-Z]?)?\s", a.upper() + " ")
    if not m:
        return set()
    lo = int(m.group(1)); hi = int(m.group(2)) if m.group(2) else lo
    if hi < lo:   # "1500-02"
        hi = int(str(lo)[: len(str(lo)) - len(m.group(2))] + m.group(2)) if m.group(2) else lo
    return {str(x) for x in range(lo, hi + 1, 2 if (hi - lo) % 2 == 0 else 1)} if 0 <= hi - lo <= 12 else {str(lo)}


def _names(*vals):
    out = []
    for v in vals:
        if not isinstance(v, str):
            continue
        v = re.sub(r"\s*\((?:MOBILE|MOBILE UNIT|COMMISSARY|CATERING|SPECIAL EVENT|SPEC EVENT|TEMP(?:ORARY)? EVENT|CP|INSIDE [^)]*)\)\s*$", "", v, flags=re.I)
        for part in re.split(r"\s*/\s*|\s+\bdba\b\s+|\s+&\s+(?=[A-Z][a-z])", v, flags=re.I):
            k = norm_name(re.sub(r"\b(?:LLC|INC|CORP|CORPORATION|LTD|CO)\b\.?", "", part, flags=re.I))
            if k and k not in out:
                out.append(k)
    return out



# TABC license types (after the September 2021 consolidation). On-premises types are bars and restaurants serving alcohol; a Food and
# Beverage Certificate (FB) on one says food service is a real part of the business. The rest are stores, makers, distributors,
# carriers, nonprofit events (NT, temporary) and veterans' and private clubs.
TABC_NAME = {"MB": "Mixed Beverage Permit", "BG": "Wine and Beer Retailer's Permit", "BE": "Beer Retailer's On-Premise License",
             "N": "Private Club Registration Permit", "NB": "Private Club Registration Permit", "NE": "Private Club (veterans)",
             "BQ": "Wine and Beer Retailer's Off-Premise Permit", "BF": "Beer Retailer's Off-Premise License", "Q": "Package Store Permit",
             "P": "Package Store Permit", "BW": "Brewer's License", "BN": "Brewer's License (nonresident)", "G": "Winery Permit",
             "D": "Distiller's and Rectifier's Permit"}
TABC_KIND = {"MB": "bar", "BG": "bar", "BE": "bar", "N": "bar", "NB": "bar", "NE": "venue", "BQ": "retail", "BF": "retail", "Q": "retail",
             "P": "retail", "BW": "brewery", "G": "brewery", "D": "brewery"}
ONPREM = ("restaurant", "bar", "brewery")
LIST_DATE = "2026-10-19"   # TABC rows fetched (data.texas.gov rows updated 2026-10-16)


def liq_kind(t):
    """Kind of a license from its shown type name (texas.py passes ltype strings)."""
    for code, name in TABC_NAME.items():
        if t == name or (t or "").startswith(name):
            return TABC_KIND[code] if TABC_KIND[code] != "bar" else "bar"
    return None


def _zip(z):
    z = re.sub(r"\D", "", str(z or ""))
    return z[:5] if len(z) >= 5 else ""


def load_liquor():
    d = pd.read_csv(f"{OFF}/tabc_licenses.csv", dtype=str)
    d = d[d.primary_status.isin(["Active"]) & d.license_type.isin(TABC_KIND)].fillna("")
    # an "Active" row whose expiration is more than a year before the list date is stale (renewals pending stay)
    d = d[~((d.expiration_date != "") & (d.expiration_date < "2025-10-19"))]
    rows = []
    for _, r in d.iterrows():
        num, st = street_key(r.address)
        kind = TABC_KIND[r.license_type]
        fb, bp = r.fb == "1", r.bp == "1"
        if kind == "bar" and fb:
            kind = "restaurant"
        if bp:
            kind = "brewery"
        lid = str(r.license_id).split(".")[0]
        ltype = TABC_NAME[r.license_type] + (" + Food and Beverage Certificate" if fb else "") + (" + Brewpub" if bp else "")
        rows.append({"jur": "liq", "lic": "TABC-" + lid, "name": r.trade_name or r.owner, "dba": r.trade_name or None, "holder": r.owner or None,
                     "keys": _names(r.trade_name, r.owner), "addr": r.address, "city": canon_city(r.city), "zip": _zip(r.zip), "num": num,
                     "street": st, "lat": np.nan, "lon": np.nan, "kind": kind, "active": True, "ltype": ltype, "code": r.license_type,
                     "fb": fb, "bp": bp, "expires": str(r.expiration_date or "")[:10] or None,
                     "since": str(r.original_issue_date or "")[:10] or None, "county": (r.county or "").title() or None,
                     # the Comptroller's mixed beverage reports carry the permit as "MB" + the license id, or the pre-2021 number
                     "permits": [r.license_type + lid] + ([re.sub(r"\s+", "", r.legacy_clp)] if r.legacy_clp else [])})
    return pd.DataFrame(rows)


OTHER = re.compile(r"\((?:MOBILE|MOBILE UNIT|COMMISSARY|CATERING|SPECIAL EVENT|TEMP(?:ORARY)? EVENT)\)|\b(?:SCHOOL|ELEMENTARY|MIDDLE|HIGH SCHOOL|"
                   r"ACADEMY|PRESCHOOL|CHILDCARE|CHILD CARE|DAYCARE|DAY CARE|HOSPITAL|JAIL|DETENTION|FOOD BANK|SENIOR|NURSING|ISD|"
                   r"MOBILE|FOOD TRUCK|CATERING|CATERER|COMMISSARY|CONCESSION)\b", re.I)


def _split_addr(a):
    """'6711 N Interstate 35 Austin, TX 78752-4307' -> ('6711 N Interstate 35', 'Austin'); '2900 MESA, SUITE# F, EL PASO, TX 79902' -> ('2900 MESA', 'El Paso')."""
    a = (a or "").strip()
    m = re.match(r"^(.*?)(?:,\s*([A-Za-z .']+?))?,?\s+TX\s*\d{5}(?:-\d{4})?\s*$", a, re.I)
    if m:
        street, city = m.group(1), m.group(2)
        if not city:   # Austin: "6711 N Interstate 35 Austin, TX" -> city is the last word(s) before the comma
            m2 = re.match(r"^(.*\S)\s+(Austin|Del Valle|Manor|Pflugerville|Sunset Valley|West Lake Hills|Rollingwood|Lakeway|Bee Cave|Cedar Park|Round Rock|Leander|Buda|Kyle|Dripping Springs|Lago Vista|Jonestown|Spicewood|Manchaca|Creedmoor)$", street, re.I)
            if m2:
                street, city = m2.group(1), m2.group(2)
        street = re.split(r",\s*(?:STE|SUITE|UNIT|#|BLDG|SPACE|APT)", street, flags=re.I)[0]
        return street.strip(" ,"), canon_city(city) if city else None
    return a.split(",")[0].strip(), None


def _row(jur, lic, name, addr, city, z, la, lo, kind, active=True, ltype=None):
    num, st = street_key(addr)
    if OTHER.search(name or ""):
        kind = "other"
    return {"jur": jur, "lic": lic, "name": name, "dba": name, "holder": None, "keys": _names(name), "addr": addr, "city": city,
            "zip": _zip(z), "num": num, "street": st, "lat": la, "lon": lo, "kind": kind, "active": active, "ltype": ltype}


def load_austin():
    d = pd.DataFrame(json.load(open(f"{OFF}/austin_inspections.json")))
    rows = []
    for fid, g in d.sort_values("inspection_date").groupby("facility_id"):
        r = g.iloc[-1]
        street, city = _split_addr(r.address)
        la = float(r.lat) if isinstance(r.get("lat"), str) else np.nan
        lo = float(r.lng) if isinstance(r.get("lng"), str) else np.nan
        rows.append(_row("aus", "AUS-" + str(fid), r.restaurant_name, street, city or "Austin", r.zip_code, la, lo, "food",
                         active=g.inspection_date.max() >= "2025-04-01"))
    return pd.DataFrame(rows)


def load_elpaso():
    d = pd.read_csv(f"{OFF}/elpaso_scores.csv", dtype=str)
    d["d"] = pd.to_datetime(d.Date, format="%m/%d/%Y").dt.strftime("%Y-%m-%d")
    rows = []
    for pid, g in d.sort_values("d").groupby("Permit ID"):
        r = g.iloc[-1]
        street, _ = _split_addr(r.Address)
        city = canon_city(r.City) if r.City and r.City.upper() != "EL PASO COUNTY" else None
        rows.append(_row("elp", "ELP-" + pid, r["Business Name"], street, city, r["Zip Code"], np.nan, np.nan, "food",
                         active=g.d.max() >= "2025-04-01"))
    return pd.DataFrame(rows)


ARL_KIND = {"Full Service Restaurant": "restaurant", "Fast Food": "restaurant", "Moderate Food Service": "restaurant",
            "Light Food Service": "food", "Bar / Lounge": "bar", "Retail Bakery": "food", "Delicatessen": "food",
            "Coffee Shop": "food", "Kiosk": "food", "Convenience Store": "retail", "Grocery": "retail", "Meat Market": "retail"}


def load_arlington():
    rows = []
    for r in json.load(open(f"{OFF}/arlington_food.json")):
        street = re.split(r",|\s+(?:STE|SUITE|#)\b", r["PropertyAddress"] or "", flags=re.I)[0].strip()
        kind = ARL_KIND.get(r["EstablishmentType"], "other")
        rows.append(_row("arl", "ARL-" + str(r["OBJECTID"]), r["FacilityName"], street, "Arlington", "", r.get("lat") or np.nan,
                         r.get("lon") or np.nan, kind, ltype=r["EstablishmentType"]))
    return pd.DataFrame(rows)


def load():
    df = pd.concat([load_liquor(), load_austin(), load_elpaso(), load_arlington()], ignore_index=True)
    # one business can hold several records (a TABC license and a city inspection): same address and a name in common
    df["biz"] = np.arange(len(df))
    town = df.city.fillna("").str.upper().str.strip()
    for num, g in df[df.num.notna() & df.street.notna()].groupby("num"):
        idx = list(g.index)
        if len(idx) < 2 or len(idx) > 400:
            continue
        for x in range(len(idx)):
            for y in range(x + 1, len(idx)):
                a, b = idx[x], idx[y]
                if not street_compat(df.at[a, "street"], df.at[b, "street"]):
                    continue
                if not ((df.at[a, "zip"] and df.at[a, "zip"] == df.at[b, "zip"]) or (town[a] and town[a] == town[b])):
                    continue
                ka, kb = df.at[a, "keys"], df.at[b, "keys"]
                if not ka or not kb:
                    continue
                if any(name_sim(p, q) >= 85 or ((_stems(p) - GENERIC) & (_stems(q) - GENERIC)) for p in ka for q in kb):
                    old, new = df.at[b, "biz"], df.at[a, "biz"]
                    df.loc[df.biz == old, "biz"] = new
    return df


# ---------------------------------------------------------------- inspections: each city's own score, never recomputed
def austin_inspections():
    """One row per inspection: facility, date, score (0-100 under the Texas Food Establishment Rules), the dataset's own score
    category (90+ Green / 70-89 Yellow / Under 70 Red) and type (Routine / Follow-Up). Oldest first."""
    d = pd.DataFrame(json.load(open(f"{OFF}/austin_inspections.json")))
    out = pd.DataFrame({"lic": "AUS-" + d.facility_id.astype(str), "d": d.inspection_date.str[:10],
                        "score": pd.to_numeric(d.score, errors="coerce"),
                        "band": d.inspectionscorecategory.fillna("").str.strip().str.extract(r"\((\w+)\)")[0],
                        "typ": d.process_description.fillna(""), "iid": pd.to_numeric(d.inspectionid, errors="coerce")})
    out["re"] = out.typ.str.contains("Follow", case=False)
    return out.sort_values(["lic", "d", "re", "iid"]).reset_index(drop=True)


def elpaso_inspections():
    """One row per inspection: permit, date, score (0-100; the city calls 70 or above passing) and type
    (1310 Routine Inspection / 1320 Re-inspection / 1300 Site Assessment). Oldest first."""
    d = pd.read_csv(f"{OFF}/elpaso_scores.csv", dtype=str)
    out = pd.DataFrame({"lic": "ELP-" + d["Permit ID"], "d": pd.to_datetime(d.Date, format="%m/%d/%Y").dt.strftime("%Y-%m-%d"),
                        "score": pd.to_numeric(d.Score, errors="coerce"),
                        "typ": d["Sanitary Code"].fillna("").str.replace(r"^\d+\s+", "", regex=True)})
    out["re"] = out.typ.str.contains("Re-inspection", case=False)
    out["band"] = None
    return out.sort_values(["lic", "d", "re"]).reset_index(drop=True)


def arlington_inspections():
    """Latest inspection per establishment: score, the city's letter grade (A 91-100, B 81-90, C 71-80, F below 70 per the city),
    inspection type and the city's result ("Attempt": Pass without Followup / Pass with Followup / Closed by COA ...)."""
    rows = []
    for r in json.load(open(f"{OFF}/arlington_food.json")):
        sc = pd.to_numeric((r["InspectionScore"] or "").strip(), errors="coerce")
        dt = pd.to_datetime(r["InspectionDateText"], format="%m/%d/%Y", errors="coerce")
        rows.append({"lic": "ARL-" + str(r["OBJECTID"]), "d": dt.strftime("%Y-%m-%d") if dt == dt else None, "score": sc,
                     "typ": r["Inspection"], "result": r["Attempt"], "re": "Follow" in (r["Inspection"] or ""), "band": None})
    return pd.DataFrame(rows)


def mixbev_receipts(months=12):
    """Texas Comptroller, Mixed Beverage Gross Receipts (data.texas.gov naix-2893, Tax Code ch. 183): the gross receipts each mixed
    beverage permit location reports every month (liquor, wine, beer, cover charges). Returns {permit: {...}} over the last `months`
    complete months: total, liquor, wine, beer, months reported, first and last month. Reported figures, not estimates."""
    d = pd.read_csv(f"{OFF}/mixbev_receipts.csv", dtype=str)
    d["m"] = d.obligation_end_date_yyyymmdd.str[:7]
    per = d.groupby("m").size()
    full = per[per >= 0.8 * per.max()].index.sort_values()   # a month still coming in (Sept 2026 had 9,280 of ~22,400) isn't complete
    keep = list(full[-months:])
    d = d[d.m.isin(keep)]
    for c in ("liquor_receipts", "wine_receipts", "beer_receipts", "cover_charge_receipts", "total_receipts"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
    g = d.groupby("tabc_permit_number").agg(total=("total_receipts", "sum"), liquor=("liquor_receipts", "sum"), wine=("wine_receipts", "sum"),
                                             beer=("beer_receipts", "sum"), n=("m", "nunique"), first=("m", "min"), last=("m", "max"),
                                             name=("location_name", "last"))
    return {k: v for k, v in g.to_dict("index").items()}, keep[0], keep[-1]
