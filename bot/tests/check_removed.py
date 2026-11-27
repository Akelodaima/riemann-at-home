"""A login on bot/removed.json (asked to be taken off, e.g. a PR opened by mistake) never shows on the page."""
import shutil, tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

rb = SourceFileLoader("rahbot", str(Path(__file__).resolve().parent.parent / "rahbot")).load_module()
src = Path(__file__).resolve().parent / "fixtures" / "sample"
tmp = Path(tempfile.mkdtemp())
shutil.copytree(src / "main", tmp / "main")
before = [r["who"] or r["name"] for r in rb.build_data([tmp / "main"])["leaderboard"]]
assert "bob" in before, before
rb.REMOVED.clear(); rb.REMOVED.add("bob")
d = rb.build_data([tmp / "main"])
print("  rows:", [r["who"] or r["name"] for r in d["leaderboard"]])
assert "bob" not in str(d["leaderboard"]) and "bob" not in str(d.get("running")), "a removed login still shows"
shutil.rmtree(tmp)
