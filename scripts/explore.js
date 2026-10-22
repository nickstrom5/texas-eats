// Texas Eats web app: the iPhone app's guides, search, filters, map and place details, in the browser.
// Keep its guide rules in step with TexasEats/Models/Guide.swift and its search with TexasEats/Models/Search.swift.
// Same data as the app, split by scripts/make-site.py into data/core.json (list, search and map columns), data/ids.json (each place's
// stable id, fetched at the first tap, key, scroll or hover, so a visit that only looks doesn't download it; saved places and #p= links
// wait for it) and data/detail-<county>.json (phones, websites, notes, TABC licenses, inspection histories), fetched per
// county when a place there is opened. Every data file carries the version of the core.json it was built with (core.json "ver",
// detail "_v", ids "v"): files from another build are fetched again, and never mixed in, because ids and details are keyed by row. No cookies, no trackers; saved places and the last guide live in this browser's localStorage only
// (keys start with txeats-: other state sites share the nickstrom5.github.io origin).
// The page runs under a strict Content-Security-Policy (hash-pinned inline script and style): never add inline event handlers or
// inline style attributes to the HTML built here; set properties from code instead.
(() => {
  "use strict";
  const BASE = document.documentElement.dataset.base || "";
  const $ = (s) => document.querySelector(s);
  // every value that goes into innerHTML passes through esc(), numbers included (the data file is trusted, but not that much)
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const own = (o, k) => typeof k === "string" && Object.prototype.hasOwnProperty.call(o, k);   // Object.hasOwn, for older Safari too
  const PREFIX = "txeats-";
  const store = {
    get(k, d) { try { const v = localStorage.getItem(PREFIX + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(PREFIX + k, JSON.stringify(v)); } catch { /* private mode */ } },
  };
  // only http(s) links leave the page; bare hosts ("example.com/menu") get https://
  const safeUrl = (u) => {
    u = String(u ?? "").trim();
    if (/^https?:\/\/[^\s"'<>\\]+$/i.test(u)) return u;
    if (/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}(?:[/?#][^\s"'<>\\]*)?$/i.test(u)) return "https://" + u;
    return null;
  };
  const num = (x) => (x == null || x === "" || !Number.isFinite(Number(x)) ? null : Number(x));
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const fmtDate = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s ?? "")); return m ? `${MONTHS[+m[2] - 1]} ${+m[3]}, ${m[1]}` : String(s ?? ""); };
  const fmtMonth = (s) => { const m = /^(\d{4})-(\d{2})/.exec(String(s ?? "")); return m ? `${MONTHS[+m[2] - 1]} ${m[1]}` : String(s ?? ""); };
  const TABC_SEARCH = "https://www.tabc.texas.gov/public-information/tabc-public-inquiry/";
  const MIXBEV = "https://data.texas.gov/d/naix-2893";
  const INS_CITY = ["Austin", "El Paso", "Arlington"], INS_KEY = ["aus", "elp", "arl"];
  const INS_URL = ["https://data.austintexas.gov/Health-and-Community-Services/Food-Establishment-Inspection-Scores/ecmv-9xxi",
    "https://foodscores.elpasotexas.gov/", "https://opendata.arlingtontx.gov/datasets/food-establishments"];
  const INS_SCALE = ["Scores are out of 100 under the Texas Food Establishment Rules; higher is better. Austin's own bands: Green 90–100, Yellow 70–89, Red under 70.",
    "Scores are out of 100; higher is better. El Paso: 70 or above is passing, and 60 or below starts a closure. The city calls these scores a summary; full reports are by open-records request.",
    "Scores are out of 100; higher is better. Arlington's letter grades: A 91–100, B 81–90, C 71–80, F under 70. Arlington publishes the latest inspection only."];
  const money = (k) => (k >= 1000 ? `$${(k / 1000).toFixed(1)}M` : `$${k}K`);

  // ---------------------------------------------------------------- search (a port of TexasEats/Models/Search.swift)
  const typeSyn = { avenue: "ave", av: "ave", street: "st", boulevard: "blvd", road: "rd", drive: "dr", place: "pl", court: "ct",
    parkway: "pkwy", highway: "hwy", lane: "ln", trail: "trl", circle: "cir", terrace: "ter" };
  // directions and Texas road names: "north lamar" finds "N Lamar Blvd", "interstate 35" finds "I-35"
  const syn = { ...typeSyn, north: "n", south: "s", east: "e", west: "w", northwest: "nw", northeast: "ne", southwest: "sw", southeast: "se",
    saint: "st", mount: "mt", fort: "ft", interstate: "i", ih: "i", freeway: "fwy", expressway: "expy" };
  const abbrs = new Set(Object.values(syn)), typeAbbrs = new Set(Object.values(typeSyn));
  const BBQ = 1, TEXMEX = 2, TAQUERIA = 4, KOLACHE = 8, CFS = 16, OLDEST = 32, BREWPUB = 64;
  // a dish ("brisket", "breakfast tacos") is not a tag: it's in each hand-checked place's search text, so it finds the places serving it
  const tagPhrases = [["barbecue", BBQ], ["barbeque", BBQ], ["bbq", BBQ], ["tex mex", TEXMEX], ["texmex", TEXMEX], ["taquerias", TAQUERIA],
    ["taqueria", TAQUERIA], ["kolaches", KOLACHE], ["kolache", KOLACHE], ["chicken fried steaks", CFS], ["chicken fried steak", CFS]];
  function normalize(s) {
    let t = String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    t = t.replace(/\b([a-z0-9])\s*&\s*([a-z0-9])\b/g, "$1$2").replace(/&/g, " and ").replace(/['’`]/g, "");
    return t.replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  }
  const normAddr = (s) => normalize(s).split(" ").map((w) => (own(syn, w) ? syn[w] : w)).join(" ");

  function parse(text) {
    const q = { tokens: [], town: null, townPhrase: null, tag: 0, tagPhrase: null, tagStem: null, townNeedle: null };
    let raw = normalize(text).split(" ").filter(Boolean);
    if (!raw.length) return q;
    let mapped = raw.map((w) => (own(syn, w) ? syn[w] : w));
    const find = (phrase) => {
      const p = phrase.split(" ");
      for (let i = 0; i + p.length <= mapped.length; i++) if (p.every((w, k) => mapped[i + k] === w)) return [i, i + p.length];
      return null;
    };
    const cut = ([a, b]) => { const words = raw.slice(a, b).join(" "); raw.splice(a, b - a); mapped.splice(a, b - a); return words; };
    for (const [phrase, tag] of tagPhrases) { const r = find(normalize(phrase)); if (r) { q.tag = tag; q.tagPhrase = cut(r); break; } }
    if (q.tagPhrase) { const stem = normalize(q.tagPhrase).replace(/s$/, ""); q.tagStem = stem ? " " + stem : null; }
    // the longest town named in the query wins, unless a street type follows it ("houston st" is a street)
    for (const key of TOWN_KEYS_BY_LENGTH) {
      const r = find(key);
      if (r && !(r[1] < mapped.length && typeAbbrs.has(mapped[r[1]]))) { q.town = TOWN_KEYS[key]; q.townPhrase = cut(r); q.townNeedle = " " + normalize(q.townPhrase); break; }
    }
    const stop = new Set(["the", "and", "of", "a", "in", "near", "me"]);   // "barbecue near me" isn't a place named "Me"
    let idx = raw.map((_, i) => i);
    // stop words stay only when they're all there is ("the"); next to a guide or a town ("kolaches near me") they go
    if (q.tag || q.town || idx.some((i) => !stop.has(mapped[i]))) idx = idx.filter((i) => !stop.has(mapped[i]));
    idx.forEach((i, n) => {
      const token = raw[i], isLast = n === idx.length - 1;
      if (own(syn, token)) { q.tokens.push([` ${syn[token]} `, ` ${token}`]); return; }
      const whole = (abbrs.has(token) && (!isLast || token.length > 1)) || (token.length <= 2 && !isLast);
      const needles = [" " + token + (whole ? " " : "")];
      if (isLast && token.length >= 3) for (const [word, abbr] of Object.entries(typeSyn)) if (word !== token && word.startsWith(token)) needles.push(` ${abbr} `);
      q.tokens.push(needles);
    });
    // "brady st": a finished street type sticks to the word before it
    if (q.tokens.length >= 2 && idx.length && typeAbbrs.has(mapped[idx[idx.length - 1]])) {
      const last = idx[idx.length - 1], prev = idx[idx.length - 2];
      q.tokens.splice(-2, 2, [` ${mapped[prev]} ${mapped[last]} `, ` ${raw[prev]} ${raw[last]}`]);
    }
    return q;
  }
  const qEmpty = (q) => !q.tokens.length && !q.town && !q.tag;
  function matches(p, q) {
    if (q.tag && !(p.g & q.tag)) { if (!q.tagStem || !p.nameText.includes(q.tagStem)) return false; }
    if (q.town && p.c !== q.town) { if (!q.townNeedle || !p.nameText.includes(q.townNeedle)) return false; }
    return q.tokens.every((needles) => needles.some((n) => p.search.includes(n)));
  }
  const nameMatches = (p, q) => q.tokens.length && q.tokens.every((needles) => needles.some((n) => p.nameText.includes(n)));

  // ---------------------------------------------------------------- guides (TexasEats/Models/Guide.swift)
  const NO_GRADE = "Texas has no statewide grade, and this site computes none: each score and band is the city's own.";
  const hcTag = (t) => (p) => p.hc && Boolean(p.g & t);
  const HC_SORTS = ["featured", "nearest", "name"];
  const GUIDES = {
    bbq: { title: "Barbecue Joints", sub: "Hand-checked brisket, ribs and sausage joints", inc: hcTag(BBQ), sorts: HC_SORTS },
    texmex: { title: "Tex-Mex", sub: "Hand-checked enchiladas, fajitas and combination plates", inc: hcTag(TEXMEX), sorts: HC_SORTS },
    taqueria: { title: "Taquerías", sub: "Hand-checked taquerías and breakfast taco spots", inc: hcTag(TAQUERIA), sorts: HC_SORTS },
    kolache: { title: "Kolaches", sub: "Hand-checked kolache bakeries and Czech-Texan stops", inc: hcTag(KOLACHE), sorts: HC_SORTS },
    cfs: { title: "Chicken-Fried Steak", sub: "Hand-checked chicken-fried steak with cream gravy", inc: hcTag(CFS), sorts: HC_SORTS },
    honors: { title: "MICHELIN & James Beard", sub: "MICHELIN Guide Texas and James Beard honorees", inc: (p) => p.mi > 0 || p.jb, sorts: ["iconic", "nearest"] },
    oldest: { title: "Oldest Places", sub: "Founding years checked at the same address, oldest first", inc: (p) => p.f != null && p.hc && Boolean(p.g & OLDEST), sorts: ["oldest"], ranked: true },
    brewpubs: { title: "Brewpubs", sub: "Places with a TABC brewpub license", inc: (p) => Boolean(p.g & BREWPUB), sorts: ["name", "nearest"] },
    alcohol: { title: "Bar Sales", sub: "Alcohol sales the Texas Comptroller publishes, biggest first: what each Mixed Beverage permit holder reported for liquor, wine, beer and cover charges. Reported, not estimated.", inc: (p) => p.al != null, sorts: ["alcohol", "nearest"], ranked: true },
    // no "lowest scores" list at the top: the lowest-score order is a sort a reader picks, never the page's default
    inspections: { title: "Inspection Scores", sub: "Official scores from Austin, El Paso and Arlington: each place's latest inspection, as the city published it. " + NO_GRADE, inc: (p) => p.idt != null, sorts: ["recent", "high", "low", "nearest"] },
    all: { title: "All Restaurants", sub: "Restaurants, cafés, bars and bakeries statewide", inc: () => true, sorts: ["name", "nearest"] },
    saved: { title: "Saved", sub: "Places you saved in this browser", inc: (p) => saved.has(p.id), sorts: ["name", "nearest"] },
  };
  const HC_GUIDES = ["bbq", "texmex", "taqueria", "kolache", "cfs"];
  const SORT_LABEL = { featured: "Featured first", nearest: "Nearest", oldest: "Oldest first", name: "A to Z", iconic: "MICHELIN, then James Beard",
    recent: "Latest inspection first", high: "Highest inspection score", low: "Lowest inspection score", alcohol: "Most alcohol sold" };
  let RESULTS = ["Green", "Yellow", "Red", "Passing", "Below 70", "A", "B", "C", "F"];
  const bandOf = (b) => (Number.isInteger(b) && b >= 0 && b < RESULTS.length ? RESULTS[b] : "");
  const resCls = (b) => { const l = bandOf(b); return ["Red", "Below 70", "F"].includes(l) ? "low" : ["Yellow", "C"].includes(l) ? "mid" : l ? "ok" : "x"; };
  const MI = ["", "MICHELIN Recommended", "Bib Gourmand", "1 MICHELIN Star", "2 MICHELIN Stars", "3 MICHELIN Stars"];
  const CHIP = [[BBQ, "Barbecue"], [TEXMEX, "Tex-Mex"], [TAQUERIA, "Taquería"], [KOLACHE, "Kolaches"], [CFS, "Chicken-fried steak"]];

  // ---------------------------------------------------------------- state
  let P = [], CAL = {}, TOWN_KEYS = {}, TOWN_KEYS_BY_LENGTH = [], GENERATED = "", META = {};
  let here = null, shown = 100, current = [], view = "list";
  const savedRaw = store.get("saved", []);
  const saved = new Set(Array.isArray(savedRaw) ? savedRaw.filter((x) => typeof x === "string" && x.length < 64) : []);
  const st = { g: "bbq", q: "", sort: "", town: "", cuisine: "", chains: false, bib: false, p: "" };
  let bibCount = 0;   // Bib Gourmand places (non-restaurants left out): the box shows only when there are some

  const miles = (a, b) => {
    const r = Math.PI / 180, dLa = (b.la - a.la) * r, dLo = (b.lo - a.lo) * r;
    const h = Math.sin(dLa / 2) ** 2 + Math.cos(a.la * r) * Math.cos(b.la * r) * Math.sin(dLo / 2) ** 2;
    return 3958.8 * 2 * Math.asin(Math.sqrt(h));
  };
  const milesText = (m) => (m < 10 ? m.toFixed(1) : Math.round(m)) + " mi";

  function order() {
    const g = GUIDES[st.g];
    let o = st.sort && g.sorts.includes(st.sort) ? st.sort : HC_GUIDES.includes(st.g) && here ? "nearest" : g.sorts[0];
    if (o === "nearest" && !here) o = g.sorts.find((s) => s !== "nearest") || o;   // no location yet: say what the list is really sorted by
    return o;
  }

  function allows(p) {
    if (st.town && p.c !== st.town) return false;
    if (st.cuisine && p.cu !== st.cuisine) return false;
    if (st.chains && p.ch >= 5) return false;
    if (st.bib && p.mi !== 2) return false;      // MICHELIN Bib Gourmand only, as the app's Filters switch
    return true;
  }

  function list() {
    const g = GUIDES[st.g], q = parse(st.q), o = order();
    if (qEmpty(q) && st.q.trim()) return [];   // typed something, but nothing searchable ("🍕", "!!!")
    let out = P.filter((p) => g.inc(p) && allows(p) && (qEmpty(q) || matches(p, q)));
    const byName = (a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : a.i - b.i);
    if (o === "nearest" && here) {
      const dist = new Map(out.map((p) => [p, p.la != null ? miles(here, p) : Infinity]));
      out.sort((a, b) => dist.get(a) - dist.get(b) || byName(a, b));
    }
    else if (o === "featured") out.sort((a, b) => (b.ip ?? -1) - (a.ip ?? -1) || (a.f ?? 9999) - (b.f ?? 9999) || byName(a, b));
    else if (o === "oldest") out.sort((a, b) => (a.f ?? 9999) - (b.f ?? 9999) || byName(a, b));
    else if (o === "iconic") {   // MICHELIN distinction, then the James Beard honor, then name (the app's order)
      const jb = (p) => (p.h & 1 ? 4 : p.h & 2 ? 3 : p.h & 4 ? 2 : p.h & 8 ? 1 : 0);
      out.sort((a, b) => (b.mi || 0) - (a.mi || 0) || jb(b) - jb(a) || byName(a, b));
    }
    else if (o === "recent") out.sort((a, b) => String(b.idt || "").localeCompare(String(a.idt || "")) || byName(a, b));
    else if (o === "high" || o === "low") {   // each city's own latest score out of 100; places without one go last
      const k = o === "high" ? -1 : 1;
      out.sort((a, b) => (a.isc == null) - (b.isc == null) || k * ((a.isc ?? 0) - (b.isc ?? 0)) || String(b.idt || "").localeCompare(String(a.idt || "")) || byName(a, b));
    }
    else if (o === "alcohol") out.sort((a, b) => (b.al ?? -1) - (a.al ?? -1) || byName(a, b));
    else out.sort(byName);
    if (q.tokens.length && !g.ranked) {       // name matches first when searching
      const named = out.filter((p) => nameMatches(p, q));
      if (named.length && named.length < out.length) { const ids = new Set(named); out = named.concat(out.filter((p) => !ids.has(p))); }
    }
    return out;
  }

  // ---------------------------------------------------------------- rendering
  const jbLabel = (p) => (p.h & 1 ? "America's Classic" : p.h & 2 ? "James Beard winner" : p.h & 4 ? "James Beard finalist" : p.h & 8 ? "James Beard semifinalist" : p.jb ? "James Beard (restaurateur)" : null);
  function chips(p, max) {
    const c = [];
    if (p.mi && MI[p.mi]) c.push(`<span class="tag tag-mi">${esc(MI[p.mi])}</span>`);
    const jb = jbLabel(p);
    if (jb) c.push(`<span class="tag tag-jb">${esc(jb)}</span>`);
    if (p.hc) for (const [t, label] of CHIP) if (p.g & t) c.push(`<span class="tag">${label}</span>`);
    if (p.hc && p.g & OLDEST && p.f) c.push(`<span class="tag tag-plain">Since ${esc(p.f)}</span>`);
    if (p.g & BREWPUB) c.push('<span class="tag tag-plain">Brewpub</span>');
    if (p.ch >= 5) c.push(`<span class="tag tag-plain">Chain · ${esc(p.ch)}</span>`);
    if (p.t === 0 && !p.h && !p.mi && !p.hc) c.push('<span class="tag tag-dash">Listing only</span>');
    return (max ? c.slice(0, max) : c).join("");
  }

  function metric(p, o) {
    if (o === "nearest" && here && p.la != null) return [milesText(miles(here, p)), "away"];
    if (st.g === "inspections" && p.idt) return [`${INS_CITY[p.ij] || ""} · ${bandOf(p.ib)} · ${p.isc}/100`, `inspected ${fmtDate(p.idt)}`];
    if (st.g === "alcohol" && p.al != null) return [money(p.al), "a year, reported"];
    if (p.f && st.g !== "all" && st.g !== "inspections") return [String(p.f), "since"];
    return null;
  }

  function render() {
    const g = GUIDES[st.g], o = order();
    if (st.g === "saved" && !idsReady) loadIds().then(() => { if (st.g === "saved") render(); });
    current = list();
    document.querySelectorAll(".ex-guides button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.g === st.g)));
    $("#ex-sub").textContent = g.sub + (st.g === "inspections" && META.through ? ` Records through ${INS_CITY.map((c, j) => `${c} ${fmtDate(META.through[INS_KEY[j]])}`).join(", ")}.` : "")
      + (st.g === "alcohol" && META.mixFrom ? ` ${fmtMonth(META.mixFrom)} through ${fmtMonth(META.mixTo)}.` : "");
    const sortSel = $("#ex-sort");
    sortSel.innerHTML = g.sorts.map((s) => `<option value="${esc(s)}"${s === o ? " selected" : ""}>${esc(SORT_LABEL[s])}</option>`).join("");
    sortSel.disabled = g.sorts.length < 2;
    const filters = [st.town && `in ${st.town}`, st.cuisine && st.cuisine, st.chains && "no chains", st.bib && "Bib Gourmand"].filter(Boolean);
    $("#ex-count").textContent = `${current.length.toLocaleString()} ${current.length === 1 ? "place" : "places"} · ${SORT_LABEL[o]}` + (filters.length ? ` · ${filters.join(", ")}` : "");
    $("#ex-clear").hidden = !filters.length;
    // Near me stays: each tap asks for a fresh fix (people move), and it's how to retry after a timeout
    if (view === "list") renderList(o); else drawMap();
    saveHash();
  }

  // typing searches only the open guide (the page opens on Barbecue Joints): when that finds little, the same words across every
  // restaurant, with the same filters, so a famous place outside the guide isn't a dead end
  const FEW = 5;
  function elsewhereCount() {
    const q = parse(st.q);
    if (st.g === "all" || qEmpty(q) || current.length >= FEW) return 0;
    let n = 0;
    for (const p of P) if (allows(p) && matches(p, q)) n++;
    return n > current.length ? n : 0;
  }
  const allButton = (n) => `<button type="button" class="ex-small" id="ex-all">Search all restaurants (${esc(n.toLocaleString())} ${n === 1 ? "match" : "matches"})</button>`;
  function wireAll() {
    const b = $("#ex-all");
    if (b) b.onclick = () => { st.g = "all"; st.sort = ""; shown = 100; render(); const r = $(".ex-row"); if (r) r.focus(); };
  }

  function renderList(o) {
    const ol = $("#ex-list");
    const g = GUIDES[st.g];
    const elsewhere = elsewhereCount();
    if (!current.length) {
      ol.innerHTML = `<li class="ex-empty">${st.g === "saved" && !idsReady ? "Loading your saved places…" : st.g === "saved" && idsFailed && saved.size ? "Your saved places couldn't load: you may be offline, or the site was just updated. Reload the page to try again." : elsewhere ? `Nothing in ${esc(g.title)} matches that. ${allButton(elsewhere)}` : st.g === "saved" ? "Nothing saved yet. Open a place and tap Save to keep it here, in this browser." : "No places match. Try fewer words or clear the filters."}</li>`;
      wireAll();
      $("#ex-more").hidden = true;
      return;
    }
    ol.innerHTML = current.slice(0, shown).map((p, i) => {
      const m = metric(p, o);
      const rank = g.ranked ? `<span class="ex-rank${i < 3 ? " top" : ""}" aria-label="Rank ${i + 1}">${i + 1}</span>` : "";
      const where = st.g === "inspections" ? [p.a, p.c].filter(Boolean).join(", ") : [p.c, p.cu].filter(Boolean).join(" · ");
      const big = st.g === "inspections" && m && o !== "nearest" ? `<span class="ex-res ex-res-${resCls(p.ib)}">${esc(m[0])}</span>` : m ? `<b>${esc(m[0])}</b>` : "";
      return `<li><button class="ex-row" data-i="${esc(p.i)}">${rank}<span class="ex-main"><b>${esc(p.n)}</b><span class="ex-town">${esc(where)}</span><span class="ex-chips">${chips(p, 4)}</span></span>${m ? `<span class="ex-metric">${big}<small>${esc(m[1])}</small></span>` : ""}</button></li>`;
    }).join("") + (elsewhere ? `<li class="ex-empty">Only ${esc(current.length)} in ${esc(g.title)}. ${allButton(elsewhere)}</li>` : "");
    wireAll();
    const left = current.length - shown;
    $("#ex-more").hidden = left <= 0;
    $("#ex-more").textContent = `Show more (${left.toLocaleString()} left)`;
  }

  // ---------------------------------------------------------------- place panel
  const TIER = { 2: "On an official list", 1: "High-confidence listing", 0: "Listing only" };   // "High-confidence", not "confirmed" (Nick, 2026-10-13)

  // how often listings like this one matched an inspected or licensed business in Austin, El Paso County and Arlington
  // (pipeline/calibrate.py); the app's matchRate
  function rate(p) {
    if (p.t === 2) return null;
    const src = SOURCES[p.s] || "meta";
    const group = src === "meta" ? (p.t === 1 ? "meta_high" : "meta_mid") : (src === "AllThePlaces" || src === "DAC") ? "brand_feed" : null;
    if (!group) return null;
    const v = Object.values(CAL || {}).map((a) => a?.groups?.[group]?.official).filter((x) => typeof x === "number").map((x) => Math.round(x * 100)).sort((a, b) => a - b);
    if (!v.length) return null;
    return v[0] === v[v.length - 1] ? `${v[0]}%` : `${v[0]}–${v[v.length - 1]}%`;
  }

  function howWeKnow(p) {
    const src = SOURCES[p.s] || "meta";
    if (src === "research") return "On our hand-checked list (checked against a 2025 or 2026 source). The open map data didn't list it as a place to eat, so it's placed from its own map listing or street address.";
    if (p.t === 2) return src === "official"
      ? "From an official list (a TABC license or a city's inspection list). The open map data didn't have it, so its location comes from the record's street address."
      : "Matched to an active TABC license or a city's inspection list.";
    const r = rate(p);
    return (p.t === 1 ? "A high-confidence listing in Overture's open map data." : "A single listing in Overture's open map data, so it may be closed or misfiled.")
      + (r ? ` Checked against the establishments Austin, El Paso and Arlington inspect, listings like this matched an inspected or licensed business ${r} of the time.` : "")
      + (p.hc ? " It's also on our hand-checked list, checked against a 2025 or 2026 source." : "");
  }

  const kv = (k, v) => (v == null || v === "" ? "" : `<div class="ex-kv"><span>${esc(k)}</span><b>${esc(v)}</b></div>`);
  const section = (t, body) => `<section class="ex-sec"><h3>${esc(t)}</h3>${body}</section>`;
  let listAtPush = null;   // the list's URL state when a place was opened with pushState (Back then closes the panel)

  // the open place is a modal dialog at every width (a bottom sheet on phones, a side sheet on wider screens, which would otherwise
  // cover Near me and the List/Map buttons): everything behind it is inert, and a click on the dimmed backdrop closes it
  function panelMode() {
    const panel = $("#ex-panel"), modal = !panel.hidden;
    if (modal) { panel.setAttribute("role", "dialog"); panel.setAttribute("aria-modal", "true"); }
    else { panel.removeAttribute("role"); panel.removeAttribute("aria-modal"); }
    $("#ex-backdrop").hidden = !modal;
    const behind = [...document.querySelectorAll("body > .skip, .wrap > header, .wrap > nav, .wrap > footer, #main > *")].filter((el) => el !== panel && el.id !== "ex-backdrop");
    behind.forEach((el) => { el.inert = modal; });
  }

  const vtype = (i) => (Number.isInteger(i) && i >= 0 && i < (META.itypes || []).length ? META.itypes[i] : "");

  function inspectionSection(p, d) {
    if (!p.idt || !Number.isInteger(p.ij)) return "";
    const j = p.ij;
    const i = d.in && typeof d.in === "object" ? d.in : {};
    const hist = Array.isArray(i.h) ? i.h.filter(Array.isArray) : [];
    let h = `<p class="ex-result"><span class="ex-res ex-res-${resCls(p.ib)}">${esc(INS_CITY[j])} · ${esc(bandOf(p.ib))}</span> ${esc(p.isc)}/100 · latest inspection ${esc(fmtDate(p.idt))}</p>`;
    if (hist.length) h += `<ul>${hist.map((v) => `<li>${esc(fmtDate(v[0]))} · ${esc(vtype(v[3]))} · ${esc(v[2])}/100 · ${esc(bandOf(v[1]))}</li>`).join("")}</ul>`;
    if (num(i.n) != null && i.n > hist.length) h += `<p class="ex-fine">The latest ${esc(hist.length)} of ${esc(i.n)} inspections in the last three years.</p>`;
    h += `<p class="ex-fine">${esc(INS_SCALE[j])} Shown as ${esc(INS_CITY[j])} published it. ${esc(NO_GRADE)} One inspection is a snapshot of one day. Records through ${esc(fmtDate((META.through || {})[INS_KEY[j]]))}.</p>`;
    h += `<p><a href="${esc(INS_URL[j])}" rel="noopener" target="_blank">${esc(INS_CITY[j])}'s inspection records</a></p>`;
    return section(`Inspections · ${INS_CITY[j]}`, h);
  }

  function openPlace(p, push = true) {
    const panel = $("#ex-panel");
    const wasOpen = !panel.hidden;
    // the place opens at once; its id (for Save, the #p= link and the Back step) follows when ids.json arrives, which the first tap
    // only starts, so a tap never waits on it. If ids.json can't load (offline, or a build changed under us), the place stays open
    // without Save and without a link.
    const waiting = p.id == null && !idsReady;
    if (waiting && (push || !wasOpen)) loadIds().then(() => { if (!panel.hidden && panel.dataset.i === String(p.i)) openPlace(p, push); });
    const noId = p.id == null, pid = p.id ?? "";
    // a re-render (the county's details just arrived) replaces the panel's buttons: remember where keyboard focus was, to put it back
    const focused = wasOpen && panel.contains(document.activeElement) ? document.activeElement : null;
    const refocus = focused && (focused.id ? `#${focused.id}` : focused.textContent.trim());
    st.p = pid;
    const loaded = DETAIL_LOADED.has(p.co), failed = DETAIL_FAILED.has(p.co);
    const d = DETAIL.get(p.i) || {};
    const la = num(p.la), lo = num(p.lo);
    const addr = [p.a, [p.c, p.z].filter(Boolean).join(" ")].filter(Boolean).join(", ");
    const apple = la != null && lo != null
      ? `https://maps.apple.com/?q=${encodeURIComponent(p.n)}&ll=${la},${lo}`
      : `https://maps.apple.com/?q=${encodeURIComponent(p.n + ", " + addr)}`;
    const dirs = la != null && lo != null ? `https://maps.apple.com/?daddr=${la},${lo}&dirflg=d` : apple;
    const site = safeUrl(d.w);
    const tel = d.ph ? String(d.ph).replace(/[^\d+]/g, "") : "";
    let html = `<button class="ex-close" id="ex-close" aria-label="Close">×</button>
      <p class="ex-kicker">${esc((p.c || "Texas").toUpperCase())}</p>
      <h2 id="ex-pname">${esc(p.n)}</h2>
      <p class="ex-addr">${esc([addr, p.cu].filter(Boolean).join(" · "))}</p>
      ${here && la != null ? `<p class="ex-dist">${esc(milesText(miles(here, p)))} away</p>` : ""}
      <p class="ex-chips">${chips(p)}</p>
      <div class="ex-actions">
        <a class="btn ex-apple" href="${esc(apple)}" rel="noopener" target="_blank">Ratings, hours &amp; photos · Apple Maps</a>
        <div class="ex-act-row">
          <a href="${esc(dirs)}" rel="noopener" target="_blank">Directions</a>
          ${tel ? `<a href="tel:${esc(tel)}">Call</a>` : ""}
          ${site ? `<a href="${esc(site)}" rel="noopener nofollow" target="_blank">Website</a>` : ""}
          ${waiting ? '<button id="ex-save" aria-pressed="false" disabled>Save</button>' : noId ? "" : `<button id="ex-save" aria-pressed="${saved.has(pid)}">${saved.has(pid) ? "Saved" : "Save"}</button>`}
        </div>
      </div>`;
    if (!loaded) html += `<p class="ex-fine">Loading details…</p>`;
    if (p.hc && (d.note || p.dish || p.f || d.seas)) {
      html += section("Hand-checked", (d.note ? `<p>${esc(d.note)}</p>` : "") + kv("On the menu", p.dish ? String(p.dish).split("; ").join(", ") : "")
        + kv("Open here since", p.f) + (d.fn ? `<p class="ex-fine">${esc(d.fn)}</p>` : "") + kv("Season", d.seas)
        + `<p class="ex-fine">Checked against a 2025 or 2026 source: the place's own site or menu, local news or an official tourism listing. Menus and hours change${p.g & BBQ ? ", and barbecue joints often sell out early" : ""}, so check before you go.</p>`);
    }
    if (p.mi || d.jbf) {
      const lines = [...(p.mi && MI[p.mi] ? [MI[p.mi] + " · MICHELIN Guide Texas"] : []),
        ...(d.jbf ? String(d.jbf).split("; ").map((x) => "James Beard: " + x) : [])];
      html += section("Honors", `<ul>${lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul><p class="ex-fine">Honors are facts, not ratings. MICHELIN and the MICHELIN Guide are trademarks of Michelin; James Beard Foundation and James Beard Award are trademarks of the James Beard Foundation.</p>`);
    }
    html += inspectionSection(p, d);
    if (p.al != null) {
      html += section("Reported alcohol sales", `<p class="ex-result">${esc(money(p.al))} a year</p><p class="ex-fine">Liquor, wine, beer and cover charges the place's Mixed Beverage permit holder reported to the Texas Comptroller, ${esc(fmtMonth(META.mixFrom))} through ${esc(fmtMonth(META.mixTo))}${num(d.aln) != null && d.aln < 12 ? ` (${esc(d.aln)} months reported)` : ""}. A reported figure, not our estimate. <a href="${esc(MIXBEV)}" rel="noopener" target="_blank">Mixed Beverage Gross Receipts</a></p>`);
    }
    if (failed) html += `<p class="ex-fine">This place's details (licenses, inspections, phone, website) didn't load: you may be offline, or the site was just updated. Reload the page to try again.</p>`;
    else if (loaded) {
      const lic = Array.isArray(d.lic) ? d.lic.filter(Array.isArray) : [];
      html += section("Official records", (lic.length ? lic.map((l) => kv(`TABC license ${l[0]}`, String(l[1] || "") + (l[2] ? ` · expires ${fmtDate(l[2])}` : ""))).join("") : kv("Serves alcohol", "— (no TABC license matched)"))
        + `<p class="ex-fine">${lic.length ? `From the Texas Alcoholic Beverage Commission's list of active licenses (data.texas.gov, read ${esc(fmtDate(META.liq))}). A Food and Beverage Certificate means food service is a real part of the business. <a href="${esc(TABC_SEARCH)}" rel="noopener" target="_blank">TABC's public inquiry</a>` : "Texas has no statewide list of food licenses, so the only statewide record is TABC's alcohol licenses. No license matched this place: it may not serve alcohol, or it's licensed under another name, so a missing license means unknown, not no."}</p>`);
    }
    html += section("How we know it's here", kv("Listed as", TIER[p.t])
      + (p.ch >= 2 ? kv("Locations in Texas", p.ch.toLocaleString()) : "") + `<p class="ex-fine">${esc(howWeKnow(p))}</p>`);
    const store_url = safeUrl(window.APP_STORE_URL);   // set in the page footer script once the App Store listing exists
    html += store_url
      ? `<p class="ex-app">Save it on your phone: <a href="${esc(store_url)}" rel="noopener">get the free iPhone app</a></p>`
      : `<p class="ex-app">The iPhone app is coming soon. <a href="${BASE}/#download">Ask for early access</a></p>`;
    panel.innerHTML = html;
    panel.dataset.id = pid;
    panel.dataset.i = String(p.i);
    panel.hidden = false;
    document.body.classList.add("ex-open");
    panelMode();
    $("#ex-close").onclick = () => closePlace();
    if (!noId) $("#ex-save").onclick = (e) => {
      if (saved.has(p.id)) saved.delete(p.id); else saved.add(p.id);
      store.set("saved", [...saved]);
      e.target.textContent = saved.has(p.id) ? "Saved" : "Save";
      e.target.setAttribute("aria-pressed", String(saved.has(p.id)));
      if (st.g === "saved") render();
    };
    const samePlace = wasOpen && panel.dataset.shown === String(p.i);   // a re-render: details or the id just arrived
    if (!samePlace) panel.scrollTop = 0;
    panel.dataset.shown = String(p.i);
    if (!samePlace) $("#ex-close").focus();
    else if (refocus) {
      const same = refocus.startsWith("#") ? panel.querySelector(refocus)
        : [...panel.querySelectorAll("a, button")].find((el) => el.textContent.trim() === refocus);
      (same || $("#ex-close")).focus();
    }
    if (push && !noId) {
      if (panel.dataset.pushed) saveHash();   // one Back step per panel, not per place looked at
      else { listAtPush = listHash(); saveHash(true); panel.dataset.pushed = "1"; }
    }
    if (!loaded) loadDetail(p.co).then(() => { if (panel.dataset.i === String(p.i) && !panel.hidden) openPlace(p, false); });
  }

  // fromHistory: the Back button (or a hash link) already moved the URL, so don't touch history again
  function closePlace(fromHistory = false) {
    st.p = "";
    const panel = $("#ex-panel");
    const wasI = panel.dataset.i;   // the row the panel belonged to: focus goes back there
    panel.hidden = true;
    delete panel.dataset.id;
    delete panel.dataset.i;
    delete panel.dataset.shown;
    delete panel.dataset.pushed;
    document.body.classList.remove("ex-open");
    panelMode();
    if (!fromHistory) {
      // the list hasn't changed since the panel opened: step back over the entry openPlace pushed, so Back isn't a dead click
      if (history.state && history.state.txeats === "place" && listHash() === listAtPush) history.back();
      else saveHash();
    }
    listAtPush = null;
    const row = wasI && document.querySelector(`.ex-row[data-i="${Number(wasI)}"]`);
    if (row) row.focus();
  }

  // ---------------------------------------------------------------- map (canvas: county outlines + a dot per place)
  let SHAPES = null, cam = null;
  const LAT0 = 31.2, KX = Math.cos(LAT0 * Math.PI / 180);
  const proj = (lo, la) => [(lo + 100.0) * KX, -(la - LAT0)];

  function fitCam(w, h) {
    const [x0, y0] = proj(-106.7, 36.55), [x1, y1] = proj(-93.45, 25.8);
    const k = Math.min(w / (x1 - x0), h / (y1 - y0)) * 0.95;
    return { k, x: (w - (x1 - x0) * k) / 2 - x0 * k, y: (h - (y1 - y0) * k) / 2 - y0 * k };
  }

  // calls f on every ring, however deeply it's nested (the state is [polygon[ring[point]]], each county [ring[point]])
  const eachRing = (g, f) => {
    if (!Array.isArray(g) || !g.length) return;
    if (Array.isArray(g[0]) && typeof g[0][0] === "number") f(g); else g.forEach((x) => eachRing(x, f));
  };

  const classic = (p) => Boolean((p.hc && p.g) || p.mi);
  async function drawMap() {
    const cv = $("#ex-map"), wrap = $("#ex-mapwrap");
    const w = wrap.clientWidth, h = wrap.clientHeight, dpr = window.devicePixelRatio || 1;
    if (!w || !h) return;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    if (!cam) cam = fitCam(w, h);
    if (!SHAPES) SHAPES = await fetchJSON(`${BASE}/data/tx_shapes.json`).catch(() => ({ state: [], counties: [] }));
    const c = cv.getContext("2d");
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, w, h);
    const X = (lo, la) => { const [x, y] = proj(lo, la); return [x * cam.k + cam.x, y * cam.k + cam.y]; };
    const ring = (r) => { r.forEach(([lo, la], i) => { const [x, y] = X(lo, la); i ? c.lineTo(x, y) : c.moveTo(x, y); }); c.closePath(); };
    c.fillStyle = "#f7f3ec";   // the map stays light in dark mode (its frame is light too), so the blue dots keep their contrast
    c.beginPath(); eachRing(SHAPES.state, ring); c.fill("evenodd");
    c.strokeStyle = "rgba(14,26,48,.22)"; c.lineWidth = 0.8;
    for (const co of SHAPES.counties || []) { c.beginPath(); eachRing(co.c, ring); c.stroke(); }
    const pts = current.filter((p) => p.la != null);
    const r = Math.max(2.2, Math.min(5, 1.6 + cam.k / 120));
    // plain places: one batch of small squares (tens of thousands draw fast that way); hand-checked and MICHELIN places: red dots on top
    c.fillStyle = "#002868";
    const sq = pts.length > 3000 ? Math.max(1.6, r - 0.6) : r * 1.6;
    for (const p of pts) {
      if (classic(p)) continue;
      const [x, y] = X(p.lo, p.la);
      if (x < -5 || y < -5 || x > w + 5 || y > h + 5) continue;
      if (pts.length > 3000) c.fillRect(x - sq / 2, y - sq / 2, sq, sq);
      else { c.beginPath(); c.arc(x, y, r, 0, 6.2832); c.fill(); }
    }
    c.fillStyle = "#bf0a30"; c.strokeStyle = "#ffffff"; c.lineWidth = 1;
    for (const p of pts) {
      if (!classic(p)) continue;
      const [x, y] = X(p.lo, p.la);
      if (x < -5 || y < -5 || x > w + 5 || y > h + 5) continue;
      c.beginPath(); c.arc(x, y, r + 1, 0, 6.2832); c.fill(); c.stroke();
    }
    $("#ex-maphint").textContent = pts.length ? `${pts.length.toLocaleString()} ${pts.length === 1 ? "place" : "places"} · tap a dot` : "No places to show";
  }

  function nearestDot(px, py) {
    let best = null, bd = 14 * 14;
    for (const p of current) {
      if (p.la == null) continue;
      const [x0, y0] = proj(p.lo, p.la), x = x0 * cam.k + cam.x, y = y0 * cam.k + cam.y;
      const d = (x - px) ** 2 + (y - py) ** 2;
      if (d < bd || (d === bd && classic(p))) { bd = d; best = p; }
    }
    return best;
  }

  function zoomAt(f, px, py) {
    const k = Math.min(Math.max(cam.k * f, 40), 60000);
    const s = k / cam.k;
    cam = { k, x: px - (px - cam.x) * s, y: py - (py - cam.y) * s };
    drawMap();
  }

  function mapEvents() {
    const cv = $("#ex-map");
    const ptrs = new Map();
    let moved = false, pinch0 = null;
    cv.addEventListener("wheel", (e) => { e.preventDefault(); const b = cv.getBoundingClientRect(); zoomAt(e.deltaY < 0 ? 1.25 : 0.8, e.clientX - b.left, e.clientY - b.top); }, { passive: false });
    cv.addEventListener("pointerdown", (e) => { cv.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, [e.clientX, e.clientY]); moved = false; pinch0 = null; });
    cv.addEventListener("pointermove", (e) => {
      if (!ptrs.has(e.pointerId)) return;
      const prev = ptrs.get(e.pointerId);
      ptrs.set(e.pointerId, [e.clientX, e.clientY]);
      if (ptrs.size === 2) {
        const [a, b] = [...ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        const r = cv.getBoundingClientRect();
        if (pinch0) zoomAt(d / pinch0, (a[0] + b[0]) / 2 - r.left, (a[1] + b[1]) / 2 - r.top);
        pinch0 = d; moved = true; return;
      }
      const dx = e.clientX - prev[0], dy = e.clientY - prev[1];
      if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
      cam.x += dx; cam.y += dy; drawMap();
    });
    const up = (e) => {
      ptrs.delete(e.pointerId);
      if (!moved && ptrs.size === 0) {
        const b = cv.getBoundingClientRect(), p = nearestDot(e.clientX - b.left, e.clientY - b.top);
        if (p) openPlace(p);
      }
      if (ptrs.size < 2) pinch0 = null;
    };
    cv.addEventListener("pointerup", up);
    cv.addEventListener("pointercancel", (e) => ptrs.delete(e.pointerId));
    $("#ex-zin").onclick = () => zoomAt(1.6, cv.clientWidth / 2, cv.clientHeight / 2);
    $("#ex-zout").onclick = () => zoomAt(0.625, cv.clientWidth / 2, cv.clientHeight / 2);
    window.addEventListener("resize", () => { if (view === "map") drawMap(); });
  }

  function centerOn(pt) {
    const cv = $("#ex-map"), w = cv.clientWidth, h = cv.clientHeight;
    const k = 4000, [x, y] = proj(pt.lo, pt.la);
    cam = { k, x: w / 2 - x * k, y: h / 2 - y * k };
  }

  // ---------------------------------------------------------------- data, URL state, controls
  let SOURCES = [], DETAIL_FILES = [];
  async function fetchJSON(url, opts) { const r = await fetch(url, opts); if (!r.ok) throw new Error(r.status + " " + url); return r.json(); }
  // the build this page's data comes from: the page names it (so a cached core.json from an older build isn't used), core.json confirms it
  const PAGE_VER = ($("#ex-app") && $("#ex-app").dataset.ver) || "";
  let DV = "";
  const vq = (v) => (v ? "?v=" + encodeURIComponent(v) : "");
  // a data file from another build (a cache that outlived a deploy) is fetched once more, then refused: its rows wouldn't line up
  async function fetchCurrent(url, verOf) {
    let d = await fetchJSON(url + vq(DV));
    if (DV && verOf(d) !== DV) d = await fetchJSON(url + vq(DV), { cache: "reload" });
    if (DV && verOf(d) !== DV) throw new Error("another build: " + url);
    return d;
  }
  const DETAIL = new Map(), DETAIL_LOADED = new Set(), DETAIL_FAILED = new Set(), detailPromises = new Map();
  // a county's detail file (phones, websites, notes, licenses, inspections) is fetched only once someone reaches for a place there
  function loadDetail(co) {
    // a county with no extras has no file (null in dfiles): nothing to fetch
    if (!Number.isInteger(co) || co < 0 || co >= DETAIL_FILES.length || !DETAIL_FILES[co]) { DETAIL_LOADED.add(co); return Promise.resolve(); }
    if (!detailPromises.has(co)) {
      detailPromises.set(co, fetchCurrent(`${BASE}/data/detail-${encodeURIComponent(DETAIL_FILES[co])}.json`, (d) => d && d._v).then((d) => {
        if (d && typeof d === "object") for (const k of Object.keys(d)) { const i = Number(k); if (Number.isInteger(i) && d[k] && typeof d[k] === "object") DETAIL.set(i, d[k]); }
      }).catch(() => { DETAIL_FAILED.add(co); /* offline or another build: the panel says so, and asks for a reload */ })
        .finally(() => DETAIL_LOADED.add(co)));
    }
    return detailPromises.get(co);
  }

  // ids.json: one stable id per place, in core order (saved places, #p= links and the panel's history entry use them)
  let idsPromise = null, idsReady = false, idsFailed = false;
  function loadIds() {
    idsPromise ||= fetchCurrent(`${BASE}/data/ids.json`, (d) => d && d.v).then((d) => {
      const ids = d && typeof d.ids === "string" ? d.ids.split(",") : [];   // one comma-separated string: smaller than a JSON array
      if (ids.length !== P.length) throw new Error("ids.json doesn't match core.json");
      ids.forEach((x, i) => { P[i].id = x; });
    }).catch(() => { idsFailed = true; /* offline or another build: saving and links wait for a reload, and the page says so */ })
      .finally(() => { idsReady = true; });
    return idsPromise;
  }

  async function load() {
    let d = await fetchJSON(`${BASE}/data/core.json${vq(PAGE_VER)}`);
    // a core.json with no version predates versioning (a cache that ignored ?v=): its rows would meet this build's ids and county
    // files unchecked, so fetch it once more past the cache, then stop with the reload message rather than mix two builds
    if (PAGE_VER && typeof d.ver !== "string") d = await fetchJSON(`${BASE}/data/core.json${vq(PAGE_VER)}`, { cache: "reload" });
    if (PAGE_VER && typeof d.ver !== "string") throw new Error("core.json from before versioning");
    DV = typeof d.ver === "string" ? d.ver : "";
    GENERATED = d.generated; CAL = d.calibration || {}; SOURCES = d.srcs || []; DETAIL_FILES = d.dfiles || [];
    if (Array.isArray(d.results) && d.results.length) RESULTS = d.results;
    META = { through: d.inspections_through || {}, liq: d.liquor_updated, mixFrom: d.mixbev_from, mixTo: d.mixbev_to, itypes: d.itypes || [] };
    const n = d.n, towns = new Map(), C = { ...d.cols };
    for (const [k, pairs] of Object.entries(d.sparse || {})) {   // mostly-empty columns arrive as [[index, value], ...]
      const col = new Array(n).fill(null);
      if (Array.isArray(pairs)) for (const pr of pairs) if (Array.isArray(pr) && Number.isInteger(pr[0]) && pr[0] >= 0 && pr[0] < n) col[pr[0]] = pr[1];
      C[k] = col;
    }
    for (const k of ["n", "c", "co", "cu", "t", "s", "a", "z", "b", "ch", "g", "hc", "ip", "f", "h", "mi", "dish", "al", "liq", "dla", "dlo", "jb", "ij", "ib", "isc", "idn"])
      if (!Array.isArray(C[k]) || C[k].length !== n) C[k] = new Array(n).fill(null);
    const day0 = Date.UTC(...String(d.day0 || "2000-01-01").split("-").map((x, k) => Number(x) - (k === 1 ? 1 : 0)));
    const isoDay = (k) => (k == null ? null : new Date(day0 + k * 86400000).toISOString().slice(0, 10));
    P = new Array(n);
    let la = 0, lo = 0;   // coordinates come as steps of 0.0001° from the previous place
    for (let i = 0; i < n; i++) {
      let pla = null, plo = null;
      if (C.dla[i] != null && C.dlo[i] != null) { la += C.dla[i]; lo += C.dlo[i]; pla = la / 10000; plo = lo / 10000; }
      const city = C.c[i] == null ? null : d.cities[C.c[i]], cu = d.cuisines[C.cu[i]], brand = C.b[i] == null ? null : d.brands[C.b[i]];
      const county = C.co[i] == null ? null : d.counties[C.co[i]];
      const p = { i, id: null, n: String(C.n[i] ?? ""), c: city, cu, t: C.t[i], s: C.s[i], a: C.a[i], z: C.z[i], la: pla, lo: plo,
        ch: num(C.ch[i]) || 1, g: C.g[i] || 0, hc: C.hc[i] === 1, ip: C.ip[i], f: num(C.f[i]), h: C.h[i] || 0,
        mi: num(C.mi[i]) || 0, jb: C.jb[i] === 1, dish: C.dish[i], co: C.co[i], al: num(C.al[i]), liq: C.liq[i] === 1,
        ij: num(C.ij[i]), ib: num(C.ib[i]), isc: num(C.isc[i]), idt: isoDay(C.idn[i]) };
      p.search = " " + normalize([p.n, city, county, p.z, cu, brand, p.dish].filter(Boolean).join(" ")) + " " + normAddr(p.a || "") + " ";
      p.nameText = " " + normalize([p.n, brand].filter(Boolean).join(" ")) + " ";
      p.key = normalize(p.n);
      P[i] = p;
      if (city) towns.set(city, (towns.get(city) || 0) + 1);
    }
    const byCount = [...towns.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    for (const [name] of byCount) { const k = normAddr(name); if (!own(TOWN_KEYS, k)) TOWN_KEYS[k] = name; }   // biggest town wins a shared spelling
    TOWN_KEYS_BY_LENGTH = Object.keys(TOWN_KEYS).sort((a, b) => b.length - a.length);
    $("#ex-town").innerHTML = '<option value="">All towns</option>' + [...towns.keys()].sort((a, b) => a.localeCompare(b)).map((t) => `<option>${esc(t)}</option>`).join("");
    const cuis = new Map();
    for (const p of P) cuis.set(p.cu, (cuis.get(p.cu) || 0) + 1);
    $("#ex-cuisine").innerHTML = '<option value="">All kinds</option>' + [...cuis.entries()].sort((a, b) => b[1] - a[1]).map(([c, k]) => `<option value="${esc(c)}">${esc(c)} (${esc(k.toLocaleString())})</option>`).join("");
    bibCount = P.filter((p) => !p.v && p.mi === 2).length;
    $("#ex-bibwrap").hidden = !bibCount;
    $("#ex-bibn").textContent = `(${bibCount.toLocaleString()})`;
    if (!bibCount) st.bib = false;
  }

  const guideOk = (g) => own(GUIDES, g);
  function readHash() {
    const h = new URLSearchParams(location.hash.slice(1));
    const last = store.get("guide", "bbq");
    // a returning visitor gets the guide they used last, unless it's an empty Saved list
    st.g = guideOk(h.get("g")) ? h.get("g") : guideOk(last) && !(last === "saved" && !saved.size) ? last : "bbq";
    st.q = h.get("q") || ""; st.town = h.get("town") || ""; st.cuisine = h.get("kind") || ""; st.chains = h.get("chains") === "1"; st.bib = h.get("bib") === "1";
    st.sort = h.get("sort") || ""; st.p = h.get("p") || "";
  }
  function hashOf(withPlace) {
    const h = new URLSearchParams();
    h.set("g", st.g);
    if (st.q) h.set("q", st.q); if (st.town) h.set("town", st.town); if (st.cuisine) h.set("kind", st.cuisine);
    if (st.chains) h.set("chains", "1"); if (st.bib) h.set("bib", "1"); if (st.sort) h.set("sort", st.sort); if (withPlace && st.p) h.set("p", st.p);
    return "#" + h.toString();
  }
  const listHash = () => hashOf(false);
  // filter changes replace the current history entry; opening a place pushes one, so Back closes the panel
  function saveHash(push = false) {
    const url = hashOf(true);
    if (push) history.pushState({ txeats: "place" }, "", url);
    else history.replaceState(st.p ? { txeats: "place" } : null, "", url);
    store.set("guide", st.g);
  }

  // a coarse Texas outline (TexasEats/Services/LocationService.swift's TexasOutline): a bounding box would count New Mexico and Oklahoma
  const TX_RING = [[-106.68, 32.03], [-103.03, 32.03], [-103.0, 36.53], [-99.97, 36.53], [-99.97, 34.6], [-99.2, 34.45], [-98.1, 34.18],
    [-96.9, 33.97], [-95.6, 33.97], [-94.45, 33.7], [-94.0, 33.6], [-94.0, 32.0], [-93.55, 31.2], [-93.7, 30.3], [-93.8, 29.65], [-94.7, 29.2],
    [-95.3, 28.7], [-96.6, 28.0], [-97.2, 27.3], [-97.1, 25.9], [-97.5, 25.8], [-98.3, 26.03], [-99.1, 26.38], [-99.55, 27.45], [-100.35, 28.25],
    [-101.05, 29.33], [-102.4, 29.72], [-103.15, 28.9], [-104.55, 29.6], [-105.0, 30.6], [-106.05, 31.35], [-106.68, 31.75]];
  function inTexas(la, lo) {
    let inside = false;
    for (let i = 0, j = TX_RING.length - 1; i < TX_RING.length; j = i++) {
      const [xi, yi] = TX_RING[i], [xj, yj] = TX_RING[j];
      if ((yi > la) !== (yj > la) && lo < (xj - xi) * (la - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  function locate() {
    if (!navigator.geolocation) { $("#ex-locmsg").textContent = "This browser can't share its location."; return; }
    $("#ex-locmsg").textContent = "Finding you…";
    navigator.geolocation.getCurrentPosition((pos) => {
      here = { la: pos.coords.latitude, lo: pos.coords.longitude };
      const inTX = inTexas(here.la, here.lo);
      $("#ex-locmsg").textContent = inTX ? "Sorted by distance from you. Your location stays in this browser." : "You're outside Texas: distances are from where you are. Your location stays in this browser.";
      st.sort = GUIDES[st.g].sorts.includes("nearest") ? "nearest" : st.sort;
      if (view === "map" && inTX) centerOn(here);
      shown = 100; render();
    }, (err) => {
      $("#ex-locmsg").textContent = err && err.code === 1 ? "Location is off for this site. Allow it in your browser settings to sort by distance."
        : "Couldn't get a location fix just now. Tap Near me to try again.";
    },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 0 });   // a fresh fix on every tap, never one from minutes ago
  }

  function setView(v) {
    view = v;
    document.querySelectorAll(".ex-view button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === v)));
    $("#ex-listwrap").hidden = v !== "list";
    $("#ex-mapwrap").hidden = v !== "map";
    render();
    // the map often starts below the fold (on phones, and on laptop-height screens): bring it into view
    if (v === "map" && $("#ex-mapwrap").getBoundingClientRect().top > innerHeight * 0.5) $("#ex-mapwrap").scrollIntoView({ block: "nearest" });
  }

  // the URL moved under us: Back/Forward (popstate) or a link to another #hash (hashchange). Both can fire for one step.
  function fromURL() {
    const before = listHash();
    readHash();
    if (listHash() !== before) { syncInputs(); shown = 100; render(); }
    if (st.p && !idsReady) { loadIds().then(fromURL); return; }
    const p = st.p && P.find((x) => x.id === st.p);
    const panel = $("#ex-panel");
    if (p) {
      if (panel.hidden || panel.dataset.id !== p.id) {
        openPlace(p, false);
        // Forward to a place opened earlier: its entry was pushed after the list's, so closing it steps back, as after a tap
        if (history.state && history.state.txeats === "place") { listAtPush = listHash(); panel.dataset.pushed = "1"; }
      }
    }
    else { if (!panel.hidden) closePlace(true); linkMissing(); }
  }

  // a #p= link whose place isn't here: ids.json didn't load, or the place has left the list since the link was made
  function linkMissing() {
    if (!st.p) return;
    $("#ex-locmsg").textContent = idsFailed ? "The place in this link couldn't load: you may be offline, or the site was just updated. Reload the page to try again."
      : "The place in this link isn't on the list anymore (it may have closed or moved).";
  }

  function controls() {
    document.querySelectorAll(".ex-guides button").forEach((b) => b.onclick = () => { if (guideOk(b.dataset.g)) st.g = b.dataset.g; st.sort = ""; shown = 100; render(); });
    let t = null;
    $("#ex-q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { st.q = e.target.value; shown = 100; render(); }, 120); });
    $("#ex-sort").onchange = (e) => { st.sort = e.target.value; if (st.sort === "nearest" && !here) locate(); shown = 100; render(); };
    $("#ex-town").onchange = (e) => { st.town = e.target.value; shown = 100; render(); };
    $("#ex-cuisine").onchange = (e) => { st.cuisine = e.target.value; shown = 100; render(); };
    $("#ex-chains").onchange = (e) => { st.chains = e.target.checked; shown = 100; render(); };
    $("#ex-bib").onchange = (e) => { st.bib = e.target.checked; shown = 100; render(); };
    $("#ex-clear").onclick = () => { st.town = st.cuisine = ""; st.chains = st.bib = false; syncInputs(); shown = 100; render(); };
    $("#ex-locate").onclick = locate;
    $("#ex-more").onclick = () => { shown += 200; renderList(order()); };
    document.querySelectorAll(".ex-view button").forEach((b) => b.onclick = () => setView(b.dataset.v));
    $("#ex-list").addEventListener("click", (e) => { const b = e.target.closest(".ex-row"); if (b && P[+b.dataset.i]) openPlace(P[+b.dataset.i]); });
    // warm the region file of the row under the pointer (or keyboard focus), so the panel opens with its details
    for (const ev of ["pointerover", "focusin"]) $("#ex-list").addEventListener(ev, (e) => { const b = e.target.closest && e.target.closest(".ex-row"); if (b && P[+b.dataset.i]) { loadIds(); loadDetail(P[+b.dataset.i].co); } });
    // the ids (a few hundred KB) wait for the first sign of use, so a visit that only looks doesn't download them
    const WARM = ["pointerdown", "keydown", "wheel", "scroll", "touchstart"];
    const warmIds = () => { WARM.forEach((ev) => removeEventListener(ev, warmIds, true)); loadIds(); };
    WARM.forEach((ev) => addEventListener(ev, warmIds, { capture: true, passive: true }));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#ex-panel").hidden) closePlace(); });
    window.addEventListener("popstate", fromURL);
    window.addEventListener("hashchange", fromURL);
    $("#ex-backdrop").addEventListener("click", () => { if (st.p || !$("#ex-panel").hidden) closePlace(); });
    mapEvents();
  }
  function syncInputs() {
    $("#ex-q").value = st.q; $("#ex-town").value = st.town; $("#ex-cuisine").value = st.cuisine; $("#ex-chains").checked = st.chains; $("#ex-bib").checked = st.bib;
  }

  (async () => {
    $("#ex-loading").hidden = false;   // hidden in the HTML, so a browser without JavaScript shows only the <noscript> note
    readHash();
    try { await load(); } catch (e) { $("#ex-loading").textContent = "The restaurant list couldn't load. Refresh to try again."; return; }
    syncInputs(); controls();
    $("#ex-app").hidden = false;
    $("#ex-loading").hidden = true;
    render();
    if (st.p) {
      await loadIds();
      const open = P.find((p) => p.id === st.p);
      if (open) { await loadDetail(open.co); openPlace(open, false); }
      else linkMissing();
    }
  })();
})();
