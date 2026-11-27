# Riemann@home

Build the Lean proof of the Riemann Hypothesis on your own computer, and add your build to a global map.

**Global leaderboard:** https://riemann-at-home.github.io/riemann-at-home/

A proof of the Riemann Hypothesis, written with AI and checked in Lean, was published on 2026-11-20 by Levent Alpöge
(https://alpo.ge). Several people have already built the whole proof and confirmed it checks. Riemann@home lets anyone
do the same and watch it add up: the proof is 175,187 Lean modules, and the page shows how many people have built each
one, who is building right now, and who has built the whole thing.

## Two proofs: start with the new one (300K)

A second, much shorter Lean proof appeared: grh-lean by Luke Sernau (https://github.com/lsernau/grh-lean,
Apache-2.0). Riemann@home builds its readable edition (`grh/`, about 300,000 lines, 803 modules) as **300K**, next to
the original **17M** build. `setup` asks which one to build: 1) the new proof (300K, recommended and the default),
2) the original (17M, the big challenge), or 3) both (new first). 300K: pinned commit
`72fead102f663d5c7a407964a13dc0cf9d977207`, Lean 4.35.0, Mathlib `56a00585`, folder macOS
`/Users/Shared/riemann-at-home/grh`, Linux `/opt/riemann-at-home/grh`; 20 min to 2 h on most computers. A whole 300K
build whose five theorems use only the three standard axioms is its finish. Its export then runs by itself (about
5 minutes, nothing written to disk; `--no-export` skips it, `riemann-at-home export --proof 300k` runs it later), and
earns the 300K EXPORT REPRODUCED badge on the joint statement once three builders' exports agree.
300K builds are submitted like 17M ones (one pull request per build, the record says `"proof": "300k"`)
and ranked on the same leaderboard: both proofs first, then 17M, then 300K. Computers already set up for 17M keep working exactly as before (add the new proof with
`setup --proof 300k`, then `build --proof 300k`).

## Join with an AI assistant

Paste this into Claude, ChatGPT, or another assistant that can run commands:

> I'd like to help build the Lean proof of the Riemann Hypothesis through Riemann@home.
> Please clone https://github.com/riemann-at-home/riemann-at-home, read its README, and walk me through the volunteer steps:
> "riemann-at-home setup", then "riemann-at-home build".
> Once the build is running, start my local dashboard with "riemann-at-home page" and open http://localhost:8642 in my browser.
> The 300K proof exports itself when its build finishes (about 5 minutes); leave that on. If I build the 17M proof and it finishes, help me run "riemann-at-home export".
> Ask me before installing anything. During setup, show me the tool's notice about what it posts to GitHub and ask me once; if I agree, it posts my progress on its own from then on, so don't ask me again for each update. Setup also shows the joint statement: signing is on by default when my build qualifies, so tell me I can say no then, or withdraw any time with "riemann-at-home sign --cancel".

## Join by hand

Needs macOS or Linux, Python 3, git, roughly 150 GB free for the whole proof (a whole build is about 120 GB, judging
from 84 GB at 70%; Lean and the tools about 3 GB; and the build always leaves 20 GB free) (less is fine: the build stops by itself at 20 GB free, so your
computer always keeps room, and every module you built still counts). Building needs no special amount of memory; the
optional export step (7) needs a lot.

1. **GitHub CLI.** Install `gh` (macOS: `brew install gh`) and log in yourself: `gh auth login -s workflow`.
   The `workflow` permission lets your updates go through: the repo holds the bot's GitHub Actions files, and GitHub
   refuses a push that touches those without it (already logged in? `gh auth refresh -h github.com -s workflow`).
   The tool never asks for or handles your password or token.
2. **Setup.** `python3 -I cli/riemann-at-home setup`
   Downloads the official archive from alpo.ge, checks its sha256
   (`9631b4f020199e580ba86178cb56c6e9b09f690c2369a80dc4334aa93f49c7fc`), unpacks it into a fixed folder
   (macOS `/Users/Shared/riemann-at-home/lean`, Linux `/opt/riemann-at-home/lean`), installs the pinned Lean
   (4.33.1) and the Mathlib cache. At the end it asks once whether to post your progress publicly (see 4).
3. **Build.** `python3 -I cli/riemann-at-home build --gentle` (or `--full`)
   Runs the official `lake build Main`, unchanged, at the lowest priority. `pause`, `resume`, `stop`, `status`.
   Measured so far: 9 to 19 hours of compute on 16- to 64-core desktops and workstations, about 2 days on a 12-core
   M2 Max; any amount counts. If Lean crashes, the tool restarts the build by itself (up to three times) and keeps
   what was built.
4. **Post your progress.** Setup asks once; or later: `python3 -I cli/riemann-at-home submit --agree`.
   From then on, one public pull request for this computer is updated about every 10 minutes while you build.
   **What becomes public:** your GitHub username, your computer's OS, chip and number of cores, and which modules
   you've built. Nothing is posted until you agree. Stop any time: `submit --disable-auto`.
   Setup then shows the joint statement (one letter for both proofs, with a badge for each thing you did) and asks
   whether to sign it when your build qualifies. The answer defaults to yes; it takes effect only when a whole build
   of yours finishes with only the three standard axioms (17M: when your export matches). Later: `sign --when-done`
   or `sign`; take it back any time: `sign --cancel`. Builders who finished before signing was on by default were
   added from their build records; to be removed, run `sign --cancel` or ask in an issue.
5. **Optional display name.** `riemann-at-home name "Your Name"` (or `submit --agree --name "Your Name"`) shows that
   on the leaderboard instead of your GitHub username. It's only a label: your pull request on GitHub always shows
   your username, so nobody here is anonymous.
6. **See your own build.** `python3 -I cli/riemann-at-home page` opens a local page for this computer.
7. **Export.** 300K: runs by itself right after a whole build (about 5 minutes, 4.5 GB streamed, nothing written to
   disk); if you skipped it, `python3 -I cli/riemann-at-home export --proof 300k`. 17M (Level 2, optional): when the whole proof is built, run `python3 -I cli/riemann-at-home update`, then
   `python3 -I cli/riemann-at-home export`. It exports the compiled proof (61.6 GB, hashed as it streams, nothing
   written to disk) and checks it is bit for bit the reference export; a match is what lets you sign. It takes 2 to 3
   hours and a lot of memory: it peaks around 145 GB. With 140 GB or more it is comfortable; with 96 to 140 GB it
   works but the end slows down a lot as memory fills (a 128 GB computer finished in about 3 hours; macOS adds swap
   by itself if the disk has room); below 96 GB it may never finish.
8. **Done or stopping for good.** `python3 -I cli/riemann-at-home finish`
9. **Updates.** The tool checks GitHub once a day (one fetch with no login; nothing about you is sent). When there's a new
   version, your local page and `status` say so. Run `python3 -I cli/riemann-at-home update`: it shows what changed,
   asks, then updates and restarts the build and page. Nothing built is lost. It never updates by itself.

## What this is, and what it isn't

- It is many people independently re-running the same official build, and posting what their computer compiled.
- Results are self-reported, tied to your GitHub account. A bot checks every update (pinned archive and versions,
  progress only grows, plausible speed, a fingerprint of the compiled files) before it counts. It can't prove you
  actually ran it.
- Building the proof doesn't settle the mathematics. Whether the Lean statement means what mathematicians mean by the
  Riemann Hypothesis, and whether Lean itself has a bug, is work for experts.

## How it works

- `cli/riemann-at-home`: the volunteer tool (one Python file, standard library only).
- `submissions/<login>/<build_id>.json`: one record per computer, updated through that computer's pull request.
- `bot/rahbot`: checks pull requests, keeps the leaderboard data (`docs/data.json`) up to date, merges a computer's
  pull request when it finishes the whole proof or runs `finish`.
- `docs/`: the global page, served by GitHub Pages.
- `CONTRACT.md`: the exact record format and every rule the bot applies.

## Why not zero-knowledge proofs?

We tried: running the independent checker nanoda inside the RISC Zero zkVM works, and the result can be verified by
anyone in milliseconds. But proving the whole proof that way would take roughly 26 to 260 GPU-years today, and modules
that import a lot don't fit in the zkVM's memory. Projects like Ix (Argument Computer) are working on making this
practical. Until then, Riemann@home is people re-running the build in the open.
