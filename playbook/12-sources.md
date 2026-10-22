# Texas sources (checked 2026-10-19)

Every host below was robots-checked with `pipeline/check_sources.py` (ClaudeBot, Claude-User, anthropic-ai) before any request.
User agent on every request: `TexasEatsBuild/1.0 (+nick@eatsranked.com)`. Raw files are in `data/raw/official/` (never public).

## Statewide

| Source | What | Terms | Cadence | Rows |
|---|---|---|---|---|
| TABC **License Information**, data.texas.gov `7hf9-qc9f` | Every TABC primary license: type, status, trade name, owner, address, county, original issue date, subordinate flags (`fb` Food & Beverage Certificate, `bp` brewpub, `lh` late hours) | Texas Open Data Portal, public information (Tex. Gov't Code ch. 552); no license field | Daily (rows updated 2026-10-16) | 127,996 (78,990 Active) |
| Comptroller **Mixed Beverage Gross Receipts**, data.texas.gov `naix-2893` | Monthly liquor/wine/beer/cover receipts per mixed-beverage permit location (Tax Code ch. 183) | Public; Comptroller privacy policy | Monthly (Aug 2026 complete; Sep partial) | 277k rows since Sep 2025 |
| Overture Maps places `2026-09-23.1` | Map listings (the statewide base), plus county and state outlines | CDLA-Permissive-2.0 / Apache-2.0 + Foursquare NOTICE | Monthly | see calibration |
| UCSD Google Local 2021 (`meta-Texas.json.gz`) | 2021 ratings — **web leaderboard only, never the app** | research dataset | frozen 2021 | — |

Active license mix: MB mixed beverage 20,835; BQ wine & beer off-premise 18,041; BG wine & beer on-premise 10,527; Q package store 5,930;
FB Food & Beverage Certificates 17,870 (TABC grants it only where food service is a real part of the business — our best statewide "this is a restaurant" record);
brewpub flag 311.

Texas DSHS licenses retail food only where no city/county program exists; its license search is reCAPTCHA-gated and there is no
bulk list (open-records request only — needs Nick's yes). Not used.

## City inspections (official scores, shown as official with the date; never recomputed)

| Jurisdiction | Source | Score system | Coverage | Status |
|---|---|---|---|---|
| **Austin** (Austin Public Health) | data.austintexas.gov `ecmv-9xxi`, Public Domain, bi-weekly (rows updated 2026-10-15) | 0–100 under TFER; the dataset's own `inspectionscorecategory`: 90+ (Green), 70–89 (Yellow), Under 70 (Red) | 20,421 inspections, 6,478 facilities, 2023-10-16 → 2026-09-24 | **used** |
| **El Paso** (City of El Paso DPH; city + county towns: Socorro, Horizon City, San Elizario, Canutillo, Fabens, Anthony, Clint…) | foodscores.elpasotexas.gov — the portal's own "download CSV" of one date-range search (2 requests; no robots.txt) | 0–100; "70 or above is passing", 60 or below initiates closure (portal text) | 24,036 inspections, 5,462 permits, 2023-10-02 → 2026-10-16 | **used**. Portal says scores are a summary; full reports by open-records request |
| **Arlington** | opendata.arlingtontx.gov "Food Establishments" (ArcGIS MapServer OD_Community/7), refreshed 2026-10-17 | 100 = perfect; city letter grade A 91–100, B 81–90, C 71–80, F <70 (city news page 2025-04) | 3,899 establishments, latest inspection only (2025-10 → 2026-09) | **used** (latest only) |
| Dallas | dallasopendata.com `dri5-wcct` **ended January 2024**; current results only on inspections.myhealthdepartment.com/dallas | — | — | **not used**: portal answers with a bot check; 2024 data is not shown as current |
| Fort Worth | data.fortworthtexas.gov "Health Inspections" points to inspections.myhealthdepartment.com/fort-worth-texas | demerits (0 perfect, >30 action) | — | **not used** (bot check) |
| Houston | data.houstontx.gov food service inspections stop at FY2015 (3/31/2015) | — | — | **not used**: Houston has no official inspection data in the app, and we say so |
| San Antonio | Metro Health reports on sa.gov — **sa.gov robots.txt disallows Claude**; data.sanantonio.gov disallows `/api/` and lists no inspection set | — | — | **not used** |
| Plano, Harris County, Travis County, Bexar County | search-only portals / apps | — | — | not used |

## Property values
County appraisal districts (HCAD, DCAD, TCAD, BCAD) — terms vary and none clearly allows redistribution: **no building-value board** in v1.

## Honors
MICHELIN Guide Texas (guide.michelin.com, robots allows), James Beard Foundation (jamesbeard.org, allows). See `data/research/honors_notes.md`.
