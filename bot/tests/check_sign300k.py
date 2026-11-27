"""The 300K joint statement (issue #76, owner 2026-11-27).
  - a whole 300K record with the three standard axioms may say "sign_statement": true; a partial one may not;
    "sign_statement": false (sign --cancel --proof 300k) is accepted
  - data.json "signatures_300k", separate from the 17M "signatures":
    (a) self-signed builders (no marker)
    (b) builders with a whole 300K build and the three axioms who have not opted out, marked "via": "record"
    opt-out wins: false in their newest 300K record, or their login in bot/optout.json
  - the page marks (b) entries "added from their build record"; the markdown page lists the 300K statement
RAHBOT=path/to/rahbot picks the bot to test (default ../rahbot). Run from bot/: python3 -I tests/check_sign300k.py"""
import contextlib, io, json, os, shutil, sys, tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("RAHBOT", str((HERE.parent / "rahbot").resolve()))
import importlib.util
_spec = importlib.util.spec_from_file_location("check_300k", HERE / "check_300k.py")
c3 = importlib.util.module_from_spec(_spec)
with contextlib.redirect_stdout(io.StringIO()):
    try:                                          # its record builder and fixtures; it runs its own checks quietly
        _spec.loader.exec_module(c3)
    except SystemExit:
        pass
rb, rec300, AX, ALL, FIX = c3.rb, c3.rec300, c3.AX, c3.ALL, c3.FIX
fails = 0


def check(ok, what):
    global fails
    print(("  ok    " if ok else "  FAIL  ") + what)
    fails += not ok


def run(what, fn):
    try:
        fn()
    except Exception as e:
        check(False, f"{what}: {type(e).__name__}: {e}")


def whole(login, t="2026-11-25T11:10:00Z", **over):
    return rec300("2026-11-25T10:00:00Z", t, ALL, f"{login}-300k", **{"whole_proof": True, "axioms": AX, **over})


print("300K signing in records")
def records():
    check(c3.rejects(whole("kim", sign_statement=True)) == [], "a whole 300K build with the three axioms may sign")
    check(c3.rejects(whole("kim", sign_statement=False)) == [], "sign_statement false (opt-out) is accepted on 300K")
    r = c3.rejects({**c3.PART, "sign_statement": True})
    check(bool(r), f"a partial 300K build may not sign: {r}")
    r = c3.rejects(whole("kim", axioms=AX + ["sorryAx"], sign_statement=True))
    check(bool(r), "a 300K build with other axioms may not sign")
run("records", records)


print("data.json signatures_300k")
tmp = Path(tempfile.mkdtemp())
try:
    shutil.copytree(FIX / "main", tmp / "main"); shutil.copytree(FIX / "open", tmp / "open")
    dirs = [tmp / "main", tmp / "open"]
    def put(login, r):
        p = tmp / "open" / login / f"{r['build_id']}.json"; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(r)); return p
    put("ana", whole("ana", sign_statement=True))                       # (a) signed it herself
    put("bo", whole("bo", "2026-11-25T11:20:00Z"))                      # (b) whole, never asked
    put("cy", whole("cy", sign_statement=False))                        # opted out in the record
    put("dee", whole("dee"))                                             # opted out by comment (optout.json)
    put("eli", rec300("2026-11-25T10:00:00Z", "2026-11-25T10:30:00Z", range(300), "eli-300k"))   # partial
    put("fay", whole("fay", axioms=AX + ["sorryAx"]))                    # whole, wrong axioms

    def board():
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return rb.build_data(dirs, now=rb.parse_ts("2026-11-26T00:00:00Z"))

    def lists():
        old = getattr(rb, "OPTOUT", None)
        rb.OPTOUT = {"dee"}
        try:
            d = board()
        finally:
            rb.OPTOUT = old
        s3 = {g["who"]: g for g in d.get("signatures_300k") or []}
        check(set(s3) == {"ana", "bo"}, f"listed: the self-signed and the finished, nobody who opted out: {sorted(s3)}")
        check("via" not in s3.get("ana", {}), "a self-signed entry has no marker")
        check((s3.get("bo") or {}).get("via") == "record", "an entry from a build record is marked via=record")
        check("cy" not in s3, "false in the newest record (sign --cancel --proof 300k) removes them")
        check("dee" not in s3, "a login in optout.json removes them")
        check(not any(g.get("who") in s3 for g in d.get("signatures") or []), "the 17M signatures list is separate")
        # bo signs later: becomes self-signed
        put("bo", whole("bo", "2026-11-25T12:00:00Z", sign_statement=True))
        d2 = board()
        g = next((g for g in d2.get("signatures_300k") or [] if g["who"] == "bo"), {})
        check(g and "via" not in g, "a builder listed from the record who signs later becomes self-signed")
        # bo withdraws: gone
        put("bo", whole("bo", "2026-11-25T13:00:00Z", sign_statement=False))
        check(not any(g["who"] == "bo" for g in board().get("signatures_300k") or []), "withdrawing removes them again")
    run("lists", lists)

    def markdown():
        html = (HERE.parent.parent / "docs" / "index.html").read_text()
        md = rb.homepage_markdown(board(), html)
        check("## 300K joint statement" in md and "added from their build record" in md,
              "index.md has the 300K statement and marks entries from build records")
        check('g.via === "record"' in html and "added from their build record" in html,
              "the page marks entries from build records")
    run("markdown", markdown)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"300K statement checks: {fails} FAILED" if fails else "300K statement checks: all ok")
sys.exit(1 if fails else 0)
