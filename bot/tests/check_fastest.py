"""Fastest build per proof (owner, 2026-11-27): the bot gives exact build_seconds (build_hours is rounded to 0.1 h,
so 300K builds tied), and the page highlights the fastest whole build of each proof."""
from importlib.machinery import SourceFileLoader
from pathlib import Path

here = Path(__file__).resolve().parent
rb = SourceFileLoader("rahbot", str(here.parent / "rahbot")).load_module()
d = rb.build_data([here / "fixtures" / "sample" / "main"])
whole = [(r["who"] or r["name"], p) for r in d["leaderboard"] for p in (r.get("proofs") or {}).values() if p["whole"]]
assert whole, "fixture has no whole build"
for who, p in whole:
    assert isinstance(p.get("build_seconds"), int) and p["build_seconds"] > 0, (who, p)
page = (here.parent.parent / "docs" / "index.html").read_text()
assert "fastestOf" in page and "fastest ${which === \"17m\" ? \"17M\" : \"300K\"} build" in page and ".fastest{" in page
print("  whole builds with exact seconds:", len(whole))
