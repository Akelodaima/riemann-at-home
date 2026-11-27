# riemann-at-home (volunteer CLI, v1)

One Python 3 file, standard library only. Run it as `python3 -I riemann-at-home <command>`.
Formats: `../CONTRACT.md` (`rah/build/1`). Needs only this folder: `riemann-at-home`, `page/index.html`,
and this README (`sign` prints the joint statement from it).

## Flow

1. `riemann-at-home setup`: downloads the 14 archive parts from alpo.ge (or `--archive PATH`), checks sha256
   `9631b4f0…c7fc`, unpacks into the fixed folder (macOS `/Users/Shared/riemann-at-home/lean`, Linux
   `/opt/riemann-at-home/lean`), installs elan + Lean 4.33.1, runs `lake exe cache get Mathlib`, and makes this
   computer's random `build_id`. Running it again skips whatever is already done.
2. `riemann-at-home build [--gentle|--full] [--submit]`: the official `lake build Main`, unchanged, in the
   background at nice 19 (gentle = macOS background policy / Linux SCHED_IDLE). `pause`, `resume`, `stop`, `status`.
   The build stops by itself when the build disk gets down to 20 GB free, so your computer always keeps room (a whole build is about 120 GB, judging from 84 GB at 70%; with Lean, the tools and that 20 GB, allow roughly 150 GB free). Everything
   compiled so far is kept, and `record` / `submit` still work for the partial build.
3. `riemann-at-home submit`: sends the latest record to this computer's one pull request on
   `riemann-at-home/riemann-at-home` (`--upstream OWNER/REPO` to change). The tool keeps its own clone in
   `~/.riemann-at-home/repo` (never your checkouts). Branch `rah/<build_id>` is upstream `main` plus one commit
   ("update: N modules") that writes only `submissions/<login>/<build_id>.json`, force-pushed on each update. If you
   can push to the repo, the branch goes there; otherwise to your fork (`gh repo fork`). The first submit opens the
   PR; later ones update it. Commits use your git name and a GitHub noreply email only. `--dry-run` shows the plan.
4. Automatic updates: `build --submit`, or `submit --enable-auto` for a build that is already running (no restart).
   Every interval (default 600 s; `submit --interval SECONDS`, minimum 30) the build writes a record and updates its
   PR: right away when the module count changed, at most every 5 minutes when only the times changed. Errors
   (network, `gh` missing or logged out) go to `~/.riemann-at-home/logs/autosubmit.log` and never stop the build.
   `submit --disable-auto` turns it off.
5. `riemann-at-home finish [--submit]`: done on this computer. Stops the build, writes a record with
   `"final": true` and submits it (always when auto-submit is on); the bot then merges the PR.
   After it, the build takes no more updates, so it refuses while the axiom check or an export is running, or when a
   whole build hasn't been exported yet (`--force` overrides). `finish --dry-run` only says what it would do.
6. `riemann-at-home name "Display Name"` / `name --clear`: a label the page shows instead of your GitHub login
   (1 to 32 characters, no control characters). Records then carry `"display_name"`. It's only a label: your pull
   request on GitHub always shows your username, so nobody here is anonymous.
   Nothing is posted until you agree: `setup` asks once (in a terminal), or run `submit --agree [--name "..."]`.
   The notice lists what becomes public: your GitHub username, OS, chip, core count, and which modules you built.
7. `riemann-at-home update [--yes]`: get the newest version. The tool checks once a day (a `git fetch` with no login
   of main; only changes under `cli/` count) and says so on the local page and in `status`. `update` lists the
   changes, asks, fast-forwards your checkout, and restarts a running build (same speed; Lean resumes where it was) and
   this computer's local page. It never updates without being asked.
8. `riemann-at-home page`: this computer's page at http://localhost:8642/ ("This computer": its terrain, what is
   compiling now, speed). Its "Global dashboard" button opens https://riemann-at-home.github.io/riemann-at-home/.

## Two proofs (`--proof 300k|17m`)

`setup` asks which proof to build (1 = the new 300K proof, the default and what a run without a terminal gets;
2 = the original 17M; 3 = both, 300K first, and 17M starts by itself when 300K is whole). `--proof` on any command
picks one (`setup --proof both` too); without it a command means what setup chose, and 17M on a computer set up
before setup asked. 300K: `git clone` of https://github.com/lsernau/grh-lean, checkout of exactly commit
`72fead102f663d5c7a407964a13dc0cf9d977207`, HEAD and the `grh/` tree (`2e133df6...`) checked, `grh/` moved to
`/Users/Shared/riemann-at-home/grh` (Linux `/opt/riemann-at-home/grh`), Lean 4.35.0 via elan, `lake exe cache get`.
`build --proof 300k` runs plain `lake build` (the edition's default targets) in the background like 17M, then
`lake env lean scripts/PrintAxioms.lean` (refused unless that file is exactly the expected five `#print axioms`);
the record is whole only when all five theorems were printed. Records carry `"proof": "300k"` and
`"source_commit"` instead of `archive_sha256`. Its files live in `~/.riemann-at-home/300k/` (own build_id, logs,
records, PR state); consent, display name and submit settings are shared. `status` shows every proof set up here.
`export` and `recheck` are 17M only. `sign --proof 300k` signs the separate 300K joint statement (below) on a whole 300K build whose five theorems use only the three standard axioms; `sign --when-done --proof 300k` signs in advance. Signing is on by default when your build qualifies; you see the statement first and can withdraw any time with riemann-at-home sign --cancel. Setup asks with [Y/n] in a terminal (without one it only prints the statement and `sign --when-done`); `setup --no-sign` opts out up front, and `sign --cancel` withdraws and records the opt-out so nothing is signed automatically again. It signs only at the moment a build first qualifies, never a build that had already qualified. A 300K opt-out is written into the record as `"sign_statement": false`. `submit` (and auto-submit) posts 300K records the same way as 17M ones:
one pull request per build, on the same leaderboard.

## Levels

- **Level 1 · Build**: any compiled modules. A whole build (all 175,187 modules) also runs the axiom check.
- **Level 2 · Export reproduced**: `riemann-at-home export`, after a whole build with a passing axiom check. Builds
  lean4export at tag v4.33.0 (https://github.com/leanprover/lean4export) into `~/.riemann-at-home/tools` with the
  proof's own Lean 4.33.1, not the 4.33.0 that tag pins (Lean only reads compiled files made by the same version:
  issue #14), runs `lake env lean4export Main` in the build folder, and streams its output straight into
  sha256 and a byte counter: the ~61 GB export is never written to disk. The reference export (Andrew Sutherland,
  https://math.mit.edu/~drew/grh) is 61,570,595,788 bytes with sha256
  `5ea74b912147c5c93cc2b6d70cc727cf908df2f62ac6a20480a3fa02f6be244e`. A match puts `export_sha256` and
  `export_bytes` into the records. Until a whole build has reproduced it, the exact exporter invocation is
  unverified, and the tool says so when the hash does not match.
  Fast exit (on by default): export builds its copy of lean4export with two lines added after its last write (flush,
  then exit), so it skips freeing its cache one object at a time, which took hours at "99%" on computers short of
  memory (issue #24). A full export with it matched the reference (1 h 19 m on a 126 GB machine), and the
  comparison with the reference hash checks every run. `export --no-fast-exit` uses the unpatched exporter.
- **Level 3 · Independent re-check** (optional): `riemann-at-home recheck --nanoda` or `--con-leche` saves the
  export once to `~/.riemann-at-home/export/` (61.6 GB of disk), confirms it is the reference export, then runs the
  checker on that file after the exporter has exited, so the two never need memory at the same time. The second
  checker reuses the saved file; delete it when you are done (the tool prints the `rm` command). It records a
  `checkers` entry. It checks memory first and refuses below the need: nanoda about 100 GB, con-leche about 50 GB.
  Build the checker yourself (nanoda: `cargo build --release` in https://github.com/ammkrn/nanoda_lib, giving
  `nanoda_bin`; con-leche: `lake build con-leche` in https://github.com/leanprover/con-leche) and put it on `PATH`,
  at `~/.riemann-at-home/tools/bin/<name>`, or pass `--checker PATH`.
- `riemann-at-home sign`: at Level 2 or 3, shows the joint statement below, asks for confirmation (y/N), and then
  records carry `"sign_statement": true`.

## GitHub: the volunteer logs in, never the tool

Before submitting, the tool checks that `gh` is installed (on macOS it offers `brew install gh`) and that
`gh auth status` says logged in. If not, it stops and asks you to run `gh auth login` yourself. It never asks for,
reads, or stores a token.

## Files

`~/.riemann-at-home/`: `build_id`, `config.json` (submit settings, PR state, display name, levels), `repo/` (the tool's clone), `logs/` (build.log,
status.txt, samples.txt, axioms.log, autosubmit.log, export.log, recheck-*.log), `tools/` (lean4export), `records/`
(the last 50 records), `olean-hashes.json` (hash cache).

## Joint statement

Riemann@home: a joint statement from independent builders. We, the undersigned, each built Levent Alpöge's Lean proof of the Riemann Hypothesis (released November 20, 2026) on our own computers, from the official archive (sha256 9631b4f0…c7fc) with the pinned Lean 4.33.1 and Mathlib. Each signatory: 1. compiled all 175,187 modules (lake build Main) without errors, 2. confirmed the final theorem depends only on Lean's three standard axioms (propext, Classical.choice, Quot.sound), 3. exported the compiled proof and reproduced the same raw export file as other independent builders (sha256 5ea74b91…244e), 4. where noted, re-checked that export with an independent checker written separately from Lean's own kernel (nanoda, con-leche, lean4checker or lean4lean), named beside that signature. We do not certify the mathematics. That the statement is Mathlib's Riemann Hypothesis, and that the proved theorem is exactly that statement, was checked by the Lean and Mathlib communities (https://leanprover-community.github.io/blog/posts/riemann-hypothesis/). Each signature is the signer's own report, tied to their GitHub account. We join the Lean and Mathlib communities in congratulating Levent Alpöge.

## 300K joint statement

Riemann@home: a joint statement from independent builders of the 300K proof. We, the undersigned, each built the 300K-line Lean proof of the Riemann Hypothesis and Dirichlet GRH (github.com/lsernau/grh-lean at commit 72fead10…7207, its readable edition grh/) on our own computers with the pinned Lean 4.35.0 and Mathlib. Each signatory compiled all 803 modules without errors, and confirmed that the five main theorems depend only on Lean's three standard axioms (propext, Classical.choice, Quot.sound). This proof has no reference export yet, so this statement does not cover reproducing an export. We do not certify the mathematics: whether the five theorems state the Riemann Hypothesis and Dirichlet GRH as intended is for mathematicians and the Lean community to judge. Each name is tied to that builder's GitHub account and their published build record.
