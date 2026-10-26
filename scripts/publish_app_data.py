#!/usr/bin/env python3
"""Publish this state's app data on its site, for the app's over-the-air data updates (~/Developer/claudecode/OTA-DATA.md).

  python3 scripts/publish_app_data.py [--docs DIR] [--data DIR] [--min-app-build N] [--allow-swing] [--dry-run] [--json]
  python3 scripts/publish_app_data.py --check [--docs DIR] [--json]

Publishing reads the data files the app bundles (what the pipeline exported into <App>/Resources: places.json, plus
detail-<region>.json for a core + detail layout; or every file in Resources/Data for a region layout with index.json) and
writes docs/data/app/:
  - <name>-<sha12>.json: each file byte for byte, under a content-addressed name;
  - manifest.json: schema 1, version "<records_through>.<n>", records_through (the head file's "generated": places.json, or
    index.json for a region layout), published, min_app_build, files {name: {path, sha256, bytes, rows}}, counts, and
    previous {version, files} (the manifest it replaced).
The data files go first and the manifest last. The previous manifest's files stay (phones part way through an update);
every other data file in docs/data/app/ is deleted, so an old copy (one with since-removed hijacked links, say) never lingers.
Versions: a later date is n = 1; the same date again (a correction) is n + 1; an older date is refused. The app treats its
bundled copy as n = 0 and never downloads a file whose SHA-256 it already has.

It never runs git and never uses the network: the scheduled refresh calls it after the rebuild and site QA, then waits for
Nick's OK before anything is pushed. It is idempotent: the same files again write nothing ("unchanged"), and files that
differ only in the head file's "generated" date write nothing ("no_new_data"), so phones don't download a copy with nothing new.

Exit 0: published_locally, unchanged, no_new_data or dry_run_ok. Exit 2: refused (older data; the place count moved more than
15% from the published copy without --allow-swing; a malformed or oversized file) or the self-check failed; docs/ is left as it
was. --check verifies docs/data/app/ (each file's hash, size, rows and name, the head file's date, no stray files) and exits 1 on
a problem; qa-site.py runs the same check through check_app_data().
"""
import os
import re
import sys
import json
import hashlib
import argparse
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCHEMA = 1
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATA_FILE = re.compile(r"^([a-z0-9]+(?:-[a-z0-9]+)*)-([0-9a-f]{12})\.json$")
VERSION = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(\d{1,4})$")
SWING = 0.15                                   # the app itself refuses 25% (DataUpdater.maxSwing)
MAX_FILE, MAX_TOTAL, MAX_FILES = 48 << 20, 160 << 20, 64   # DataUpdater's caps


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def real_day(s):
    try:
        return isinstance(s, str) and dt.date.fromisoformat(s).isoformat() == s
    except ValueError:
        return False


def app_data_dir(root=ROOT):
    """The folder the app bundles its data from: <Target>/Resources/Data for a region layout (index.json), else <Target>/Resources."""
    name = None
    with open(os.path.join(root, "project.yml"), encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^name:\s*(\S+)", line)
            if m:
                name = m.group(1)
                break
    if not name:
        raise SystemExit("publish_app_data: no name: in project.yml")
    res = os.path.join(root, name, "Resources")
    data = os.path.join(res, "Data")
    return data if os.path.exists(os.path.join(data, "index.json")) else res


def data_files(d):
    """({name: path}, head): the app's data files in d, and the file whose "generated" dates the copy."""
    regions = os.path.exists(os.path.join(d, "index.json"))
    out = {}
    for fn in sorted(os.listdir(d)):
        name = fn[:-5]
        if fn.endswith(".json") and (regions or name == "places" or name.startswith("detail-")):
            out[name] = os.path.join(d, fn)
    return out, ("index" if regions else "places")


def rows_of(name, j):
    """Places in a file with places, ids in a detail file, 0 for anything else (an index). The app's loader reports the same."""
    if isinstance(j, dict):
        if isinstance(j.get("places"), list):
            return len(j["places"])
        if name.startswith("detail-"):
            return len(j)
    return 0


def head_of(files):
    return "index" if "index" in files else "places"


# ---------------------------------------------------------------------------------------------------------------- check

def check_app_data(docs, data_dir=None, ignore=()):
    """(problems, notes) for docs/data/app/: every manifest entry matches its file, the previous copy's files are intact,
    nothing else is there (but `ignore`). With data_dir (the app's bundled data), a note when the app has data the site
    doesn't publish."""
    problems, notes = [], []
    d = os.path.join(docs, "data", "app")
    mp = os.path.join(d, "manifest.json")
    if not os.path.exists(mp):
        if os.path.isdir(d) and os.listdir(d):
            problems.append("docs/data/app/ has files but no manifest.json")
        else:
            notes.append("no docs/data/app/manifest.json: nothing published for the app's data updates yet")
        return problems, notes
    try:
        m = json.load(open(mp, encoding="utf-8"))
    except ValueError as e:
        return [f"docs/data/app/manifest.json doesn't parse: {e}"], notes
    bad = problems.append
    if m.get("schema") != SCHEMA:
        bad(f"manifest schema {m.get('schema')!r}, expected {SCHEMA}")
    rt, ver = m.get("records_through"), m.get("version") or ""
    vm = VERSION.match(ver)
    if not real_day(rt):
        bad(f"manifest records_through {rt!r} isn't a real yyyy-mm-dd day")
    if not vm or vm.group(1) != rt or int(vm.group(2)) < 1:
        bad(f"manifest version {ver!r} isn't <records_through>.<n>, n >= 1")
    if not isinstance(m.get("min_app_build", 1), int) or m.get("min_app_build", 1) < 1:
        bad(f"manifest min_app_build {m.get('min_app_build')!r}")
    files = m.get("files")
    if not isinstance(files, dict) or not files:
        bad("manifest has no files")
        files = {}
    if len(files) > MAX_FILES:
        bad(f"{len(files)} files, more than the app's {MAX_FILES}")
    head = head_of(files)
    if head not in files:
        bad("manifest has neither places nor index")
    total = 0
    for name, f in sorted(files.items()):
        where = f"docs/data/app/{f.get('path')} ({name})"
        if not NAME.match(name):
            bad(f"file name {name!r} isn't lowercase words joined by hyphens")
            continue
        sha, path = str(f.get("sha256", "")).lower(), f.get("path", "")
        if not re.fullmatch(r"[0-9a-f]{64}", sha) or path != f"{name}-{sha[:12]}.json":
            bad(f"{where}: path isn't {name}-<first 12 of its sha256>.json")
            continue
        p = os.path.join(d, path)
        if not os.path.exists(p):
            bad(f"{where}: missing")
            continue
        b = open(p, "rb").read()
        total += len(b)
        if sha256(b) != sha:
            bad(f"{where}: sha256 {sha256(b)[:12]}..., manifest {sha[:12]}...")
        if len(b) != f.get("bytes"):
            bad(f"{where}: {len(b)} bytes, manifest {f.get('bytes')}")
        if len(b) > MAX_FILE:
            bad(f"{where}: {len(b)} bytes, over the app's {MAX_FILE} cap")
        try:
            j = json.loads(b)
        except ValueError as e:
            bad(f"{where}: doesn't parse ({e})")
            continue
        if rows_of(name, j) != f.get("rows"):
            bad(f"{where}: {rows_of(name, j)} rows, manifest {f.get('rows')}")
        if name == head and (not isinstance(j, dict) or j.get("generated") != rt):
            bad(f"{where}: generated {j.get('generated') if isinstance(j, dict) else None!r}, manifest records_through {rt!r}")
    if total > MAX_TOTAL:
        bad(f"{total} bytes in all, over the app's {MAX_TOTAL} cap")
    keep = {"manifest.json"} | {f.get("path") for f in files.values()}
    prev = m.get("previous") or {}
    for name, path in sorted((prev.get("files") or {}).items()):
        keep.add(path)
        p = os.path.join(d, path)
        dm = DATA_FILE.match(path or "")
        if not dm or not os.path.exists(p):
            bad(f"docs/data/app/{path}: the previous copy's {name} is missing (phones part way through an update need it)")
        elif sha256(open(p, "rb").read())[:12] != dm.group(2):
            bad(f"docs/data/app/{path}: content doesn't match its name")
    for fn in sorted(os.listdir(d)):
        if fn not in keep and fn not in ignore:
            bad(f"docs/data/app/{fn}: stray file the manifest doesn't name (publish_app_data.py removes old copies)")
    if data_dir and os.path.isdir(data_dir):
        bundled, bhead = data_files(data_dir)
        if bhead in bundled:
            try:
                gen = json.load(open(bundled[bhead], encoding="utf-8")).get("generated")
            except ValueError:
                gen = None
            same = all(n in files and sha256(open(p, "rb").read()) == str(files[n].get("sha256", "")).lower() for n, p in bundled.items())
            if gen and rt and gen > rt:
                notes.append(f"the app's data ({gen}) is newer than the published copy ({rt}): run scripts/publish_app_data.py")
            elif not same:
                notes.append("the app's bundled data differs from the published copy")
    return problems, notes


# -------------------------------------------------------------------------------------------------------------- publish

def load_files(data_dir):
    files, head = data_files(data_dir)
    if head not in files:
        raise Refused(f"no {head}.json in {data_dir}")
    if len(files) > MAX_FILES:
        raise Refused(f"{len(files)} data files, more than the app's {MAX_FILES}")
    blobs, parsed = {}, {}
    for name, p in files.items():
        if not NAME.match(name):
            raise Refused(f"{os.path.basename(p)}: names must be lowercase words joined by hyphens")
        b = open(p, "rb").read()
        if not b or len(b) > MAX_FILE:
            raise Refused(f"{os.path.basename(p)}: {len(b)} bytes (the app takes 1 to {MAX_FILE})")
        try:
            parsed[name] = json.loads(b)
        except ValueError as e:
            raise Refused(f"{os.path.basename(p)} doesn't parse: {e}")
        blobs[name] = b
    if sum(map(len, blobs.values())) > MAX_TOTAL:
        raise Refused(f"{sum(map(len, blobs.values()))} bytes in all, over the app's {MAX_TOTAL} cap")
    return blobs, parsed, head


class Refused(Exception):
    pass


def only_date_changed(old, blobs, parsed, head, d):
    """The new files are the published ones but for the head file's "generated"."""
    if set(old.get("files", {})) != set(blobs):
        return False
    for name, b in blobs.items():
        f = old["files"][name]
        if name != head:
            if sha256(b) != f.get("sha256"):
                return False
            continue
        p = os.path.join(d, f.get("path", ""))
        if not os.path.exists(p):
            return False
        try:
            was = json.load(open(p, encoding="utf-8"))
        except ValueError:
            return False
        if not isinstance(was, dict) or not isinstance(parsed[name], dict):
            return False
        was, now = dict(was), dict(parsed[name])
        was.pop("generated", None)
        now.pop("generated", None)
        if was != now:
            return False
    return True


def write_bytes(p, b):
    with open(p + ".part", "wb") as f:
        f.write(b)
    os.replace(p + ".part", p)


def publish(a):
    data_dir = os.path.abspath(a.data or app_data_dir())
    docs = os.path.abspath(a.docs)
    out = os.path.join(docs, "data", "app")
    res = {"status": None, "data": data_dir, "out": out}
    blobs, parsed, head = load_files(data_dir)
    rt = parsed[head].get("generated") if isinstance(parsed[head], dict) else None
    if not real_day(rt):
        raise Refused(f"{head}.json has no generated date (got {rt!r})")
    entries = {n: {"path": f"{n}-{sha256(b)[:12]}.json", "sha256": sha256(b), "bytes": len(b), "rows": rows_of(n, parsed[n])}
               for n, b in sorted(blobs.items())}
    places = sum(len(j["places"]) for j in parsed.values() if isinstance(j, dict) and isinstance(j.get("places"), list))
    counts = {"places": places, "files": len(blobs), "bytes": sum(map(len, blobs.values()))}
    if isinstance(parsed[head], dict) and isinstance(parsed[head].get("count_restaurants"), int):
        counts["restaurants"] = parsed[head]["count_restaurants"]
    old = None
    mp = os.path.join(out, "manifest.json")
    if os.path.exists(mp):
        try:
            old = json.load(open(mp, encoding="utf-8"))
        except ValueError as e:
            raise Refused(f"docs/data/app/manifest.json doesn't parse ({e}): look at it before publishing over it")
    n, min_build = 1, max(a.min_app_build or 1, 1)
    if old:
        om = VERSION.match(old.get("version") or "")
        if not om:
            raise Refused(f"the published manifest's version {old.get('version')!r} isn't <date>.<n>")
        min_build = max(min_build, old.get("min_app_build", 1))
        if {k: v["sha256"] for k, v in old.get("files", {}).items()} == {k: v["sha256"] for k, v in entries.items()} and \
                old.get("min_app_build", 1) == min_build:
            res.update(status="unchanged", version=old["version"], records_through=old.get("records_through"))
            problems, _ = check_app_data(docs)
            if problems and not a.dry_run:
                # the published copy, damaged or with leftovers: put its files back and remove the rest
                for name, e in old["files"].items():
                    p = os.path.join(out, e["path"])
                    if not os.path.exists(p) or open(p, "rb").read() != blobs[name]:
                        write_bytes(p, blobs[name])
                keep = {"manifest.json"} | {e["path"] for e in old["files"].values()} | \
                    set(((old.get("previous") or {}).get("files") or {}).values())
                for fn in os.listdir(out):
                    if DATA_FILE.match(fn) and fn not in keep:
                        os.remove(os.path.join(out, fn))
                problems, _ = check_app_data(docs)
                res["repaired"] = True
            if problems:
                raise Refused("the published copy has problems: " + "; ".join(problems))
            return res
        if only_date_changed(old, blobs, parsed, head, out) and old.get("min_app_build", 1) == min_build:
            res.update(status="no_new_data", version=old["version"], records_through=old.get("records_through"),
                       detail=f"only {head}.json's generated date changed ({old.get('records_through')} -> {rt})")
            return res
        if rt < om.group(1):
            raise Refused(f"the data is dated {rt}, older than the published {old['version']}")
        n = int(om.group(2)) + 1 if rt == om.group(1) else 1
        was = (old.get("counts") or {}).get("places")
        if isinstance(was, int) and was > 0 and abs(places - was) > was * SWING and not a.allow_swing:
            raise Refused(f"{places} places against {was} published ({(places - was) / was:+.0%}): a pipeline problem? "
                          f"--allow-swing publishes it anyway (the app refuses more than 25%)")
    version = f"{rt}.{n}"
    manifest = {"schema": SCHEMA, "version": version, "records_through": rt,
                "published": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "min_app_build": min_build, "files": entries, "counts": counts}
    if old:
        manifest["previous"] = {"version": old["version"], "files": {k: v["path"] for k, v in sorted(old.get("files", {}).items())}}
    keep = {"manifest.json"} | {e["path"] for e in entries.values()} | set((manifest.get("previous") or {}).get("files", {}).values())
    existing = sorted(os.listdir(out)) if os.path.isdir(out) else []
    prune = [fn for fn in existing if DATA_FILE.match(fn) and fn not in keep]
    write = [e["path"] for e in entries.values() if not os.path.exists(os.path.join(out, e["path"]))]
    res.update(version=version, records_through=rt, counts=counts, write=write, prune=prune,
               previous=old.get("version") if old else None)
    if a.dry_run:
        res["status"] = "dry_run_ok"
        return res
    os.makedirs(out, exist_ok=True)
    before = open(mp, "rb").read() if os.path.exists(mp) else None
    written = []
    try:
        for name, e in entries.items():
            p = os.path.join(out, e["path"])
            if not os.path.exists(p) or open(p, "rb").read() != blobs[name]:
                write_bytes(p, blobs[name])
                written.append(p)
        write_bytes(mp, (json.dumps(manifest, indent=1) + "\n").encode())
        problems, _ = check_app_data(docs, ignore=set(prune))
        if problems:
            raise Refused("self-check failed: " + "; ".join(problems))
    except BaseException:
        # put docs/data/app/ back as it was (old copies are removed only after the new one checked out)
        for p in written:
            if os.path.exists(p) and os.path.basename(p) not in {e["path"] for e in (old or {}).get("files", {}).values()}:
                os.remove(p)
        if before is None:
            if os.path.exists(mp):
                os.remove(mp)
        else:
            write_bytes(mp, before)
        raise
    for fn in prune:
        os.remove(os.path.join(out, fn))
    res["status"] = "published_locally"
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--docs", default=os.path.join(ROOT, "docs"), help="the site folder (default: docs/ next to scripts/)")
    ap.add_argument("--data", help="the app's data folder (default: from project.yml, <App>/Resources or Resources/Data)")
    ap.add_argument("--min-app-build", type=int, help="the oldest app build that can read this data (default: as published, else 1)")
    ap.add_argument("--allow-swing", action="store_true", help="publish although the place count moved more than 15%%")
    ap.add_argument("--dry-run", action="store_true", help="say what would change and write nothing")
    ap.add_argument("--check", action="store_true", help="only check docs/data/app/ (what qa-site.py runs)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    a = ap.parse_args()
    if a.check:
        try:
            data_dir = a.data or app_data_dir()
        except (OSError, SystemExit):
            data_dir = None
        problems, notes = check_app_data(os.path.abspath(a.docs), data_dir)
        if a.json:
            print(json.dumps({"status": "ok" if not problems else "problems", "problems": problems, "notes": notes}, indent=1))
        else:
            for x in notes:
                print("  note:", x)
            for x in problems:
                print("  ✗", x)
            print("app data: OK" if not problems else f"app data: {len(problems)} problems")
        sys.exit(1 if problems else 0)
    try:
        res = publish(a)
    except Refused as e:
        res = {"status": "refused", "reason": str(e)}
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        s = res["status"]
        if s == "refused":
            print(f"publish_app_data: refused: {res['reason']}")
        elif s in ("unchanged", "no_new_data"):
            print(f"publish_app_data: {s} ({res.get('version')}){': ' + res['detail'] if res.get('detail') else ''}; nothing written")
        else:
            c = res["counts"]
            print(f"publish_app_data: {s} {res['version']} (records through {res['records_through']}; {c['places']:,} places in "
                  f"{c['files']} files, {c['bytes']:,} bytes){'; replaces ' + res['previous'] if res.get('previous') else ''}")
            for p in res.get("write", []):
                print("  write docs/data/app/" + p)
            for p in res.get("prune", []):
                print("  delete docs/data/app/" + p)
    sys.exit(2 if res["status"] == "refused" else 0)


if __name__ == "__main__":
    main()
