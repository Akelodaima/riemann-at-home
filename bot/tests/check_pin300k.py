"""The 300K export reference is pinned (owner, 2026-11-28): independent builders' exports agreed on one hash and size.
  - the bot and the CLI pin the same 300K export_sha256 and export_bytes (not None)
  - with the real pinned values (no test override), a whole 300K record whose export matches earns
    "300K EXPORT REPRODUCED"; a different hash or size does not, and is still accepted (no reject: CONTRACT)
  - data.json export_300k.reference is the pinned hash
  - CONTRACT.md describes the pinned state, not "no 300K reference yet"
RAHBOT=path/to/rahbot picks the bot to test (default ../rahbot). Run from bot/: python3 -I tests/check_pin300k.py"""
import contextlib, io, json, os, re, shutil, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
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
OTHER = "2" * 64


def check(ok, what):
    global fails
    print(("  ok    " if ok else "  FAIL  ") + what)
    fails += not ok


def run(what, fn):
    try:
        fn()
    except Exception as e:
        check(False, f"{what}: {type(e).__name__}: {e}")


P3 = rb.PROOFS["300k"]
REF, REF_BYTES = P3.get("export_sha256"), P3.get("export_bytes")

print("pinned values: bot and CLI")
def pinned_values():
    check(isinstance(REF, str) and re.fullmatch(r"[0-9a-f]{64}", REF or "") is not None, f"bot pins a 300K hash: {REF}")
    check(type(REF_BYTES) is int and REF_BYTES > 0, f"bot pins the 300K export size: {REF_BYTES}")
    import importlib.machinery
    loader = importlib.machinery.SourceFileLoader("rah_cli", str(ROOT / "cli" / "riemann-at-home"))
    cli = importlib.util.module_from_spec(importlib.util.spec_from_loader("rah_cli", loader))
    with contextlib.redirect_stdout(io.StringIO()):
        loader.exec_module(cli)
    c3k = cli.PROOFS["300k"]
    check(bool(REF) and c3k.get("export_sha256") == REF, f"the CLI pins the same hash: {c3k.get('export_sha256')}")
    check(REF_BYTES is not None and c3k.get("export_bytes") == REF_BYTES, f"the CLI pins the same size: {c3k.get('export_bytes')}")
run("pinned values", pinned_values)


def whole(login, t="2026-11-25T11:10:00Z", **over):
    return rec300("2026-11-25T10:00:00Z", t, ALL, f"{login}-300k", **{"whole_proof": True, "axioms": AX, **over})


print("records and badges with the real pinned reference")
tmp = Path(tempfile.mkdtemp())
try:
    def badges():
        if not REF:
            check(False, "no reference pinned, so no badge can be earned"); return
        check(c3.rejects(whole("eve", export_sha256=OTHER, export_bytes=REF_BYTES)) == [],
              "a different hash is still accepted (only no badge)")
        shutil.copytree(FIX / "main", tmp / "main"); shutil.copytree(FIX / "open", tmp / "open")
        def put(login, r):
            p = tmp / "open" / login / f"{r['build_id']}.json"; p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(r))
        put("ana", whole("ana", export_sha256=REF, export_bytes=REF_BYTES))
        put("cy", whole("cy", export_sha256=OTHER, export_bytes=REF_BYTES))
        put("dee", whole("dee", export_sha256=REF, export_bytes=REF_BYTES + 1))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            d = rb.build_data([tmp / "main", tmp / "open"], now=rb.parse_ts("2026-11-26T00:00:00Z"))
        by = {g["who"]: [b["label"] for b in g["badges"]] for g in d["signatures"]}
        check("300K EXPORT REPRODUCED" in by.get("ana", []), f"a matching export earns the badge: {by.get('ana')}")
        check("300K EXPORT REPRODUCED" not in by.get("cy", []), "a different hash: no badge")
        check("300K EXPORT REPRODUCED" not in by.get("dee", []), "the right hash with a different size: no badge")
        check((d.get("export_300k") or {}).get("reference") == REF, "data.json names the pinned reference")
    run("badges", badges)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("CONTRACT.md: the pinned state")
def contract():
    c = (ROOT / "CONTRACT.md").read_text()
    check("There is no 300K reference yet" not in c, "no longer says there is no 300K reference")
    check(bool(REF) and REF in c, "names the pinned hash")
    check("`export_*` and `checkers` are rejected on 300K records" not in c,
          "no longer says export fields are rejected on 300K records")
run("contract", contract)

print(f"300K pin checks: {fails} FAILED" if fails else "300K pin checks: all ok")
sys.exit(1 if fails else 0)
