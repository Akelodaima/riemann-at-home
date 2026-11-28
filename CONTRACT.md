# Riemann@home v1 contract: the formats every piece agrees on

Workstreams A (volunteer CLI), B (bot), C (global page) all read/write these. Change only by updating this file.

## Constants

- archive: `lean.tar.gz` from https://alpo.ge (parts 01–14), sha256 `9631b4f020199e580ba86178cb56c6e9b09f690c2369a80dc4334aa93f49c7fc`
- toolchain `leanprover/lean4:v4.33.1`, Mathlib `0df444a360eaa60ab8c11dca51a86af692955474`
- build folder (fixed): macOS `/Users/Shared/riemann-at-home/lean`, Linux `/opt/riemann-at-home/lean` (pending M0)
- module list: all `src/**/*.lean` of the archive, as dotted names, sorted byte-wise; N = 175,187.
  Module index i = position in that list (0-based). Published once as `modules.txt` (same list for everyone).

## Build record — `submissions/<github-login>/<UTC time YYYYMMDDTHHMMSSZ>.json`

```json
{
  "format": "rah/build/1",
  "tool": "riemann-at-home 1.0.0",
  "archive_sha256": "9631b4f0…",
  "toolchain": "leanprover/lean4:v4.33.1",
  "mathlib_rev": "0df444a3…",
  "build_folder": "/Users/Shared/riemann-at-home/lean",
  "machine": {"os": "Darwin 25.4.0", "arch": "arm64", "cpu": "Apple M5 Max", "cores": 18},
  "started": "2026-11-21T15:26:31Z",
  "recorded": "2026-11-22T09:10:02Z",
  "busy_seconds": 63000,
  "modules_compiled": 3565,
  "bitmap_b64": "<N bits, bit i = module i compiled, LSB-first per byte, gzip then base64>",
  "olean_digest": "<sha256 over, for each compiled module in index order: sha256(.olean bytes) as 32 raw bytes>",
  "whole_proof": false,
  "axioms": null
}
```

- `whole_proof` true only when all N compiled AND the axiom check ran; then `axioms` is the list printed for
  `riemannHypothesis` (expected `["propext", "Classical.choice", "Quot.sound"]`).
- No name/email inside: the identity is the PR author (GitHub login), which must equal `<github-login>` in the path.
- A person may submit many records; each supersedes their previous one (bitmap must be a superset).

## Bot acceptance rules (B)

Reject with a PR comment if any fails: format/tool known · constants match · path login == PR author · bitmap ⊇ the
person's last accepted bitmap · `modules_compiled` == popcount(bitmap) · speed plausible: new modules ÷ elapsed hours
since last accepted record ≤ max(12,000, 1,000 × cores)/h (flag, don't reject, above max(6,000, 250 × cores); cores counted up to 512) · `olean_digest` == reference digest
for that bitmap (reference = the project's own build; skipped until M0 confirms cross-machine identity).
Accept → merge, regenerate `data.json`, commit.

## data.json (C reads; B writes)

```json
{
  "generated": "…Z",
  "n": 175187,
  "libraries": [["BuildAid", 0], ["CompanionTheory", 5], …],
  "builders_b64": "<N bytes gzip+base64: per module, number of distinct people whose accepted build compiled it (cap 250)>",
  "summary": {"people": 0, "whole_proofs": 0, "modules_built_once": 0, "modules_built_3x": 0},
  "leaderboard": [{"who": "login", "modules": 0, "whole_proof": false, "build_hours": null, "machine": "Apple M5 Max",
                   "since": "2026-11-21T15:26:31Z", "finished": null, "first_whole_proof_rank": null}],
  "latest": {"who": "login", "modules": 0, "recorded": "…Z", "machine": "Apple M5 Max"},
  "validated": [{"who": "Andrew Sutherland (MIT)", "what": "…", "url": "https://math.mit.edu/~drew/grh"}]
}
```

Leaderboard order: modules compiled (desc); among whole proofs, `first_whole_proof_rank` (who finished first);
otherwise earliest `since`. `since` = full UTC timestamp of the person's first accepted record.
`build_hours` = `busy_seconds` / 3600 of the record that completed the whole proof (null until then).
`finished` = `recorded` (UTC) of that same record (null until then).
`finished` and `validated_at` (first record at Level 2 or higher; null below Level 2) come from the bot's ledger
(`state/firsts.json`, seeded from `bot/firsts-seed.json`) and only ever move earlier: a build is one file that each
`submit` overwrites, so re-submitting must not change when someone finished (issue #12). Validators are listed by
`validated_at`.
`libraries` = top-level folders only, with their first module index. `modules.txt` is published next to index.html
by whoever publishes data.json (the bot), unchanged from the reference list.

## Additional rules (from building the bot, 2026-11-21)

- A submission PR adds exactly one new file under `submissions/<login>/` and touches nothing else. Rejected PRs are
  closed with a comment listing the reasons; the volunteer resubmits as a new PR.
- Unknown fields are rejected. `machine` = {os, arch, cpu: strings; cores: integer}. Record ≤ 256 KB.
- `recorded` > `started`, not in the future (10 min skew allowed), and after the person's last accepted record.
  `busy_seconds` ≤ `recorded − started`. Bitmap non-empty, no bits past module N−1.
- `build_folder` is one of the two fixed folders. `tool` is an exact known release string ("riemann-at-home 1.0.0").
- `olean_digest` = lowercase hex sha256 over the concatenation of the 32-byte raw sha256 of each compiled module's
  `.olean`, in module-index order.
- Speed: new modules ÷ wall-clock hours since the previous accepted record (first record: since `started`), with the
  gap counted as at least 10 minutes, so frequent updates aren't judged on a few seconds of bursty finishes.
- `recent` (optional, data.json): modules whose builder count went up since the previously published data.json,
  `{"since": <previous generated>, "gaps": [first index, then differences]}`, at most 20,000 (evenly sampled). The page
  replays them one by one until the next update. Ignored when deciding whether data.json changed.
- The digest reference is a frozen hash table (`rahbot reference-snapshot`), not the live build folder, which changes
  while a build runs. Kept by the bot; can be published.

## Several computers per person (2026-11-21)

- `setup` creates a random `build_id` (16 hex chars) per computer and keeps it; every record carries `"build_id"`.
- Path: `submissions/<github-login>/<build_id>/<UTC time>.json`.
- Bot rules that said "the person's last accepted record" now mean "this build's last accepted record"
  (bitmap superset, recorded-after, speed). Different builds of one person are independent.
- Leaderboard per person: `modules` = union of all their builds' bitmaps; `whole_proof` if any build is whole
  (`build_hours`/`finished` from the first whole build); new field `computers` = number of builds.
  `machine` = the machine of their largest build.
- Terrain (`builders_b64`) still counts distinct PEOPLE per module, not builds.

## Running now + staleness (2026-11-21)

- data.json gets `"running"`: one entry per BUILD that is not whole:
  `{"who": "login", "build_id": "…", "machine": "…", "modules": 0, "recorded": "…Z"}`, sorted by modules desc.
- The page shows a running entry only if `recorded` is within the last 1 h (was 24 h) (checked in the browser against the
  current time, so stale builds vanish even if the bot is idle). Stale builds still count in the terrain and in the
  person's leaderboard modules.
- (Superseded) Updates are pushed to the build's single PR every ~10 minutes; see "One PR per computer".

## One PR per computer, updated in place (2026-11-21) — supersedes per-record PRs and the 6-hour auto-submit

- Each build (computer) opens ONE pull request when it starts: branch `rah/<build_id>` in the volunteer's fork, adding
  `submissions/<login>/<build_id>.json` (one file per build, overwritten on each update; no timestamp in the name).
- While building, the tool commits the updated record to that same branch every ~10 minutes (quiet: no new PR).
- The bot polls every ~10 minutes, reading all open PRs' head records in batches (GraphQL), checks each (rules apply
  between successive versions of the same build's record), and includes accepted open-PR records in data.json
  (`running`, leaderboard, terrain) WITHOUT merging. It republishes data.json at most ~6×/hour (GitHub Pages limit).
- The bot merges the PR when the record is whole_proof, or when the volunteer runs `riemann-at-home finish`
  (marks the record `"final": true`), or after 7 days without updates (merge the last accepted version).
- A version that fails checks is not used; the bot comments once on the PR with the reason and keeps the last
  accepted version until a newer one passes. It only closes a PR for identity/path violations.
- Staleness: Running Now hides builds whose `recorded` is older than 1 h (page-side), but only when more than 10
  people have builds running; with 10 or fewer, every unfinished build stays listed (2026-11-21).

## Clarifications from building the CLI (2026-11-21)

- A module counts as compiled only when both its `.olean` and its `.trace` exist (Lake writes the trace last; an
  `.olean` without `.trace` is an interrupted build and gets rebuilt). CLI, bot reference snapshot and page all use this.
- Compare bitmaps by decompressing and comparing bits, never by the base64 text (gzip output differs by implementation).
- Records are checked as a SET of keys, not key order. `build_id` and `final` are part of the schema.
- `whole_proof` is only a claim: the bot itself verifies `axioms` == ["propext", "Classical.choice", "Quot.sound"]
  (in any order) and rejects anything else, including `sorryAx`.
- `busy_seconds` = wall time while the build was running, minus pauses.
- `modules.txt` is sorted by UTF-8 bytes (identical to code-point order for these names).

## Display names (2026-11-21)

- Records may carry optional `"display_name"`: plain text, 1–32 chars, no control chars. There is no anonymous
  option (dropped 2026-11-21): the pull request always shows the GitHub username, so the bot rejects records with
  `"anonymous"`.
- The page shows display_name instead of the login, and no GitHub profile link. data.json leaderboard/running/latest
  entries carry `"name"` (what to show) and keep `"who"` (login) only when the person did not choose a display name;
  otherwise `"who": null`.
- Bot rejects a display_name equal (case-insensitive) to another participant's GitHub login.
- The CLI explains when setting it: "This is only a label on the Riemann@home page. Your pull request on GitHub
  always shows your username, so nobody here is anonymous."
- Consent (2026-11-21): nothing is submitted until the person agrees (`setup` asks once in a terminal; otherwise
  `submit --agree`). The notice lists what becomes public: GitHub username, OS, chip, core count, modules built.
- `running` excludes builds marked `"final": true`.
- display_name validation (CLI and bot identical): trim ends, 1–32 chars, reject Unicode categories Cc, Cf, Zl, Zp.
  Impersonation check compares NFKC-normalised, casefolded text against every other participant's login.
- Decisions: display names are validated when a record version is accepted; an accepted name is not re-judged later
  (a newcomer can't knock an existing name off the board). Display names may not start with "anonymous"
  (case-insensitive), in CLI and bot. `running` entries of display-name people omit `build_id`.

## Resuming after a merge (2026-11-21)

- A build whose PR was merged (whole, final, or 7 days stale) may continue: the same build_id opens a FOLLOW-UP PR that
  modifies its existing `submissions/<login>/<build_id>.json` on main. Checked against the merged version (bitmap grows,
  recorded later, speed over the whole gap). Not an identity violation. Only one open PR per build at a time.
- After `"final": true` is merged, further versions are still rejected (final means final); a stale-merged build is not final.
- The CLI detects that its PR was merged and opens the follow-up PR automatically on the next update.

## No stale merge (2026-11-21) — supersedes the 7-day merge and "Resuming after a merge"

- The bot merges a build's PR only when its accepted version is `"final": true` (`riemann-at-home finish`). No time-based merge.
  (2026-11-22: a whole-proof PR is no longer merged automatically; it stays open so the export progress and the
  Level 2/3 result can arrive on it. Run `finish` when you're done.)
  Abandoned PRs simply stay open. Follow-up PRs are therefore not needed: a build has one PR for its whole life.
- If the bot's state is lost, it rebuilds by re-reading every open PR's head and re-checking it from scratch
  (no previous version → checked as a first version).

## Levels and the joint statement (2026-11-21)

Modelled on the Lean and Mathlib communities' joint statement
(https://leanprover-community.github.io/blog/posts/riemann-hypothesis/): their check 2 is "reproducing the same raw
proof export file"; their check 4 is re-checking that export with independent checkers. Checks 1 and 3 (statement =
Mathlib's RiemannHypothesis; proved theorem is exactly that statement) are theirs; we cite them, we don't redo them.

- **Level 1 · Build**: any compiled modules (as now). `whole_proof` as now.
- **Level 2 · Export reproduced**: whole_proof AND `export_sha256` equals the reference export.
  Reference (Andrew Sutherland, https://math.mit.edu/~drew/grh): `solution.ndjson`, 61,570,595,788 bytes,
  sha256 `5ea74b912147c5c93cc2b6d70cc727cf908df2f62ac6a20480a3fa02f6be244e`, made with lean4export v4.33.0.
  The CLI streams the exporter's output straight into sha256 and a byte counter (no 61 GB file on disk).
  The exact exporter invocation must reproduce that hash; until a full build has confirmed it, treat it as unverified.
- **Level 3 · Independent re-check**: Level 2 AND at least one independent checker accepted the export
  (nanoda, con-leche, lean4checker, lean4lean). Needs a large-memory machine (nanoda ~100 GB RAM, con-leche ~50 GB).
- New optional record fields: `"export_sha256"`, `"export_bytes"` (int), `"checkers"`:
  `[{"name": "nanoda", "version": "…", "result": "accept", "seconds": 0}]`, `"sign_statement": true`.
- One joint statement for every proof (owner, 2026-11-27). `"sign_statement": true` is accepted on any whole record
  (either proof) whose axioms are exactly the three standard ones; `"sign_statement": false` is an explicit opt-out
  (`sign --cancel`, `setup --no-sign`), accepted on any record. The bot rejects an `export_sha256` that isn't the
  reference (reason: "export does not reproduce the reference").
- data.json `"signatures"`: everyone with a whole build of either proof and only the three standard axioms, unless
  they opted out (false in their newest record that says either way, or their login in bot/optout.json):
  `[{"who": login|null, "name": "…", "first_finished": "…Z", "signed": "…Z", "via": "signed"|"record",
  "badges": [{"kind": "17m"|"300k"|"export"|"recheck", "label": "17M BUILT"|"300K BUILT"|"EXPORT REPRODUCED"|
  "RE-CHECKED: <checker>"}], "machine": "…", "level": 1|2|3, "checkers": ["nanoda"]}]`, ordered by `first_finished`
  (their earliest whole build). `via: "signed"` = they signed (signed = time the signing version was accepted);
  `via: "record"` = listed from their build record (signed = first_finished). Leaderboard entries get `"level"` (1–3).
- Page: a "Joint statement" tab beside the leaderboard view: the one statement (owner-approved wording, kept in the
  page) with its colored badge legend (17M BUILT #ffd23f, 300K BUILT #ff9ae8, EXPORT REPRODUCED #7dff95, RE-CHECKED
  #7fd8ff), then the signatures list (avatar, name, date, machine, badges, "added from their build record" for
  via=record). DOWNLOAD PDF prints the same, numbered, badges in color. Empty state: "No signatures yet."

## 300K export (2026-11-27, optional)

- `riemann-at-home export --proof 300k` on a whole 300K build with the three standard axioms: lean4export v4.35.0
  (commit `5a9a355d…`), the same 38 export targets, hashed as it streams. The 300K record then carries
  `export_sha256` (64 hex) and `export_bytes`; the bot accepts any well-formed hash, but only on a whole build.
  `checkers` stay 17M-only.
- The 300K reference is pinned (2026-11-28) in the tool and the bot, `PROOFS["300k"]`: `export_sha256`
  `baf221c81749bf4bcbd6cd56238adfb4e8e780c38ef92d6a7ab458d57df36fc1`, `export_bytes` 4,485,867,644, after six independent builders' exports agreed (3 were needed).
  A different hash is still accepted and shown; it only earns no badge.
- data.json `"export_300k"`: `{"reference": sha|null, "agree_needed": 3, "builders": N, "hashes": {sha: [names]}}`,
  most-agreed hash first. The page shows one line under "The builders so far".
- With a reference pinned, a builder whose newest 300K export matches it gets the badge kind `"export300k"`
  ("300K EXPORT REPRODUCED", #b6ff7d) in `"signatures"`, and the badge key gains its line.

## Export progress (2026-11-22, tool 1.1.0)

- While `riemann-at-home export` runs, records carry `"export_progress"`: `{"bytes": int, "seconds": number,
  "left_seconds": number|null, "peak_memory_gb": number|null, "done": bool}` (whole_proof only; exactly these keys).
  The tool sends an update at the auto-submit interval during the export and one when it finishes. An unfinished
  export not heard from for 30 minutes is left out of later records.
- data.json: leaderboard rows and running entries get `"export"`: the same numbers plus `"total"` (reference bytes)
  and, once done, `"matches"`, which the bot decides from `export_sha256` (Level 2), never from the record.
  A whole-proof build whose export is in progress is listed in `running`.
- Known tools: "riemann-at-home 1.0.0", "riemann-at-home 1.1.0", "riemann-at-home 1.2.0" (see "Tool 1.2.0").

## Tool 1.2.0 (2026-11-28)

- The version now changes when export features change, so records show which tool made them (ops #64, asked on
  issue #24). 1.2.0 is the first tool with `--fast-exit` on by default and `--parallel` listed.
- Records with `export_sha256` may also carry `"export_exporter"`: the exporter that ran, `"lean4export <tag>"`, or
  `"lean4export <tag> + parallel <commit8>"` with `--parallel`; and `"export_fast_exit"`: true when the exporter's
  fast exit was on (the default; `--no-fast-exit` turns it off; the parallel exporter has none, so false there).
  Both are optional, 17M and 300K alike, and refused without `export_sha256`. Older records without them are fine.
- The tool and the bot accept records from any known tool, so a saved 1.1.0 record can still be submitted after
  `update`.

## Build crashes (2026-11-23)

- Lean has segfaulted (exit code 139) near the end of whole builds; a restart finished them. The tool restarts a
  crashed `lake build` up to 3 times (finished modules are kept) and, if it still fails, posts its last progress.
- Records may carry `"crashes"`: up to 20 `{"module": str, "code": int, "at": UTC time}`, newest last: the module
  lake reported Lean crashing on (its `✖ [i/n] Building X` line) and Lean's own exit code from that log line (lake
  itself exits 1). `"module"` is `"unknown"` if the log did not say.
- data.json: `"crashes"`: one entry per module, `{"module", "codes", "names", "times", "last"}`, the modules that
  crashed on the most people first. Not shown on the page; it is there to learn which module crashes and why.

## Several proofs (2026-11-25): 17M and 300K

- Records may carry `"proof"`: `"300k"`; absent means `"17m"`, so every earlier record and the bot state stay valid.
  Per proof (the `PROOFS` table in the bot and the CLI; a future proof is one more entry):
  - 17M: as above (`archive_sha256`, Lean 4.33.1, folder `.../lean`, `modules.txt`, N = 175,187).
  - 300K: grh-lean (https://github.com/lsernau/grh-lean, Apache-2.0), readable edition `grh/`. Source identity
    `"source_commit": "72fead102f663d5c7a407964a13dc0cf9d977207"` (instead of `archive_sha256`, which a 300K record
    must not have); `grh/` tree `2e133df63d7f4da6b3059c4195324f8e9187ba73`; toolchain `leanprover/lean4:v4.35.0`;
    Mathlib `56a005855ea17e0b0958f73ec801ae140b0a1679`; folder macOS `/Users/Shared/riemann-at-home/grh`, Linux
    `/opt/riemann-at-home/grh`; module list `bot/modules-300k.txt` (src/**/*.lean sorted byte-wise, N = 803, sha256
    `f0b574a8...13d1`). Build: plain `lake build`; axioms: `lake env lean scripts/PrintAxioms.lean`. `whole_proof`
    needs all 803 modules and all five theorems printed; `axioms` = their axioms together, exactly the three.
  - 300K has no Levels: `checkers` are rejected on 300K records, and its export is optional (see "300K export":
    a pinned reference since 2026-11-28 gives a badge, not a Level). Since 2026-11-27 a whole 300K
    record with the three standard axioms counts for the one joint statement (300K BUILT badge; see "Levels and
    the joint statement").
    `olean_digest` has no 300K reference either (not checked, like 17M today).
- Each proof gets its own `build_id` (one PR per build, same path rules). A build cannot switch proofs.
- Speed: the same rule; with 803 modules and the 10-minute floor it cannot trigger for 300K (needs 300K timings
  to tighten).
- data.json: existing fields keep their 17M meaning. New: top-level `proofs` {key: {label, title, n, toolchain,
  source, whole_proofs}}; per leaderboard row `proofs` {key: {modules, n, whole, finished, build_hours, computers,
  machine, rank}} and `tier` ("17m+300k" | "17m" | "300k" | "partial"); `running`/`latest` entries of other proofs
  carry `"proof"`. Order: both proofs, then 17M only (first_whole_proof_rank), then 300K only (who finished first),
  then partial builds. Ledger keys `whole_300k`, `hours_300k` only ever move earlier, as for 17M.
- Version note: the CLI that first knew 300K kept 300K records local; since the bot ranks them (2026-11-25) the CLI
  submits them through the same PR path as 17M.
