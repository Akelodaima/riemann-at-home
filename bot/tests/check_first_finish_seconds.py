"""build_seconds is the build as it was when the person FIRST finished (2026-11-27): a later record of the same build
had 46 min of busy time where the first finish took 13 min, and the fastest-time list ranked by the 46."""
from importlib.machinery import SourceFileLoader
from pathlib import Path

here = Path(__file__).resolve().parent
rb = SourceFileLoader("rahbot", str(here.parent / "rahbot")).load_module()
dirs = [here / "fixtures" / "sample" / "main"]
base = rb.build_data(dirs)
row = next(r for r in base["leaderboard"] if (r.get("proofs") or {}).get("17m", {}).get("whole"))
login = row["who"] or row["name"]
real = row["proofs"]["17m"]["build_seconds"]
# the ledger says they first finished in a third of the time the current record shows
d = rb.build_data(dirs, firsts={login: {"hours": round(real / 3 / 3600, 6)}})
got = next(r for r in d["leaderboard"] if (r["who"] or r["name"]) == login)["proofs"]["17m"]
assert abs(got["build_seconds"] - real / 3) <= 1, (got, real)
assert abs(got["build_seconds"] / 3600 - got["build_hours"]) < 0.01, got
# an old ledger value rounded to 0.1 h does not replace exact seconds
d = rb.build_data(dirs, firsts={login: {"hours": round(real / 3600, 1)}})
got = next(r for r in d["leaderboard"] if (r["who"] or r["name"]) == login)["proofs"]["17m"]
assert got["build_seconds"] == real, (got, real)
print("  build_seconds follows the first finish; rounded ledger hours keep exact seconds")
