"""The one joint statement (owner, 2026-11-27): one letter for every proof, one signature list with badges.
  - any whole build with only the three standard axioms may say "sign_statement": true (17M no longer needs
    Level 2); false (sign --cancel) is accepted on any record; partial / other axioms may not sign
  - data.json "signatures": everyone with a whole build of either proof, ordered by when they FIRST finished,
    badges per entry (17M BUILT, 300K BUILT, EXPORT REPRODUCED, RE-CHECKED: <checker>), "via": "signed" for the
    self-signed, "via": "record" for everyone else; no separate "signatures_300k"
  - opt-out wins: false in their newest record that says either way, or their login in bot/optout.json
  - the page and index.md show one statement, badges and the "added from their build record" marker
RAHBOT=path/to/rahbot picks the bot to test (default ../rahbot). Run from bot/: python3 -I tests/check_statement.py"""
import contextlib, io, json, os, shutil, sys, tempfile
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


carol17 = json.loads((FIX / "main/carol/4c26d9074c27d89e.json").read_text())       # 17M, Level 3 (nanoda), signed
frank17 = json.loads((FIX / "main/frank/3495d649921f8b53.json").read_text())       # 17M, Level 2, signed
bare17 = {k: v for k, v in frank17.items() if k not in ("export_sha256", "export_bytes", "checkers", "sign_statement")}

print("signing in records: one statement, any whole build")
def records():
    check(c3.rejects(whole("kim", sign_statement=True)) == [], "a whole 300K build with the three axioms may sign")
    check(c3.rejects(whole("kim", sign_statement=False)) == [], "sign_statement false (opt-out) is accepted on 300K")
    check(bool(c3.rejects({**c3.PART, "sign_statement": True})), "a partial 300K build may not sign")
    check(bool(c3.rejects(whole("kim", axioms=AX + ["sorryAx"], sign_statement=True))), "other axioms may not sign")
    check(not [e for e in c3.rejects({**bare17, "sign_statement": True}, "frank") if "sign_statement" in e],
          "a whole 17M build without the export may sign (no Level 2 needed any more)")
    check(not [e for e in c3.rejects({**frank17, "sign_statement": False}, "frank") if "sign_statement" in e],
          "sign_statement false (opt-out) is accepted on 17M")
run("records", records)


print("data.json: one signature list")
tmp = Path(tempfile.mkdtemp())
try:
    shutil.copytree(FIX / "main", tmp / "main"); shutil.copytree(FIX / "open", tmp / "open")
    dirs = [tmp / "main", tmp / "open"]
    def put(login, r):
        p = tmp / "open" / login / f"{r['build_id']}.json"; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(r)); return p
    # carol, frank: 17M signers from the sample (finished 2026-11-19/20)
    put("carol", whole("carol", "2026-11-25T12:40:00Z"))                # carol also builds 300K
    put("ana", whole("ana", "2026-11-25T11:30:00Z", sign_statement=True))   # signed it herself
    put("bo", whole("bo", "2026-11-25T11:20:00Z"))                      # whole, never asked
    put("cy", whole("cy", sign_statement=False))                        # opted out in the record
    put("dee", whole("dee"))                                             # opted out by comment (optout.json)
    put("eli", rec300("2026-11-25T10:00:00Z", "2026-11-25T10:30:00Z", range(300), "eli-300k"))   # partial
    put("fay", whole("fay", axioms=AX + ["sorryAx"]))                    # whole, wrong axioms

    def board():
        old = rb.OPTOUT
        rb.OPTOUT = {"dee"}
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return rb.build_data(dirs, now=rb.parse_ts("2026-11-26T00:00:00Z"))
        finally:
            rb.OPTOUT = old

    def lists():
        d = board()
        check("signatures_300k" not in d, "no separate 300K list")
        sigs = d.get("signatures") or []
        who = [g["who"] for g in sigs]
        check(set(who) == {"carol", "frank", "ana", "bo"}, f"listed: whole builds of either proof, no opt-outs: {who}")
        check(who == sorted(who, key=lambda w: next(g["first_finished"] for g in sigs if g["who"] == w))
              and who[:2] == ["carol", "frank"] and who.index("bo") < who.index("ana"),
              f"ordered by when they first finished (17M signers first, then bo before ana): {who}")
        by = {g["who"]: g for g in sigs}
        lab = lambda w: [b["label"] for b in by[w]["badges"]]
        check(lab("carol") == ["17M BUILT", "300K BUILT", "EXPORT REPRODUCED", "RE-CHECKED: nanoda"],
              f"carol: both builds, export, re-check: {lab('carol')}")
        check(lab("frank") == ["17M BUILT", "EXPORT REPRODUCED"], f"a 17M signer has 17M BUILT + EXPORT REPRODUCED: {lab('frank')}")
        check(lab("bo") == ["300K BUILT"], f"bo: 300K only: {lab('bo')}")
        check(by["carol"]["first_finished"].startswith("2026-11-19"), "first_finished is their earliest whole build")
        check(by["ana"]["via"] == "signed" and by["frank"]["via"] == "signed", "self-signed entries are via=signed")
        check(by["bo"]["via"] == "record", "an entry from a build record is marked via=record")
        check({b["kind"] for g in sigs for b in g["badges"]} <= {"17m", "300k", "export", "recheck"}, "badge kinds")
        # bo signs later: becomes self-signed; then withdraws: gone
        put("bo", whole("bo", "2026-11-25T12:00:00Z", sign_statement=True))
        g = next((g for g in board()["signatures"] if g["who"] == "bo"), {})
        check(g.get("via") == "signed", "a builder listed from the record who signs later becomes self-signed")
        put("bo", whole("bo", "2026-11-25T13:00:00Z", sign_statement=False))
        check(not any(g["who"] == "bo" for g in board()["signatures"]), "withdrawing removes them again")
        # a 17M signer who withdraws on their 300K build: one statement, gone everywhere
        put("carol", whole("carol", "2026-11-25T14:00:00Z", sign_statement=False))
        check(not any(g["who"] == "carol" for g in board()["signatures"]), "an opt-out on either proof removes them")
    run("lists", lists)

    def page():
        html = (HERE.parent.parent / "docs" / "index.html").read_text()
        put("gus", whole("gus", "2026-11-25T15:00:00Z"))                # listed from his build record
        md = rb.homepage_markdown(board(), html)
        check("## 300K joint statement" not in md and md.count("## Joint statement") == 1, "index.md: one statement")
        check("**17M BUILT**" in md and "**300K BUILT**" in md and "added from their build record" in md
              and "in the order they first finished" in md, "index.md: badge legend, marker, order")
        check("sigs3" not in html and "signatures_300k" not in html, "the page has no separate 300K list")
        key = html.split('<ul class="badgekey">')[1].split("</ul>")[0] if '<ul class="badgekey">' in html else ""
        check(all(f'class="lvl {c}"' in key for c in ("b17", "b3", "l2", "l3")), "the letter has the four-badge key")
        check(".legend{" not in html.split(".stmt .badgekey")[0][-200:] and "badgekey{" in html,
              "the key has its own class (the map's .legend is display:none)")
        for c, col in (("b17", "#ffd23f"), ("b3", "#ff9ae8"), ("l2", "#7dff95"), ("l3", "#7fd8ff")):
            check(f"#printdoc .lvl.{c}{{background:{col}}}" in html, f"the PDF prints the {c} badge in {col}")
        check("print-color-adjust:exact" in html.split("#printdoc .lvl{")[1][:400], "badge colors survive printing")
        check('g.via === "record"' in html and "added from their build record" in html, "the page marks record entries")
    run("page", page)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"joint statement checks: {fails} FAILED" if fails else "joint statement checks: all ok")
sys.exit(1 if fails else 0)
