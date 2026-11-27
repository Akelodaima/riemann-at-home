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
`recheck` is 17M only. The 300K export (`export --proof 300k`, about 5 minutes, hashed as it streams, nothing written to disk) runs by default right after a whole 300K build passes the axiom check, after that build's own record is sent; `build --no-export` or `setup --no-export` turns that off (`build --export` turns it back on), and `update` and `status` remind a finished 300K build that has no export yet. The export earns the 300K EXPORT REPRODUCED badge on the joint statement once three independent builders' exports agree and that hash is pinned as the reference; until then the hashes are gathered on the page. There is one joint statement for both proofs (below), with a badge for each thing a signatory did (17M BUILT, 300K BUILT, EXPORT REPRODUCED, RE-CHECKED). `sign` signs it from whichever of your builds qualifies: a whole build of either proof whose theorems use only the three standard axioms; `sign --when-done` signs in advance. Signing is on by default when a build qualifies; you see this statement first and can withdraw any time with `riemann-at-home sign --cancel`. Builders who finished before signing was on by default were added from their build records; to be removed, run that command or ask in an issue. Setup asks once with [Y/n] in a terminal (without one it only prints the statement and `sign --when-done`); `setup --no-sign` opts out up front, and `sign --cancel` withdraws on every proof and records the opt-out (`"sign_statement": false` in your records) so nothing is signed automatically again. It signs only at the moment a build first qualifies (17M: when the export matches; 300K: when the whole build passes the axiom check), never a build that had already qualified. `submit` (and auto-submit) posts 300K records the same way as 17M ones:
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

Riemann@home: a joint statement from independent builders. We, the undersigned, each built an AI-assisted Lean proof of the Riemann Hypothesis on our own computers, from the official sources with the pinned Lean toolchain and Mathlib, and confirmed that its main theorems depend only on Lean's three standard axioms (propext, Classical.choice, Quot.sound). Each signature carries badges for exactly what that signatory did: 17M BUILT: compiled all 175,187 modules of Levent Alpöge's proof (released November 20, 2026; archive sha256 9631b4f0…c7fc, Lean 4.33.1). 300K BUILT: compiled all 803 modules of the 300K-line proof of the Riemann Hypothesis and Dirichlet GRH (lsernau/grh-lean at 72fead10…7207, Lean 4.35.0). EXPORT REPRODUCED: exported the compiled 17M proof and reproduced the same raw export file as other independent builders (sha256 5ea74b91…244e). RE-CHECKED: re-checked that export with an independent checker written separately from Lean's own kernel, named on the badge. We do not certify the mathematics. That the theorems state the Riemann Hypothesis (and Dirichlet GRH) as intended was checked by the Lean and Mathlib communities. Each name is tied to that builder's GitHub account and published build record. We join the Lean and Mathlib communities in congratulating Levent Alpöge.

