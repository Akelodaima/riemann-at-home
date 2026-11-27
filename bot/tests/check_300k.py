"""The second proof, 300K (grh-lean, readable edition), CONTRACT "Several proofs" (2026-11-25).
  - 300K records are checked as strictly as 17M ones: pinned toolchain, Mathlib and commit; the 300K module list
    (bitmap length, popcount); axioms of a whole build; schema (unknown fields, 17M-only fields); speed
  - one leaderboard: tiers both proofs, then 17M only, then 300K only, then partial builds
  - re-submitting a finished 300K build does not move its finish time or build hours (issue #12's bug class)
  - a poll round over fake PRs accepts a 300K build and publishes it

Self-contained: the records are written here, from the CONTRACT's numbers, not from the bot's own tables, so this
file also shows the old bot (without 300K) failing. RAHBOT=path/to/rahbot picks the bot to test (default ../rahbot).
Run from bot/: python3 -I tests/check_300k.py"""
import base64, contextlib, copy, gzip, hashlib, io, json, os, shutil, subprocess, sys, tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

BOT = Path(os.environ.get("RAHBOT") or Path(__file__).resolve().parent.parent / "rahbot").resolve()
rb = SourceFileLoader("rahbot_300k", str(BOT)).load_module()
FIX = Path(__file__).resolve().parent / "fixtures" / "sample"
fails = 0


def check(ok, what):
    global fails
    print(("  ok    " if ok else "  FAIL  ") + what)
    fails += not ok


def run(what, fn):
    """One case; an exception (an old bot without 300K) counts as a failure, not a crash of the whole file."""
    try:
        fn()
    except Exception as e:
        check(False, f"{what}: {type(e).__name__}: {e}")


# ---- 300K constants, as CONTRACT.md states them -------------------------------------------------------------------
N300 = 803
COMMIT = "72fead102f663d5c7a407964a13dc0cf9d977207"
TOOLCHAIN = "leanprover/lean4:v4.35.0"
MATHLIB = "56a005855ea17e0b0958f73ec801ae140b0a1679"
FOLDER = "/Users/Shared/riemann-at-home/grh"
AX = ["propext", "Classical.choice", "Quot.sound"]
check(hashlib.sha256((BOT.parent / "modules-300k.txt").read_bytes()).hexdigest()
      == "f0b574a8ad08e8049f098971f03e5cc3087ffb23e2d9f9692a389ccb924813d1"
      if (BOT.parent / "modules-300k.txt").exists() else False, "bot/modules-300k.txt is the pinned 803-module list")


def bitmap(idx, n):
    b = bytearray((n + 7) // 8)
    for i in idx:
        b[i >> 3] |= 1 << (i & 7)
    return base64.b64encode(gzip.compress(bytes(b), mtime=0)).decode()


def bid(tag):
    return hashlib.sha256(tag.encode()).hexdigest()[:16]


def rec300(started, recorded, idx, build, cores=12, **over):
    t0, t1 = rb.parse_ts(started), rb.parse_ts(recorded)
    idx = sorted(set(idx))
    r = {"format": "rah/build/1", "tool": "riemann-at-home 1.1.0", "proof": "300k", "source_commit": COMMIT,
         "toolchain": TOOLCHAIN, "mathlib_rev": MATHLIB, "build_folder": FOLDER, "build_id": bid(build),
         "machine": {"os": "Darwin 25.4.0", "arch": "arm64", "cpu": "Apple M3 Pro", "cores": cores},
         "started": started, "recorded": recorded, "busy_seconds": int((t1 - t0).total_seconds() * 0.9),
         "modules_compiled": len(idx), "bitmap_b64": bitmap(idx, N300),
         "olean_digest": hashlib.sha256(build.encode()).hexdigest(), "whole_proof": False, "axioms": None, "final": False}
    r.update(over)
    return r


ALL = range(N300)
WHOLE = rec300("2026-11-25T10:00:00Z", "2026-11-25T11:10:00Z", ALL, "kim-300k", whole_proof=True, axioms=AX)
PART = rec300("2026-11-25T10:00:00Z", "2026-11-25T10:40:00Z", range(400), "kim-300k")
path = lambda login, r: f"submissions/{login}/{r['build_id']}.json"


def rejects(rec, login="kim", prev=None, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return rb.check_record(rec, login, path(login, rec), prev, now=rb.parse_ts("2026-11-26T00:00:00Z"), **kw)[0]


def says(rec, text, **kw):
    r = rejects(rec, **kw)
    return bool(r) and any(text in x for x in r), r


# ---- acceptance rules -------------------------------------------------------------------------------------------
print("300K records")
def acceptance():
    check(rejects(PART) == [], f"a partial 300K build is accepted: {rejects(PART)}")
    check(rejects(WHOLE, prev=PART) == [], f"the whole 300K build (all 803 modules, three axioms) is accepted after it: {rejects(WHOLE, prev=PART)}")
    check(rejects(WHOLE) == [], "a whole 300K build as a first version is accepted")
    with contextlib.redirect_stdout(io.StringIO()):
        rj, fl, _ = rb.check_record(WHOLE, "kim", path("kim", WHOLE), None, check_digest=True,
                                    now=rb.parse_ts("2026-11-26T00:00:00Z"))
    check(rj == [] and not any(f.startswith("PENDING") for f in fl), f"--check-digest: no 300K reference, so not pending: {rj} {fl}")
run("acceptance", acceptance)

def strict():
    for what, rec, text in [
        ("wrong toolchain", {**WHOLE, "toolchain": "leanprover/lean4:v4.33.1"}, "toolchain"),
        ("wrong Mathlib", {**WHOLE, "mathlib_rev": "0df444a360eaa60ab8c11dca51a86af692955474"}, "mathlib_rev"),
        ("wrong commit", {**WHOLE, "source_commit": "ce4eb6fb2591d62095c5aa61b7a21414c7385bd5"}, "source_commit"),
        ("17M build folder", {**WHOLE, "build_folder": "/Users/Shared/riemann-at-home/lean"}, "build_folder"),
        ("modules_compiled != popcount", {**PART, "modules_compiled": 401}, "popcount"),
        ("bitmap sized for the 17M list", {**PART, "bitmap_b64": bitmap(range(400), 175187)}, "bitmap"),
        ("whole claimed, 802 of 803", {**WHOLE, "bitmap_b64": bitmap(range(802), N300), "modules_compiled": 802}, "802 of 803"),
        ("whole with sorryAx", {**WHOLE, "axioms": AX + ["sorryAx"]}, "sorryAx"),
        ("whole, axiom check not run", {**WHOLE, "axioms": None}, "axiom check did not run"),
        ("whole, only two axioms", {**WHOLE, "axioms": AX[:2]}, "not exactly"),
        ("17M archive field on a 300K record", {**WHOLE, "archive_sha256": rb.ARCHIVE_SHA256}, "unknown fields"),
        ("no source_commit", {k: v for k, v in WHOLE.items() if k != "source_commit"}, "missing fields"),
        ("an unknown field", {**WHOLE, "lines": 300000}, "unknown fields"),
        ("an unknown proof", {**WHOLE, "proof": "1b"}, "proof"),
        ("checkers (17M only)", {**WHOLE, "checkers": [{"name": "nanoda", "version": "1", "result": "accept", "seconds": 1}]}, "17M only"),
        ("a 300K export on a partial build", {**PART, "export_sha256": "a" * 64, "export_bytes": 10}, "whole_proof"),
        ("a malformed 300K export hash", {**WHOLE, "export_sha256": "XYZ", "export_bytes": 10}, "64 lowercase hex"),
        ("signing a partial 300K build (issue #76: only a whole one)", {**PART, "sign_statement": True}, "three standard axioms"),
        ("speed: 800 modules in 1 minute on 1 core", {**PART, "machine": {**PART["machine"], "cores": 1},
         "bitmap_b64": bitmap(range(800), N300), "modules_compiled": 800, "started": "2026-11-25T10:39:00Z",
         "busy_seconds": 50}, None),
    ]:
        ok, got = says(rec, text) if text else (True, None)
        if text is None:                        # 300K: 803 modules can never exceed the limits (see CONTRACT); flag only
            got = rejects(rec)
            check(got == [], f"{what}: accepted (the speed rule cannot reach 803 modules; CONTRACT notes it): {got}")
            continue
        check(ok, f"{what}: rejected ({'; '.join(got or [])[:110]})")
    ok, got = says(WHOLE, "switch proofs", prev={**PART, "proof": "17m"})
    check(ok, f"a build cannot switch proofs: {got}")
    ok, got = says(PART, "shrank", prev=WHOLE)
    check(ok, "300K bitmap may not shrink")
run("strict", strict)

def seventeen_unchanged():
    idx = json.load(open(Path(__file__).resolve().parent / "fixtures/check/index.json"))
    r17 = json.load(open(BOT.parent / idx["alice2"]["file"]))
    check("proof" not in r17 and rejects(r17, "alice") == [], "a 17M record without `proof` is still a 17M record")
    check(rejects({**r17, "proof": "17m"}, "alice") == [], "and \"proof\": \"17m\" says the same")
run("17M unchanged", seventeen_unchanged)


# ---- one leaderboard, tiers -------------------------------------------------------------------------------------
print("leaderboard tiers")
tmp = Path(tempfile.mkdtemp())
try:
    shutil.copytree(FIX / "main", tmp / "main"); shutil.copytree(FIX / "open", tmp / "open")
    dirs = [tmp / "main", tmp / "open"]
    def put(login, r):
        p = tmp / "open" / login / f"{r['build_id']}.json"; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(r)); return p
    # carol: whole 17M (sample main) + whole 300K -> BOTH; kim: 300K only; lee: 300K partial; frank: 17M only
    carol300 = rec300("2026-11-25T12:00:00Z", "2026-11-25T12:40:00Z", ALL, "carol-300k", whole_proof=True, axioms=AX)
    kim300 = WHOLE
    lee300 = rec300("2026-11-25T10:00:00Z", "2026-11-25T10:20:00Z", range(200), "lee-300k")
    put("carol", carol300); kimf = put("kim", kim300); put("lee", lee300)

    def board(**kw):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return rb.build_data(dirs, now=rb.parse_ts("2026-11-26T00:00:00Z"), **kw)
        except TypeError:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return rb.build_data(dirs, **kw)

    def tiers():
        d = board()
        lb = d["leaderboard"]; who = [r["who"] or r["name"] for r in lb]
        print("    order:", [(r["who"] or r["name"], r.get("tier")) for r in lb])
        row = {r["who"] or r["name"]: r for r in lb}
        check(set(who) >= {"carol", "kim", "lee", "frank"}, f"300K people are on the one leaderboard: {who}")
        check(row["carol"].get("tier") == "17m+300k" and who[0] == "carol", "carol (17M + 300K) is first, tier BOTH")
        check(row["frank"].get("tier") == "17m" and who.index("frank") < who.index("kim"), "frank (17M only) ranks above kim (300K only)")
        check(row["kim"].get("tier") == "300k" and who.index("kim") < who.index("lee"), "kim (300K only) ranks above lee (partial)")
        check(all(row[w].get("tier") == "partial" for w in who[who.index("lee"):]), "partial builds come last")
        k = row["kim"].get("proofs", {}).get("300k", {})
        check(k.get("whole") is True and k.get("finished") == "2026-11-25T11:10:00Z" and round(k.get("build_hours") or 0, 1) == 1.1
              and k.get("n") == 803 and k.get("rank") == 1, f"kim's proofs.300k: {k}")
        check(row["kim"]["whole_proof"] is False and row["kim"]["modules"] == 0 and "17m" not in row["kim"]["proofs"],
              "17M fields stay about 17M (a 300K-only row has whole_proof false, 0 modules)")
        check(row["carol"]["proofs"]["300k"]["rank"] == 2 and row["carol"]["first_whole_proof_rank"] == 1,
              "ranks per proof: carol finished 300K second, 17M first")
        run_ = [e for e in d["running"] if e.get("who") == "lee"]
        check(run_ and run_[0].get("proof") == "300k" and run_[0]["modules"] == 200, f"lee's running entry says proof 300k: {run_}")
        check(d.get("proofs", {}).get("300k", {}).get("n") == 803 and d["proofs"]["300k"]["whole_proofs"] == 2
              and d["n"] == 175187, "data.json proofs: 300K n 803, 2 whole; top-level n stays 17M")
        check(d["summary"]["whole_proofs"] == 2, "summary.whole_proofs still counts 17M only (carol, frank)")
        # the 17M terrain is not touched by 300K builds
        b = gzip.decompress(base64.b64decode(d["builders_b64"]))
        check(len(b) == 175187, "terrain is the 17M module list")
        (tmp / "data-300k.json").write_text(json.dumps(d))
        md = rb.homepage_markdown(d, (BOT.parent.parent / "docs/index.html").read_text())
        check("### Both proofs built" in md and "### 300K proof built" in md and "kim" in md, "index.md lists the tiers")
    run("tiers", tiers)

    def resubmit():
        ledger = {}
        before = {r["who"] or r["name"]: r for r in board(firsts=ledger)["leaderboard"]}["kim"]["proofs"]["300k"]
        r = json.loads(kimf.read_text()); r["recorded"] = "2026-11-25T23:00:00Z"; r["busy_seconds"] += 7200
        kimf.write_text(json.dumps(r))
        after = {x["who"] or x["name"]: x for x in board(firsts=ledger)["leaderboard"]}["kim"]["proofs"]["300k"]
        check(after["finished"] == before["finished"] == "2026-11-25T11:10:00Z",
              f"re-submit keeps the 300K finish time ({after['finished']})")
        check(after["build_hours"] == before["build_hours"], f"re-submit keeps the 300K build hours ({after['build_hours']})")
        check(after["rank"] == before["rank"] == 1, "re-submit keeps the 300K rank")
        check(ledger.get("kim", {}).get("whole_300k") == "2026-11-25T11:10:00Z", f"ledger key whole_300k: {ledger.get('kim')}")
        # state AND ledger lost: the finish time comes back from the published data.json
        pub = board(firsts=copy.deepcopy(ledger))
        lost = {x["who"] or x["name"]: x for x in board(firsts={}, published=pub)["leaderboard"]}["kim"]["proofs"]["300k"]
        check(lost["finished"] == "2026-11-25T11:10:00Z", f"ledger lost: 300K finish time from the published data.json ({lost['finished']})")
        kimf.write_text(json.dumps(kim300))
    run("re-submit", resubmit)
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# ---- poll over fake PRs ---------------------------------------------------------------------------------------------
print("poll")
def poll():
    fx = Path(tempfile.mkdtemp()); wd = fx / "work"
    try:
        (fx / "versions").mkdir()
        for k, r in (("part", PART), ("whole", WHOLE), ("bad", {**WHOLE, "recorded": "2026-11-25T11:20:00Z",
                                                                  "axioms": AX + ["sorryAx"]})):
            (fx / "versions" / f"{k}.json").write_text(json.dumps(r))
        pr = lambda k, head: {"number": 1, "author": "kim", "branch": f"rah/{PART['build_id']}", "head": head,
                              "files": [{"path": path("kim", PART), "changeType": "ADDED"}], "content_file": f"versions/{k}.json"}
        rounds = [{"now": "2026-11-25T10:45:00Z", "prs": [pr("part", "h1")]},
                  {"now": "2026-11-25T11:15:00Z", "prs": [pr("whole", "h2")]},
                  {"now": "2026-11-25T11:30:00Z", "prs": [pr("bad", "h3")]}]
        (fx / "rounds.json").write_text(json.dumps(rounds))
        outs = []
        for k in (1, 2, 3):
            r = subprocess.run([sys.executable, "-I", str(BOT), "poll", "--fixtures", str(fx), "--round", str(k),
                                "--workdir", str(wd)], capture_output=True, text=True, env={**os.environ, "RAHBOT_PUBLISH_MINUTES": "0"})
            outs.append(r.stdout + r.stderr)
        check("#1 kim: ACCEPT version h1 (400 modules)" in outs[0], "round 1: the partial 300K version is accepted")
        check("#1 kim: ACCEPT version h2 (803 modules)" in outs[1], "round 2: the whole 300K version is accepted")
        check("#1 kim: REJECT version h3" in outs[2] and "sorryAx" in outs[2], "round 3: a sorryAx version is rejected")
        check("MERGE" not in "".join(outs), "nothing merged (only `finish` merges)")
        d = json.loads((wd / "repo/docs/data.json").read_text())
        row = d["leaderboard"][0]
        check(row["who"] == "kim" and row.get("tier") == "300k" and row["proofs"]["300k"]["finished"] == WHOLE["recorded"],
              f"published: kim in tier 300k, finished {row.get('proofs', {}).get('300k', {}).get('finished')}")
    finally:
        shutil.rmtree(fx, ignore_errors=True)
run("poll", poll)

print(f"300K checks: {'all ok' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
