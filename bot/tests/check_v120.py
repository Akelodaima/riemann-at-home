"""Tool 1.2.0 (owner, ops #64, 2026-11-28): the version changes with the export features, and records say which
exporter ran and whether fast exit was on.
  - "riemann-at-home 1.2.0" is a known tool; 1.0.0 and 1.1.0 records are still accepted
  - export_exporter (str, "lean4export <tag>[ + parallel <commit8>]") and export_fast_exit (bool) are accepted on
    17M and 300K records next to export_sha256, and refused without it or with the wrong type or shape
  - CONTRACT.md lists 1.2.0 and both fields
Run from bot/: python3 -I tests/check_v120.py"""
import contextlib, io, json, os, re, sys
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
rb, rec300, AX, ALL = c3.rb, c3.rec300, c3.AX, c3.ALL
NOW = rb.parse_ts("2026-11-28T12:00:00Z")
idx = json.load(open(HERE / "fixtures/check/index.json"))
fails = 0


def check(ok, what):
    global fails
    print(("  ok    " if ok else "  FAIL  ") + what)
    fails += not ok


def rej17(rec):
    path = idx["level2_sign"]["path"]
    with contextlib.redirect_stdout(io.StringIO()):
        return rb.check_record(rec, path.split("/")[1], path, None, now=NOW)[0]


def rej3(rec):
    with contextlib.redirect_stdout(io.StringIO()):
        return rb.check_record(rec, "kim", f"submissions/kim/{rec['build_id']}.json", None, now=NOW)[0]


L2 = json.load(open(idx["level2_sign"]["file"]))
print("known tools")
check("riemann-at-home 1.2.0" in rb.KNOWN_TOOLS, "1.2.0 is a known tool")
for t in ("riemann-at-home 1.0.0", "riemann-at-home 1.1.0"):
    check(rej17({**L2, "tool": t}) == [], f"a 17M {t} record without the new fields is still accepted")

print("17M: the export options")
r = {**L2, "tool": "riemann-at-home 1.2.0", "export_exporter": "lean4export v4.33.0", "export_fast_exit": True}
check(rej17(r) == [], f"1.2.0 record with export_exporter + export_fast_exit accepted: {rej17(r)}")
r = {**r, "export_exporter": "lean4export v4.33.0 + parallel 73d9ad9b", "export_fast_exit": False}
check(rej17(r) == [], f"parallel exporter name accepted: {rej17(r)}")
noexp = {k: v for k, v in r.items() if k not in ("export_sha256", "export_bytes", "checkers", "sign_statement")}
check(any("export_sha256" in x or "export_exporter" in x or "export_fast_exit" in x for x in rej17(noexp)),
      f"export options without export_sha256 refused: {rej17(noexp)}")
check(any("export_fast_exit" in x for x in rej17({**r, "export_fast_exit": "yes"})), "export_fast_exit must be a bool")
check(any("export_exporter" in x for x in rej17({**r, "export_exporter": 5})), "export_exporter must be a string")
check(any("export_exporter" in x for x in rej17({**r, "export_exporter": "rm -rf /"})), "export_exporter must name lean4export")

print("300K: the export options")
w = rec300("2026-11-28T10:00:00Z", "2026-11-28T11:00:00Z", ALL, "kim-v120", whole_proof=True, axioms=AX,
           tool="riemann-at-home 1.2.0", export_sha256="a" * 64, export_bytes=10,
           export_exporter="lean4export v4.35.0", export_fast_exit=True)
check(rej3(w) == [], f"1.2.0 300K record with the export options accepted: {rej3(w)}")
old = {k: v for k, v in w.items() if not k.startswith("export_")}
check(rej3({**old, "tool": "riemann-at-home 1.1.0"}) == [], "a 1.1.0 300K record without them is still accepted")

print("CONTRACT.md")
ct = (ROOT / "CONTRACT.md").read_text()
check('"riemann-at-home 1.2.0"' in ct, "CONTRACT lists the 1.2.0 tool")
check("export_exporter" in ct and "export_fast_exit" in ct, "CONTRACT documents export_exporter and export_fast_exit")

print(f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
