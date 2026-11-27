"""The 300K proof's optional export (owner, 2026-11-27).
  - a whole 300K record may carry any 64-hex export_sha256 + export_bytes (no reference yet); partial or malformed
    ones are rejected; 17M keeps its reference rule
  - data.json "export_300k": the reference (None for now), how many builders, and everyone's hash, most agreed first
  - once a reference is pinned, a matching export earns the 300K EXPORT REPRODUCED badge; before that, nobody has it
RAHBOT=path/to/rahbot picks the bot to test (default ../rahbot). Run from bot/: python3 -I tests/check_export300k.py"""
import contextlib, io, json, os, shutil, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("RAHBOT", str((HERE.parent / "rahbot").resolve()))
import importlib.util
_spec = importlib.util.spec_from_file_location("check_300k", HERE / "check_300k.py")
c3 = importlib.util.module_from_spec(_spec)
with contextlib.redirect_stdout(io.StringIO()):
    try:
        _spec.loader.exec_module(c3)
    except SystemExit:
        pass
rb, rec300, AX, ALL, FIX = c3.rb, c3.rec300, c3.AX, c3.ALL, c3.FIX
fails = 0
H1, H2 = "1" * 64, "2" * 64


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


print("records: a 300K export hash is carried")
def records():
    check(c3.rejects(whole("kim", export_sha256=H1, export_bytes=1234)) == [], "a whole 300K build may carry any hash")
    check(bool(c3.rejects(whole("kim", export_sha256="XYZ", export_bytes=1))), "a malformed hash is rejected")
    check(bool(c3.rejects({**c3.PART, "export_sha256": H1, "export_bytes": 1})), "a partial build may not carry one")
run("records", records)

print("data.json: hashes gathered; badge only with a pinned reference")
tmp = Path(tempfile.mkdtemp())
try:
    shutil.copytree(FIX / "main", tmp / "main"); shutil.copytree(FIX / "open", tmp / "open")
    dirs = [tmp / "main", tmp / "open"]
    def put(login, r):
        p = tmp / "open" / login / f"{r['build_id']}.json"; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(r))
    put("ana", whole("ana", export_sha256=H1, export_bytes=100))
    put("bo", whole("bo", export_sha256=H1, export_bytes=100))
    put("cy", whole("cy", export_sha256=H2, export_bytes=100))
    put("dee", whole("dee"))                                             # no export

    def board(ref=None):
        old = dict(rb.PROOFS["300k"])
        rb.PROOFS["300k"].update({"export_sha256": ref, "export_bytes": 100 if ref else None})
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return rb.build_data(dirs, now=rb.parse_ts("2026-11-26T00:00:00Z"))
        finally:
            rb.PROOFS["300k"].clear(); rb.PROOFS["300k"].update(old)

    def gathered():
        d = board()
        x = d.get("export_300k") or {}
        check(x.get("reference") is None and x.get("agree_needed") == 3, f"no reference yet: {x.get('reference')}")
        check(x.get("builders") == 3, f"three builders exported: {x.get('builders')}")
        check(list((x.get("hashes") or {}).items()) == [(H1, ["ana", "bo"]), (H2, ["cy"])],
              f"hashes, most agreed first: {x.get('hashes')}")
        kinds = {b["kind"] for g in d["signatures"] for b in g["badges"]}
        check("export300k" not in kinds, "no 300K export badge without a reference")
    run("gathered", gathered)

    def pinned():
        d = board(H1)
        by = {g["who"]: [b["label"] for b in g["badges"]] for g in d["signatures"]}
        check("300K EXPORT REPRODUCED" in by.get("ana", []) and "300K EXPORT REPRODUCED" in by.get("bo", []),
              f"matching exports earn the badge: {by.get('ana')}")
        check("300K EXPORT REPRODUCED" not in by.get("cy", []) and "300K EXPORT REPRODUCED" not in by.get("dee", []),
              "a different hash or no export: no badge")
        check(d["export_300k"]["reference"] == H1, "data.json names the reference once pinned")
    run("pinned", pinned)

    def page():
        html = (HERE.parent.parent / "docs" / "index.html").read_text()
        check("export_300k" in html and "distinct hash" in html, "the page shows the 300K export line")
        check('class="lvl x3"' in html and "#b6ff7d" in html, "the page has the 300K export badge style")
        check("x.reference" in html, "its legend line shows only once a reference is pinned")
    run("page", page)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"300K export checks: {fails} FAILED" if fails else "300K export checks: all ok")
sys.exit(1 if fails else 0)
