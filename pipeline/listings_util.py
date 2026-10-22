"""Matching map listings to official license records (used by calibrate.py and colorado.py). Adapted from wi-eats."""
import math
from rapidfuzz import fuzz
from common import name_sim, _stems, GENERIC
from official import street_key, street_nums, street_compat


def _close_words(a, b):
    """A distinctive word in common, allowing a spelling slip ("HIMAL CHULI" / "HIMALI CHULO")."""
    return any(x == y or (len(x) >= 5 and len(y) >= 5 and fuzz.ratio(x, y) >= 85) for x in a for y in b)


def official_match(L, R, one_to_one=False, town_words=frozenset(), street_col="street"):
    """L: listings with k (name key), street, lat, lon. R: official records with keys, num, street, addr, lat, lon.
    Returns {listing index: official index}. A match needs the same business name nearby, or the same street address
    with a distinctive (non-generic, non-town) name word in common."""
    by_num, grid = {}, {}
    for j, (a, st) in enumerate(zip(R.addr, R.street)):
        for n in street_nums(a):
            if st:
                by_num.setdefault(n, []).append(j)
    for j, (la, lo) in enumerate(zip(R.lat, R.lon)):
        if la == la and lo == lo:
            grid.setdefault((round(la / 0.0015), round(lo / 0.002)), []).append(j)
    rstems = [set().union(*[(_stems(k) - GENERIC - town_words) for k in ks]) if ks else set() for ks in R["keys"]]
    rnums = [street_nums(a) for a in R.addr]
    pairs = []
    for i, (k, street, la, lo) in enumerate(zip(L.k, L[street_col], L.lat, L.lon)):
        if not k:
            continue
        _, st = street_key(street)
        nums = street_nums(street)
        cand = set()
        for n in nums:
            cand.update(j for j in by_num.get(n, []) if street_compat(st, R.street.iat[j]))
        if la == la:
            gy, gx = round(la / 0.0015), round(lo / 0.002)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    cand.update(grid.get((gy + dy, gx + dx), []))
        mine = _stems(k) - GENERIC - town_words
        for j in cand:
            same_addr = bool(st and street_compat(R.street.iat[j], st) and nums & rnums[j])
            rl, ro = R.lat.iat[j], R.lon.iat[j]
            dist = math.hypot((rl - la) * 111000, (ro - lo) * 79000) if (rl == rl and la == la) else (40 if same_addr else 9999)
            s = max((name_sim(k, rk) for rk in R["keys"].iat[j]), default=0)
            shared = bool(mine & rstems[j]) or _close_words(mine, rstems[j])
            if same_addr and rl == rl and la == la and dist > 2000:
                same_addr = False
            if (same_addr and (s >= 75 or shared)) or (dist <= 150 and s >= 88) or (dist <= 60 and s >= 80 and shared):
                pairs.append((s + (15 if same_addr else 0) - dist / 20, i, j))
    out, taken_l, taken_r = {}, set(), set()
    for sc, i, j in sorted(pairs, key=lambda t: -t[0]):
        if i in taken_l or (one_to_one and j in taken_r):
            continue
        taken_l.add(i); taken_r.add(j); out[i] = j
    return out
