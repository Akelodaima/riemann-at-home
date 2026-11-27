#!/bin/zsh
# rahbot tests. Fixtures: python3 -I tests/make_fixtures.py. No gh/git calls are made.
cd "${0:A:h}/.." || exit 1
IDX=tests/fixtures/check/index.json
q() { python3 -I -c 'import json,sys; v=json.load(open(sys.argv[1]))[sys.argv[2]]; print(v[sys.argv[3]] if sys.argv[3:] else v)' $IDX "$@"; }
f() { q $1 file; }
ck() { print -r -- "$(q $1 file) --path $(q $1 path)"; }      # a version + the repo path it lives at
SNAP=(--reference-hashes tests/reference.snap)
fails=0
t() {  # t NAME EXPECT(0=ACCEPT,1=REJECT,2=PENDING) ARGS...
  local name=$1 want=$2; shift 2
  print "=== $name (expect ${${(s:,:)${:-ACCEPT,REJECT,PENDING}}[want+1]})"
  print -r -- "\$ rahbot $*"
  python3 -I ./rahbot "$@"; local got=$?
  if [[ $got == $want ]]; then echo "--> ok"; else echo "--> TEST FAILED (exit $got)"; fails=$((fails+1)); fi
  print
}
t "honest first version"           0 check ${=$(ck alice1)} --author alice --prev none
t "honest next version (grows)"    0 check ${=$(ck alice2)} --author alice --prev $(f alice1)
t "honest, digest checked"         0 check ${=$(ck alice2)} --author alice --prev $(f alice1) --check-digest $SNAP
t "honest other person, digest"    0 check ${=$(ck bob)} --author bob --prev none --check-digest $SNAP
t "whole proof with axioms"        0 check ${=$(ck carol_whole)} --author carol --prev none
t "fast but plausible (flag)"      0 check ${=$(ck dave_fast)} --author dave --prev none
t "too fast"                       1 check ${=$(ck eve_too_fast)} --author eve --prev none
t "shrinking bitmap"               1 check ${=$(ck alice3_shrink)} --author alice --prev $(f alice2)
t "wrong archive hash"             1 check ${=$(ck wrong_archive)} --author frank --prev none
t "author/path mismatch"           1 check ${=$(ck alice1)} --author mallory --prev none
t "modules_compiled != popcount"   1 check ${=$(ck bad_count)} --author grace --prev none
t "whole_proof without axioms"     1 check ${=$(ck whole_no_axioms)} --author heidi --prev none
t "whole_proof, partial bitmap"    1 check ${=$(ck whole_partial)} --author ivan --prev none
t "bad digest, check off (default)" 0 check ${=$(ck bad_digest)} --author judy --prev none
t "bad digest, --check-digest"     1 check ${=$(ck bad_digest)} --author judy --prev none --check-digest $SNAP
t "unknown tool version"           1 check ${=$(ck unknown_tool)} --author mallory --prev none
t "digest on, reference lacks modules" 2 check ${=$(ck dave_fast)} --author dave --prev none --check-digest $SNAP
t "digest vs live build folder"    0 check ${=$(ck bob)} --author bob --prev none --check-digest
t "older version replayed as new"  1 check ${=$(ck alice1)} --author alice --prev $(f alice2)
t "same record pushed again"      0 check ${=$(ck alice2)} --author alice --prev $(f alice2)
t "final version"                  0 check ${=$(ck bob_final)} --author bob --prev $(f bob)
t "update after final"             1 check ${=$(ck bob_after_final)} --author bob --prev $(f bob_final)
t "real CLI record, first version"   0 check ${=$(ck real_cli)} --author volunteer --prev none
t "real CLI record, digest checked"   0 check ${=$(ck real_cli)} --author volunteer --prev none --check-digest $SNAP
t "whole_proof with sorryAx"         1 check ${=$(ck whole_sorry)} --author whole --prev none
t "whole_proof, duplicated axiom"    1 check ${=$(ck whole_dup_axioms)} --author whole --prev none
t "whole_proof, axioms reordered"    0 check ${=$(ck whole_reordered)} --author whole --prev none
t "same bits, other gzip bytes + key order" 0 check ${=$(ck regzipped)} --author regzipped --prev $(f alice2)
# display names
t "display_name ok (unicode)"        0 check ${=$(ck dn_ok)} --author ada --prev none --logins alice,bob,carol
t "display_name = own login"         0 check ${=$(ck dn_own_login)} --author alice --prev none --logins alice,bob
t "display_name = another's login"   1 check ${=$(ck dn_is_login)} --author x1 --prev none --logins alice,bob
t "display_name 33 chars"            1 check ${=$(ck dn_too_long)} --author x2 --prev none
t "display_name with control char"   1 check ${=$(ck dn_control)} --author x3 --prev none
t "display_name + anonymous"         1 check ${=$(ck dn_and_anon)} --author x4 --prev none
t "display_name = login after NFKC+casefold" 1 check ${=$(ck dn_nfkc)} --author x5 --prev none --logins alice,bob
t "display_name starts with anonymous" 1 check ${=$(ck dn_fake_anon)} --author x8 --prev none
t "display_name kept from accepted prev is not re-judged" 0 check ${=$(ck dn_is_login2)} --author x1 --prev $(f dn_is_login) --logins alice,bob
t "display_name trimmed, ends ok"    0 check ${=$(ck dn_padded)} --author x6 --prev none
t "display_name only spaces"         1 check ${=$(ck dn_blank)} --author x7 --prev none
t "anonymous: true (not offered)"    1 check ${=$(ck anon_ok)} --author anon --prev none
# levels and the joint statement
t "Level 3 + signs (whole, reference export, nanoda)" 0 check ${=$(ck carol_whole)} --author carol --prev none
t "Level 2 + signs"                  0 check ${=$(ck level2_sign)} --author lv --prev none
t "export hash not the reference"    1 check ${=$(ck export_wrong)} --author lv --prev none
t "export_bytes not the reference"   1 check ${=$(ck export_bytes_wrong)} --author lv --prev none
t "export without whole_proof"       1 check ${=$(ck export_not_whole)} --author lv --prev none
t "export progress (whole, running)"  0 check ${=$(ck carol_exporting)} --author carol --prev none
t "export progress without whole"    1 check ${=$(ck export_progress_not_whole)} --author alice --prev none
t "export progress, wrong type"      1 check ${=$(ck export_progress_bad)} --author carol --prev none
t "export progress, self-declared match" 1 check ${=$(ck export_progress_extra)} --author carol --prev none
t "sign_statement at Level 1"        1 check ${=$(ck sign_level1)} --author lv --prev none
t "sign_statement, whole but no export" 1 check ${=$(ck sign_whole_no_export)} --author lv --prev none
t "checkers entry malformed"         1 check ${=$(ck checker_malformed)} --author lv --prev none
t "a checker rejected the export (accept + loud flag)" 0 check ${=$(ck checker_rejects)} --author lv --prev none
# several computers per person
t "2nd computer, first version (A has later versions)" 0 check ${=$(ck aliceB1)} --author alice --prev none
t "2nd computer grows vs its own prev" 0 check ${=$(ck aliceB2)} --author alice --prev $(f aliceB1)
t "2nd computer's bitmap shrinks"  1 check ${=$(ck aliceB_shrink)} --author alice --prev $(f aliceB2)
t "prev from another build"        1 check ${=$(ck aliceB2)} --author alice --prev $(f alice2)
t "path build_id != record build_id" 1 check $(f alice2) --path submissions/alice/$(q build_B).json --author alice --prev none
t "old per-record path"            1 check $(f alice1) --path submissions/alice/$(q build_A)/20261119T140000Z.json --author alice --prev none

print "=== reference-digest == digest stored in the honest record"
want=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["olean_digest"])' $(f bob))
got=$(python3 -I ./rahbot reference-digest $(f bob) $SNAP)
print "record:    $want\nreference: $got"
[[ $want == $got ]] && echo "--> ok" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
print

# poll: 7 rounds of fake PRs; each expectation is a line that must appear in that round's output
W=tests/out/poll-workdir
expect() {  # expect ROUND PATTERN...
  local r=$1; shift
  for pat in "$@"; do
    if grep -qF -- "$pat" tests/out/round$r.txt; then echo "--> ok   round $r: $pat"
    else echo "--> TEST FAILED round $r: missing '$pat'"; fails=$((fails+1)); fi
  done
}
for r in 1 2 3 4 5 6 7 8; do
  print "=== poll --fixtures round $r$([[ $r == 7 ]] && echo ' (bot state lost first)')$([[ $r == 8 ]] && echo ' (state AND backups lost)')"
  extra=(); [[ $r == 7 ]] && extra=(--lose-state); [[ $r == 8 ]] && extra=(--lose-state --lose-backups)
  python3 -I ./rahbot poll --fixtures tests/fixtures/poll --round $r --workdir $W $extra > tests/out/round$r.txt 2>&1 || fails=$((fails+1))
  grep -v '^    (fixture)' tests/out/round$r.txt
  [[ $r == 7 ]] && cp $W/state/signatures.json tests/out/signatures-after-round7.json
done
print "=== poll expectations"
expect 1 "#1 alice: ACCEPT version" "#2 alice: ACCEPT version" "#3 carol: ACCEPT version" \
         "#4 mallory: CLOSE (the file is under 'bob'" "#5 dave: CLOSE (the PR changes 2 files" \
         "#9 alice: CLOSE (build 7eec4904a145d203 already has an open PR (#1)" "data.json: published"
expect 2 "#1 alice: ACCEPT version" "#2 alice: unchanged" "data.json: published"
expect 3 "#1 alice: REJECT version" "bitmap shrank: 100 modules" "#2 alice: ACCEPT version" \
         "#6 eve: REJECT version" "speed implausible" "#7 dave: ACCEPT version" "FLAG fast" "#8 bob: MERGE (final)"
expect 4 "#1 alice: REJECT version 1-alice4 (same reasons, already commented)" "#2 alice: REJECT version" \
         "#6 eve: unchanged" "#10 erin: ACCEPT version" "publish deferred" \
         "#11 zed: REJECT version" "display_name 'Carol' is another participant's GitHub login" \
         "#11 zed: REJECT version" "display_name 'Carol' is another participant's GitHub login"
expect 5 "data.json: published" "#11: no longer open"
expect 6 "#12 bob: CLOSE (build 81b637d8fcd2c6da is already merged (final)" "data.json: unchanged"
expect 1 "signatures 1" "state backed up to 20261120T000000Z"
expect 7 "state missing: restored newest backup 20261121T104500Z" "#1 alice: unchanged" "#2 alice: unchanged" \
         "#6 eve: unchanged" "data.json: unchanged"
expect 8 "state missing and no backup: rebuilding from open PR heads" \
         "#1 alice: ACCEPT version 1-alice4" "#2 alice: ACCEPT version 2-aliceB" "#6 eve: REJECT version 6-eve_to, comment" \
         "#7 dave: ACCEPT version" "#10 erin: ACCEPT version" "data.json: published"
python3 -I -c '
import json, sys
d = json.load(open(sys.argv[1]))
s = d["signatures"]
assert json.load(open(sys.argv[2])) == {"carol": "2026-11-20T00:00:00Z"}   # ledger restored from backup in round 7
# round 8 lost state AND backups: the signed time falls back to the recorded time of the signing record
assert s == [{"who": "carol", "name": "carol", "signed": "2026-11-19T22:00:00Z", "machine": "AMD Ryzen 9 7950X",
              "level": 3, "checkers": ["nanoda"]}], s
lv = {r["who"]: r["level"] for r in d["leaderboard"]}
assert lv["carol"] == 3 and all(v == 1 for k, v in lv.items() if k != "carol"), lv
print("signatures:", s); print("levels:", lv)' $W/repo/docs/data.json tests/out/signatures-after-round7.json && echo "--> ok   signed = acceptance time (round 1) kept through backup restore; recorded-time fallback after total loss; carol Level 3" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
for r in 6 7 8; do
  if grep -q "MERGE" tests/out/round$r.txt; then echo "--> TEST FAILED round $r merged something (no time-based merge)"; fails=$((fails+1))
  else echo "--> ok   round $r: nothing merged by time"; fi
done
print "=== poll end state: main = merged builds (final only), bot state = rebuilt from open PR heads"
python3 -I -c '
import json, sys
from pathlib import Path
W, F = Path(sys.argv[1]), Path(sys.argv[2])
main = sorted(str(p.relative_to(W / "repo")) for p in (W / "repo/submissions").glob("*/*.json"))
acc = {str(p.relative_to(W / "state/accepted")): p.read_bytes() for p in (W / "state/accepted").glob("*/*.json")}
heads = {pr["files"][0]["path"].removeprefix("submissions/"): (F / pr["content_file"]).read_bytes()
         for pr in json.loads((F / "rounds.json").read_text())[7]["prs"] if pr["number"] != 6}   # eve never passes
print("main:", main); print("rebuilt state:", sorted(acc))
assert len(main) == 1 and acc == heads, "state must equal the open heads that pass as first versions"
' $W tests/fixtures/poll && echo "--> ok   1 merged on main (final); rebuilt state = the 5 passing open heads (carol's whole proof stays open)" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
python3 -I tests/check_aggregate.py $W/repo/docs/data.json $W/repo/submissions $W/state/accepted && echo "--> ok" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
print

print "=== state backups keep the newest 20"
python3 -I -c '
import sys, tempfile
from datetime import datetime, timedelta, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path
rb = SourceFileLoader("rahbot", "rahbot").load_module()
d = Path(tempfile.mkdtemp(dir=sys.argv[1])); st = d / "state"; st.mkdir(); (st / "state.json").write_text("{}")
t0 = datetime(2026, 11, 21, tzinfo=timezone.utc)
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    for i in range(25): rb.backup_state(st, t0 + timedelta(minutes=10 * i))
names = sorted(p.name for p in (d / "state-backups").iterdir())
assert len(names) == 20 and names[0] == "20261121T005000Z" and names[-1] == "20261121T040000Z", names
print("kept", len(names), names[0], "...", names[-1])' tests/out && echo "--> ok" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
print

print "=== re-submitting a finished build keeps its finish date and Level 2 time (issue #12)"
python3 -I tests/check_firsts.py && echo "--> ok" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
print

print "=== review fixes: closed PRs, state loss, ranking, frozen build hours (2026-11-25)"
python3 -I tests/check_review_fixes.py && echo "--> ok" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
print

print "=== export progress on the page data"
python3 -I tests/check_export.py && echo "--> ok" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
print
print "=== crash reports"
python3 -I tests/check_crashes.py && echo "--> ok" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
python3 -I tests/check_speed.py && echo "--> ok" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
print
print "=== the second proof, 300K: acceptance rules, one leaderboard in tiers, finish times kept (2026-11-25)"
python3 -I tests/check_300k.py && echo "--> ok" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
print
print "=== the 300K joint statement: signing, listing from build records, opt-out (issue #76)"
python3 -I tests/check_sign300k.py && echo "--> ok" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
print
print "=== a renamed GitHub account: one row, old-login PRs still accepted (2026-11-26)"
python3 -I tests/check_renamed.py && echo "--> ok" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
print
print "=== aggregate sample (merged + open PRs) + leaderboard/terrain/running assertions"
S=tests/fixtures/sample
python3 -I ./rahbot aggregate $S/main $S/open --out sample-data.json || fails=$((fails+1))
python3 -I tests/check_aggregate.py sample-data.json $S/main $S/open && echo "--> ok" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
print "=== a later joiner; only display names hide the login, nobody is anonymous"
python3 -I ./rahbot aggregate $S/main $S/open $S/extra --out tests/out/sample-plus-erin.json || fails=$((fails+1))
python3 -I tests/check_aggregate.py tests/out/sample-plus-erin.json $S/main $S/open $S/extra || fails=$((fails+1))
got=$(python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print(" ".join(sorted(r["name"] for r in d["leaderboard"] if r["who"] is None)))' tests/out/sample-plus-erin.json)
print "names without login: $got"
[[ $got == "Alice L." ]] && echo "--> ok   only Alice's display name hides her login" || { echo "--> TEST FAILED"; fails=$((fails+1)); }
print
print "FAILURES: $fails"
exit $fails
