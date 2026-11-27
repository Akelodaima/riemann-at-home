"""Tests for the riemann-at-home volunteer CLI.

  python3 -I tests/test_cli.py            fast tests + read-only tests on the real build folder
  RAH_SLOW=1 python3 -I tests/test_cli.py also: setup from parts and from the archive, build start/pause/resume/stop

Nothing here writes to the real build folder or to GitHub.
"""
import base64, getpass, gzip, hashlib, importlib.machinery, importlib.util, json, os, re, shutil, socket
import contextlib, io, subprocess, sys, tempfile, threading, time, types, unittest, unittest.mock
from pathlib import Path

CLI_DIR = Path(__file__).resolve().parents[1]
SCRIPT = CLI_DIR / "riemann-at-home"
TMP = CLI_DIR / "tmp"
TMP.mkdir(parents=True, exist_ok=True)          # not in a fresh checkout (GitHub Actions)
loader = importlib.machinery.SourceFileLoader("rah", str(SCRIPT))
spec = importlib.util.spec_from_loader("rah", loader)
rah = importlib.util.module_from_spec(spec)
loader.exec_module(rah)

REAL = Path(rah.FIXED_FOLDERS.get(os.uname().sysname, "/nonexistent"))
SLOW = os.environ.get("RAH_SLOW") == "1"
SETUP_FOLDER = TMP / "setup-test/riemann-at-home/lean"   # made by the slow setup test (or by hand)
ARCHIVE = Path.home() / "rh-lean/replay/lean.tar.gz"
PARTS = Path.home() / "rh-lean/replay/parts"


def cli(*args, home, check=True, timeout=600):
    env = {**os.environ, "RAH_HOME": str(home), "RAH_SAMPLE_SECONDS": "2", "RAH_NO_STATS": "1"}
    r = subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                       env=env, timeout=timeout)
    if check and r.returncode != 0:
        raise AssertionError(f"exit {r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")
    return r


def personal_strings():
    """Things that must never appear in a build record."""
    out = {getpass.getuser(), str(Path.home()), socket.gethostname().split(".")[0]}
    for k in ("user.email", "user.name"):
        v = subprocess.run(["git", "config", k], capture_output=True, text=True).stdout.strip()
        if v:
            out.add(v)
    return {s for s in out if s and len(s) >= 3}


def assert_private(tc, rec_text):
    for s in personal_strings():
        tc.assertNotIn(s.lower(), rec_text.lower(), f"personal string {s!r} leaked into the record")
    rec = json.loads(rec_text)
    tc.assertNotRegex(rec_text, r"[\w.+-]+@[\w-]+\.[\w.]+", "something email-shaped in the record")
    paths = re.findall(r'"(/[^"]*)"', rec_text)
    tc.assertTrue(all(p in rah.FIXED_FOLDERS.values() for p in paths), f"paths in record: {paths}")
    tc.assertEqual([k for k in rec if k not in rah.OPTIONAL_KEYS], rah.RECORD_KEYS)


def fake_folder(root: Path, n=20, compiled=(0, 3, 7, 8, 9, 15, 19), olean_only=(5,)):
    """A miniature project: n modules, some compiled (olean+trace), one interrupted (olean only)."""
    (root / "src/A/B").mkdir(parents=True)
    (root / "lean-toolchain").write_text(rah.TOOLCHAIN + "\n")
    (root / "lake-manifest.json").write_text(json.dumps({"packages": [{"name": "mathlib", "rev": rah.MATHLIB_REV}]}))
    mods = []
    for i in range(n):
        m = f"A.B.M{i:02d}" if i % 2 else f"A.N{i:02d}"
        mods.append(m)
        (root / "src" / (m.replace(".", "/") + ".lean")).write_text(f"-- {m}\n")
    lib = root / ".lake/build/lib/lean"
    for i in set(compiled) | set(olean_only):
        p = lib / (mods[i].replace(".", "/") + ".olean")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"olean of {mods[i]}".encode())
        if i in compiled:
            p.with_suffix(".trace").write_text("{}")
    return sorted(mods, key=lambda m: m.encode())


class Fast(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=TMP, prefix="t-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bitmap_lsb_first_gzip_base64(self):
        bits = [True] + [False] * 8 + [True]          # bit 0 and bit 9
        b64 = rah.encode_bitmap(bits)
        self.assertEqual(gzip.decompress(base64.b64decode(b64)), bytes([0x01, 0x02]))
        self.assertEqual(rah.decode_bitmap(b64, 10), bits)
        self.assertEqual(b64, rah.encode_bitmap(bits), "gzip output must be deterministic (mtime 0)")
        full = rah.encode_bitmap([True] * rah.N_MODULES)
        self.assertEqual(len(gzip.decompress(base64.b64decode(full))), 21899)

    def test_compiled_needs_trace(self):
        mods = fake_folder(self.tmp / "p")
        done = rah.compiled_modules(self.tmp / "p/.lake/build/lib/lean")
        self.assertEqual(len(done), 7)
        self.assertNotIn("A.B.M05", done)               # .olean without .trace = interrupted

    def test_module_order_bytewise(self):
        (self.tmp / "src/a").mkdir(parents=True)
        for n in ("Zeta", "alpha", "a/b", "A_b", "Ä"):
            (self.tmp / "src" / f"{n}.lean").write_text("")
        self.assertEqual(rah.all_modules(self.tmp), ["A_b", "Zeta", "a.b", "alpha", "Ä"])

    def test_busy_seconds_with_pauses_and_crash(self):
        logs = self.tmp / "logs"; logs.mkdir()
        ctx = rah.Ctx(type("A", (), {"folder": str(self.tmp), "logs": str(logs)})())
        t0 = 1_800_000_000
        I = rah.iso
        ctx.status.write_text(
            f"START {I(t0)}\nPAUSE {I(t0 + 100)}\nRESUME {I(t0 + 400)}\nBUILD_EXIT=143 {I(t0 + 1000)}\n"   # 700
            f"RESTART {I(t0 + 5000)}\n"                                                                  # crash
            f"RESTART {I(t0 + 9000)}\nPAUSE {I(t0 + 9500)}\n")                                          # open, paused
        ctx.samples.write_text(f"{I(t0 + 5300)} modules=5\n{I(t0 + 5600)} modules=9\n")
        started, busy = rah.busy_seconds(ctx, running=True, now=t0 + 9900)
        self.assertEqual(started, t0)
        self.assertEqual(busy, 700 + 600 + 500)

    def test_busy_seconds_legacy_run_build_logs(self):
        logs = self.tmp / "logs"; logs.mkdir()
        ctx = rah.Ctx(type("A", (), {"folder": str(self.tmp), "logs": str(logs)})())
        ctx.status.write_text("START 2026-11-21 07:26:31 PST\n")
        ctx.samples.write_text("2026-11-21 07:31:32 oleans=10 System-wide memory free percentage: 73%\n"
                               "2026-11-21 08:36:35 oleans=3469 System-wide memory free percentage: 73%\n")
        t_start = rah.parse_time("2026-11-21 07:26:31 PST")
        end = t_start + 4365
        (logs / "build.log").write_text("x"); os.utime(logs / "build.log", (end, end))
        started, busy = rah.busy_seconds(ctx, running=False, now=end + 99999)
        self.assertEqual((started, busy), (t_start, 4365))
        self.assertEqual(len(rah.samples(ctx)), 2)

    def test_parse_axioms(self):
        out = "'riemannHypothesis' depends on axioms: [propext,\n Classical.choice,\n Quot.sound]\n'x' depends on axioms: [sorryAx]"
        self.assertEqual(rah.parse_axioms(out), rah.EXPECTED_AXIOMS)
        self.assertEqual(rah.parse_axioms("'riemannHypothesis' does not depend on any axioms"), [])
        self.assertIsNone(rah.parse_axioms("error: unknown constant"))

    def test_record_fake_folder_contract_and_privacy(self):
        mods = fake_folder(self.tmp / "p")
        home = self.tmp / "home"
        logs = home / "logs"; logs.mkdir(parents=True)
        (logs / "status.txt").write_text("START 2026-11-21T15:26:31Z\nBUILD_EXIT=0 2026-11-21T16:26:31Z\n")
        r = cli("record", "--folder", self.tmp / "p", "--test-unofficial-folder", home=home)
        out = Path(r.stdout.strip().splitlines()[-1])
        self.assertRegex(out.name, r"^\d{8}T\d{6}Z\.json$")
        text = out.read_text()
        rec = json.loads(text)
        assert_private(self, text)
        self.assertEqual(rec["format"], "rah/build/1")
        self.assertEqual(rec["tool"], "riemann-at-home 1.1.0")
        self.assertEqual(rec["build_folder"], "unofficial")
        self.assertEqual(rec["modules_compiled"], 7)
        self.assertEqual(rec["busy_seconds"], 3600)
        self.assertEqual(rec["started"], "2026-11-21T15:26:31Z")
        self.assertFalse(rec["whole_proof"]); self.assertIsNone(rec["axioms"])
        self.assertEqual(set(rec["machine"]), {"os", "arch", "cpu", "cores"})
        bits = rah.decode_bitmap(rec["bitmap_b64"], len(mods))
        self.assertEqual(sum(bits), 7)
        lib = self.tmp / "p/.lake/build/lib/lean"
        h = hashlib.sha256()
        for m, on in zip(mods, bits):
            if on:
                h.update(hashlib.sha256((lib / (m.replace(".", "/") + ".olean")).read_bytes()).digest())
        self.assertEqual(rec["olean_digest"], h.hexdigest())
        self.assertRegex(rec["build_id"], r"^[0-9a-f]{16}$")
        # a second record reuses the hash cache and gives the same digest, and keeps the build_id
        r2 = cli("record", "--folder", self.tmp / "p", "--test-unofficial-folder", home=home)
        rec2 = json.loads(Path(r2.stdout.strip().splitlines()[-1]).read_text())
        self.assertEqual(rec2["olean_digest"], h.hexdigest())
        self.assertEqual(rec2["build_id"], rec["build_id"])
        self.assertNotEqual(rah.Ctx(type("A", (), {"folder": None, "logs": None})()).build_id(create=False), rec["build_id"])

    def test_record_whole_proof_reads_axioms(self):
        fake_folder(self.tmp / "p", n=4, compiled=(0, 1, 2, 3), olean_only=())
        home = self.tmp / "home"; (home / "logs").mkdir(parents=True)
        (home / "logs/axioms.log").write_text("'riemannHypothesis' depends on axioms: [propext, Classical.choice, Quot.sound]\n")
        r = cli("record", "--folder", self.tmp / "p", "--test-unofficial-folder", home=home)
        rec = json.loads(Path(r.stdout.strip().splitlines()[-1]).read_text())
        self.assertTrue(rec["whole_proof"]); self.assertEqual(rec["axioms"], rah.EXPECTED_AXIOMS)
        self.assertFalse(rec["final"])

    def test_finish_writes_final_record(self):
        fake_folder(self.tmp / "p")
        r = cli("finish", "--folder", self.tmp / "p", "--test-unofficial-folder", home=self.tmp / "h")
        out = Path([l for l in r.stdout.splitlines() if l.endswith(".json")][-1])
        rec = json.loads(out.read_text())
        self.assertTrue(rec["final"]); self.assertEqual(list(rec), rah.RECORD_KEYS)
        self.assertIn("submit it with", r.stdout)

    def test_record_refuses_other_folders_and_toolchains(self):
        fake_folder(self.tmp / "p")
        r = cli("record", "--folder", self.tmp / "p", home=self.tmp / "h", check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("fixed folder", r.stderr)
        (self.tmp / "p/lean-toolchain").write_text("leanprover/lean4:v4.33.0\n")
        r = cli("record", "--folder", self.tmp / "p", "--test-unofficial-folder", home=self.tmp / "h", check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("expected leanprover/lean4:v4.33.1", r.stderr)
        self.assertFalse((self.tmp / "h/records").exists() and any((self.tmp / "h/records").iterdir()))

    def test_prebuilt_folder_speed_and_started(self):
        """Resuming a folder that already had modules: speed counts only modules built while measured, and the
        record's `started` reaches back to the first finished module so the bot's rate check passes."""
        fake_folder(self.tmp / "p", n=40, compiled=tuple(range(30)), olean_only=())
        lib = self.tmp / "p/.lake/build/lib/lean"
        old = time.time() - 30 * 86400              # pre-existing modules finished a month ago
        for f in lib.rglob("*.trace"):
            os.utime(f, (old, old))
        home = self.tmp / "h"; logs = home / "logs"; logs.mkdir(parents=True)
        now = time.time(); I = rah.iso
        logs.joinpath("status.txt").write_text(f"START {I(now - 20)}\n")
        logs.joinpath("samples.txt").write_text(f"{I(now - 20)} modules=30\n")
        logs.joinpath("build.pid").write_text(str(os.getpid()))   # not a supervisor: counts as stopped
        st = cli("status", "--folder", self.tmp / "p", home=home).stdout
        self.assertNotIn("modules/hour", st, st)    # 30 old modules / 20 s must not show up as a speed
        ctx = rah.Ctx(type("A", (), {"folder": str(self.tmp / "p"), "logs": str(logs)})())
        self.assertIsNone(rah.rate_per_hour(ctx))
        # 6 new modules over the next 30 minutes -> 12/hour; old modules still don't count
        logs.joinpath("samples.txt").write_text(f"{I(now - 1800)} modules=30\n{I(now - 900)} modules=33\n{I(now)} modules=36\n")
        logs.joinpath("status.txt").write_text(f"START {I(now - 1800)}\n")
        self.assertAlmostEqual(rah.rate_per_hour(ctx), 12, places=3)
        self.assertEqual(rah.built_by_this_tool(ctx), 6)
        # an earlier session's samples are not mixed into the current one
        logs.joinpath("status.txt").write_text(f"START {I(now - 9000)}\nBUILD_EXIT=143 {I(now - 8000)}\nRESTART {I(now - 1800)}\n")
        logs.joinpath("samples.txt").write_text(f"{I(now - 8900)} modules=2\n{I(now - 8100)} modules=20\n"
                                                f"{I(now - 1800)} modules=30\n{I(now)} modules=36\n")
        self.assertAlmostEqual(rah.rate_per_hour(ctx), 12, places=3)
        self.assertEqual(rah.built_by_this_tool(ctx), 18 + 6)
        # record: started = first finished module (a month ago), so 30 modules / 30 days is a plausible rate
        logs.joinpath("status.txt").write_text(f"START {I(now - 20)}\n")
        r = cli("record", "--folder", self.tmp / "p", "--test-unofficial-folder", home=home)
        rec = json.loads(Path(r.stdout.strip().splitlines()[-1]).read_text())
        span = rah.parse_time(rec["recorded"]) - rah.parse_time(rec["started"])
        self.assertGreater(span, 29 * 86400)
        self.assertLess(rec["modules_compiled"] / (span / 3600), 6000, "bot would flag this honest first record")
        self.assertLessEqual(rec["busy_seconds"], span)

    def test_page_serves_from_own_files(self):
        fake_folder(self.tmp / "p")
        home = self.tmp / "h"; (home / "logs").mkdir(parents=True)
        (home / "logs/build.log").write_text("✔ [1/9] Built A.N00 (24s)\n✔ [2/9] Built A.B.M03 (805ms)\n"
                                             "✔ [3/9] Built A.N08 (1m 3s)\n✔ [4/9] Built A.N08:c.o (1s)\n")
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        env = {**os.environ, "RAH_HOME": str(home)}
        p = subprocess.Popen([sys.executable, "-I", str(SCRIPT), "page", "--folder", str(self.tmp / "p"), "--port", str(port)],
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            import urllib.request, urllib.error
            base = f"http://127.0.0.1:{port}"
            for _ in range(100):
                try:
                    urllib.request.urlopen(base + "/data.json", timeout=1); break
                except OSError:
                    time.sleep(0.1)
            html = urllib.request.urlopen(base + "/").read().decode()
            self.assertIn("Riemann@home", html); self.assertNotIn("rhcheck", html)
            d = json.loads(urllib.request.urlopen(base + "/data.json").read())
            self.assertEqual(d["terrain"]["n"], 20); self.assertEqual(d["terrain"]["local_compiled"], 7)
            self.assertEqual([x[0] for x in d["terrain"]["libraries"]], ["A"])
            live = json.loads(urllib.request.urlopen(base + "/live.json").read())
            self.assertEqual(live["compiled"], 7); self.assertFalse(live["running"])
            times = json.loads(urllib.request.urlopen(base + "/times.json").read())
            self.assertEqual(times, {"A.N00": 24.0, "A.B.M03": 0.8, "A.N08": 63.0})
            req = lambda hdr: urllib.request.Request(base + "/mode", data=b'{"mode": "paused"}', method="POST", headers=hdr)
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req({"Content-Type": "application/json"}))
            self.assertEqual(e.exception.code, 403)                 # no header: refused
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req({"X-Riemann-At-Home": "1", "Host": f"evil.example:{port}"}))
            self.assertEqual(e.exception.code, 403)                 # other host: refused
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req({"X-Riemann-At-Home": "1", "Host": f"localhost:{port}"}))
            self.assertEqual(e.exception.code, 409)                 # no build of ours running
        finally:
            p.terminate(); p.wait(5)

    def test_status_fake(self):
        fake_folder(self.tmp / "p")
        r = cli("status", "--folder", self.tmp / "p", home=self.tmp / "h")
        self.assertIn("7 / 175,187 modules", r.stdout)
        self.assertIn("not started yet", r.stdout)

    def test_build_refuses_when_disk_low(self):
        fake_folder(self.tmp / "p")
        env_cli = lambda *a: subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, a)], capture_output=True,
                                            text=True, env={**os.environ, "RAH_HOME": str(self.tmp / "h"),
                                                            "RAH_MIN_FREE_GB": "1e9"}, timeout=120)
        r = env_cli("build", "--folder", self.tmp / "p")
        self.assertEqual(r.returncode, 1); self.assertIn("GB free on the build disk", r.stderr)
        self.assertIn("record` and `submit` still work", r.stderr)
        # the background supervisor checks too, and stops before starting lake
        r = env_cli("_run", "--folder", self.tmp / "p", "--logs", self.tmp / "h/logs")
        self.assertEqual(r.returncode, 1)
        st = (self.tmp / "h/logs/status.txt").read_text()
        self.assertIn("DISK_LOW", st); self.assertIn("BUILD_EXIT=disk", st)
        self.assertFalse((self.tmp / "h/logs/build.log").exists())

    def _crashing_run(self, crashes: int):
        """The real supervisor (`_run`) over a fake lake whose `build` exits 139 (a Lean segfault) `crashes` times."""
        fake_folder(self.tmp / "p")
        elan = self.tmp / "elan"; (elan / "bin").mkdir(parents=True)
        n = self.tmp / "lake-builds"
        lake = elan / "bin/lake"
        lake.write_text(f"#!/bin/sh\nif [ \"$2\" = build ]; then echo x >> {n}; "
                        f"[ $(wc -l < {n}) -gt {crashes} ] && exit 0; "
                        "printf '\\342\\234\\224 [1/3] Built A.N00 (1s)\\n\\342\\234\\226 [2/3] Building Formalism.Big.Final (40s)\\n"
                        "error: Lean exited with code 139\\nerror: build failed\\n'; exit 1; fi\n"   # as lake: exit 1
                        "exit 0\n")
        lake.chmod(0o755)
        env = {**os.environ, "RAH_HOME": str(self.tmp / "h"), "ELAN_HOME": str(elan), "RAH_AUTOSUBMIT": "off",
               "RAH_BUILD_RETRY_WAIT": "0.2", "RAH_SAMPLE_SECONDS": "1"}
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "_run", "--folder", self.tmp / "p",
                            "--logs", self.tmp / "h/logs", "--target", "Main"], capture_output=True, text=True,
                           env=env, timeout=120)
        st = cli("status", "--folder", self.tmp / "p", home=self.tmp / "h", check=False).stdout
        return r, len(n.read_text().splitlines()), (self.tmp / "h/logs/status.txt").read_text(), st

    def test_build_crash_is_restarted(self):
        """A crashed lake build (a segfault near 99%) restarts by itself and finishes."""
        r, builds, events, st = self._crashing_run(crashes=2)
        self.assertEqual((r.returncode, builds), (0, 3), r.stderr)
        self.assertEqual(events.count("BUILD_CRASH=1"), 2); self.assertIn("BUILD_EXIT=0", events)
        log = (self.tmp / "h/logs/build.log").read_text()
        self.assertIn("restarting it", log)
        self.assertIn("failed: Formalism.Big.Final (Lean exit code 139)", log)
        self.assertNotIn("CRASHED", st)
        # which module, and Lean's own exit code (lake exits 1): kept for status and the build record
        got = json.loads((self.tmp / "h/logs/crashes.json").read_text())["crashes"]
        self.assertEqual([(c["module"], c["code"]) for c in got], [("Formalism.Big.Final", 139)] * 2)
        self.assertIn("crashes   2: Lean crashed on Formalism.Big.Final (exit code 139", st)

    def test_build_that_keeps_crashing_says_so(self):
        r, builds, events, st = self._crashing_run(crashes=99)
        self.assertEqual((r.returncode, builds), (1, 1 + rah.BUILD_RETRIES))
        self.assertIn("BUILD_GAVE_UP", events)
        self.assertIn("the build CRASHED and stopped after 3 automatic restarts", st)
        self.assertIn("run `riemann-at-home build` to continue", st)

    def test_submit_needs_gh_logged_in(self):
        repo = self.tmp / "repo"; repo.mkdir(); subprocess.run(["git", "init", "-q", str(repo)], check=True)
        rec = self.tmp / "rec.json"; self._valid_record(rec)
        nogh = self.tmp / "bin"; nogh.mkdir()
        os.symlink(shutil.which("git"), nogh / "git")
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "submit", "--repo", str(repo), "--record", str(rec),
                            "--login", "x-y", "--dry-run"], capture_output=True, text=True,
                           env={**os.environ, "RAH_HOME": str(self.tmp / "h"), "PATH": str(nogh)})
        self.assertEqual(r.returncode, 1); self.assertIn("`gh` tool is not installed", r.stderr)
        fake = self.tmp / "bin/gh"; fake.write_text("#!/bin/sh\necho 'You are not logged into any GitHub hosts.' >&2; exit 1\n")
        fake.chmod(0o755)
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "submit", "--repo", str(repo), "--record", str(rec),
                            "--login", "x-y", "--dry-run"], capture_output=True, text=True,
                           env={**os.environ, "RAH_HOME": str(self.tmp / "h"), "PATH": f"{nogh}:/bin:/usr/bin"})
        self.assertEqual(r.returncode, 1); self.assertIn("run `gh auth login` yourself", r.stderr)

    def test_name_display_clear_no_anonymous(self):
        fake_folder(self.tmp / "p")
        home = self.tmp / "h"
        rec_of = lambda: json.loads(Path(cli("record", "--folder", self.tmp / "p", "--test-unofficial-folder",
                                              home=home).stdout.strip().splitlines()[-1]).read_text())
        self.assertNotIn("display_name", rec_of())
        r = cli("name", "Ada L.", home=home)
        self.assertIn(rah.NAME_NOTICE, r.stdout)
        self.assertIn("This is only a label on the Riemann@home page. Your pull request on GitHub always shows your username", r.stdout)
        rec = rec_of(); self.assertEqual(rec["display_name"], "Ada L."); self.assertNotIn("anonymous", rec)
        self.assertEqual(list(rec)[:-1], rah.RECORD_KEYS)
        self.assertNotEqual(cli("name", "--anonymous", home=home, check=False).returncode, 0)   # not offered
        cli("name", "--clear", home=home)
        rec = rec_of(); self.assertNotIn("anonymous", rec); self.assertNotIn("display_name", rec)
        for bad in ("", "x" * 33, "Anonymous #3", "ANONYMOUSLY", "anonymous", "tab\there", "new\nline", "bell\x07", "zero\u200bwidth"):
            r = cli("name", bad, home=home, check=False)
            self.assertEqual(r.returncode, 1, repr(bad)); self.assertNotIn(rah.NAME_NOTICE, r.stdout)
        self.assertEqual(cli("name", "x" * 32, home=home).returncode, 0)
        self.assertEqual(cli("name", "Not anonymous", home=home).returncode, 0)
        self.assertEqual(cli("name", "Éloïse 数学", home=home).returncode, 0)

    def test_validate_optional_name_keys(self):
        rec = self._valid_record(self.tmp / "r.json")
        self.assertEqual(rah.validate_record({**rec, "display_name": "Ada"}), [])
        self.assertTrue(rah.validate_record({**rec, "anonymous": True}))     # not offered: the PR shows the username
        self.assertTrue(rah.validate_record({**rec, "anonymous": False}))
        self.assertTrue(rah.validate_record({**rec, "display_name": "x" * 33}))
        self.assertTrue(rah.validate_record({**rec, "display_name": "Ada", "anonymous": True}))
        rp = self.tmp / "rn.json"; rp.write_text(json.dumps({**rec, "display_name": "Ada"}))
        repo = self.tmp / "repo"; repo.mkdir(); subprocess.run(["git", "init", "-q", str(repo)], check=True)
        r = cli("submit", "--repo", repo, "--record", rp, "--login", "x-y", "--dry-run", "--no-gh-check", home=self.tmp / "h")
        self.assertIn("DRY RUN", r.stdout); self.assertFalse((repo / "submissions").exists())

    def test_pause_without_build(self):
        r = cli("pause", "--folder", self.tmp, home=self.tmp / "h", check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("no build is running", r.stderr)

    def _valid_record(self, path):
        bits = [i % 3 == 0 for i in range(rah.N_MODULES)]
        rec = {"format": rah.FORMAT, "tool": rah.TOOL, "archive_sha256": rah.ARCHIVE_SHA256,
               "toolchain": rah.TOOLCHAIN, "mathlib_rev": rah.MATHLIB_REV, "build_folder": str(REAL),
               "build_id": "0123456789abcdef",
               "machine": {"os": "Darwin 25.4.0", "arch": "arm64", "cpu": "Apple M5 Max", "cores": 18},
               "started": "2026-11-20T15:26:31Z", "recorded": "2026-11-21T09:10:02Z", "busy_seconds": 63000,
               "modules_compiled": sum(bits), "bitmap_b64": rah.encode_bitmap(bits), "olean_digest": "0" * 64,
               "whole_proof": False, "axioms": None, "final": False}
        path.write_text(json.dumps(rec))
        return rec

    def test_submit_dry_run_changes_nothing(self):
        repo = self.tmp / "repo"; repo.mkdir()
        g = ["git", "-C", str(repo)]
        subprocess.run(g + ["init", "-q", "-b", "main"], check=True)
        subprocess.run(g + ["remote", "add", "origin", "https://github.com/example-org/riemann-at-home.git"], check=True)
        subprocess.run(g + ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q",
                            "--allow-empty", "-m", "init"], check=True)
        before = subprocess.run(g + ["log", "--all", "--format=%H %D"], capture_output=True, text=True).stdout
        rec = self.tmp / "rec.json"; self._valid_record(rec)
        r = cli("submit", "--repo", repo, "--record", rec, "--login", "test-volunteer", "--dry-run", "--no-gh-check", home=self.tmp / "h")
        self.assertIn("DRY RUN", r.stdout)
        self.assertIn("as:     submissions/test-volunteer/0123456789abcdef.json on branch rah/0123456789abcdef", r.stdout)
        self.assertIn("gh pr create --repo example-org/riemann-at-home --head '<example-org or test-volunteer>:rah/0123456789abcdef'", r.stdout)
        self.assertIn("HEAD:refs/heads/rah/0123456789abcdef", r.stdout)
        # once the PR is open, later submits only commit + push to the same branch (no new PR)
        (self.tmp / "h").mkdir(exist_ok=True)
        (self.tmp / "h/config.json").write_text(json.dumps({"pr": {"build_id": "0123456789abcdef", "state": "open"}}))
        r = cli("submit", "--repo", repo, "--record", rec, "--login", "test-volunteer", "--dry-run", "--no-gh-check", home=self.tmp / "h")
        self.assertIn("update the open PR", r.stdout)
        self.assertNotIn("gh pr create", r.stdout)
        self.assertIn("checkout -B rah/0123456789abcdef origin/main", r.stdout); self.assertIn("push --force", r.stdout)
        self.assertFalse((repo / "submissions").exists())
        self.assertEqual(subprocess.run(g + ["status", "--porcelain"], capture_output=True, text=True).stdout, "")
        self.assertEqual(subprocess.run(g + ["log", "--all", "--format=%H %D"], capture_output=True, text=True).stdout, before)
        r = cli("submit", "--repo", repo, "--record", rec, "--login", "test-volunteer", "--no-gh-check", home=self.tmp / "h", check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("only for --dry-run", r.stderr)   # never a user's checkout
        self.assertFalse((repo / "submissions").exists())

    def test_validate_matches_bot_rules(self):
        rec = self._valid_record(self.tmp / "r.json")
        self.assertEqual(rah.validate_record(rec), [])
        bad = [("recorded", "2099-01-01T00:00:00Z", "recorded <= now"), ("busy_seconds", 10 ** 6, "busy_seconds"),
               ("tool", "riemann-at-home 1.0.1", "tool"), ("build_folder", "/home/x/lean", "fixed folder"),
               ("olean_digest", "A" * 64, "lowercase"), ("extra", 1, "keys"),
               ("whole_proof", True, "whole_proof"), ("build_id", "XYZ", "build_id"), ("final", None, "final")]
        for k, v, msg in bad:
            d = dict(rec); d[k] = v
            self.assertTrue(any(msg in e for e in rah.validate_record(d)), (k, rah.validate_record(d)))
        d = dict(rec); d["machine"] = {**rec["machine"], "cores": "18"}
        self.assertTrue(rah.validate_record(d))
        raw = bytearray(gzip.decompress(base64.b64decode(rec["bitmap_b64"]))); raw[-1] |= 0x80   # bit past N-1
        d = dict(rec); d["bitmap_b64"] = base64.b64encode(gzip.compress(bytes(raw), mtime=0)).decode()
        self.assertTrue(any("past module" in e for e in rah.validate_record(d)))
        d = dict(rec); d["bitmap_b64"] = rah.encode_bitmap([False] * rah.N_MODULES); d["modules_compiled"] = 0
        self.assertTrue(any("empty" in e for e in rah.validate_record(d)))

    def _repo_with_main(self, files: dict):
        """A local 'upstream' with a main branch holding `files`, and a clone of it (origin/main = that)."""
        up = self.tmp / "upstream"; up.mkdir()
        g = ["git", "-C", str(up)]; idn = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run(g + ["init", "-q", "-b", "main"], check=True)
        for rel, text in files.items():
            (up / rel).parent.mkdir(parents=True, exist_ok=True); (up / rel).write_text(text)
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + idn + ["commit", "-q", "--allow-empty", "-m", "main"], check=True)
        clone = self.tmp / "clone"
        subprocess.run(["git", "clone", "-q", str(up), str(clone)], check=True)
        return clone

    def test_submit_one_pr_for_life_nothing_after_merge(self):
        rec = self.tmp / "rec.json"; d = self._valid_record(rec)
        rel = "submissions/test-volunteer/0123456789abcdef.json"
        sub = lambda clone: cli("submit", "--repo", clone, "--record", rec, "--login", "test-volunteer", "--dry-run",
                                "--no-gh-check", home=self.tmp / "h", check=False)
        # nothing on main yet: open the one PR, on branch rah/<build_id> (no follow-up branches exist)
        clone = self._repo_with_main({})
        r = sub(clone)
        self.assertIn("open this build's one PR", r.stdout); self.assertIn("checkout -B rah/0123456789abcdef origin/main", r.stdout)
        self.assertNotRegex(r.stdout, r"rah/0123456789abcdef-\d")
        shutil.rmtree(self.tmp / "upstream"); shutil.rmtree(clone)
        # merged (only happens when whole or final): nothing more is submitted, and the clone is untouched
        for merged in ({**d, "final": True}, {**d, "whole_proof": True, "axioms": rah.EXPECTED_AXIOMS}):
            clone = self._repo_with_main({rel: json.dumps(merged)})
            head = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
            r = sub(clone)
            self.assertEqual(r.returncode, 1); self.assertIn("nothing more is submitted", r.stderr)
            self.assertNotIn("would run", r.stdout)
            self.assertEqual(subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True).stdout, head)
            shutil.rmtree(self.tmp / "upstream"); shutil.rmtree(clone)
        # a final record already sent from this computer (PR still open): also nothing more
        clone = self._repo_with_main({})
        (self.tmp / "h").mkdir(exist_ok=True)
        (self.tmp / "h/config.json").write_text(json.dumps({"pr": {"build_id": "0123456789abcdef", "state": "open",
                                                                   "final_sent": True}}))
        r = sub(clone)
        self.assertEqual(r.returncode, 1); self.assertIn("final record was already sent", r.stderr)

    def test_submit_rejects_bad_record(self):
        repo = self.tmp / "repo"; repo.mkdir(); subprocess.run(["git", "init", "-q", str(repo)], check=True)
        rec = self.tmp / "rec.json"; d = self._valid_record(rec)
        d["modules_compiled"] += 1; rec.write_text(json.dumps(d))
        r = cli("submit", "--repo", repo, "--record", rec, "--login", "x-y", "--dry-run", "--no-gh-check", home=self.tmp / "h", check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("popcount", r.stderr)


STATEMENT = ("Riemann@home: a joint statement from independent builders. We, the undersigned, each built an "
    "AI-assisted Lean proof of the Riemann Hypothesis on our own computers, from the official sources with the pinned "
    "Lean toolchain and Mathlib, and confirmed that its main theorems depend only on Lean's three standard axioms "
    "(propext, Classical.choice, Quot.sound). Each signature carries badges for exactly what that signatory did: "
    "17M BUILT: compiled all 175,187 modules of Levent Alpöge's proof (released November 20, 2026; archive sha256 "
    "9631b4f0…c7fc, Lean 4.33.1). 300K BUILT: compiled all 803 modules of the 300K-line proof of the Riemann "
    "Hypothesis and Dirichlet GRH (lsernau/grh-lean at 72fead10…7207, Lean 4.35.0). EXPORT REPRODUCED: exported the "
    "compiled 17M proof and reproduced the same raw export file as other independent builders (sha256 5ea74b91…244e). "
    "RE-CHECKED: re-checked that export with an independent checker written separately from Lean's own kernel, named "
    "on the badge. We do not certify the mathematics. That the theorems state the Riemann Hypothesis (and Dirichlet "
    "GRH) as intended was checked by the Lean and Mathlib communities. Each name is tied to that builder's GitHub "
    "account and published build record. We join the Lean and Mathlib communities in congratulating Levent Alpöge.")
EXPORT_CHUNK = b'{"marker":"EXPORT-BYTES-MUST-NOT-HIT-DISK"}\n'


class Levels(unittest.TestCase):
    """export / recheck / sign with stand-in exporter and checkers (nothing real is exported or checked)."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=TMP, prefix="t-"))
        self.folder = self.tmp / "p"
        fake_folder(self.folder, n=4, compiled=(0, 1, 2, 3), olean_only=())
        self.home = self.tmp / "h"; (self.home / "logs").mkdir(parents=True)
        (self.home / "logs/axioms.log").write_text(
            "'riemannHypothesis' depends on axioms: [propext, Classical.choice, Quot.sound]\n")
        self.export = EXPORT_CHUNK * 300_000                    # ~13 MB, streamed in many chunks
        self.sha = hashlib.sha256(self.export).hexdigest()
        ex = self.tmp / "bin/fake-lean4export"; ex.parent.mkdir()
        ex.write_text(f"#!{sys.executable} -I\nimport os, sys\nassert sys.argv[1:] == ['Main', '--'] + {rah.EXPORT_TARGETS!r}, sys.argv\n"
                      "print('cwd', os.getcwd(), file=sys.stderr)\n"
                      f"chunk = {EXPORT_CHUNK!r}\n"
                      "for _ in range(300_000): sys.stdout.buffer.write(chunk)\n")
        ex.chmod(0o755); self.exporter = ex
        self.old_env = dict(os.environ)
        os.environ["RAH_HOME"] = str(self.home)

    def tearDown(self):
        os.environ.clear(); os.environ.update(self.old_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def main(self, *args, stdin="", ref=True):
        """Run the CLI in-process; with ref=True the stand-in export counts as the reference."""
        import contextlib, io, builtins
        from unittest import mock
        out, err = io.StringIO(), io.StringIO()
        answers = iter(stdin.splitlines())
        def fake_input(prompt=""):
            print(prompt, end="")
            try:
                return next(answers)
            except StopIteration:
                raise EOFError
        patches = [mock.patch.object(builtins, "input", fake_input)]
        if ref:
            patches += [mock.patch.object(rah, "EXPORT_SHA256", self.sha), mock.patch.object(rah, "EXPORT_BYTES", len(self.export))]
        with contextlib.ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            st.enter_context(contextlib.redirect_stdout(out)); st.enter_context(contextlib.redirect_stderr(err))
            unoff = [] if args[0] == "status" else ["--test-unofficial-folder"]
            code = rah.main([*map(str, args), "--folder", str(self.folder), *unoff])
        return code, out.getvalue(), err.getvalue()

    def latest_record(self):
        return json.loads(sorted((self.home / "records").glob("*.json"))[-1].read_text())

    def assert_export_not_on_disk(self):
        for root, _, files in os.walk(self.tmp):
            for f in files:
                p = Path(root) / f
                if p.stat().st_size >= len(EXPORT_CHUNK) and b"EXPORT-BYTES-MUST-NOT-HIT-DISK" in p.read_bytes() \
                        and p != self.exporter:
                    self.fail(f"export bytes written to {p}")

    def test_statement_text_from_readme(self):
        self.assertEqual(rah.statement_text(), STATEMENT)

    def test_export_refuses_partial_build_and_failed_axioms(self):
        shutil.rmtree(self.folder); fake_folder(self.folder, n=4, compiled=(0, 1), olean_only=())
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 1); self.assertIn("needs the whole build first: 2 / ", err)
        shutil.rmtree(self.folder); fake_folder(self.folder, n=4, compiled=(0, 1, 2, 3), olean_only=())
        (self.home / "logs/axioms.log").write_text("'riemannHypothesis' depends on axioms: [propext, sorryAx]\n")
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 1); self.assertIn("passing axiom check", err)

    def test_export_mismatch_is_unverified_and_not_recorded(self):
        code, out, err = self.main("export", "--exporter", self.exporter, ref=False)
        self.assertEqual(code, 1)
        self.assertIn(f"export sha256 {self.sha}", out); self.assertIn(f"export bytes  {len(self.export):,}", out)
        self.assertIn("other builders have reproduced the reference with this tool", out)
        self.assertIn(f"cwd {self.folder}", (self.home / "logs/export.log").read_text())   # ran in the build folder
        self.assert_export_not_on_disk()
        code, _, _ = self.main("record", ref=False)
        rec = self.latest_record()
        self.assertNotIn("export_sha256", rec); self.assertEqual(rah.validate_levels(rec), [])
        # one joint statement since 2026-11-27: a whole build with the three axioms can sign without the export
        code, out, err = self.main("sign", stdin="y\n", ref=False)
        self.assertEqual(code, 0, err)
        rec = self.latest_record()
        self.assertIs(rec.get("sign_statement"), True); self.assertNotIn("export_sha256", rec)
        self.assertEqual(rah.record_level(rec), 1); self.assertEqual(rah.validate_levels(rec), [])

    def test_export_progress_shown_and_recorded(self):
        """1.1.0: a live progress line, peak memory, and export_progress in records (the leaderboard's gold bar)."""
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 0, err)
        self.assertIn("EXPORTING 100%", err); self.assertIn("export matches the reference ✓", out)
        p = json.loads((self.home / "export-progress.json").read_text())
        self.assertTrue(p["done"]); self.assertEqual(p["bytes"], len(self.export)); self.assertIsNone(p["left_seconds"])
        self.assertGreater(p["peak_memory_gb"], 0)                 # the stand-in exporter's own memory was measured
        rec = self.latest_record()
        ep = rec["export_progress"]
        self.assertEqual(sorted(ep), sorted(rah.EXPORT_PROGRESS_FIELDS)); self.assertTrue(ep["done"])
        from unittest import mock
        with mock.patch.object(rah, "EXPORT_SHA256", self.sha):
            self.assertEqual([e for e in rah.validate_record(rec) if e.startswith("keys")], [])   # export_progress is an allowed key
        # an export that stopped half way and was not heard from for 30 min drops out of records
        p.update(done=False, bytes=1000, left_seconds=60, updated=int(time.time()) - rah.EXPORT_STALE - 5)
        (self.home / "export-progress.json").write_text(json.dumps(p))
        self.main("record"); self.assertNotIn("export_progress", self.latest_record())
        p["updated"] = int(time.time())
        (self.home / "export-progress.json").write_text(json.dumps(p))
        self.main("record"); self.assertEqual(self.latest_record()["export_progress"]["bytes"], 1000)

    def test_export_quiet_tail_keeps_progress_moving(self):
        """2026-11-23: 2.4 MB from the end the exporter went quiet and the screen and the PR froze, because the
        tool waited for whole 1 MB pieces. Now partial output counts at once and progress ticks during the silence."""
        from unittest import mock
        head, tail = EXPORT_CHUNK * 75_000, EXPORT_CHUNK * 5_000          # 3.3 MB, then a pause, then 0.2 MB
        ex = self.tmp / "bin/quiet-lean4export"
        ex.write_text(f"#!{sys.executable} -I\nimport sys, time\nchunk = {EXPORT_CHUNK!r}\n"
                      "sys.stdout.buffer.write(chunk * 75_000); sys.stdout.buffer.flush()\n"
                      "time.sleep(4)\nsys.stdout.buffer.write(chunk * 5_000)\n")
        ex.chmod(0o755)
        seen, stop = [], threading.Event()
        pf = self.home / "export-progress.json"
        def watch():
            while not stop.is_set():
                try:
                    seen.append(json.loads(pf.read_text())["bytes"])
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(0.2)
        t = threading.Thread(target=watch); t.start()
        try:
            with mock.patch.object(rah, "EXPORT_QUIET_SECONDS", 1):
                self.export = head + tail; self.sha = hashlib.sha256(self.export).hexdigest()
                code, out, err = self.main("export", "--exporter", ex)
        finally:
            stop.set(); t.join()
        self.assertEqual(code, 0, err)
        self.assertGreaterEqual(seen.count(len(head)), 5, "progress must show the partial piece and keep ticking")
        self.assertIn("no output for", err); self.assertIn("the exporter is still running", err)
        self.assertIn("export matches the reference ✓", out)

    def test_export_time_left_counts_from_first_output(self):
        """Issue #9: lean4export loads the proof silently first; the old estimate divided by that silence too, so
        right after output began it said many times too long. The speed now counts from the first byte."""
        from unittest import mock
        half = EXPORT_CHUNK * 40_000
        ex = self.tmp / "bin/slow-start-lean4export"
        ex.write_text(f"#!{sys.executable} -I\nimport sys, time\nchunk = {EXPORT_CHUNK!r}\n"
                      "time.sleep(6)\nsys.stdout.buffer.write(chunk * 40_000); sys.stdout.buffer.flush()\n"
                      "time.sleep(3)\nsys.stdout.buffer.write(chunk * 40_000)\n")
        ex.chmod(0o755)
        seen, stop = [], threading.Event()
        pf = self.home / "export-progress.json"
        def watch():
            while not stop.is_set():
                try:
                    p = json.loads(pf.read_text())
                    if p["bytes"] == len(half) and p["left_seconds"] is not None:
                        seen.append(p["left_seconds"])
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(0.2)
        t = threading.Thread(target=watch); t.start()
        try:
            with mock.patch.object(rah, "EXPORT_ETA_AFTER", 1, create=True):
                self.export = half * 2; self.sha = hashlib.sha256(self.export).hexdigest()
                code, out, err = self.main("export", "--exporter", ex)
        finally:
            stop.set(); t.join()
        self.assertEqual(code, 0, err)
        self.assertTrue(seen, "an estimate must show once output is flowing")
        self.assertLessEqual(max(seen), 4, f"half done after ~3 s of output: about 3 s left, not {max(seen)} s")

    def test_export_write_error_stops_the_exporter(self):
        """Review, 2026-11-23: if saving the export fails (disk full), the exporter must be stopped; it used to be
        left blocked on a full pipe while the tool waited for it forever."""
        import argparse
        ex = self.tmp / "bin/endless-lean4export"
        ex.write_text(f"#!{sys.executable} -I\nimport sys\nb = b'x' * (1 << 20)\nwhile True: sys.stdout.buffer.write(b)\n")
        ex.chmod(0o755)
        class Full:
            def __init__(self): self.n = 0
            def write(self, b):
                self.n += 1
                if self.n > 3: raise OSError(28, "No space left on device")
        ctx = types.SimpleNamespace(folder=self.folder)
        box = {}
        def go():
            try:
                rah.stream_export(ctx, [str(ex)], self.tmp / "x.log", sink=Full())
            except OSError as e:
                box["err"] = e
        with contextlib.redirect_stderr(io.StringIO()):
            th = threading.Thread(target=go, daemon=True); th.start(); th.join(30)
        self.assertFalse(th.is_alive(), "stream_export hung after a write error")
        self.assertEqual(box["err"].errno, 28)
        self.assertEqual(subprocess.run(["pgrep", "-f", str(ex)], capture_output=True).stdout, b"", "exporter still running")

    def test_export_memory_warning(self):
        """Before exporting, say plainly if this computer's memory is tight (a 125 GiB run crawled at the end)."""
        self.assertIsNone(rah.export_memory_warning(256)); self.assertIsNone(rah.export_memory_warning(0))
        mid, low = rah.export_memory_warning(125), rah.export_memory_warning(64)
        self.assertIn("125 GB", mid); self.assertIn("should work", mid)
        self.assertIn("64 GB", low); self.assertIn("may never finish", low); self.assertIn("Level 2 is optional", low)
        for ram, expect in (("125", "should work"), ("256", None)):
            os.environ["RAH_TEST_RAM_GB"] = ram
            code, out, err = self.main("export", "--exporter", self.exporter)
            self.assertEqual(code, 0, err)
            if expect:
                self.assertIn(expect, err)
            else:
                self.assertNotIn("warning: this computer has", err)

    def test_export_progress_on_mismatch_is_done_without_level2(self):
        code, out, err = self.main("export", "--exporter", self.exporter, ref=False)
        self.assertEqual(code, 1)
        self.main("record", ref=False); rec = self.latest_record()
        self.assertTrue(rec["export_progress"]["done"]); self.assertNotIn("export_sha256", rec)   # page: "differs"

    def test_exporter_built_with_the_proofs_toolchain(self):
        """Issue #14: lean4export v4.33.0 pins Lean v4.33.0, which can't read this v4.33.1 build's .olean files
        ("incompatible header"). The tool must build it with TOOLCHAIN, in a folder named for that toolchain."""
        from unittest import mock
        import argparse
        calls = []
        def fake_run(cmd, cwd=None, env=None, **kw):
            calls.append(list(map(str, cmd)))
            if cmd[:2] == ["git", "clone"]:
                d = Path(cmd[-1]); d.mkdir(parents=True); (d / "lean-toolchain").write_text("leanprover/lean4:v4.33.0\n")
            elif "rev-parse" in map(str, cmd):
                return subprocess.CompletedProcess(cmd, 0, rah.EXPORTER_COMMIT + "\n")
            elif str(cmd[-1]) == "build":
                exe = Path(cwd) / ".lake/build/bin/lean4export"; exe.parent.mkdir(parents=True); exe.write_text("")
            return subprocess.CompletedProcess(cmd, 0)
        ctx = rah.Ctx(argparse.Namespace(folder=str(self.folder), logs=None))
        with mock.patch.object(rah, "run", fake_run), mock.patch.object(rah, "ensure_elan", lambda: "elan"), \
                mock.patch.object(rah, "toolchain_installed", lambda e, t: True), mock.patch.object(rah, "which", lambda x: x), \
                contextlib.redirect_stdout(io.StringIO()):
            cmd = rah.exporter_command(ctx, argparse.Namespace(exporter=None))
        src = Path(cmd[2]).parents[3]
        self.assertEqual(src.name, f"lean4export-{rah.EXPORTER_TAG}-lean-{rah.TOOLCHAIN.split(':')[-1]}")
        self.assertEqual((src / "lean-toolchain").read_text().strip(), rah.TOOLCHAIN)
        # the reference command: lean4export Main -- $(cat export-targets.txt)  (issue #15)
        self.assertEqual(cmd[3:], ["Main", "--", *rah.EXPORT_TARGETS])
        self.assertIn("riemannHypothesis", rah.EXPORT_TARGETS); self.assertEqual(len(rah.EXPORT_TARGETS), 38)
        self.assertEqual(hashlib.sha256(rah.EXPORT_TARGETS_TXT.encode()).hexdigest(), rah.EXPORT_TARGETS_SHA256)

    def test_export_check_fast(self):
        """`export --check` (and the 5-minute check in every build): ok only if the exporter reads this Lean version."""
        def fake(name, body):
            f = self.tmp / f"bin/{name}"
            f.write_text(f"#!{sys.executable} -I\nimport sys, json\n{body}\n"); f.chmod(0o755); return f
        meta = lambda v: f"print(json.dumps({{'meta': {{'lean': {{'version': '{v}'}}}}}})); print('{{}}' * 3)"
        ok = fake("ok-export", meta(rah.TOOLCHAIN.rsplit(":v", 1)[-1]))
        code, out, err = self.main("export", "--check", "--exporter", ok)
        self.assertEqual(code, 0, err); self.assertIn("export check ok", out)
        self.assertTrue(json.loads((self.home / "export-check.json").read_text())["ok"])
        old = fake("old-export", "print(\"uncaught exception: failed to read file 'x.olean', incompatible header\", "
                                 "file=sys.stderr); sys.exit(1)")
        code, out, err = self.main("export", "--check", "--exporter", old)
        self.assertEqual(code, 1); self.assertIn("incompatible header", err)
        wrong = fake("wrong-export", meta("4.33.0"))
        code, out, err = self.main("export", "--check", "--exporter", wrong)
        self.assertEqual(code, 1); self.assertIn("expected " + rah.TOOLCHAIN.rsplit(":v", 1)[-1], err)
        code, out, err = self.main("status")
        self.assertIn("export    check FAILED", out)

    def test_sign_in_advance_takes_effect_only_on_a_match(self):
        """Setup can ask now (owner, 2026-11-23): sign the joint statement if the export later matches."""
        from unittest import mock
        code, out, err = self.main("sign", "--when-done", stdin="y\n")
        self.assertEqual(code, 0, err); self.assertIn("Riemann@home: a joint statement", out)
        self.assertIn("Nothing is signed before then", out)
        code, out, err = self.main("status")
        self.assertIn("statement signed in advance", out)
        # a mismatching export (other bytes): no signature
        other = self.tmp / "bin/other-export"
        other.write_text(f"#!{sys.executable} -I\nimport sys\nsys.stdout.buffer.write(b'not the proof')\n"); other.chmod(0o755)
        code, out, err = self.main("export", "--exporter", other, ref=False)
        self.assertEqual(code, 1); self.main("record", ref=False)
        self.assertNotIn("sign_statement", self.latest_record())
        # a reworded statement needs a new yes
        with mock.patch.object(rah, "statement_text", lambda proof="17m": "Riemann@home: a joint statement, reworded."):
            ctx = rah.Ctx(type("A", (), {"folder": str(self.folder), "logs": None})())
            self.assertIsNone(rah.sign_when_done(ctx))
        # the matching export signs, and says so
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 0, err); self.assertIn("You signed this statement. To withdraw: riemann-at-home sign --cancel", out)
        self.assertIn("Riemann@home: a joint statement from independent builders", out.split("export matches")[1])
        self.assertIn("You're a validator! Tell people", out); self.assertIn("https://x.com/intent/tweet?text=", out)
        self.assertIs(self.latest_record().get("sign_statement"), True)
        # and it can be taken back
        code, out, err = self.main("sign", "--cancel")
        self.assertEqual(code, 0, err); self.assertIn("signature withdrawn", out)
        self.assertIs(self.latest_record().get("sign_statement"), False)     # the opt-out is in the record

    def test_share_nudge_links_back_to_the_site(self):
        """Setup and signing invite a post that links to the site, so others join (owner, 2026-11-23)."""
        import contextlib, io
        from urllib.parse import quote
        ctx = rah.Ctx(type("A", (), {"folder": str(self.folder), "logs": None})())
        ctx.set_conf(consent={"agreed": "2026-11-23T00:00:00Z", "login": "octo-cat"})
        mine = rah.SITE_URL + "#@octo-cat"
        for kind, head in (("joined", "You're validating!"), ("signed", "You're a validator!")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rah.share_nudge(ctx, kind)
            o = buf.getvalue()
            self.assertIn(head, o); self.assertIn(rah.SHARE_TEXT[kind] + " " + mine, o)
            self.assertIn("url=" + quote(mine, safe=""), o)
            self.assertIn("bsky.app/intent/compose?text=", o); self.assertIn("linkedin.com/sharing", o)
            self.assertNotIn(" ", o.split("x.com/intent/tweet?text=")[1].split()[0])   # one clickable link
        # a chosen display name is the link, and the login stays out of it
        ctx.set_conf(display={"display_name": "Ada L"})
        self.assertEqual(rah.my_link(ctx), rah.SITE_URL + "#@Ada%20L")
        # a mismatching export never invites a "signed" post
        code, out, err = self.main("sign", "--when-done", stdin="y\n")
        code, out, err = self.main("export", "--exporter", self.exporter, ref=False)
        self.assertEqual(code, 1); self.assertNotIn("You're a validator", out)

    def test_crash_report_rides_on_the_record(self):
        ctx = rah.Ctx(type("A", (), {"folder": str(self.folder), "logs": None})())
        ctx.logs.mkdir(parents=True, exist_ok=True)
        crash = {"module": "Formalism.Big.Final", "code": 139, "at": "2026-11-23T12:00:00Z"}
        (ctx.logs / "crashes.json").write_text(json.dumps({"build_id": ctx.build_id(), "crashes": [crash]}))
        code, out, err = self.main("record")
        self.assertEqual(code, 0, err); self.assertEqual(self.latest_record()["crashes"], [crash])
        msg = f"crashes must be at most {rah.CRASHES_MAX} {{module, code, at}} entries"
        self.assertIn(msg, rah.validate_record({**self.latest_record(), "crashes": [{**crash, "code": "139"}]}))
        self.assertNotIn(msg, rah.validate_record(self.latest_record()))
        # another build's crashes are not this build's
        (ctx.logs / "crashes.json").write_text(json.dumps({"build_id": "0" * 16, "crashes": [crash]}))
        self.main("record"); self.assertNotIn("crashes", self.latest_record())

    def test_crashed_modules_from_lake_output(self):
        log = ("✔ [10/20] Built A.Ok (2s)\n✖ [11/20] Building A.Crash (9s)\ntrace: .> lean A/Crash.lean\n"
               "error: Lean exited with code 139\n✖ [12/20] Building A.Error (1s)\nerror: A/Error.lean:3:0: unknown\n"
               "✔ [13/20] Built A.Ok2 (1s)\nerror: build failed\n")
        self.assertEqual(rah.crashed_modules(log), [("A.Crash", 139)])   # an ordinary error is not a crash

    def test_setup_question_without_terminal_only_prints(self):
        import contextlib, io
        from unittest import mock
        ctx = rah.Ctx(type("A", (), {"folder": str(self.folder), "logs": None})())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch("sys.stdin", io.StringIO("y\n")):
            rah.ask_sign_when_done(ctx)
        self.assertIn("riemann-at-home sign --when-done", buf.getvalue())
        self.assertIn("Riemann@home: a joint statement", buf.getvalue())
        self.assertIsNone(rah.sign_when_done(ctx))         # an assistant can't answer for the person

    def test_export_match_recheck_sign(self):
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 0, err); self.assertIn("Level 2: matches the reference", out)
        self.assertNotIn("unverified", out)
        self.assert_export_not_on_disk()
        rec = self.latest_record()
        self.assertEqual((rec["export_sha256"], rec["export_bytes"]), (self.sha, len(self.export)))
        from unittest import mock
        with mock.patch.object(rah, "EXPORT_SHA256", self.sha):
            self.assertEqual(rah.validate_levels(rec), []); self.assertEqual(rah.record_level(rec), 2)
        # Level 3: memory is checked first, before anything else
        os.environ["RAH_TEST_RAM_GB"] = "64"
        code, out, err = self.main("recheck", "--nanoda", "--checker", "/nonexistent")
        self.assertEqual(code, 1); self.assertIn("nanoda needs about 100 GB of memory; this computer has 64 GB", err)
        os.environ["RAH_TEST_RAM_GB"] = "40"
        code, out, err = self.main("recheck", "--con-leche", "--checker", "/nonexistent")
        self.assertEqual(code, 1); self.assertIn("con-leche needs about 50 GB", err)
        os.environ["RAH_TEST_RAM_GB"] = "128"
        # nanoda_bin takes only a JSON config naming the export file (no stdin, no --version)
        chk = self.tmp / "bin/fake-nanoda"
        chk.write_text(f"#!{sys.executable} -I\nimport hashlib, json, sys\n"
                       "cfg = json.load(open(sys.argv[1])); assert sys.argv[2:] == [], sys.argv\n"
                       "assert cfg['use_stdin'] is False and cfg['permitted_axioms'], cfg\n"
                       f"ok = hashlib.sha256(open(cfg['export_file_path'], 'rb').read()).hexdigest() == {self.sha!r}\n"
                       "print('checked config', ok); sys.exit(0 if ok else 3)\n")
        chk.chmod(0o755)
        code, out, err = self.main("recheck", "--nanoda", "--checker", chk, "--exporter", self.exporter)
        self.assertEqual(code, 0, err + out); self.assertIn("nanoda: ACCEPT", out)
        self.assertIn("checked config True", (self.home / "logs/recheck-nanoda.log").read_text())
        saved = self.home / "export" / f"proof-{self.sha[:16]}.ndjson"
        self.assertEqual(saved.read_bytes(), self.export)             # saved once, whole, for the checkers
        self.assertFalse(list(saved.parent.glob("*.partial")))
        self.assertIn("rm ", out); self.assertIn("recheck --con-leche` can reuse it", out)
        rec = self.latest_record()
        self.assertEqual([(c["name"], c["version"], c["result"]) for c in rec["checkers"]], [("nanoda", "unknown", "accept")])
        self.assertIsInstance(rec["checkers"][0]["seconds"], int)
        with mock.patch.object(rah, "EXPORT_SHA256", self.sha):
            self.assertEqual(rah.validate_levels(rec), []); self.assertEqual(rah.record_level(rec), 3)
        code, out, err = self.main("recheck", "--nanoda", "--checker", chk, "--checker-args=-x", "--exporter", self.exporter)
        self.assertEqual(code, 1); self.assertIn("nanoda takes no command-line arguments", err)
        # con-leche takes the file as its last argument; it reuses the saved export (no second export run)
        runs = (self.home / "logs/export.log").read_text().count("cwd ")
        bad = self.tmp / "bin/fake-con-leche"
        bad.write_text(f"#!{sys.executable} -I\nimport sys\n"
                       "if sys.argv[1:] == ['--version']: print('con-leche 0.1-test'); sys.exit(0)\n"
                       f"assert sys.argv[-2:] == ['--', {str(saved)!r}], sys.argv\n"
                       "print('args', sys.argv[1:-2], len(open(sys.argv[-1], 'rb').read())); sys.exit(1)\n")
        bad.chmod(0o755)
        os.environ["RAH_TEST_RAM_GB"] = "64"
        code, out, err = self.main("recheck", "--con-leche", "--checker", bad, "--checker-args=--jobs=2",
                                   "--exporter", self.exporter)
        self.assertEqual(code, 1); self.assertIn("con-leche: REJECT", out); self.assertIn("using the saved export", out)
        self.assertIn(f"args ['--jobs=2'] {len(self.export)}", (self.home / "logs/recheck-con-leche.log").read_text())
        self.assertEqual((self.home / "logs/export.log").read_text().count("cwd "), runs, "the export must not run again")
        self.assertEqual({(c["name"], c["version"], c["result"]) for c in self.latest_record()["checkers"]},
                         {("nanoda", "unknown", "accept"), ("con-leche", "con-leche 0.1-test", "reject")})
        # a damaged saved export is made again, never handed to a checker
        saved.write_bytes(b"x" * len(self.export))
        code, out, err = self.main("recheck", "--con-leche", "--checker", bad, "--exporter", self.exporter)
        self.assertIn("is not the reference export; making it again", out)
        self.assertEqual(saved.read_bytes(), self.export)
        # not enough disk: says so, and nothing is left behind
        saved.unlink()
        with mock.patch.object(rah.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(10**12, 10**12 - 1, 1)):
            code, out, err = self.main("recheck", "--con-leche", "--checker", bad, "--exporter", self.exporter)
        self.assertEqual(code, 1); self.assertIn("Free some disk", err); self.assertFalse(saved.exists())
        # an export that is not the reference is refused and its partial file removed
        code, out, err = self.main("recheck", "--con-leche", "--checker", bad, "--exporter", self.exporter, ref=False)
        self.assertEqual(code, 1); self.assertFalse(saved.exists())
        self.assertFalse(list(saved.parent.glob("*.partial")))
        # a stale .partial from a killed run is removed before free disk is measured (it is our own space)
        stale = saved.with_name(saved.name + ".partial"); stale.write_bytes(b"left over")
        real_du = shutil.disk_usage
        def du(p):
            self.assertFalse(stale.exists(), "stale .partial must be gone before measuring free disk")
            return real_du(p)
        with mock.patch.object(rah.shutil, "disk_usage", du):
            code, out, err = self.main("recheck", "--con-leche", "--checker", bad, "--exporter", self.exporter)
        self.assertEqual(saved.read_bytes(), self.export)
        # the disk fails while saving: error, no hang, partial removed, nothing recorded
        saved.unlink(); before = self.latest_record().get("checkers")
        with mock.patch.object(rah, "stream_export", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                self.main("recheck", "--con-leche", "--checker", bad, "--exporter", self.exporter)
        self.assertFalse(saved.exists()); self.assertFalse(list(saved.parent.glob("*.partial")))
        self.assertEqual(self.latest_record().get("checkers"), before)
        # con-leche exit 2 (declined) and 3 (error) are not verdicts on the proof: nothing recorded
        for code_, word in ((2, "declined"), (3, "stopped with an error")):
            odd = self.tmp / f"bin/con-leche-{code_}"
            odd.write_text(f"#!/bin/sh\nexit {code_}\n"); odd.chmod(0o755)
            before = self.latest_record().get("checkers")
            code, out, err = self.main("recheck", "--con-leche", "--checker", odd, "--checker-version", "1",
                                       "--exporter", self.exporter)
            self.assertEqual(code, 1); self.assertIn(f"con-leche {word}", err); self.assertIn("nothing recorded", err)
            self.assertEqual(self.latest_record().get("checkers"), before)
        # a checker killed by a signal (the out-of-memory killer) gives no verdict: nothing recorded
        self.main("recheck", "--con-leche", "--checker", bad, "--exporter", self.exporter)   # saved again
        before = self.latest_record()["checkers"]
        oom = self.tmp / "bin/oom-con-leche"
        oom.write_text(f"#!{sys.executable} -I\nimport os, sys\nif sys.argv[1:] == ['--version']: print('x'); sys.exit(0)\n"
                       "os.kill(os.getpid(), 9)\n"); oom.chmod(0o755)
        code, out, err = self.main("recheck", "--con-leche", "--checker", oom, "--exporter", self.exporter)
        self.assertEqual(code, 1); self.assertIn("stopped by signal 9 (usually: the computer ran out of memory)", err)
        self.assertIn("nothing recorded", err); self.assertEqual(self.latest_record()["checkers"], before)
        # a checker that cannot start: a plain error, not a traceback
        nox = self.tmp / "bin/not-executable"; nox.write_text("not a program"); nox.chmod(0o644)
        code, out, err = self.main("recheck", "--con-leche", "--checker", nox, "--checker-version", "1", "--exporter", self.exporter)
        self.assertEqual(code, 1); self.assertIn("could not start con-leche", err)
        os.environ["RAH_TEST_RAM_GB"] = "128"
        self.main("recheck", "--nanoda", "--checker", chk, "--exporter", self.exporter)   # back to a good state
        # sign: shows the statement from the README, asks, and only "y" signs
        code, out, err = self.main("sign", stdin="n\n")
        self.assertEqual(code, 1); self.assertIn("not signed", out)
        self.assertIn(" ".join(STATEMENT.split()[:12]), " ".join(out.split()))
        self.assertEqual(" ".join(out.split()).count(" ".join(STATEMENT.split())), 1)
        self.assertNotIn("sign_statement", self.latest_record())
        code, out, err = self.main("sign")                        # no answer (EOF) = no
        self.assertEqual(code, 1)
        code, out, err = self.main("sign", stdin="y\n")
        self.assertEqual(code, 0, err); self.assertIn("Sign this statement? [y/N]", out)
        rec = self.latest_record(); self.assertIs(rec["sign_statement"], True)
        with mock.patch.object(rah, "EXPORT_SHA256", self.sha):
            self.assertEqual(rah.validate_levels(rec), [])
        code, out, err = self.main("status")
        self.assertIn("level     3: export reproduces the reference, re-checked by nanoda, joint statement signed", out)
        # a changed build (different olean digest) does not inherit the levels
        (self.folder / ".lake/build/lib/lean/A/N00.olean").write_bytes(b"different")
        self.main("record")
        self.assertFalse(set(rah.LEVEL_KEYS) & set(self.latest_record()))

    def test_validate_level_fields(self):
        base = Fast._valid_record(None, self.tmp / "r.json")
        whole = {**base, "whole_proof": True, "axioms": list(reversed(rah.EXPECTED_AXIOMS))}
        l2 = {**whole, "export_sha256": rah.EXPORT_SHA256, "export_bytes": rah.EXPORT_BYTES}
        l3 = {**l2, "checkers": [{"name": "nanoda", "version": "0.9", "result": "accept", "seconds": 3600}],
              "sign_statement": True, "display_name": "Ada"}
        for ok, lvl in ((base, 1), (whole, 1), (l2, 2), (l3, 3), ({**l2, "sign_statement": True}, 2),
                        ({**whole, "sign_statement": True}, 1), ({**whole, "sign_statement": False}, 1)):
            self.assertEqual(rah.validate_record(ok), [], ok.keys()); self.assertEqual(rah.record_level(ok), lvl)
        shuffled = dict(reversed(list(l3.items())))                # keys are a set: order does not matter
        self.assertEqual(rah.validate_record(shuffled), [])
        bad = [({**l2, "export_sha256": "0" * 64}, "export does not reproduce the reference"),
               ({**base, "export_sha256": rah.EXPORT_SHA256, "export_bytes": 1}, "need a whole proof"),
               ({**whole, "export_sha256": rah.EXPORT_SHA256}, "go together"),
               ({**l2, "export_bytes": "61570595788"}, "export_bytes"),
               ({**whole, "checkers": l3["checkers"]}, "Level 2"),
               ({**l2, "checkers": []}, "non-empty"),
               ({**l2, "checkers": [{"name": "nanoda", "result": "accept", "seconds": 1}]}, "checkers must be"),
               ({**l2, "checkers": [{**l3["checkers"][0], "result": "maybe"}]}, "checkers must be"),
               ({**l2, "checkers": l3["checkers"] * 2}, "one entry per checker"),
               ({**base, "sign_statement": True}, "three standard axioms"),
               ({**whole, "axioms": ["propext", "sorryAx"], "sign_statement": True}, "three standard axioms"),
               ({**l2, "sign_statement": "yes"}, "true or false"),
               ({**l3, "anonymous": True}, "at most one")]
        for rec, msg in bad:
            errs = rah.validate_record(rec)
            self.assertTrue(any(msg in e for e in errs), (msg, errs))

    def test_record_started_stays_put(self):
        """`started` (first finished module for a pre-built folder) is kept across this build's records."""
        lib = self.folder / ".lake/build/lib/lean"
        old = time.time() - 7200
        for f in lib.rglob("*.trace"):
            os.utime(f, (old, old))
        self.main("record"); first = self.latest_record()
        self.assertEqual(first["started"], rah.iso(old))
        now = time.time()
        for f in lib.rglob("*.trace"):                              # rebuilt later: earliest trace moves forward
            os.utime(f, (now, now))
        time.sleep(1.1); self.main("record")
        self.assertEqual(self.latest_record()["started"], first["started"])


FAKE_GH = r"""#!PYTHON -I
# A stand-in for GitHub's `gh`: a local bare repo is "upstream", PRs live in a JSON file. No network.
import json, os, subprocess, sys
a = sys.argv[1:]
E = os.environ
with open(E["FAKE_GH_LOG"], "a") as f:
    f.write(json.dumps(a) + "\n")
if E.get("FAKE_GH_FAIL"):
    print("error connecting to api.github.com", file=sys.stderr); sys.exit(1)
state = json.load(open(E["FAKE_GH_STATE"])) if os.path.exists(E["FAKE_GH_STATE"]) else {"prs": []}
save = lambda: json.dump(state, open(E["FAKE_GH_STATE"], "w"))
if a[:2] == ["auth", "status"]:
    sys.exit(0)
if a[:2] == ["api", "user"]:
    print(E["FAKE_GH_LOGIN"]); sys.exit(0)
if a[0] == "api" and a[1].startswith("repos/"):
    print(E.get("FAKE_GH_PUSH", "true")); sys.exit(0)
if a[:2] == ["repo", "clone"]:
    assert a[2] == E["FAKE_GH_UPSTREAM_NAME"], a
    sys.exit(subprocess.run(["git", "clone", "-q", E["FAKE_UPSTREAM"], a[3]]).returncode)
if a[:2] == ["repo", "fork"]:
    if not os.path.exists(E["FAKE_FORK"]):
        subprocess.run(["git", "clone", "-q", "--bare", E["FAKE_UPSTREAM"], E["FAKE_FORK"]], check=True)
    sys.exit(subprocess.run(["git", "remote", "add", "fork", E["FAKE_FORK"]]).returncode)
if a[:2] == ["pr", "list"]:
    head = a[a.index("--head") + 1]
    print(json.dumps([{k: p[k] for k in ("number", "url", "state")} for p in state["prs"]
                      if p["head"].split(":")[1] == head])); sys.exit(0)
if a[:2] == ["pr", "create"]:
    g = lambda k: a[a.index(k) + 1]
    n = len(state["prs"]) + 1
    url = f"https://github.com/{g('--repo')}/pull/{n}"
    state["prs"].append({"number": n, "url": url, "state": "OPEN", "head": g("--head"), "title": g("--title"),
                         "body": g("--body"), "repo": g("--repo")})
    save(); print(url); sys.exit(0)
print("fake gh: unexpected", a, file=sys.stderr); sys.exit(2)
"""


class ReviewFixes(Levels):
    """2026-11-25 review: commands that lost results for good, or never sent them."""
    locals().update({n: None for n in dir(Levels) if n.startswith("test_")})   # reuse setUp, not Levels' tests
    def submitted(self):
        """Patch autosubmit; returns the list of reasons it was called with."""
        from unittest import mock
        calls = []
        p = mock.patch.object(rah, "autosubmit", lambda ctx, a, why: calls.append(why)); p.start(); self.addCleanup(p.stop)
        p2 = mock.patch.object(rah, "AUTOSUBMIT", "on"); p2.start(); self.addCleanup(p2.stop)
        return calls

    def auto_on(self):
        ctx = rah.Ctx(types.SimpleNamespace(folder=str(self.folder), logs=None, test_unofficial_folder=True))
        ctx.set_conf(submit={"auto": True})
        return ctx

    def test_finish_dry_run_changes_nothing(self):
        recs = sorted((self.home / "records").glob("*.json")) if (self.home / "records").exists() else []
        code, out, err = self.main("finish", "--dry-run")
        self.assertEqual(code, 0, err); self.assertIn("would", out)
        now = sorted((self.home / "records").glob("*.json")) if (self.home / "records").exists() else []
        self.assertEqual(recs, now, "finish --dry-run wrote a record")

    def test_finish_refuses_during_axiom_check(self):
        (self.home / "logs/axioms.log").write_bytes(b"")        # the build truncates it when the check starts
        code, out, err = self.main("finish")
        self.assertEqual(code, 1); self.assertIn("axiom check has not finished", err)
        self.assertFalse((self.home / "records").exists() and any((self.home / "records").glob("*.json")),
                         "a final record was written while the axiom check ran")

    def test_finish_refuses_before_export(self):
        code, out, err = self.main("finish")
        self.assertEqual(code, 1); self.assertIn("has not been exported yet", err)

    def test_finish_refuses_during_export(self):
        (self.home / "export-progress.json").write_text(json.dumps({"done": False, "updated": int(time.time())}))
        code, out, err = self.main("finish")
        self.assertEqual(code, 1); self.assertIn("an export is running", err)

    def test_second_export_mismatch_keeps_level2_and_signature(self):
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 0, err)
        code, out, err = self.main("sign", stdin="y\n")
        self.assertEqual(code, 0, err)
        bad = self.tmp / "bin/fake-lean4export-differs"                               # a run that does not match
        bad.write_text(self.exporter.read_text().replace("sys.stdout.buffer.write(chunk)", "sys.stdout.buffer.write(chunk[::-1])"))
        bad.chmod(0o755)
        code, out, err = self.main("export", "--exporter", bad)
        self.assertIn("keeping that result", out)
        code, _, err = self.main("record")
        rec = self.latest_record()
        self.assertEqual(rec.get("export_sha256"), self.sha, "a non-matching re-export erased the matching one")
        self.assertTrue(rec.get("sign_statement"), "a non-matching re-export erased the signature")

    def test_sign_and_cancel_reach_the_pr_after_the_build(self):
        self.auto_on(); calls = self.submitted()
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 0, err)
        code, out, err = self.main("sign", stdin="y\n")
        self.assertEqual(code, 0, err); self.assertIn("signed", calls)
        code, out, err = self.main("sign", "--cancel")
        self.assertEqual(code, 0, err); self.assertIn("signature withdrawn", calls)

    def test_after_final_says_it_cannot_send(self):
        ctx = self.auto_on()
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 0, err)
        calls = self.submitted()
        ctx.set_conf(pr={"build_id": ctx.build_id(), "final_sent": True})
        code, out, err = self.main("sign", stdin="y\n")
        self.assertIn("final record was already sent", out); self.assertEqual(calls, [])
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 1); self.assertIn("final record was already sent", err)


class SetupStats(unittest.TestCase):
    """setup shows how long the build and the export took on others' computers (from the leaderboard)."""
    DATA = {"leaderboard": [
        {"whole_proof": True, "build_hours": 64.3, "machine": "Apple M5 Max", "export": None},
        {"whole_proof": True, "build_hours": 9.0, "machine": "AMD Ryzen Threadripper PRO 9975WX 32-Cores",
         "export": {"done": True, "matches": True, "seconds": 9916}},
        {"whole_proof": True, "build_hours": 48.6, "machine": "Apple M2 Max",
         "export": {"done": True, "matches": True, "seconds": 94468}},
        {"whole_proof": True, "build_hours": 41.0, "machine": "Apple M4 Max",
         "export": {"done": False, "seconds": 84106}},
        {"whole_proof": False, "build_hours": None, "machine": "Apple M3 Ultra"}]}

    def test_table(self):
        t = rah.others_text(self.DATA, "Apple  M5 Max")
        lines = t.splitlines()
        self.assertIn("4 whole builds", lines[0])
        self.assertIn("build:  9.0 h to 64 h; half finished within 41 h", t)
        self.assertIn("export: 2.8 h to 26 h (2 finished)", t)
        rows = [l for l in lines if l.startswith("  ") and ("Apple" in l or "AMD" in l)]
        self.assertEqual([r.split()[0] for r in rows], ["AMD", "Apple", "Apple", "Apple"])   # fastest first
        self.assertTrue(rows[-1].endswith("<- like this computer") and "M5 Max" in rows[-1])
        self.assertNotIn("M3 Ultra", t)                     # unfinished builds are not listed
        self.assertIn("41 h       -", t)                    # an export still running shows no time

    def test_empty_and_offline(self):
        self.assertEqual(rah.others_text({}), "")
        from unittest import mock
        with mock.patch.object(rah.urllib.request, "urlopen", side_effect=OSError("offline")), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            rah.show_others(None)
        self.assertEqual(out.getvalue(), "")

    def test_fmt_dur_never_60_minutes(self):
        self.assertEqual([rah.fmt_dur(x) for x in (59, 3599, 7170, 86399)], ["1 m", "1 h 0 m", "2 h 0 m", "24 h 0 m"])


class FastExit(unittest.TestCase):
    """export --fast-exit: Derek Blanchette's lean4export patch (issue #24)."""
    MAIN = ("def main (args : List String) : IO Unit := do\n  M.run env do\n    let _ ← initState env opts\n"
            "    dumpMetadata\n" + rah.FAST_EXIT_LOOP)

    def test_patch_appends_flush_and_exit_after_the_loop(self):
        out = rah.patch_fast_exit(self.MAIN)
        self.assertTrue(out.startswith(self.MAIN))
        self.assertTrue(out.endswith("      dumpConstant c\n    (← IO.getStdout).flush\n    IO.Process.exit 0\n"))
        self.assertEqual(rah.patch_fast_exit(self.MAIN + "\n\n"), out)          # trailing blank lines are fine

    def test_patch_refuses_a_changed_main(self):
        self.assertIsNone(rah.patch_fast_exit(self.MAIN + "    IO.println \"done\"\n"))   # loop no longer last
        self.assertIsNone(rah.patch_fast_exit(self.MAIN.replace("dumpConstant c", "dumpConstant' c")))
        self.assertIsNone(rah.patch_fast_exit(rah.patch_fast_exit(self.MAIN)))    # never patched twice

    def test_real_v4_33_0_main_if_present(self):
        p = Path(os.environ.get("RAH_L4E_MAIN", "/nonexistent"))
        if not p.exists():
            self.skipTest("set RAH_L4E_MAIN to lean4export v4.33.0's Main.lean")
        self.assertIsNotNone(rah.patch_fast_exit(p.read_text()))

    def test_export_uses_fast_exit_by_default(self):
        """issue #24: a full export with the fast exit matched the reference, so it is the default (2026-11-26)."""
        from unittest import mock
        got = {}
        def fake_export(ctx, a): got["fast"] = a.fast_exit; return 0
        with mock.patch.object(rah, "cmd_export", fake_export), mock.patch.object(rah, "Ctx", lambda a: types.SimpleNamespace(p={"levels": True})):
            for argv, want in ((["export"], True), (["export", "--fast-exit"], True), (["export", "--no-fast-exit"], False)):
                rah.main(argv + ["--proof", "17m"]); self.assertEqual(got.pop("fast"), want, argv)

    def test_fast_exit_uses_its_own_tools_folder(self):
        from unittest import mock
        home = Path(tempfile.mkdtemp(dir=TMP)); self.addCleanup(shutil.rmtree, home, True)
        ctx = types.SimpleNamespace(home=home)
        seen = []
        def fake_run(cmd, **kw):
            if "rev-parse" in map(str, cmd):
                return types.SimpleNamespace(returncode=0, stdout=rah.EXPORTER_COMMIT + "\n")
            seen.append(cmd); dest = Path(cmd[-1]); dest.mkdir(parents=True)
            (dest / "Main.lean").write_text(self.MAIN); return types.SimpleNamespace(returncode=0)
        with mock.patch.object(rah, "run", fake_run), mock.patch.object(rah, "ensure_elan", side_effect=rah.Fail("stop")):
            for fast in (False, True):
                with self.assertRaises(rah.Fail):
                    rah.exporter_command(ctx, types.SimpleNamespace(exporter=None, fast_exit=fast))
        names = sorted(p.name for p in (home / "tools").iterdir())
        self.assertEqual(len(names), 2); self.assertTrue(names[1].endswith("-fastexit"), names)
        self.assertNotIn("IO.Process.exit", (home / "tools" / names[0] / "Main.lean").read_text())
        self.assertIn("IO.Process.exit 0", (home / "tools" / names[1] / "Main.lean").read_text())


class Parallel(unittest.TestCase):
    """export --parallel (issue #24): an experimental, pinned copy of the parallel lean4export from lean4export#63,
    with our review's fixes (2026-11-26)."""
    LINE = "  if ((declar.isUnsafe || declar.isPartial) && !ctx.exportUnsafe) || (← get).contains c then\n"
    END = "    (do\n      finishOutputG : MB Unit).run {}\n"

    def test_partial_rule_matches_v4_33_0(self):
        out = rah.patch_parallel_partial(self.LINE)
        self.assertEqual(out, "  if (declar.isUnsafe && !ctx.exportUnsafe) || (← get).contains c then\n")
        self.assertIsNone(rah.patch_parallel_partial(out))                    # never twice
        self.assertIsNone(rah.patch_parallel_partial(self.LINE * 2))          # exactly one place

    def test_real_par_lean_if_present(self):
        p = Path(os.environ.get("RAH_PAR_LEAN", "/nonexistent"))
        if not p.exists():
            self.skipTest("set RAH_PAR_LEAN to Export/Par.lean at the pinned parallel commit")
        out = rah.patch_parallel_forget(rah.patch_parallel_partial(p.read_text()))
        self.assertNotIn("isPartial", out); self.assertIn("Runtime.forget (← get)", out)

    def apply_with(self, parents):
        from unittest import mock
        calls = []
        def fake_run(cmd, **kw):
            cmd = list(map(str, cmd)); calls.append(cmd)
            if "rev-parse" in cmd:
                k = int(cmd[-1].rsplit("~", 1)[1])
                return types.SimpleNamespace(returncode=0, stdout=parents[k - 1] + "\n")
            return types.SimpleNamespace(returncode=0, stdout=b"diff")
        src = Path(tempfile.mkdtemp(dir=TMP)); self.addCleanup(shutil.rmtree, src, True)
        (src / "Export").mkdir(); (src / "Export" / "Par.lean").write_text(self.LINE + self.END)
        with mock.patch.object(rah, "run", fake_run):
            rah.apply_parallel(src)
        return calls, (src / "Export" / "Par.lean").read_text()

    def test_applies_only_the_reviewed_history(self):
        calls, par = self.apply_with(rah.PARALLEL_PARENTS)
        self.assertIn(rah.PARALLEL_COMMIT, calls[0])                           # fetched by full hash
        self.assertNotIn("isPartial", par); self.assertIn("Runtime.forget", par)
        with self.assertRaises(rah.Fail):
            self.apply_with(["0" * 40, rah.PARALLEL_PARENTS[1]])

    def test_refuses_a_moved_exporter_tag(self):
        from unittest import mock
        home = Path(tempfile.mkdtemp(dir=TMP)); self.addCleanup(shutil.rmtree, home, True)
        def fake_run(cmd, **kw):
            if "rev-parse" in map(str, cmd):
                return types.SimpleNamespace(returncode=0, stdout="f" * 40 + "\n")
            Path(cmd[-1]).mkdir(parents=True); return types.SimpleNamespace(returncode=0)
        with mock.patch.object(rah, "run", fake_run), self.assertRaises(rah.Fail) as e:
            rah.exporter_command(types.SimpleNamespace(home=home), types.SimpleNamespace(exporter=None, fast_exit=True))
        self.assertIn("not the", str(e.exception))
        self.assertEqual(list((home / "tools").iterdir()), [])                 # nothing half-made left behind

    def test_needs_memory(self):
        self.assertIsNotNone(rah.parallel_ram_problem(64))
        self.assertIsNone(rah.parallel_ram_problem(125))                      # upstream's 125 GiB machine ran it
        self.assertIsNone(rah.parallel_ram_problem(0))                        # unknown: let it try

    def test_flag_is_listed_and_needs_fast_exit(self):
        """Listed in --help since a run of the pinned version matched the reference (issue #24, 2026-11-26)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            rah.main(["export", "--help"])
        self.assertIn("--parallel", out.getvalue()); self.assertIn("--low-memory-ok", out.getvalue())
        for argv in (["--parallel", "--no-fast-exit"], ["--low-memory-ok"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                rah.main(["export", *argv, "--proof", "17m"])

    def test_low_memory_ok_lets_it_start(self):
        """Below 100 GB --parallel refuses before building anything, unless --low-memory-ok (issue #24)."""
        from unittest import mock
        built = []
        ctx = types.SimpleNamespace(conf=lambda: {})
        a = types.SimpleNamespace(check=False, parallel=True, low_memory_ok=False, fast_exit=True)
        stop = rah.Fail("stop here")
        with mock.patch.object(rah, "whole_build", lambda c, a, w: {"build_id": "b"}), \
                mock.patch.object(rah, "total_ram_gb", lambda: 64), mock.patch.object(rah, "keep_awake", lambda: None), \
                mock.patch.object(rah, "exporter_command", lambda c, a: built.append(1) or (_ for _ in ()).throw(stop)):
            with self.assertRaises(rah.Fail) as e:
                rah.cmd_export(ctx, a)
            self.assertIn("--low-memory-ok", str(e.exception)); self.assertEqual(built, [])
            a.low_memory_ok = True
            with self.assertRaises(rah.Fail) as e:
                rah.cmd_export(ctx, a)
            self.assertIs(e.exception, stop); self.assertEqual(built, [1])

    def test_memory_warning_without_the_old_end_pause(self):
        """The fast exit removed the end pause, so the '2 hours' figure is not shown with it (issue #24)."""
        self.assertNotIn("2 hours", rah.export_memory_warning(125, fast=True))
        self.assertIn("2 hours", rah.export_memory_warning(125, fast=False))

    def test_record_names_the_exporter(self):
        self.assertEqual(rah.exporter_name(types.SimpleNamespace(parallel=True)),
                         f"lean4export v4.33.0 + parallel {rah.PARALLEL_COMMIT[:8]}")
        self.assertEqual(rah.exporter_name(types.SimpleNamespace()), "lean4export v4.33.0")


class FileMax(unittest.TestCase):
    """Issue #92: a 32-thread 17M build crashed at Linux's fs.file-max of 2,097,152 (each lean maps ~31K files)."""
    def test_warns_when_the_limit_is_low_for_the_thread_count(self):
        w = rah.file_max_warning(32, "2097152\n")
        self.assertIn("2,097,152", w); self.assertIn("sudo sysctl --system", w); self.assertIn("#92", w)
        self.assertIsNone(rah.file_max_warning(32, "9223372036854775807\n"))
        self.assertIsNone(rah.file_max_warning(8, "2097152"))             # 8 threads fit
        self.assertIsNone(rah.file_max_warning(32, ""))                   # not Linux, or unreadable: say nothing


class Sign300K(unittest.TestCase):
    """The 300K joint statement (issue #76) and default-yes signing with opt-out (owner, 2026-11-27): signed only at
    the moment a build first qualifies, with the setup yes on file, never without a terminal, never after an opt-out,
    never retroactively."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=TMP, prefix="s3-"))
        self.home = self.tmp / "h"; self.home.mkdir()
        self.folder = self.tmp / "g"
        self.env = unittest.mock.patch.dict(os.environ, {"RAH_HOME": str(self.home), "RAH_NO_STATS": "1"})
        self.env.start()
        (self.home / "300k/logs").mkdir(parents=True)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, whole=True, axioms=None):
        axioms = FIVE if axioms is None else axioms
        if self.folder.exists():
            shutil.rmtree(self.folder)
        fake_300k(self.folder, compiled=None if whole else {0, 1})
        (self.home / "300k/logs/axioms.log").write_text(axioms if whole else "")

    def main(self, *args, stdin="", tty=True):
        import builtins
        from unittest import mock
        out, err = io.StringIO(), io.StringIO()
        answers = iter(stdin.splitlines())
        def fake_input(prompt=""):
            print(prompt, end="")
            try:
                return next(answers)
            except StopIteration:
                raise EOFError
        sin = io.StringIO(stdin); sin.isatty = lambda: tty
        with mock.patch.object(builtins, "input", fake_input), mock.patch("sys.stdin", sin), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            unoff = [] if args[0] == "status" else ["--test-unofficial-folder"]
            code = rah.main([*map(str, args), "--proof", "300k", "--folder", str(self.folder), *unoff])
        return code, out.getvalue(), err.getvalue()

    def ctx(self):
        return rah.Ctx(types.SimpleNamespace(folder=str(self.folder), logs=None, proof="300k"))

    def ask(self, answer, tty=True):
        sin = io.StringIO(answer + "\n"); sin.isatty = lambda: tty
        out = io.StringIO()
        with contextlib.redirect_stdout(out), unittest.mock.patch("sys.stdin", sin), \
                unittest.mock.patch("builtins.input", lambda prompt="": print(prompt, end="") or answer):
            rah.ask_sign_when_done(self.ctx())
        return out.getvalue()

    def rec(self):
        return json.loads(sorted((self.home / "300k/records").glob("*.json"))[-1].read_text())

    def sign_errors(self):
        return [e for e in rah.validate_record(self.rec()) if "sign_statement" in e or "keys" in e]

    def test_sign_without_proof_tries_every_build_and_opt_out_is_shared(self):
        """One statement: `sign` with no --proof looks at every proof set up here (this one first), and a no on
        one proof is a no on all of them (sign_opt_out / sign_when_done are shared choices)."""
        f17, f3 = self.tmp / "f17", self.tmp / "f3"
        f3.mkdir()                                            # only the 300K build exists here
        with unittest.mock.patch.object(rah, "fixed_folder", lambda pk: f17 if pk == "17m" else f3):
            a = types.SimpleNamespace(folder=None, logs=None, proof=None)
            c17 = rah.Ctx(a, proof="17m")
            self.assertEqual([c.proof for c in rah.sign_contexts(c17, a)], ["17m", "300k"])
            f3.rmdir()
            self.assertEqual([c.proof for c in rah.sign_contexts(c17, a)], ["17m"])
            self.assertEqual([c.proof for c in rah.sign_contexts(c17, types.SimpleNamespace(**{**vars(a), "proof": "17m"}))], ["17m"])
            c3 = rah.Ctx(a, proof="300k")
            rah.set_sign_opt_out(c3, True)
            self.assertTrue(rah.sign_opted_out(c17))
            rah.set_sign_when_done(c17)
            self.assertIsNone(rah.sign_opted_out(c3) or None); self.assertTrue(rah.sign_when_done(c3))

    def test_one_statement_for_both_proofs(self):
        """2026-11-27: one letter with a badge per thing each signatory did, for 17M and 300K alike."""
        t = rah.statement_text("300k")
        self.assertEqual(t, rah.statement_text("17m")); self.assertEqual(t, rah.statement_text())
        self.assertEqual(t, STATEMENT)
        for badge in ("17M BUILT", "300K BUILT", "EXPORT REPRODUCED", "RE-CHECKED"):
            self.assertIn(badge, t)
        self.assertIn("all 803 modules", t); self.assertIn("72fead10", t); self.assertNotIn("—", t)

    def test_sign_needs_a_whole_build_with_the_three_axioms(self):
        self.build(whole=False)
        code, out, err = self.main("sign", stdin="y\n")
        self.assertEqual(code, 1); self.assertIn("needs the whole build", err)
        self.build(axioms=FIVE.replace("Quot.sound]", "Quot.sound, sorryAx]"))
        code, out, err = self.main("sign", stdin="y\n")
        self.assertEqual(code, 1)
        self.build()
        code, out, err = self.main("sign", stdin="n\n")
        self.assertEqual(code, 1); self.assertIn("not signed", out)
        code, out, err = self.main("sign", stdin="y\n")
        self.assertEqual(code, 0, err); self.assertIn("Riemann@home: a joint statement from independent builders", out)
        self.assertIs(self.rec().get("sign_statement"), True); self.assertEqual(self.sign_errors(), [])
        self.assertIn(rah.SHARE_TEXT["signed_300k"], out)
        code, out, err = self.main("status")
        self.assertIn("joint statement signed", out)

    def test_cancel_withdraws_and_the_opt_out_persists(self):
        self.build()
        self.main("sign", stdin="y\n")
        code, out, err = self.main("sign", "--cancel")
        self.assertEqual(code, 0, err); self.assertIn("signature withdrawn", out)
        self.assertIs(self.rec().get("sign_statement"), False, "the record says no, so the page drops them")
        self.assertEqual(self.sign_errors(), [])
        self.assertTrue(rah.sign_opted_out(self.ctx()))
        self.ask("")                                          # setup again: no question, no yes
        self.assertIsNone(rah.sign_when_done(self.ctx()))
        self.main("record"); self.assertIs(self.rec().get("sign_statement"), False)
        code, out, err = self.main("sign", stdin="y\n")       # signing again by hand is always possible
        self.assertEqual(code, 0, err); self.assertIs(self.rec().get("sign_statement"), True)
        self.assertFalse(rah.sign_opted_out(self.ctx()))

    def test_default_yes_signs_at_the_moment_the_build_qualifies(self):
        out = self.ask("")                                    # Enter
        self.assertIn("[Y/n]", out); self.assertIn("Riemann@home: a joint statement from independent builders", out)
        self.assertIn(rah.SIGN_DEFAULT_LINE, out)
        self.assertTrue(rah.sign_when_done(self.ctx()))
        self.build(whole=False); self.main("record")
        self.assertNotIn("sign_statement", self.rec())
        self.build(); code, out, err = self.main("record")
        self.assertEqual(code, 0, err)
        self.assertIs(self.rec().get("sign_statement"), True)
        self.assertIn("You signed this statement. To withdraw: riemann-at-home sign --cancel\n", out)
        self.assertIn("Riemann@home: a joint statement from independent builders", out)

    def test_no_terminal_never_signs(self):
        out = self.ask("y", tty=False)
        self.assertIn("riemann-at-home sign --when-done", out)
        self.assertIsNone(rah.sign_when_done(self.ctx()))
        self.build(whole=False); self.main("record"); self.build(); self.main("record")
        self.assertNotIn("sign_statement", self.rec())

    def test_no_at_setup_or_no_sign_flag_is_an_opt_out(self):
        self.ask("n")
        self.assertTrue(rah.sign_opted_out(self.ctx())); self.assertIsNone(rah.sign_when_done(self.ctx()))
        self.build(whole=False); self.main("record"); self.build(); self.main("record")
        self.assertIs(self.rec().get("sign_statement"), False)
        self.assertIn("--no-sign", rah.main.__code__.co_consts.__repr__() + Path(rah.__file__).read_text())

    def test_not_retroactive(self):
        self.build(); self.main("record")                    # already whole before the yes
        self.ask("")
        self.assertTrue(rah.sign_when_done(self.ctx()))
        code, out, err = self.main("record")
        self.assertNotIn("sign_statement", self.rec()); self.assertNotIn("You signed this statement", out)
        self.assertNotIn("sign_statement", self.rec())


class Export300K(Sign300K):
    """The 300K proof's optional export (owner, 2026-11-27): lean4export v4.35.0 pinned by commit, the record carries
    the hash either way; no reference yet, so the bot gathers hashes until three builders agree."""
    OUT = b"{\"meta\": 1}\n" * 500

    def fake_exporter(self, out=None):
        f = self.tmp / "fake-l4e"
        f.write_text(f"#!{sys.executable} -I\nimport sys\nsys.stdout.buffer.write({(out or self.OUT)!r})\n")
        f.chmod(0o755)
        return f

    def export(self, *extra, out=None):
        return self.main("export", "--exporter", self.fake_exporter(out), *extra)

    def test_records_the_hash_with_no_reference(self):
        self.build()
        code, out, err = self.export()
        self.assertEqual(code, 0, err)
        sha = hashlib.sha256(self.OUT).hexdigest()
        self.assertIn(sha, out); self.assertIn("no 300K reference export yet", out)
        rec = self.rec()
        self.assertEqual((rec["export_sha256"], rec["export_bytes"]), (sha, len(self.OUT)))
        self.assertEqual([e for e in rah.validate_record(rec) if "export" in e or "keys" in e], [])
        self.assertEqual(rah.record_level(rec), 1)                  # no Levels for 300K: a hash is not Level 2
        code, out, err = self.main("status")
        self.assertIn(f"export    sha256 {sha}", out)

    def test_with_a_pinned_reference(self):
        self.build()
        sha = hashlib.sha256(self.OUT).hexdigest()
        with unittest.mock.patch.dict(rah.PROOFS["300k"], {"export_sha256": sha, "export_bytes": len(self.OUT)}):
            code, out, err = self.export()
            self.assertEqual(code, 0, err); self.assertIn("matches the 300K reference", out)
            code, out, err = self.export(out=b"different\n")
            self.assertEqual(code, 1); self.assertIn("does not match the 300K reference", out)
            self.assertEqual(self.rec()["export_sha256"], hashlib.sha256(b"different\n").hexdigest())  # still carried

    def test_needs_the_whole_build_and_no_parallel(self):
        self.build(whole=False)
        code, out, err = self.export()
        self.assertEqual(code, 1); self.assertIn("needs the whole build", err)
        self.build()
        code, out, err = self.export("--parallel")
        self.assertEqual(code, 1); self.assertIn("17M export only", err)

    def test_bad_hashes_refused_in_records(self):
        self.build()
        self.export()
        rec = self.rec()
        self.assertTrue(any("64 lowercase hex" in e for e in rah.validate_record({**rec, "export_sha256": "XYZ"})))
        part = {**rec, "whole_proof": False, "axioms": None}
        self.assertTrue(any("whole proof" in e for e in rah.validate_record(part)))

    def test_exporter_is_v4_35_pinned_by_commit(self):
        from unittest import mock
        P = rah.PROOFS["300k"]
        self.assertEqual((P["exporter_tag"], P["exporter_commit"]), ("v4.35.0", "5a9a355dc6c5fd82b69058d433e2ae2e8dfbf8fe"))
        self.assertEqual(P["export_targets"], rah.EXPORT_TARGETS)
        self.assertTrue(set(P["theorems"]) <= set(P["export_targets"]))
        home = Path(tempfile.mkdtemp(dir=TMP)); self.addCleanup(shutil.rmtree, home, True)
        seen = []
        def fake_run(cmd, **kw):
            cmd = list(map(str, cmd)); seen.append(cmd)
            if "rev-parse" in cmd:
                return types.SimpleNamespace(returncode=0, stdout=P["exporter_commit"] + "\n")
            d = Path(cmd[-1]); d.mkdir(parents=True)
            (d / "Main.lean").write_text(FastExit.MAIN); return types.SimpleNamespace(returncode=0)
        ctx = types.SimpleNamespace(home=home, p=P)
        with mock.patch.object(rah, "run", fake_run), mock.patch.object(rah, "ensure_elan", side_effect=rah.Fail("stop")):
            with self.assertRaises(rah.Fail):
                rah.exporter_command(ctx, types.SimpleNamespace(exporter=None, fast_exit=True))
        self.assertIn("v4.35.0", seen[0])
        [made] = list((home / "tools").iterdir())
        self.assertEqual(made.name, "lean4export-v4.35.0-lean-v4.35.0-fastexit")
        self.assertEqual((made / "lean-toolchain").read_text().strip(), P["toolchain"])

    def test_real_v4_35_main_takes_the_fast_exit_if_present(self):
        p = Path(os.environ.get("RAH_L4E435_MAIN", "/nonexistent"))
        if not p.exists():
            self.skipTest("set RAH_L4E435_MAIN to lean4export v4.35.0's Main.lean")
        self.assertIsNotNone(rah.patch_fast_exit(p.read_text()))


class SignDefault17M(unittest.TestCase):
    """17M: default yes at setup; signs when the export first matches; never on a build that already had Level 2;
    never after an opt-out (owner, 2026-11-27). Uses Levels' stand-in exporter without re-running its tests."""
    setUp, tearDown, main, latest_record = Levels.setUp, Levels.tearDown, Levels.main, Levels.latest_record
    def ask(self, answer, tty=True):
        sin = io.StringIO(answer + "\n"); sin.isatty = lambda: tty
        out = io.StringIO()
        with contextlib.redirect_stdout(out), unittest.mock.patch("sys.stdin", sin), \
                unittest.mock.patch("builtins.input", lambda prompt="": print(prompt, end="") or answer):
            rah.ask_sign_when_done(rah.Ctx(types.SimpleNamespace(folder=str(self.folder), logs=None)))
        return out.getvalue()

    def test_enter_is_yes_and_signs_at_the_first_match(self):
        out = self.ask("")
        self.assertIn("[Y/n]", out); self.assertIn(rah.SIGN_DEFAULT_LINE, out)
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 0, err); self.assertIs(self.latest_record().get("sign_statement"), True)
        self.assertIn("You signed this statement. To withdraw: riemann-at-home sign --cancel", out)

    def test_not_retroactive_on_a_build_that_already_matched(self):
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 0, err); self.assertNotIn("sign_statement", self.latest_record())
        self.ask("")
        code, out, err = self.main("export", "--exporter", self.exporter)   # the same build, exported again
        self.assertEqual(code, 0, err); self.assertNotIn("sign_statement", self.latest_record())

    def test_opt_out_wins(self):
        self.ask("")
        self.main("sign", "--cancel")
        self.ask("")                                          # asked again: no, the opt-out stands
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 0, err); self.assertIs(self.latest_record().get("sign_statement"), False)

    def test_no_terminal_no_yes(self):
        self.ask("y", tty=False)
        code, out, err = self.main("export", "--exporter", self.exporter)
        self.assertEqual(code, 0, err); self.assertNotIn("sign_statement", self.latest_record())


class CpuName(unittest.TestCase):
    def test_cpu_name_on_x86_power_and_arm(self):
        self.assertEqual(rah.cpu_from_cpuinfo("processor\t: 0\nmodel name\t: AMD Ryzen 9 5950X\n"), "AMD Ryzen 9 5950X")
        self.assertEqual(rah.cpu_from_cpuinfo("processor\t: 0\ncpu\t\t: POWER9 (raw), altivec supported\n"),
                         "POWER9 (raw), altivec supported")
        self.assertEqual(rah.cpu_from_cpuinfo("Processor\t: ARMv7 Processor rev 4 (v7l)\n"), "ARMv7 Processor rev 4 (v7l)")
        self.assertEqual(rah.cpu_from_cpuinfo("cpu MHz\t\t: 2400\n"), "")   # "cpu MHz" is not the name
        self.assertEqual(rah.cpu_from_cpuinfo(""), "")


class AutoExport300K(Export300K):
    """The 300K export is the default path after a whole 300K build (owner, 2026-11-27), and finished builds without
    one are encouraged to run it."""
    def auto(self, exporter=None):
        a = types.SimpleNamespace(exporter=str(exporter or self.fake_exporter()), folder=str(self.folder), logs=None,
                               proof="300k", test_unofficial_folder=True)
        return rah.auto_export(self.ctx(), a)

    def log(self):
        return (self.home / "300k/logs/build.log").read_text() if (self.home / "300k/logs/build.log").exists() else ""

    def test_runs_after_a_whole_build_with_the_three_axioms(self):
        self.build()
        self.assertEqual(self.auto(), "done")
        self.assertEqual(self.rec()["export_sha256"], hashlib.sha256(self.OUT).hexdigest())
        self.assertIn("exporting it now", self.log())
        self.assertEqual(self.auto(), "")                          # already exported: never again

    def test_not_after_a_partial_build_or_other_axioms(self):
        self.build(whole=False)
        self.assertEqual(self.auto(), "")
        self.build(axioms=FIVE.replace("Quot.sound", "sorryAx"))
        self.assertEqual(self.auto(), "")
        self.assertFalse(list((self.home / "300k").glob("records/*.json")) and "export_sha256" in self.rec())

    def test_opt_out_is_respected_and_nudges(self):
        self.build()
        self.ctx().set_conf(export_300k_auto=False)
        self.assertEqual(self.auto(), "opted out")
        self.assertIn(rah.EXPORT_300K_NUDGE, self.log())
        self.assertNotIn("export_sha256", json.dumps([json.loads(p.read_text()) for p in
                                                       (self.home / "300k").glob("records/*.json")]))

    def test_a_failing_export_never_raises(self):
        self.build()
        bad = self.tmp / "bad-l4e"; bad.write_text(f"#!{sys.executable} -I\nimport sys\nsys.exit(3)\n"); bad.chmod(0o755)
        self.assertEqual(self.auto(bad), "failed")
        self.assertIn("did not finish", self.log()); self.assertIn("riemann-at-home export --proof 300k", self.log())

    def test_status_and_update_encourage_until_exported(self):
        from unittest import mock
        self.build()
        code, out, err = self.main("status")
        self.assertIn(rah.EXPORT_300K_NUDGE, out)
        out = self.update()
        self.assertEqual(out.count(rah.EXPORT_300K_NUDGE), 1)
        self.export()
        code, out, err = self.main("status")
        self.assertNotIn(rah.EXPORT_300K_NUDGE, out)
        out = self.update()
        self.assertNotIn(rah.EXPORT_300K_NUDGE, out)

    def update(self):
        from unittest import mock
        buf = io.StringIO()
        with mock.patch.object(rah, "tool_checkout", lambda: "/x"), \
                mock.patch.object(rah, "check_update", lambda ctx: {"available": False}), contextlib.redirect_stdout(buf):
            self.assertEqual(rah.cmd_update(self.ctx(), types.SimpleNamespace(yes=True, folder=str(self.folder),
                                                                              logs=None, proof="300k")), 0)
        return buf.getvalue()

    def test_wording_names_the_badge_accurately(self):
        self.assertIn("300K EXPORT REPRODUCED badge", rah.EXPORT_300K_NUDGE)
        self.assertIn("once three builders' exports agree", rah.EXPORT_300K_NUDGE)
        self.assertIn("riemann-at-home export --proof 300k", rah.EXPORT_300K_NUDGE)
        self.assertIn("once three", rah.export_badge_note({"export_sha256": None}))
        self.assertNotIn("once three", rah.export_badge_note({"export_sha256": "ab" * 32}))
        self.build()
        self.assertEqual(self.auto(), "done")
        self.assertIn("300K EXPORT REPRODUCED badge", self.log())          # said after the automatic export too

    def test_build_no_export_flag_is_stored(self):
        from unittest import mock
        self.build()
        with mock.patch.object(rah, "supervisor", lambda ctx: 4242):
            code, out, err = self.main("build", "--no-export")
        self.assertEqual(code, 0, err)
        self.assertIs(self.ctx().conf().get("export_300k_auto"), False)
        self.assertIn(rah.EXPORT_300K_NUDGE, out)
        with mock.patch.object(rah, "supervisor", lambda ctx: 4242):
            self.main("build", "--export")
        self.assertIs(self.ctx().conf().get("export_300k_auto"), True)


class RealSubmit(unittest.TestCase):
    """The real submit path against a local bare repo as upstream and a fake `gh` (no network, no GitHub)."""
    BID = "0123456789abcdef"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=TMP, prefix="t-"))
        self.up = self.tmp / "upstream.git"
        seed = self.tmp / "seed"; seed.mkdir()
        self.git(seed, "init", "-q", "-b", "main")
        (seed / "README.md").write_text("upstream\n"); (seed / "submissions/someone").mkdir(parents=True)
        (seed / "submissions/someone/aaaaaaaaaaaaaaaa.json").write_text("{}\n")
        self.git(seed, "add", "-A"); self.git(seed, "commit", "-q", "-m", "init")
        subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(self.up)], check=True)
        self.seed = seed; self.git(seed, "remote", "add", "origin", str(self.up))
        bindir = self.tmp / "bin"; bindir.mkdir()
        (bindir / "gh").write_text(FAKE_GH.replace("PYTHON", sys.executable)); (bindir / "gh").chmod(0o755)
        self.home = self.tmp / "h"; self.home.mkdir()
        self.env = {**os.environ, "RAH_HOME": str(self.home), "PATH": f"{bindir}:{os.environ['PATH']}",
                    "FAKE_GH_LOG": str(self.tmp / "gh.log"), "FAKE_GH_STATE": str(self.tmp / "gh.json"),
                    "FAKE_GH_LOGIN": "test-volunteer", "FAKE_UPSTREAM": str(self.up),
                    "FAKE_GH_UPSTREAM_NAME": "riemann-at-home/riemann-at-home", "FAKE_FORK": str(self.tmp / "fork.git"),
                    "GIT_CONFIG_GLOBAL": str(self.tmp / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"}
        (self.tmp / "gitconfig").write_text("")
        (self.home / "config.json").write_text(json.dumps({"consent": {"agreed": "2026-11-21T00:00:00Z"}}))   # said yes
        self.rec_path = self.tmp / "rec.json"
        self.rec = Fast._valid_record(None, self.rec_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, repo, *args):
        idn = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        return subprocess.run(["git", "-C", str(repo), *idn, *args], check=True, capture_output=True, text=True).stdout

    def submit(self, *extra, check=True, **env):
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "submit", "--record", str(self.rec_path), *extra],
                           capture_output=True, text=True, env={**self.env, **env}, timeout=120)
        if check and r.returncode != 0:
            raise AssertionError(f"exit {r.returncode}\n{r.stdout}\n{r.stderr}")
        return r

    def gh_calls(self):
        p = self.tmp / "gh.log"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def prs(self):
        return json.loads((self.tmp / "gh.json").read_text())["prs"]

    def branch_commits(self, bare, branch=f"rah/{BID}"):
        return self.git(bare, "log", "--format=%an <%ae>|%s", f"main..{branch}").splitlines()

    def changed_files(self, bare, branch=f"rah/{BID}"):
        return self.git(bare, "diff", "--name-only", f"main...{branch}").split()

    def test_push_access_first_update_unchanged_and_main_moves(self):
        r = self.submit()
        self.assertIn("opened https://github.com/riemann-at-home/riemann-at-home/pull/1", r.stdout)
        rel = f"submissions/test-volunteer/{self.BID}.json"
        self.assertTrue((self.home / "repo/.git").exists(), "the tool's own clone")
        self.assertEqual(self.changed_files(self.up), [rel])                     # never touches anything else
        self.assertEqual(self.branch_commits(self.up),
                         [f"test-volunteer <test-volunteer@users.noreply.github.com>|update: {self.rec['modules_compiled']} modules"])
        self.assertEqual(json.loads(self.git(self.up, "show", f"rah/{self.BID}:{rel}")), self.rec)
        [pr] = self.prs()
        self.assertEqual(pr["head"], f"riemann-at-home:rah/{self.BID}")         # pushed to upstream directly
        self.assertEqual(pr["title"], f"Riemann@home build {self.BID} (test-volunteer)")
        self.assertIn("modules compiled: 58,396 / 175,187", pr["body"]); self.assertIn("Apple M5 Max", pr["body"])
        st = json.loads((self.home / "config.json").read_text())["pr"]
        self.assertEqual((st["number"], st["url"], st["state"], st["final_sent"]),
                         (1, "https://github.com/riemann-at-home/riemann-at-home/pull/1", "open", False))
        self.assertFalse((self.tmp / "fork.git").exists())
        # same record again: nothing to do (no commit, no push, no PR)
        before = self.git(self.up, "rev-parse", f"rah/{self.BID}")
        r = self.submit()
        self.assertIn("nothing new since the last push", r.stdout)
        self.assertEqual(self.git(self.up, "rev-parse", f"rah/{self.BID}"), before)
        # upstream main moves on (another merge), and the build grows: reset onto main, one commit, force-push
        (self.seed / "data.json").write_text("{}\n"); self.git(self.seed, "add", "-A")
        self.git(self.seed, "commit", "-q", "-m", "bot: data.json"); self.git(self.seed, "push", "-q", "origin", "main")
        bits = [i % 2 == 0 for i in range(rah.N_MODULES)]
        rec2 = {**self.rec, "bitmap_b64": rah.encode_bitmap(bits), "modules_compiled": sum(bits),
                "recorded": "2026-11-21T10:10:02Z"}
        self.rec_path.write_text(json.dumps(rec2))
        r = self.submit()
        self.assertIn("updated https://github.com/riemann-at-home/riemann-at-home/pull/1", r.stdout)
        self.assertEqual(self.branch_commits(self.up), [f"test-volunteer <test-volunteer@users.noreply.github.com>|update: {sum(bits)} modules"])
        self.assertEqual(self.changed_files(self.up), [rel])
        self.assertEqual(self.git(self.up, "merge-base", "main", f"rah/{self.BID}"), self.git(self.up, "rev-parse", "main"))
        self.assertEqual(len(self.prs()), 1, "one PR for the build's whole life")
        self.assertEqual(sum(1 for c in self.gh_calls() if c[:2] == ["pr", "create"]), 1)

    def test_times_only_change_pushed_at_most_every_5_min(self):
        self.submit()
        head = lambda: self.git(self.up, "rev-parse", f"rah/{self.BID}")
        first = head()
        self.rec_path.write_text(json.dumps({**self.rec, "recorded": "2026-11-21T09:20:02Z"}))   # only times changed
        r = self.submit(); self.assertIn("only times changed", r.stdout); self.assertEqual(head(), first)
        cfg = json.loads((self.home / "config.json").read_text()); cfg["pr"]["pushed_at"] -= 301
        (self.home / "config.json").write_text(json.dumps(cfg))
        r = self.submit(); self.assertIn("updated", r.stdout); self.assertNotEqual(head(), first)
        second = head()
        bits = [i % 7 == 0 for i in range(rah.N_MODULES)]                        # modules changed: push right away
        self.rec_path.write_text(json.dumps({**self.rec, "bitmap_b64": rah.encode_bitmap(bits), "modules_compiled": sum(bits)}))
        r = self.submit(); self.assertIn("updated", r.stdout); self.assertNotEqual(head(), second)

    def test_interval_setting_and_companion_for_older_build(self):
        cli_ = lambda *a: subprocess.run([sys.executable, "-I", str(SCRIPT), *a], capture_output=True, text=True,
                                         env=self.env, timeout=60)
        r = cli_("submit", "--interval", "10"); self.assertEqual(r.returncode, 1); self.assertIn("at least 30", r.stderr)
        cli_("submit", "--interval", "30")
        ctx = rah.Ctx(type("A", (), {"folder": None, "logs": None})())
        os.environ["RAH_HOME"] = str(self.home)
        try:
            ctx = rah.Ctx(type("A", (), {"folder": None, "logs": None})())
            self.assertEqual(rah.autosubmit_interval(ctx), 30)
            ctx.set_conf(submit={"interval": 5}); self.assertEqual(rah.autosubmit_interval(ctx), 30)    # minimum
            ctx.set_conf(submit={}); self.assertEqual(rah.autosubmit_interval(ctx), rah.AUTOSUBMIT_SECONDS)
        finally:
            del os.environ["RAH_HOME"]
        # a running build from an older version (no supervisor.features): enable-auto starts the interval companion
        logs = self.home / "logs"; logs.mkdir(exist_ok=True)
        sup = subprocess.Popen(["sh", "-c", f"echo $$ > {logs}/build.pid; sleep 120; true", "sh", "_run"])
        try:
            for _ in range(50):
                if (logs / "build.pid").exists() and (logs / "build.pid").read_text().strip():
                    break
                time.sleep(0.1)
            r = cli_("submit", "--enable-auto", "--interval", "30")
            self.assertIn("every 30 s", r.stdout)
            pid = int((logs / "autosubmit-loop.pid").read_text())
            self.assertTrue(rah.pid_alive(pid, "_autosubmit_loop"))
            cli_("submit", "--enable-auto")                                 # no second companion
            self.assertEqual(int((logs / "autosubmit-loop.pid").read_text()), pid)
            os.kill(pid, 15)
            # a current supervisor marks itself: no companion (it rereads the interval itself)
            (logs / "autosubmit-loop.pid").unlink()
            (logs / "supervisor.features").write_text(f"{sup.pid} autosubmit-v2\n")
            cli_("submit", "--enable-auto")
            self.assertFalse((logs / "autosubmit-loop.pid").exists())
        finally:
            sup.kill(); sup.wait()

    def test_no_push_access_uses_fork(self):
        r = self.submit(FAKE_GH_PUSH="false")
        fork = self.tmp / "fork.git"
        self.assertTrue(fork.exists())
        self.assertEqual(self.changed_files(fork), [f"submissions/test-volunteer/{self.BID}.json"])
        self.assertNotIn(f"rah/{self.BID}", self.git(self.up, "branch", "--list"))   # nothing pushed upstream
        self.assertEqual(self.prs()[0]["head"], f"test-volunteer:rah/{self.BID}")
        self.assertEqual(self.prs()[0]["repo"], "riemann-at-home/riemann-at-home")

    def test_commit_identity_only_noreply_email(self):
        (self.tmp / "gitconfig").write_text("[user]\n\tname = Ada Builder\n\temail = ada@example.com\n")
        self.submit()
        self.assertEqual(self.branch_commits(self.up)[0].split("|")[0], "Ada Builder <test-volunteer@users.noreply.github.com>")
        log = self.git(self.up, "log", "--format=%ae %ce", f"rah/{self.BID}", "-1")
        self.assertNotIn("example.com", log)
        (self.tmp / "gitconfig").write_text("[user]\n\tname = Ada Builder\n\temail = 123+ada@users.noreply.github.com\n")
        bits = [i % 5 == 0 for i in range(rah.N_MODULES)]
        self.rec_path.write_text(json.dumps({**self.rec, "bitmap_b64": rah.encode_bitmap(bits), "modules_compiled": sum(bits)}))
        self.submit()
        self.assertEqual(self.branch_commits(self.up)[0].split("|")[0], "Ada Builder <123+ada@users.noreply.github.com>")

    def test_final_then_nothing_more(self):
        self.rec_path.write_text(json.dumps({**self.rec, "final": True}))
        self.submit()
        self.assertTrue(json.loads((self.home / "config.json").read_text())["pr"]["final_sent"])
        r = self.submit(check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("final record was already sent", r.stderr)

    def test_repo_flag_is_dry_run_only(self):
        r = self.submit("--repo", str(self.seed), check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("only for --dry-run", r.stderr)
        self.assertFalse(self.gh_calls())

    def test_workflow_scope_refusal_is_explained_and_shown_in_status(self):
        """Issue #16: GitHub refuses a push carrying the bot's workflow files when the gh login lacks the `workflow`
        permission. The tool must say exactly how to fix it, and `status` must show updates are failing."""
        hook = self.up / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\necho 'refusing to allow an OAuth App to create or update workflow "
                        "`.github/workflows/rahbot.yml` without `workflow` scope' >&2\nexit 1\n"); hook.chmod(0o755)
        r = self.submit(check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("gh auth refresh -h github.com -s workflow", r.stderr)
        recs = self.home / "records"; recs.mkdir(exist_ok=True); shutil.copy(self.rec_path, recs / "29991231T000000Z.json")
        cfg = json.loads((self.home / "config.json").read_text()); cfg["submit"] = {"auto": True}
        (self.home / "config.json").write_text(json.dumps(cfg))
        auto = lambda: subprocess.run([sys.executable, "-I", "-c", f"""
import importlib.machinery, importlib.util, argparse, sys
l = importlib.machinery.SourceFileLoader("rah", {str(SCRIPT)!r}); s = importlib.util.spec_from_loader("rah", l)
rah = importlib.util.module_from_spec(s); l.exec_module(rah)
rah.make_record = lambda ctx, a: (_ for _ in ()).throw(rah.Fail("skip"))   # keep the valid latest record
a = argparse.Namespace(cmd="record", folder=None, logs=None, test_unofficial_folder=True)
sys.exit(rah.cmd_autosubmit(rah.Ctx(a), a))
"""], capture_output=True, text=True, env=self.env, timeout=120)
        status = lambda: subprocess.run([sys.executable, "-I", str(SCRIPT), "status"], capture_output=True, text=True,
                                        env=self.env, timeout=60).stdout
        self.assertIn("gh auth refresh", auto().stdout)
        self.assertIn("submit    FAILING since", status()); self.assertIn("-s workflow", status())
        hook.unlink()                                                     # the volunteer ran gh auth refresh
        self.assertIn("opened https://github.com/", auto().stdout)
        self.assertIn("submit    last update sent", status())

    def test_autosubmit_off_on_errors_never_fail(self):
        fake_folder(self.tmp / "p")
        run = lambda **env: subprocess.run([sys.executable, "-I", str(SCRIPT), "_autosubmit", "--folder", str(self.tmp / "p"),
                                            "--test-unofficial-folder"], capture_output=True, text=True,
                                           env={**self.env, **env}, timeout=120)
        r = run()
        self.assertEqual(r.returncode, 0); self.assertIn("auto-submit is off", r.stdout)
        self.assertFalse(self.gh_calls())
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "submit", "--enable-auto"], capture_output=True,
                           text=True, env=self.env, timeout=60)
        self.assertIn("auto-submit on", r.stdout)
        self.assertEqual(json.loads((self.home / "config.json").read_text())["submit"],
                         {"auto": True, "upstream": "riemann-at-home/riemann-at-home"})
        # on: tries for real. Unofficial test records are refused by the record check, network errors are logged;
        # either way exit 0 so the build goes on
        r = run()
        self.assertEqual(r.returncode, 0); self.assertIn("auto-submit: ", r.stdout); self.assertIn("not a valid", r.stdout)
        r = run(FAKE_GH_FAIL="1")
        self.assertEqual(r.returncode, 0); self.assertIn("auto-submit: ", r.stdout)
        r = run(PATH="/usr/bin:/bin:/usr/sbin:/sbin")                         # gh missing
        self.assertEqual(r.returncode, 0); self.assertIn("auto-submit: ", r.stdout)
        # the real path through the same entry point, with a valid record as the latest
        recs = self.home / "records"; shutil.copy(self.rec_path, recs / "29991231T000000Z.json")
        ns = subprocess.run([sys.executable, "-I", "-c", f"""
import importlib.machinery, importlib.util, argparse, sys
l = importlib.machinery.SourceFileLoader("rah", {str(SCRIPT)!r}); s = importlib.util.spec_from_loader("rah", l)
rah = importlib.util.module_from_spec(s); l.exec_module(rah)
rah.make_record = lambda ctx, a: (_ for _ in ()).throw(rah.Fail("skip"))   # keep the valid latest record
a = argparse.Namespace(cmd="record", folder=None, logs=None, test_unofficial_folder=True)
sys.exit(rah.cmd_autosubmit(rah.Ctx(a), a))
"""], capture_output=True, text=True, env=self.env, timeout=120)
        self.assertEqual(ns.returncode, 0, ns.stderr); self.assertIn("opened https://github.com/", ns.stdout)
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "submit", "--disable-auto"], capture_output=True,
                           text=True, env=self.env, timeout=60)
        self.assertFalse(json.loads((self.home / "config.json").read_text())["submit"]["auto"])

    def test_older_supervisor_record_call_submits_when_enabled(self):
        """A build started before `_autosubmit` existed runs `record` every 10 min; with auto on, that submits."""
        fake_folder(self.tmp / "p")
        logs = self.home / "logs"; logs.mkdir()
        (self.home / "config.json").write_text(json.dumps({"submit": {"auto": True, "upstream": "riemann-at-home/riemann-at-home"}}))
        cmd = shlex_join([sys.executable, "-I", str(SCRIPT), "record", "--folder", str(self.tmp / "p"), "--logs", str(logs),
                          "--test-unofficial-folder"])
        # a stand-in supervisor: a shell whose command line contains " _run" and whose pid is in build.pid
        r = subprocess.run(["sh", "-c", f"echo $$ > {logs}/build.pid; {cmd}; true", "sh", "_run"], capture_output=True,
                           text=True, env=self.env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("auto-submit: ", r.stdout)                              # it tried (test record: refused)
        r = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, env=self.env, timeout=120)
        self.assertNotIn("auto-submit", r.stdout)                             # a manual `record` never submits


def shlex_join(parts):
    import shlex
    return shlex.join(map(str, parts))


@unittest.skipUnless(REAL.exists(), "no real build folder on this machine")
class RealFolderReadOnly(unittest.TestCase):
    """Reads the real build folder; never writes to it."""
    home = TMP / "real-home"

    def test_record_real_folder(self):
        shutil.rmtree(self.home, ignore_errors=True)
        legacy = Path.home() / "rh-lean/logs/shared-build"
        args = ["record"] + (["--logs", legacy] if legacy.exists() else [])
        r = cli(*args, home=self.home, timeout=3600)
        out = Path(r.stdout.strip().splitlines()[-1])
        text = out.read_text()
        assert_private(self, text)
        rec = json.loads(text)
        self.assertEqual(rec["build_folder"], str(REAL))
        bits = rah.decode_bitmap(rec["bitmap_b64"], rah.N_MODULES)
        self.assertEqual(sum(bits), rec["modules_compiled"])
        self.assertGreater(rec["modules_compiled"], 3000)
        self.assertEqual(rah.validate_record(rec), [])
        shutil.copy(out, TMP / "sample-real-record.json")

    def test_status_real_folder(self):
        r = cli("status", home=self.home)
        self.assertRegex(r.stdout, r"compiled  [\d,]+ / 175,187 modules")

    def test_build_refuses_while_outside_build_runs(self):
        ctx = rah.Ctx(type("A", (), {"folder": None, "logs": None})())
        if not rah.outside_build(ctx):
            self.skipTest("no outside build running right now")
        r = cli("build", home=TMP / "refuse-home", check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("another build is already running", r.stderr)

    def test_page_once(self):
        home = TMP / "page-home"; shutil.rmtree(home, ignore_errors=True)
        r = cli("page", "--once", home=home, timeout=600)
        self.assertIn("http://localhost:8642/", r.stdout)
        d = json.loads((home / "page/data.json").read_text())
        self.assertEqual(d["terrain"]["n"], rah.N_MODULES)
        self.assertGreater(d["terrain"]["local_compiled"], 3000)
        self.assertEqual(len((home / "page/modules.txt").read_text().splitlines()), rah.N_MODULES)
        html = (home / "page/index.html").read_text()
        self.assertIn("https://riemann-at-home.github.io/riemann-at-home/", html)


@unittest.skipUnless(SLOW, "set RAH_SLOW=1")
class Slow(unittest.TestCase):
    def test_1_setup_from_parts_verifies_sha(self):
        if not PARTS.exists():
            self.skipTest("no local parts")
        home = TMP / "parts-home"; folder = TMP / "parts-test/riemann-at-home/lean"
        shutil.rmtree(home, ignore_errors=True); shutil.rmtree(TMP / "parts-test", ignore_errors=True)
        # corrupt parts: refused, nothing unpacked
        bad = TMP / "bad-parts"; bad.mkdir(exist_ok=True)
        for i in range(1, 15):
            (bad / f"part{i:02d}").write_bytes(b"not the archive")
        r = cli("setup", "--folder", folder, "--skip-cache", "--parts-url", f"file://{bad}/part{{nn}}", home=home, check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("expected 9631b4f0", r.stderr)
        self.assertFalse(folder.exists())
        shutil.rmtree(home / "download"); shutil.rmtree(bad)
        # the real parts, through the same download path (file:// instead of https://alpo.ge)
        r = cli("setup", "--folder", folder, "--skip-cache", "--parts-url", f"file://{PARTS}/part{{nn}}", home=home,
                timeout=1800)
        self.assertIn("sha256 9631b4f0", r.stdout)
        self.assertEqual(len(rah.all_modules(folder)), rah.N_MODULES)
        self.assertEqual(rah.sha256_file(home / "download/lean.tar.gz"), rah.ARCHIVE_SHA256)
        shutil.rmtree(TMP / "parts-test"); shutil.rmtree(home)

    def test_2_setup_archive_idempotent(self):
        home = TMP / "home"
        if not SETUP_FOLDER.exists():
            cli("setup", "--archive", ARCHIVE, "--folder", SETUP_FOLDER, home=home, timeout=7200)
        t = time.time()
        r = cli("setup", "--archive", ARCHIVE, "--folder", SETUP_FOLDER, home=home)
        self.assertIn("already here", r.stdout); self.assertIn("already installed", r.stdout)
        self.assertIn("Mathlib compiled cache already here", r.stdout)
        self.assertLess(time.time() - t, 30)
        self.assertEqual(len(rah.all_modules(SETUP_FOLDER)), rah.N_MODULES)

    def test_3_build_start_pause_resume_stop(self):
        home = TMP / "build-home"; shutil.rmtree(home, ignore_errors=True)
        target = "Formalism.MeanHeightDescent.BadRowsNumeric"
        repo = TMP / "autosubmit-repo"; shutil.rmtree(repo, ignore_errors=True); repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        os.environ["RAH_AUTOSUBMIT_SECONDS"] = "20"          # inherited by the supervisor via cli()
        r = cli("build", "--folder", SETUP_FOLDER, "--gentle", "--target", target, "--submit-repo", repo,
                "--test-unofficial-folder", home=home)
        del os.environ["RAH_AUTOSUBMIT_SECONDS"]
        self.assertIn("in the background", r.stdout)
        ctx = rah.Ctx(type("A", (), {"folder": str(SETUP_FOLDER), "logs": str(home / "logs")})())
        pgid = rah.read_pid(ctx.pgid_file)
        for _ in range(120):
            if rah.build_pids(ctx, ("lean",)):
                break
            time.sleep(1)
        self.assertTrue(rah.build_pids(ctx, ("lake",)), "lake did not start")
        lake = rah.build_pids(ctx, ("lake",))[0]
        ni = subprocess.run(["ps", "-o", "nice=", "-p", str(lake)], capture_output=True, text=True).stdout.strip()
        self.assertEqual(ni, "19")
        self.assertIn("running, gentle", cli("status", "--folder", SETUP_FOLDER, home=home).stdout)
        r2 = cli("build", "--folder", SETUP_FOLDER, home=home)
        self.assertIn("already running", r2.stdout)
        cli("pause", "--folder", SETUP_FOLDER, home=home)
        time.sleep(1)
        states = {s for _, g, s, _ in rah.ps_table() if g == pgid}
        self.assertTrue(states and all(s.startswith("T") for s in states), states)
        self.assertIn("PAUSED", cli("status", "--folder", SETUP_FOLDER, home=home).stdout)
        cli("resume", "--folder", SETUP_FOLDER, home=home)
        time.sleep(1)
        states = {s for _, g, s, _ in rah.ps_table() if g == pgid}
        self.assertFalse(any(s.startswith("T") for s in states), states)
        cli("build", "--full", "--folder", SETUP_FOLDER, home=home)
        self.assertIn("running, full", cli("status", "--folder", SETUP_FOLDER, home=home).stdout)
        time.sleep(5)
        cli("stop", "--folder", SETUP_FOLDER, home=home)
        time.sleep(1)
        self.assertFalse([1 for _, g, _, _ in rah.ps_table() if g == pgid], "build processes left behind")
        st = cli("status", "--folder", SETUP_FOLDER, home=home).stdout
        self.assertIn("not running", st)
        status = (home / "logs/status.txt").read_text()
        for k in ("START", "PAUSE", "RESUME", "MODE_FULL", "STOP_REQUESTED", "BUILD_EXIT="):
            self.assertIn(k, status)
        self.assertTrue((home / "logs/build.log").exists())   # lake prints only when a module finishes
        self.assertFalse((home / "logs/build.pid").exists())
        log = (home / "logs/autosubmit.log").read_text()
        self.assertIn("--- autosubmit (progress)", log)
        self.assertFalse((repo / "submissions").exists(), "autosubmit must stay a dry run")
        _, busy = rah.busy_seconds(ctx, running=False)
        self.assertGreater(busy, 3)


def fake_300k(root: Path, n=6, compiled=None, commit=None, tree=None):
    """A miniature 300K build folder (the grh/ edition): its toolchain, Mathlib, source file, axiom script."""
    P = rah.PROOFS["300k"]
    (root / "src/Lib").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "lean-toolchain").write_text(P["toolchain"] + "\n")
    (root / "lake-manifest.json").write_text(json.dumps({"packages": [{"name": "mathlib", "rev": P["mathlib_rev"]}]}))
    (root / "scripts/PrintAxioms.lean").write_text(rah.AUDIT_LEAN)
    (root / rah.SOURCE_FILE).write_text(json.dumps({"commit": commit or P["source"], "tree": tree or P["tree"]}))
    mods = [f"Lib.M{i}" for i in range(n - 2)] + ["Main", "Statements"]
    lib = root / ".lake/build/lib/lean"
    for i, m in enumerate(mods):
        (root / "src" / (m.replace(".", "/") + ".lean")).write_text(f"-- {m}\n")
        if compiled is None or i in compiled:
            o = lib / (m.replace(".", "/") + ".olean"); o.parent.mkdir(parents=True, exist_ok=True)
            o.write_bytes(m.encode()); o.with_suffix(".trace").write_text("{}")
    return sorted(mods, key=lambda m: m.encode())


PINNED_300K = "72fead102f663d5c7a407964a13dc0cf9d977207"     # CONTRACT "Several proofs" (literal: tests the tool's table)
THEOREMS_300K = ["riemannHypothesis", "riemannZeta_eq_zero_re", "LFunction_ne_zero_of_half_lt_re", "LFunction_eq_zero_re",
                 "LFunction_eq_zero_re_of_isPrimitive"]
FIVE = "".join(f"'{t}' depends on axioms: [propext, Classical.choice, Quot.sound]\n" for t in THEOREMS_300K)


class Proof300K(unittest.TestCase):
    """The second proof, 300K (CONTRACT "Several proofs", 2026-11-25): setup asks which proof (default 300K), records
    say "proof": "300k", its state lives apart from 17M's, and 17M computers keep working as before."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=TMP, prefix="k-"))
        self.home = self.tmp / "h"; self.home.mkdir()
        self.env = unittest.mock.patch.dict(os.environ, {"RAH_HOME": str(self.home), "RAH_NO_STATS": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ns(self, **kw):
        return types.SimpleNamespace(**{"folder": None, "logs": None, "proof": None, "archive": None,
                                        "parts_url": rah.PART_URL, **kw})

    def choose(self, tty, answer="", **kw):
        a = self.ns(**kw)
        ctx = rah.Ctx(a)
        buf = io.StringIO()
        stdin = io.StringIO(answer + "\n"); stdin.isatty = lambda: tty
        with contextlib.redirect_stdout(buf), unittest.mock.patch("sys.stdin", stdin), \
                unittest.mock.patch("builtins.input", lambda prompt="": answer):
            got = rah.setup_choice(ctx, a)
        return got, buf.getvalue()

    def test_setup_question_default_and_choices(self):
        got, out = self.choose(tty=False)
        self.assertEqual(got, ["300k"], "no terminal: the new proof")
        self.assertIn("Which proof do you want to build?", out)
        self.assertIn("1) The new proof  [300K]  recommended", out)
        self.assertIn("2) The original proof  [17M]  the big challenge", out)
        self.assertIn("3) Both  [17M] [300K]  ranks highest", out)
        self.assertIn("riemann-at-home setup --proof 17m", out)
        self.assertNotIn("—", out)                     # no em dashes in what volunteers read
        self.assertEqual(self.choose(tty=True, answer="")[0], ["300k"], "Enter = 1")
        self.assertEqual(self.choose(tty=True, answer="2")[0], ["17m"])
        self.assertEqual(self.choose(tty=True, answer="3")[0], ["300k", "17m"], "both: the new proof first")
        self.assertEqual(self.choose(tty=False, proof="both")[0], ["300k", "17m"])
        self.assertEqual(self.choose(tty=False, proof="17m")[0], ["17m"])
        self.assertEqual(self.choose(tty=False, archive="/x/lean.tar.gz")[0], ["17m"], "the 17M archive means 17M")

    def test_setup_keeps_a_17m_computer_on_17m(self):
        (self.home / "build_id").write_text("0123456789abcdef\n")         # set up before setup asked
        got, out = self.choose(tty=False)
        self.assertEqual(got, ["17m"]); self.assertNotIn("Which proof", out)
        self.assertIn("setup --proof 300k", out)
        ctx = rah.Ctx(self.ns())
        self.assertEqual((ctx.proof, ctx.home, ctx.folder), ("17m", self.home, rah.fixed_folder("17m")))

    def test_state_apart_and_shared_choices(self):
        c17, c3 = rah.Ctx(self.ns(proof="17m")), rah.Ctx(self.ns(proof="300k"))
        self.assertEqual(c3.home, self.home / "300k"); self.assertEqual(c3.logs, self.home / "300k/logs")
        self.assertEqual(str(c3.folder), rah.PROOFS["300k"]["folders"][os.uname().sysname])
        self.assertNotEqual(c17.build_id(), c3.build_id())                 # one build_id per proof
        self.assertEqual(c3.build_id(), rah.Ctx(self.ns(proof="300k")).build_id())
        c17.set_conf(consent={"agreed": "2026-11-25T00:00:00Z", "login": "x"}, display={"display_name": "Ada"},
                     pr={"build_id": c17.build_id(), "state": "open", "number": 5})
        self.assertTrue(rah.has_consent(c3))                               # agreed once, for the person
        self.assertEqual(c3.conf()["display"], {"display_name": "Ada"})
        self.assertIsNone(c3.conf().get("pr"))                            # each build has its own PR
        c3.set_conf(pr={"build_id": c3.build_id(), "state": "open", "number": 9}, submit={"auto": True})
        self.assertEqual(c17.conf()["pr"]["number"], 5); self.assertEqual(c17.conf()["submit"], {"auto": True})
        self.assertEqual(json.loads((self.home / "300k/config.json").read_text())["pr"]["number"], 9)
        # commands without --proof: what setup chose; 17M before that
        self.assertEqual(rah.Ctx(self.ns()).proof, "17m")
        c17.set_conf(proofs={"active": "300k", "next": []})
        self.assertEqual(rah.Ctx(self.ns()).proof, "300k")
        f17 = self.tmp / "p17"; fake_folder(f17)
        self.assertEqual(rah.Ctx(self.ns(folder=str(f17))).proof, "17m", "a 17M folder is a 17M build")

    def test_record_shape_300k_and_17m_unchanged(self):
        mods = fake_300k(self.tmp / "g", compiled={0, 1, 4})
        r = cli("record", "--proof", "300k", "--folder", self.tmp / "g", "--test-unofficial-folder", home=self.home)
        out = Path(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out.parent, self.home / "300k/records")
        rec = json.loads(out.read_text())
        self.assertEqual([k for k in rec if k not in rah.OPTIONAL_KEYS], rah.record_keys("300k"))
        self.assertEqual(rec["proof"], "300k"); self.assertNotIn("archive_sha256", rec)
        self.assertEqual(rec["source_commit"], PINNED_300K)
        self.assertEqual((rec["toolchain"], rec["mathlib_rev"]), ("leanprover/lean4:v4.35.0", "56a005855ea17e0b0958f73ec801ae140b0a1679"))
        self.assertEqual(rec["modules_compiled"], 3); self.assertFalse(rec["whole_proof"])
        self.assertEqual(sum(rah.decode_bitmap(rec["bitmap_b64"], len(mods))), 3)
        # whole: every module, and the axiom check printed all five theorems
        shutil.rmtree(self.tmp / "g"); fake_300k(self.tmp / "g")
        (self.home / "300k/logs").mkdir(parents=True, exist_ok=True)
        (self.home / "300k/logs/axioms.log").write_text(FIVE.splitlines(True)[0])     # only riemannHypothesis
        rec = json.loads(Path(cli("record", "--proof", "300k", "--folder", self.tmp / "g", "--test-unofficial-folder",
                                  home=self.home).stdout.strip().splitlines()[-1]).read_text())
        self.assertFalse(rec["whole_proof"], "300K is whole only when all five theorems were checked")
        (self.home / "300k/logs/axioms.log").write_text(FIVE)
        rec = json.loads(Path(cli("record", "--proof", "300k", "--folder", self.tmp / "g", "--test-unofficial-folder",
                                  home=self.home).stdout.strip().splitlines()[-1]).read_text())
        self.assertTrue(rec["whole_proof"]); self.assertEqual(rec["axioms"], rah.EXPECTED_AXIOMS)
        # 17M: no "proof" key, the same keys as ever, state at the top of RAH_HOME
        fake_folder(self.tmp / "p")
        r = cli("record", "--folder", self.tmp / "p", "--test-unofficial-folder", home=self.home)
        out = Path(r.stdout.strip().splitlines()[-1]); rec17 = json.loads(out.read_text())
        self.assertEqual(out.parent, self.home / "records")
        self.assertEqual([k for k in rec17 if k not in rah.OPTIONAL_KEYS], rah.RECORD_KEYS)
        self.assertNotIn("proof", rec17); self.assertEqual(rec17["archive_sha256"], rah.ARCHIVE_SHA256)
        self.assertNotEqual(rec17["build_id"], rec["build_id"])

    def test_submit_300k_same_pr_path(self):
        """300K is submitted like 17M (the bot ranks it since 2026-11-25): one PR per build, nothing is held back."""
        fake_300k(self.tmp / "g", compiled={0, 1, 4})
        out = Path(cli("record", "--proof", "300k", "--folder", self.tmp / "g", "--test-unofficial-folder",
                       home=self.home).stdout.strip().splitlines()[-1])
        rec = json.loads(out.read_text()); bid = rec["build_id"]
        P = rah.PROOFS["300k"]; bits = [i % 3 == 0 for i in range(P["n"])]     # as a real 300K build would send it
        rec.update(build_folder=P["folders"]["Darwin"], bitmap_b64=rah.encode_bitmap(bits), modules_compiled=sum(bits))
        out.write_text(json.dumps(rec))
        repo = self.tmp / "repo"; repo.mkdir()
        g = ["git", "-C", str(repo)]
        subprocess.run(g + ["init", "-q", "-b", "main"], check=True)
        subprocess.run(g + ["remote", "add", "origin", "https://github.com/example-org/riemann-at-home.git"], check=True)
        subprocess.run(g + ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q",
                            "--allow-empty", "-m", "init"], check=True)
        r = cli("submit", "--proof", "300k", "--repo", repo, "--record", out, "--login", "test-volunteer", "--dry-run",
                "--no-gh-check", home=self.home)
        self.assertNotIn("submitted yet", r.stdout)
        self.assertIn("DRY RUN", r.stdout)
        self.assertIn(f"as:     submissions/test-volunteer/{bid}.json on branch rah/{bid}", r.stdout)
        self.assertIn("gh pr create", r.stdout)
        self.assertFalse((repo / "submissions").exists())

    def test_record_refuses_another_source(self):
        fake_300k(self.tmp / "g", commit="ce4eb6fb2591d62095c5aa61b7a21414c7385bd5")
        ctx = rah.Ctx(self.ns(proof="300k", folder=str(self.tmp / "g")))
        with unittest.mock.patch.object(rah, "fixed_folder", lambda proof="17m": self.tmp / "g"):
            with self.assertRaises(rah.Fail) as e:
                rah.make_record(ctx, self.ns(test_unofficial_folder=False))
        self.assertIn("expected 72fead10", str(e.exception))

    def test_validate_300k_matches_the_bot(self):
        n = rah.PROOFS["300k"]["n"]
        bits = [True] * n
        rec = {"format": rah.FORMAT, "tool": rah.TOOL, "proof": "300k", "source_commit": rah.GRH_COMMIT,
               "toolchain": "leanprover/lean4:v4.35.0", "mathlib_rev": "56a005855ea17e0b0958f73ec801ae140b0a1679",
               "build_folder": "/Users/Shared/riemann-at-home/grh", "build_id": "0123456789abcdef",
               "machine": {"os": "Darwin 25.4.0", "arch": "arm64", "cpu": "Apple M3 Pro", "cores": 12},
               "started": "2026-11-25T10:00:00Z", "recorded": "2026-11-25T11:10:00Z", "busy_seconds": 3600,
               "modules_compiled": n, "bitmap_b64": rah.encode_bitmap(bits), "olean_digest": "0" * 64,
               "whole_proof": True, "axioms": rah.EXPECTED_AXIOMS, "final": False}
        self.assertEqual(rah.validate_record(rec), [])
        for k, v, msg in (("toolchain", rah.TOOLCHAIN, "toolchain"), ("source_commit", "0" * 40, "source_commit"),
                          ("build_folder", "/Users/Shared/riemann-at-home/lean", "fixed folder"),
                          ("export_sha256", rah.EXPORT_SHA256, "export"), ("proof", "17m", "proof"), ("proof", "1b", "proof")):
            self.assertTrue(any(msg in e for e in rah.validate_record({**rec, k: v})), (k, rah.validate_record({**rec, k: v})))
        d = {**rec, "bitmap_b64": rah.encode_bitmap([True] * rah.N_MODULES), "modules_compiled": rah.N_MODULES}
        self.assertTrue(any("bitmap" in e for e in rah.validate_record(d)), "a 17M-sized bitmap is not a 300K one")
        bot = Path(__file__).resolve().parents[2] / "bot/rahbot"
        if bot.exists() and "PROOFS" in bot.read_text():                   # the bot agrees (once it knows 300K)
            rb = importlib.machinery.SourceFileLoader("rahbot_cli_test", str(bot)).load_module()
            with contextlib.redirect_stdout(io.StringIO()):
                rej = rb.check_record(rec, "kim", "submissions/kim/0123456789abcdef.json", None,
                                      now=rb.parse_ts("2026-11-26T00:00:00Z"))[0]
            self.assertEqual(rej, [])

    def test_recheck_is_17m_only(self):
        """300K has an optional export since 2026-11-27, but no reference to re-check yet."""
        r = cli("recheck", "--nanoda", "--proof", "300k", home=self.home, check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("for the 17M proof only", r.stderr)
        r = cli("export", "--proof", "300k", home=self.home, check=False)     # not set up here: it says why
        self.assertEqual(r.returncode, 1); self.assertNotIn("for the 17M proof only", r.stderr)
        r = cli("build", "--proof", "both", home=self.home, check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("setup only", r.stderr)

    def test_others_text_both_proofs(self):
        data = {"leaderboard": [
            {"whole_proof": True, "build_hours": 9.0, "machine": "AMD Ryzen 9 5950X", "export": None,
             "proofs": {"17m": {"whole": True, "build_hours": 9.0}, "300k": {"whole": True, "build_hours": 0.4, "machine": "AMD Ryzen 9 5950X"}}},
            {"whole_proof": True, "build_hours": 64.3, "machine": "Apple M5 Max", "export": None},
            {"whole_proof": False, "build_hours": None, "machine": "Apple M3 Pro",
             "proofs": {"300k": {"whole": True, "build_hours": 1.2, "machine": "Apple M3 Pro"}}},
            {"whole_proof": False, "build_hours": None, "machine": "Apple M4",
             "proofs": {"300k": {"whole": False, "build_hours": None, "machine": "Apple M4"}}}]}
        t = rah.others_text(data, "Apple M3 Pro")
        self.assertIn("2 whole builds so far", t.splitlines()[0])              # 17M, as before
        self.assertIn("The 300K proof (the new proof): 2 whole builds so far, 0.4 h to 1.2 h", t)
        rows = [l for l in t.split("The 300K proof")[1].splitlines()[2:]]
        self.assertEqual([r.split()[0] for r in rows], ["AMD", "Apple"])          # fastest first
        self.assertTrue(rows[-1].endswith("<- like this computer"))
        self.assertNotIn("Apple M4", t)
        only = rah.others_text({"leaderboard": [data["leaderboard"][2]]})
        self.assertTrue(only.startswith("The 300K proof") and "How long it took others" not in only, only)

    def test_whole_300k_build_runs_its_axiom_check_and_status_shows_both(self):
        """The real supervisor (`_run`) on a fake lake: plain `lake build` (the edition's defaults), then
        `lake env lean scripts/PrintAxioms.lean`; status lists 17M and 300K."""
        g = self.tmp / "g"; mods = fake_300k(g, compiled=set())
        elan = self.tmp / "elan"; (elan / "bin").mkdir(parents=True)
        calls = self.tmp / "calls"
        lake = elan / "bin/lake"
        touch = "; ".join(f"mkdir -p {g}/.lake/build/lib/lean/{os.path.dirname(m.replace('.', '/')) or '.'}; "
                          f"echo x > {g}/.lake/build/lib/lean/{m.replace('.', '/')}.olean; "
                          f"echo x > {g}/.lake/build/lib/lean/{m.replace('.', '/')}.trace" for m in mods)
        five = FIVE.replace("'", "'\\''")
        lake.write_text(f"#!/bin/sh\necho \"$@\" >> {calls}\n"
                        f"case \"$*\" in *build) {touch}; exit 0;; *PrintAxioms.lean) printf '%s' '{five}'; exit 0;; esac\nexit 0\n")
        lake.chmod(0o755)
        env = {**os.environ, "ELAN_HOME": str(elan), "RAH_AUTOSUBMIT": "off", "RAH_SAMPLE_SECONDS": "1",
               "RAH_UPDATE_URL": str(self.tmp / "no-such-repo")}       # no network: the daily update check fails here
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "_run", "--proof", "300k", "--folder", g,
                            "--logs", self.home / "300k/logs"], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = calls.read_text().splitlines()
        self.assertEqual(lines[0], "--no-ansi build", "300K builds the edition's default targets")
        self.assertEqual(lines[1], "--no-ansi env lean scripts/PrintAxioms.lean")
        st = cli("status", "--proof", "300k", "--folder", g, home=self.home).stdout
        self.assertIn(f"compiled  {len(mods)} / 803 modules", st)
        self.assertIn("axioms    ['propext', 'Classical.choice', 'Quot.sound'] (5 theorems)", st)
        # without --proof: every proof set up here, 17M first when it is the default
        rah.Ctx(self.ns(proof="17m")).build_id()
        st = cli("status", home=self.home).stdout
        self.assertIn("proof     17M: the original proof (commands without --proof)", st)
        self.assertIn("proof     300K: the new proof (add --proof 300k)", st)

    def test_both_starts_the_17m_build_when_300k_is_done(self):
        c3 = rah.Ctx(self.ns(proof="300k", folder=str(self.tmp / "g"), logs=str(self.home / "300k/logs")))
        c3.logs.mkdir(parents=True); (c3.logs / "axioms.log").write_text(FIVE); (c3.logs / "mode.txt").write_text("full")
        c3.set_conf(proofs={"active": "300k", "next": ["17m"]})
        f17 = self.tmp / "p17"; fake_folder(f17)
        with unittest.mock.patch.object(rah, "fixed_folder", lambda proof="17m": f17 if proof == "17m" else self.tmp / "g"), \
                unittest.mock.patch.object(rah.subprocess, "Popen") as popen:
            rah.start_next_proof(c3)
        self.assertEqual(popen.call_args[0][0][-4:], ["build", "--full", "--proof", "17m"])
        self.assertEqual(c3.conf()["proofs"], {"active": "17m", "next": []})
        with unittest.mock.patch.object(rah.subprocess, "Popen") as popen:       # nothing more after that
            rah.start_next_proof(c3)
        popen.assert_not_called()

    def test_setup_300k_clones_the_pinned_commit(self):
        """setup --proof 300k from a local stand-in for github.com/lsernau/grh-lean: clone, check out exactly the
        pinned commit, check HEAD and the grh/ tree, move grh/ into the build folder; a wrong commit is refused."""
        up = self.tmp / "grh-lean"; (up / "grh/src/Lib").mkdir(parents=True)
        (up / "grh/lean-toolchain").write_text(rah.PROOFS["300k"]["toolchain"] + "\n")
        (up / "grh/lake-manifest.json").write_text(json.dumps({"packages": [{"name": "mathlib", "rev": rah.PROOFS["300k"]["mathlib_rev"]}]}))
        (up / "grh/src/Lib/A.lean").write_text("-- A\n"); (up / "README.md").write_text("compact edition\n")
        g = lambda *x: subprocess.run(["git", "-C", str(up), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *x],
                                      capture_output=True, text=True, check=True).stdout.strip()
        g("init", "-q", "-b", "main"); g("add", "-A"); g("commit", "-q", "-m", "proof")
        pinned, tree = g("rev-parse", "HEAD"), g("rev-parse", "HEAD:grh")
        (up / "README.md").write_text("later\n"); g("commit", "-q", "-am", "later")    # main moved on
        elan = self.tmp / "elan"; (elan / "bin").mkdir(parents=True)
        for tool, body in (("elan", 'case "$*" in "toolchain list") echo "leanprover/lean4:v4.35.0";; esac'),
                           ("lake", f'echo "$@" >> {self.tmp}/lake-calls')):
            (elan / "bin" / tool).write_text(f"#!/bin/sh\n{body}\nexit 0\n"); (elan / "bin" / tool).chmod(0o755)
        folder = self.tmp / "shared/grh"
        def setup(commit, t):
            a = self.ns(proof="300k", folder=str(folder), source_url=f"file://{up}", skip_cache=False, force_cache=False)
            P = {**rah.PROOFS["300k"], "source": commit, "tree": t}
            buf = io.StringIO()
            with unittest.mock.patch.dict(os.environ, {"ELAN_HOME": str(elan)}), \
                    unittest.mock.patch.dict(rah.PROOFS, {"300k": P}), unittest.mock.patch("sys.stdin", io.StringIO()), \
                    unittest.mock.patch.object(rah, "gh_login", side_effect=rah.Fail("no gh")), \
                    contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                rah.cmd_setup(rah.Ctx(a), a)
            return buf.getvalue()
        with self.assertRaises(rah.Fail):
            setup("0" * 40, tree)                                          # not a commit of that repo
        self.assertFalse(folder.exists())
        out = setup(pinned, tree)
        self.assertIn(f"HEAD {pinned} ok, grh/ tree {tree} ok", out)
        self.assertTrue((folder / "src/Lib/A.lean").exists()); self.assertFalse((folder / "README.md").exists())
        self.assertEqual(json.loads((folder / rah.SOURCE_FILE).read_text())["commit"], pinned)
        self.assertEqual((self.tmp / "lake-calls").read_text().split("\n")[0], "exe cache get", "`lake exe cache get` in grh/")
        self.assertIn("300K build_id", out)
        self.assertEqual(rah.Ctx(self.ns()).proof, "300k", "setup chose 300K: commands without --proof mean it")
        self.assertEqual(list(folder.parent.iterdir()), [folder], "the clone's staging folder is gone")
        again = setup(pinned, tree)
        self.assertIn("proof folder already here at commit", again)

    @unittest.skipUnless(subprocess.run(["git", "-C", str(Path.home() / "grh-lean"), "cat-file", "-e",
                                         PINNED_300K + "^{commit}"], capture_output=True).returncode == 0,
                         "no local clone of grh-lean with the pinned commit")
    def test_pinned_commit_and_tree_are_real(self):
        """Read-only check against a local clone: the pinned commit's grh/ is GRH_TREE and has the 803 modules."""
        src = Path.home() / "grh-lean"
        tree = subprocess.run(["git", "-C", str(src), "rev-parse", f"{rah.GRH_COMMIT}:grh"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(tree, rah.GRH_TREE)
        names = subprocess.run(["git", "-C", str(src), "ls-tree", "-r", "--name-only", rah.GRH_COMMIT, "grh/src"],
                               capture_output=True, text=True).stdout.split()
        mods = sorted((n[8:-5].replace("/", ".") for n in names if n.endswith(".lean")), key=lambda m: m.encode())
        self.assertEqual(len(mods), 803)
        self.assertEqual(hashlib.sha256(("\n".join(mods) + "\n").encode()).hexdigest(), rah.PROOFS["300k"]["modules_sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class Consent(unittest.TestCase):
    """Nothing is posted until the person agrees; the notice says what becomes public."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.home = self.tmp / "h"; self.home.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_notice_says_what_is_public(self):
        n = rah.consent_notice("octocat")
        for part in ("your GitHub account (octocat)", "carry that username", "your name is connected",
                     "OS, chip and number of cores", "GitHub always shows your username", "Nothing is posted until you agree"):
            self.assertIn(part, n)
        self.assertNotIn("anonymous", n.lower())
        self.assertIn("the one `gh` is logged into", rah.consent_notice())

    def test_no_submit_or_auto_without_agreeing(self):
        rp = self.tmp / "r.json"; rp.write_text(json.dumps(Fast._valid_record(None, rp)))
        r = cli("submit", "--record", rp, "--login", "x-y", "--no-gh-check", home=self.home, check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("Nothing is posted until you agree", r.stderr)
        self.assertIn("riemann-at-home submit --agree", r.stderr)
        r = cli("submit", "--enable-auto", home=self.home, check=False)
        self.assertEqual(r.returncode, 1); self.assertIn("Nothing is posted until you agree", r.stderr)

    def test_already_posting_before_consent_counts_as_agreed(self):
        os.environ["RAH_HOME"] = str(self.home)
        try:
            ctx = rah.Ctx(type("A", (), {"folder": None, "logs": str(self.tmp / "logs")})())
            self.assertFalse(rah.has_consent(ctx))
            ctx.set_conf(pr={"build_id": "0123456789abcdef", "number": 7, "state": "open"})
            self.assertTrue(rah.has_consent(ctx))
        finally:
            del os.environ["RAH_HOME"]

    def test_ask_consent_without_terminal_only_prints(self):
        ctx = rah.Ctx(type("A", (), {"folder": None, "logs": str(self.tmp / "logs")})())
        os.environ["RAH_HOME"] = str(self.home)
        try:
            ctx = rah.Ctx(type("A", (), {"folder": None, "logs": str(self.tmp / "logs")})())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), unittest.mock.patch("sys.stdin", io.StringIO("y\n")):
                rah.ask_consent(ctx)
        finally:
            del os.environ["RAH_HOME"]
        self.assertIn("riemann-at-home submit --agree", buf.getvalue())
        self.assertFalse(rah.has_consent(ctx))           # an assistant can't answer for the person


def _toolchain_ready() -> bool:
    elan = rah.elan_bin() / "elan"
    if not elan.exists() or not shutil.which("git"):
        return False
    r = subprocess.run([str(elan), "toolchain", "list"], capture_output=True, text=True)
    return rah.TOOLCHAIN.split(":")[-1] in r.stdout


@unittest.skipUnless(_toolchain_ready(), f"needs elan with {rah.TOOLCHAIN} installed (and network for lean4export)")
class ExportSmoke(unittest.TestCase):
    """The REAL exporter, built exactly as `export` builds it, on a tiny Lean project compiled with the proof's Lean.
    This is the test that would have caught issue #14 on day one; GitHub Actions runs it on every change to cli/."""
    def test_real_exporter_reads_a_tiny_project(self):
        import argparse
        tmp = Path(tempfile.mkdtemp(dir=TMP, prefix="smoke-"))
        try:
            proj = tmp / "lean"; proj.mkdir()
            (proj / "lean-toolchain").write_text(rah.TOOLCHAIN + "\n")
            (proj / "lakefile.toml").write_text('name = "tiny"\ndefaultTargets = ["Tiny"]\n\n[[lean_lib]]\nname = "Tiny"\n')
            (proj / "Tiny.lean").write_text("theorem tiny : 1 + 1 = 2 := rfl\n")
            b = subprocess.run([rah.which("lake") or "lake", "build"], cwd=proj, capture_output=True, text=True, env=rah.lean_env())
            self.assertEqual(b.returncode, 0, b.stdout + b.stderr)
            old = dict(os.environ); os.environ["RAH_HOME"] = str(tmp / "home")
            try:
                ctx = rah.Ctx(argparse.Namespace(folder=str(proj), logs=None))
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    r = rah.export_check(ctx)
            finally:
                os.environ.clear(); os.environ.update(old)
            self.assertTrue(r["ok"], r); self.assertEqual(r["module"], "Tiny")
            self.assertEqual(r["lean_version"], rah.TOOLCHAIN.rsplit(":v", 1)[-1])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


CHECKER_BINS = {"nanoda": os.environ.get("RAH_NANODA") or shutil.which("nanoda_bin"),
                "con-leche": os.environ.get("RAH_CON_LECHE") or shutil.which("con-leche")}


@unittest.skipUnless(_toolchain_ready() and any(CHECKER_BINS.values()),
                     "needs the proof's Lean and a real checker (RAH_NANODA / RAH_CON_LECHE = path to nanoda_bin / con-leche)")
class RecheckSmoke(unittest.TestCase):
    """End to end on a tiny real project: the tool's own lean4export saves the export to a file (saved_export), and
    each REAL checker is run on it exactly as `recheck` runs it (checker_command). A correct export must pass and a
    tampered one (1 + 1 = 3, proved by rfl) must fail: an accept that also accepts nonsense proves nothing."""
    def test_real_checkers_on_a_tiny_export(self):
        import argparse
        from unittest import mock
        tmp = Path(tempfile.mkdtemp(dir=TMP, prefix="recheck-smoke-"))
        old = dict(os.environ)
        try:
            proj = tmp / "lean"; proj.mkdir()
            (proj / "lean-toolchain").write_text(rah.TOOLCHAIN + "\n")
            (proj / "lakefile.toml").write_text('name = "tiny"\ndefaultTargets = ["Main"]\n\n[[lean_lib]]\nname = "Main"\n')
            (proj / "Main.lean").write_text("theorem tiny : 1 + 1 = 2 := rfl\n"
                                            "theorem tiny2 (p q : Prop) (hp : p) (hq : q) : p ∧ q := ⟨hp, hq⟩\n")
            b = subprocess.run([rah.which("lake") or "lake", "build"], cwd=proj, capture_output=True, text=True, env=rah.lean_env())
            self.assertEqual(b.returncode, 0, b.stdout + b.stderr)
            os.environ["RAH_HOME"] = str(tmp / "home")
            ctx = rah.Ctx(argparse.Namespace(folder=str(proj), logs=None)); ctx.logs.mkdir(parents=True, exist_ok=True)
            a = argparse.Namespace(exporter=None)
            with mock.patch.object(rah, "EXPORT_TARGETS", ["tiny", "tiny2"]):
                cmd = rah.exporter_command(ctx, a)                # builds the real lean4export, as `export` does
            ref = subprocess.run(cmd, cwd=proj, capture_output=True, env=rah.lean_env()).stdout
            self.assertTrue(ref.startswith(b'{"meta":'), ref[:200])
            sha = hashlib.sha256(ref).hexdigest()
            with mock.patch.object(rah, "EXPORT_TARGETS", ["tiny", "tiny2"]), mock.patch.object(rah, "EXPORT_SHA256", sha), \
                    mock.patch.object(rah, "EXPORT_BYTES", len(ref)), mock.patch.object(rah, "MIN_FREE_GB", 0), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                good = rah.saved_export(ctx, a)
                self.assertEqual(good.read_bytes(), ref)
                again = rah.saved_export(ctx, a)                  # reused, after checking its hash
            self.assertEqual(again, good)
            lit = b'"natVal":"2"}'
            self.assertEqual(ref.count(lit), 1)
            bad = tmp / "bad" / "proof.ndjson"; bad.parent.mkdir(); bad.write_bytes(ref.replace(lit, b'"natVal":"3"}'))
            for name, exe in CHECKER_BINS.items():
                if not exe:
                    continue
                with self.subTest(checker=name):
                    for export, want_ok in ((good, True), (bad, False)):
                        c = subprocess.run(rah.checker_command(name, exe, export, [], 2), capture_output=True, text=True,
                                           stdin=subprocess.DEVNULL, timeout=600)
                        self.assertEqual(c.returncode == 0, want_ok, f"{name} on {export.parent.name}: exit {c.returncode}\n"
                                         + c.stdout[-1000:] + c.stderr[-1000:])
        finally:
            os.environ.clear(); os.environ.update(old)
            shutil.rmtree(tmp, ignore_errors=True)
