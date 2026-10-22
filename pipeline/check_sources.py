"""Every host the research cites, checked against its robots.txt: a source is usable only if its host lets ClaudeBot, Claude-User
and anthropic-ai fetch that path and doesn't answer with a bot check. One robots.txt request per host, cached for 7 days.

    ../.venv/bin/python check_sources.py            # report -> data/research/source_hosts.json, exit 1 if any record cites a blocked URL
    ../.venv/bin/python check_sources.py URL ...    # before using a new source: "usable" or why not, per URL
"""
import glob, json, os, re, subprocess, sys, time, urllib.parse
from datetime import date, datetime
import requests

R = os.path.join(os.path.dirname(__file__), "..", "data", "research")
CACHE = os.path.join(R, "source_hosts.json")
AGENTS = ("ClaudeBot", "Claude-User", "anthropic-ai")
UA = "TexasEatsSourceCheck/1.0 (+nick@eatsranked.com)"
# official data portals we read through their APIs: their robots.txt governs crawling the HTML site, not the documented API
API_HOSTS = set()


def records():
    for f in sorted(glob.glob(f"{R}/app/*.json")) + sorted(glob.glob(f"{R}/*.json")):
        if f.endswith("source_hosts.json") or f.endswith("geocode_census.json") or f.endswith("geocode_todo.json"):
            continue
        d = json.load(open(f))
        if isinstance(d, dict):
            d = d.get("places") or d.get("restaurants") or []
        for x in d:
            if isinstance(x, dict):
                yield os.path.relpath(f, R), x


def host(u):
    return urllib.parse.urlsplit(u).netloc.lower().removeprefix("www.")


def check_host(h):
    for attempt in range(2):
        c = _check_host(h)
        if c["verdict"] != "unreachable":
            return c
        time.sleep(3)
    return c


def _get(url):
    """(status, content type, body) of one GET with our own user agent. Some servers reset Python's TLS client but answer curl
    (michelinmedia.com): curl is the same plain request with the same honest user agent, not a workaround for a bot check."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True)
        return r.status_code, r.headers.get("content-type", ""), r.text[:200_000]
    except requests.RequestException as e:
        if not isinstance(e, requests.ConnectionError) or "reset" not in str(e).lower():
            raise
    out = subprocess.run(["curl", "-sL", "--max-time", "20", "-A", UA, "-o", "-", "-w", "\n%{http_code} %{content_type}", url],
                         capture_output=True, text=True, timeout=40)
    body, _, tail = out.stdout.rpartition("\n")
    code, _, ctype = tail.partition(" ")
    if not code.isdigit() or code == "000":
        raise requests.ConnectionError(f"curl exit {out.returncode}")
    return int(code), ctype, body[:200_000]


def _check_host(h):
    err = None
    for scheme_host in (f"https://www.{h}", f"https://{h}"):
        try:
            status, ctype, body = _get(scheme_host + "/robots.txt")
        except (requests.RequestException, subprocess.SubprocessError) as e:
            err = type(e).__name__
            continue
        challenge = bool(re.search(r"Just a moment|cf-chl|captcha|Attention Required", body[:3000], re.I))
        if status in (401, 403, 429, 503) or challenge:
            return {"status": status, "verdict": "bot check", "rules": None}
        if status >= 400 or "html" in ctype and "<html" in body[:500].lower():
            return {"status": status, "verdict": "ok", "rules": None}          # no robots.txt: nothing disallowed
        return {"status": status, "verdict": "ok", "rules": body}
    return {"status": None, "verdict": "unreachable", "rules": None, "error": err}


def refresh(cache, hosts, quiet=False):
    fresh = date.today().toordinal() - 7
    for i, h in enumerate(hosts):
        c = cache.get(h)
        if c and c["verdict"] != "unreachable" and date.fromisoformat(c["checked"]).toordinal() >= fresh:
            continue
        cache[h] = dict(check_host(h), checked=date.today().isoformat())
        time.sleep(0.5)
        if i % 25 == 0 and not quiet:
            print(f"  {i}/{len(hosts)}", flush=True)
    # several checkers run at once (research agents, the build): merge with what's on disk now, or one run's save drops another's hosts
    on_disk = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    for h, v in on_disk.items():
        if h not in cache or v.get("checked", "") > cache[h].get("checked", ""):
            cache[h] = v
    tmp = f"{CACHE}.{os.getpid()}.tmp"
    json.dump(cache, open(tmp, "w"), indent=1)
    os.replace(tmp, CACHE)


def _groups(text):
    """robots.txt -> [(agent tokens, [(allow, pattern)])], per RFC 9309 (consecutive user-agent lines share one group)."""
    groups, agents, rules, last = [], [], [], None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if last != "user-agent" and (agents or rules):
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(v.lower())
        elif k in ("allow", "disallow") and agents:
            rules.append((k == "allow", v))
        else:
            continue
        last = k
    if agents:
        groups.append((agents, rules))
    return groups


def _pat(p):
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in p.rstrip("$"))
    return re.compile(rx + ("$" if p.endswith("$") else ""))


def robots_allows(text, agent, url):
    """True when robots.txt lets `agent` fetch `url`. Python's urllib.robotparser ignores `*` and `$` in paths, so it called
    apps.isp.idaho.gov's `Disallow: /AbcReporting/*/search` an allowed path; this follows RFC 9309: the agent's own group (else
    `*`), the longest matching rule wins, Allow wins a tie, an empty Disallow allows everything."""
    parts = urllib.parse.urlsplit(url)
    path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
    groups = _groups(text)
    mine = [r for a, r in groups if any(t != "*" and t in agent.lower() for t in a)]
    rules = [x for r in (mine or [r for a, r in groups if "*" in a]) for x in r]
    best = None
    for allow, p in rules:
        if p == "" or not _pat(p).match(path):
            continue
        key = (len(p), allow)
        if best is None or key > best:
            best = key
    return best is None or best[1]


def why_not(cache, u):
    """None when the URL is usable, else the reason."""
    h = host(u)
    if h in API_HOSTS:
        return None
    c = cache[h]
    if c["verdict"] != "ok":
        return c["verdict"]
    if c.get("rules"):
        blocked = [a for a in AGENTS if not robots_allows(c["rules"], a, u)]
        if blocked:
            return "robots.txt disallows " + ", ".join(blocked)
    return None


def main():
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    if len(sys.argv) > 1:
        refresh(cache, sorted({host(u) for u in sys.argv[1:]} - API_HOSTS), quiet=True)
        reasons = {u: why_not(cache, u) for u in sys.argv[1:]}
        for u, why in reasons.items():
            print(("usable  " if why is None else f"NO ({why})  ") + u)
        sys.exit(1 if any(reasons.values()) else 0)
    urls = {}
    for f, x in records():
        for s in x.get("sources") or []:
            urls.setdefault(s, []).append((f, x.get("name")))
    refresh(cache, sorted({host(u) for u in urls} - API_HOSTS))
    bad = {}
    for u, where in urls.items():
        why = why_not(cache, u)
        if why:
            bad[u] = (why, where)
    print(f"{len(urls)} source URLs on {len({host(u) for u in urls})} hosts; {len(bad)} unusable")
    by_host = {}
    for u, (why, where) in bad.items():
        by_host.setdefault((host(u), why), []).extend(where)
    for (h, why), where in sorted(by_host.items()):
        names = sorted({f"{n} ({f})" for f, n in where})
        print(f"- {h}: {why} | {len(names)} records: {'; '.join(names[:12])}{' …' if len(names) > 12 else ''}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
