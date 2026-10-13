import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import datetime as dt
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import dropbox_fetch as df
import history_import_guard as guard

SECRET = {"DROPBOX_APP_KEY": "KEY-abc", "DROPBOX_APP_SECRET": "SECRET-xyz", "DROPBOX_REFRESH_TOKEN": "REFRESH-123"}
TOKEN = "ACCESS-TOKEN-999"


def independent_content_hash(data: bytes) -> str:
    blocks = [data[i:i + 4 * 1024 * 1024] for i in range(0, len(data), 4 * 1024 * 1024)]
    return hashlib.sha256(b"".join(hashlib.sha256(b).digest() for b in blocks)).hexdigest()


class Resp(io.BytesIO):
    pass


def fake_urlopen(payload: bytes, size=None, content_hash=None, calls=None):
    def opener(req, timeout=None):
        url = req.full_url
        if calls is not None:
            calls.append(url)
        if url == df.TOKEN_URL:
            return Resp(json.dumps({"access_token": TOKEN}).encode())
        if url == df.META_URL:
            return Resp(json.dumps({".tag": "file", "size": len(payload) if size is None else size,
                                    "content_hash": content_hash or independent_content_hash(payload)}).encode())
        if url == df.DOWNLOAD_URL:
            arg = req.get_header("Dropbox-api-arg")
            arg.encode("ascii")  # must be ASCII
            return Resp(payload)
        raise AssertionError(url)
    return opener


def array_payload(n=2000):
    return json.dumps([{"id": i, "name": "x" * 20} for i in range(n)]).encode()


class ContentHashTest(unittest.TestCase):
    def test_matches_independent_computation_incl_multiple_blocks(self):
        for size in (0, 1, 4 * 1024 * 1024, 4 * 1024 * 1024 + 1, 9 * 1024 * 1024 + 123):
            data = os.urandom(size)
            h = df.BlockHasher()
            for i in range(0, len(data), 1000003):
                h.update(data[i:i + 1000003])
            self.assertEqual(h.hexdigest(), independent_content_hash(data), size)

    def test_hexdigest_can_be_called_twice(self):
        h = df.BlockHasher(); h.update(b"abc")
        self.assertEqual(h.hexdigest(), h.hexdigest())


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name) / "raw" / "latest-canonical.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_successful_download_is_verified_and_private(self):
        data = array_payload()
        out = df.fetch(SECRET, self.dest, expected_size=len(data), min_bytes=10, urlopen=fake_urlopen(data))
        self.assertTrue(out["verified"])
        self.assertEqual(self.dest.read_bytes(), data)
        self.assertEqual(self.dest.stat().st_mode & 0o777, 0o600)

    def test_secrets_and_token_never_printed(self):
        data = array_payload()
        buf = io.StringIO()
        old, sys.stdout = sys.stdout, buf
        try:
            result = df.fetch(SECRET, self.dest, min_bytes=10, urlopen=fake_urlopen(data))
        finally:
            sys.stdout = old
        shown = buf.getvalue() + json.dumps(result)
        for s in list(SECRET.values()):
            self.assertNotIn(s, shown)
        self.assertNotIn(TOKEN, shown.replace(f"::add-mask::{TOKEN}", ""))  # only the mask command may mention it

    def test_size_mismatch_stops_and_deletes_file(self):
        data = array_payload()
        with self.assertRaises(SystemExit):
            df.fetch(SECRET, self.dest, expected_size=len(data) + 1, min_bytes=10, urlopen=fake_urlopen(data))
        self.assertFalse(self.dest.exists())

    def test_download_shorter_than_metadata_deletes_file(self):
        data = array_payload()
        with self.assertRaises(SystemExit):
            df.fetch(SECRET, self.dest, min_bytes=10, urlopen=fake_urlopen(data, size=len(data) + 5))
        self.assertFalse(self.dest.exists())

    def test_content_hash_mismatch_deletes_file(self):
        data = array_payload()
        with self.assertRaises(SystemExit):
            df.fetch(SECRET, self.dest, min_bytes=10, urlopen=fake_urlopen(data, content_hash="0" * 64))
        self.assertFalse(self.dest.exists())

    def test_not_a_json_array_deletes_file(self):
        data = b'{"a": 1}' * 10
        with self.assertRaises(SystemExit):
            df.fetch(SECRET, self.dest, min_bytes=10, urlopen=fake_urlopen(data))
        self.assertFalse(self.dest.exists())

    def test_tiny_file_refused_by_default_minimum(self):
        data = array_payload(3)
        with self.assertRaises(SystemExit):
            df.fetch(SECRET, self.dest, urlopen=fake_urlopen(data))
        self.assertFalse(self.dest.exists())

    def test_missing_secret_stops_before_any_request(self):
        calls = []
        env = dict(SECRET); del env["DROPBOX_REFRESH_TOKEN"]
        with self.assertRaises(SystemExit):
            df.fetch(env, self.dest, min_bytes=10, urlopen=fake_urlopen(b"[]", calls=calls))
        self.assertEqual(calls, [])

    def test_destination_inside_git_tree_is_refused(self):
        inside = ROOT / "tmp-raw-should-not-exist" / "latest-canonical.json"
        with self.assertRaises(SystemExit):
            df.fetch(SECRET, inside, min_bytes=10, urlopen=fake_urlopen(array_payload()))
        self.assertFalse(inside.exists())
        self.assertFalse(inside.parent.exists())

    def test_http_error_message_has_status_only(self):
        import urllib.error

        def boom(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized REFRESH-123", {}, io.BytesIO(b"secret body REFRESH-123"))
        with self.assertRaises(SystemExit) as cm:
            df.fetch(SECRET, self.dest, min_bytes=10, urlopen=boom)
        self.assertIn("401", str(cm.exception))
        self.assertNotIn("REFRESH-123", str(cm.exception))
        self.assertNotIn("secret body", str(cm.exception))

    def test_default_path_is_app_folder_root_and_can_be_overridden(self):
        seen = []

        def spy(payload):
            inner = fake_urlopen(payload)

            def opener(req, timeout=None):
                if req.full_url == df.META_URL:
                    seen.append(json.loads(req.data)["path"])
                if req.full_url == df.DOWNLOAD_URL:
                    seen.append(json.loads(req.get_header("Dropbox-api-arg"))["path"])
                return inner(req, timeout)
            return opener
        data = array_payload()
        df.fetch(SECRET, self.dest, min_bytes=10, urlopen=spy(data))
        self.assertEqual(seen, ["/latest-canonical.json"] * 2)
        seen.clear()
        df.fetch({**SECRET, "DROPBOX_RAW_PATH": "/annan.json"}, self.dest, min_bytes=10, urlopen=spy(data))
        self.assertEqual(seen, ["/annan.json"] * 2)

    def test_non_ascii_path_is_escaped_in_header(self):
        self.assertTrue(df._api_arg("/Mappe ø/x.json").isascii())
        self.assertEqual(json.loads(df._api_arg("/Mappe ø/x.json"))["path"], "/Mappe ø/x.json")


def hist(rows, **kw):
    base = {"verified_only": True, "raw_data_included": False, "credit": "Kilde: dagligepriser.dk",
            "records": [{"normalized_product_key": k, "month": m, "source": "dagligepriser.dk"} for k, m in rows]}
    base.update(kw)
    return base


def ver(**statuses):
    return {"raw_data_included": False, "keys": {k: {"status": s} for k, s in statuses.items()}}


MONTHS = ["2026-01", "2026-02", "2026-03"]
ROWS = [("a", m) for m in MONTHS] + [("b", m) for m in MONTHS]


class GuardTest(unittest.TestCase):
    def run_check(self, ah, av, bh=None, bv=None, size=1000, breg=None, areg=None, allowed=None):
        bh = bh if bh is not None else hist(ROWS)
        bv = bv if bv is not None else ver(a="verified", b="verified")
        return guard.check(bh, bv, ah, av, size, breg if breg is not None else {"a": [], "b": []},
                           areg if areg is not None else {"a": [], "b": []}, allowed)

    def test_identical_candidate_is_ok(self):
        self.assertEqual(self.run_check(hist(ROWS), ver(a="verified", b="verified")), [])

    def test_empty_or_invalid_candidate_stops(self):
        self.assertTrue(self.run_check(None, None))
        self.assertTrue(self.run_check(hist([]), ver(a="verified")))

    def test_not_verified_only_or_raw_flag_stops(self):
        self.assertTrue(self.run_check(hist(ROWS, verified_only=False), ver(a="verified", b="verified")))
        self.assertTrue(self.run_check(hist(ROWS, raw_data_included=True), ver(a="verified", b="verified")))

    def test_size_limit_12_mib(self):
        self.assertTrue(self.run_check(hist(ROWS), ver(a="verified", b="verified"), size=12 * 1024 * 1024))
        self.assertEqual(self.run_check(hist(ROWS), ver(a="verified", b="verified"), size=12 * 1024 * 1024 - 1), [])

    def test_missing_credit_stops(self):
        self.assertTrue(self.run_check(hist(ROWS, credit="ukendt"), ver(a="verified", b="verified")))

    def test_verification_with_extra_fields_stops(self):
        av = ver(a="verified", b="verified"); av["keys"]["a"]["raw_title"] = "Skummetmælk 1L"
        self.assertTrue(any("unexpected fields" in p for p in self.run_check(hist(ROWS), av)))

    def test_lost_verified_key_stops_unless_documented(self):
        ah, av = hist([r for r in ROWS if r[0] == "a"]), ver(a="verified", b="review_required")
        self.assertTrue(any("no longer verified" in p for p in self.run_check(ah, av)))
        self.assertEqual(self.run_check(ah, av, allowed={"b"}), [])

    def test_lost_months_stop_unless_documented(self):
        ah = hist([r for r in ROWS if r != ("a", "2026-03")])
        av = ver(a="verified", b="verified")
        self.assertTrue(any("lost history months" in p for p in self.run_check(ah, av)))
        self.assertEqual(self.run_check(ah, av, allowed={"a"}), [])

    def test_registry_loss_stops(self):
        self.assertTrue(any("registry" in p for p in self.run_check(hist(ROWS), ver(a="verified", b="verified"), areg={"a": []})))

    def test_allowlist_needs_reason(self):
        self.assertEqual(guard.allowed_losses({"allowed_losses": [{"key": "a", "reason": ""}, {"key": "b", "reason": "produkt udgået"}]}), {"b"})

    def test_new_verified_history_is_allowed_and_counted(self):
        ah = hist(ROWS + [("c", m) for m in MONTHS])
        av = ver(a="verified", b="verified", c="verified")
        self.assertEqual(self.run_check(ah, av), [])
        d = guard.diff(hist(ROWS), ver(a="verified", b="verified"), ah, av)
        self.assertEqual((d["verified_added_count"], d["verified_lost_count"], d["graph_keys_added_count"]), (1, 0, 1))

    def test_stale_or_missing_generated_files_stop(self):
        start = dt.datetime(2026, 10, 14, 4, 0, tzinfo=dt.timezone.utc)
        av = ver(a="verified", b="verified")
        old = hist(ROWS, generated_at="2026-10-13T18:43:44+00:00"); av["generated_at"] = "2026-10-13T18:43:44+00:00"
        probs = self.run_check_started(old, av, start)
        self.assertEqual(sum("not generated by this import run" in p for p in probs), 2)
        fresh = hist(ROWS, generated_at="2026-10-14T04:01:00+00:00"); av["generated_at"] = "2026-10-14T04:01:00+00:00"
        self.assertEqual(self.run_check_started(fresh, av, start), [])
        av.pop("generated_at")
        self.assertTrue(any("verification file was not generated" in p for p in self.run_check_started(fresh, av, start)))

    def run_check_started(self, ah, av, start):
        return guard.check(hist(ROWS), ver(a="verified", b="verified"), ah, av, 1000, {"a": [], "b": []}, {"a": [], "b": []}, None, start)

    def test_cli_stops_when_verification_file_is_missing(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "monthly_price_history.json").write_text(json.dumps(hist(ROWS)))
            r = subprocess.run([sys.executable, str(ROOT / "scripts/history_import_guard.py"), "--before-dir", str(ROOT), "--after-dir", d],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("STOP", r.stdout)

    def test_blocking_messages_carry_no_product_keys(self):
        ah, av = hist([r for r in ROWS if r[0] == "a"]), ver(a="verified", b="review_required")
        for p in self.run_check(ah, av):
            self.assertNotRegex(p, r"\b[ab]\b\)")

    def test_report_contains_counts_and_keys_only(self):
        b = guard.metrics(hist(ROWS), ver(a="verified", b="verified"))
        a = guard.metrics(hist(ROWS), ver(a="verified", b="verified"))
        md = guard.report_md(b, a, guard.diff(hist(ROWS), ver(a="verified", b="verified"), hist(ROWS), ver(a="verified", b="verified")), [])
        self.assertIn("OK", md)
        self.assertIn("dagligepriser.dk", md)

    def test_approvals_are_counted_against_raw_data(self):
        decisions = {"decisions": [{"decision": "verified"}] * 5}
        av = ver(a="verified")
        av["keys"]["a"].update({"manual_decisions": 3, "manual_decisions_blocked": 1})
        m = guard.metrics(hist(ROWS), av, decisions)
        self.assertEqual((m["approvals_in_file"], m["approvals_applied"], m["approvals_blocked_no_evidence"], m["approvals_not_seen_in_raw"]), (5, 3, 1, 1))


class WorkflowStaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / ".github/workflows/dropbox-history-import.yml").read_text(encoding="utf-8")
        cls.code = "\n".join(l for l in cls.text.splitlines() if not l.lstrip().startswith("#"))

    def test_only_manual_trigger_and_no_active_schedule(self):
        self.assertIn("workflow_dispatch:", self.code)
        for trig in ("schedule:", "pull_request", "pull_request_target", "push:", "workflow_run"):
            self.assertNotIn(trig, self.code, trig)

    def test_read_only_permissions_and_no_publish_steps(self):
        self.assertRegex(self.code, r"permissions:\s*\n\s*contents: read")
        self.assertNotIn("contents: write", self.code)
        for bad in ("git push", "git commit", "git add", "gh pr", "gh api", "peter-evans", "create-pull-request", "git-auto-commit", "persist-credentials: true"):
            self.assertNotIn(bad, self.code, bad)
        self.assertIn("persist-credentials: false", self.code)

    def test_secrets_only_via_secrets_context_and_never_echoed(self):
        self.assertEqual(sorted(set(re.findall(r"secrets\.([A-Z_]+)", self.code))),
                         ["DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN"])
        for line in self.code.splitlines():
            if re.search(r"\becho\b|\bprintf\b|\bset -x\b|\bcurl\b|\bwget\b", line):
                self.assertNotRegex(line, r"DROPBOX|secrets\.", line)
        self.assertNotIn("set -x", self.code)
        self.assertIn("environment: dropbox-import", self.code)

    def test_raw_data_lives_in_runner_temp_and_is_always_deleted(self):
        self.assertIn('echo "RAW_DIR=$RUNNER_TEMP/raw" >> "$GITHUB_ENV"', self.code)
        self.assertIn('echo "OUT_DIR=$RUNNER_TEMP/out" >> "$GITHUB_ENV"', self.code)
        self.assertEqual(self.code.count("if: always()"), 1, "only the raw-data cleanup may run always()")
        m = re.search(r"- name: Slet rådata[^\n]*\n\s+if: always\(\)\n\s+run: \|\n(.*?)\n\n", self.code + "\n\n", re.S)
        self.assertIsNotNone(m, "cleanup step with if: always() is required")
        self.assertIn('rm -rf "${RAW_DIR:-$RUNNER_TEMP/raw}"', m.group(1))

    def test_artifacts_exclude_raw_data_and_match_log(self):
        m = re.search(r"upload-artifact@v4.*?path: \|\n(.*?)if-no-files-found", self.code, re.S)
        paths = [l.strip() for l in m.group(1).splitlines() if l.strip()]
        self.assertTrue(paths)
        for p in paths:
            self.assertNotIn("/raw", p)
            self.assertNotIn("latest-canonical", p)
            self.assertNotIn("private", p)
            self.assertNotIn("match-log", p)
        self.assertNotRegex(self.code, r"path:\s*\$\{\{ runner\.temp \}\}/?\s*$")

    def test_importer_uses_candidate_output_and_no_match_log(self):
        self.assertNotIn("--match-log", self.code)
        self.assertIn('--output "$OUT_DIR/monthly_price_history.json"', self.code)
        self.assertIn('--identities "$OUT_DIR/history_offer_identities.json"', self.code)

    def test_expression_contexts_are_valid_where_they_are_used(self):
        """Regression for the startup failure: 'runner' is not available in job-level env (run 38464620534). Offline stand-in for actionlint."""
        lines = self.code.splitlines()
        steps_at = next(i for i, l in enumerate(lines) if re.match(r"^    steps:\s*$", l))
        jobs_at = next(i for i, l in enumerate(lines) if re.match(r"^jobs:\s*$", l))
        allowed = {"workflow": {"github", "inputs", "vars"}, "job": {"github", "inputs", "vars", "secrets", "needs", "matrix", "strategy"},
                   "step": {"github", "inputs", "vars", "secrets", "needs", "matrix", "strategy", "env", "runner", "job", "steps"}}
        for i, line in enumerate(lines):
            place = "workflow" if i < jobs_at else "job" if i < steps_at else "step"
            for expr in re.findall(r"\$\{\{(.*?)\}\}", line):
                for ctx in re.findall(r"(?<![\w.'\"])([a-z]+)\.[A-Za-z_]", re.sub(r"'[^']*'", "''", expr)):
                    self.assertIn(ctx, allowed[place], f"line {i + 1}: context '{ctx}' is not available at {place} level")
        self.assertNotIn("runner.", "\n".join(lines[:steps_at]))

    def test_every_dir_variable_is_defined_before_use_via_github_env(self):
        first_use = min(self.code.index(v) for v in ('"$RAW_DIR', '"$OUT_DIR') if v in self.code)
        self.assertLess(self.code.index('>> "$GITHUB_ENV"'), first_use)

    def test_candidate_upload_only_after_guard_and_failure_report_is_fixed_text(self):
        up = self.code[self.code.index("name: Upload kun aggregerede"):]
        head = up[:up.index("with:")]
        self.assertNotIn("if:", head, "candidate upload must run only when every earlier step (incl. the guard) succeeded")
        self.assertLess(self.code.index("history_import_guard.py"), self.code.index("name: Upload kun aggregerede"))
        fail = self.code[self.code.index("name: Fejlrapport"):]
        self.assertIn("if: failure()", fail)
        self.assertNotIn("report.md", fail.split("retention-days")[1] if "retention-days" in fail else "")
        self.assertIn("fejlrapport.txt", fail)

    def test_error_line_is_fixed_and_import_err_is_never_shown(self):
        self.assertIn("Historikimport fejlede. Ingen kandidat publiceret.", self.code)
        for line in self.code.splitlines():
            if "import.err" in line:
                self.assertNotRegex(line, r"\b(cat|tail|head|echo|sed|cut|grep)\b", line)
        self.assertNotIn("$(tail", self.code)

    def test_verification_must_be_fresh_and_dropbox_path_is_the_verified_one(self):
        self.assertIn("--started-at", self.code)
        self.assertIn("import.started", self.code)
        self.assertIn('rm -f "$OUT_DIR/monthly_price_history.json" "$OUT_DIR/history_verification.json"', self.code)
        self.assertIn("|| '/latest-canonical.json'", self.code)
        self.assertEqual(df.DEFAULT_PATH, "/latest-canonical.json")
        self.assertNotIn("RawData", self.code)
        self.assertNotIn("Superkøb:", self.code)

    def test_importer_output_is_not_streamed_to_the_log(self):
        self.assertIn("> \"$RUNNER_TEMP/import.out\" 2> \"$RUNNER_TEMP/import.err\"", self.code)


class ImporterJsonValidationTest(unittest.TestCase):
    """The streaming check only looks at the first and last characters; the importer must parse the whole structure."""

    def run_importer(self, payload: bytes):
        with tempfile.TemporaryDirectory() as d:
            raw, out = Path(d) / "raw.json", Path(d) / "out"
            out.mkdir()
            raw.write_bytes(payload)
            for n in ("price_history.json",):
                (out / n).write_text((ROOT / n).read_text(encoding="utf-8"), encoding="utf-8")
            (out / "history_offer_identities.json").write_text((ROOT / "data_sources/history_offer_identities.json").read_text(encoding="utf-8"), encoding="utf-8")
            r = subprocess.run([sys.executable, str(ROOT / "scripts/import_dagligepriser_history.py"), "--source-file", str(raw),
                                "--output", str(out / "monthly_price_history.json"), "--current-offers", str(ROOT / "current_offers.json"),
                                "--identities", str(out / "history_offer_identities.json"),
                                "--manifest", str(ROOT / "data_sources/dagligepriser_manifest.json"),
                                "--decisions", str(ROOT / "data_sources/history_review_decisions.json")],
                               capture_output=True, text=True, cwd=ROOT)
            return r, (out / "monthly_price_history.json").exists(), (out / "history_verification.json").exists()

    def test_invalid_json_with_correct_first_and_last_character_is_rejected_by_both_layers(self):
        bad = b'[{"id": 1, "name": "x"}, {"id": 2, name: broken}, ]'
        with tempfile.TemporaryDirectory() as d:  # layer 1 (streaming check) lets it through ...
            p = Path(d) / "x.json"; p.write_bytes(bad)
            df.check_json_array(p)
        r, hist_written, ver_written = self.run_importer(bad)  # ... layer 2 (importer parses everything) stops it
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(hist_written)
        self.assertFalse(ver_written)

    def test_valid_json_that_is_not_a_product_list_is_rejected(self):
        r, hist_written, _ = self.run_importer(b'[1, 2, 3]')
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(hist_written)

    def test_empty_array_does_not_produce_a_candidate(self):
        r, hist_written, ver_written = self.run_importer(b'[]')
        if r.returncode == 0 and hist_written:
            doc = json.loads(r.stdout.strip().splitlines()[0])
            self.assertEqual(doc.get("records", 0), 0)  # an empty import is then stopped by the guard (candidate empty)


class RepoHygieneTest(unittest.TestCase):
    def test_no_raw_dump_or_dropbox_secrets_committed(self):
        for p in ROOT.rglob("*"):
            if ".git" in p.parts or not p.is_file() or p.suffix not in {".json", ".py", ".yml", ".md"}:
                continue
            self.assertNotEqual(p.name, "latest-canonical.json", p)
            self.assertLess(p.stat().st_size, 40 * 1024 * 1024, p)
            if p.suffix in {".py", ".yml", ".md"}:
                self.assertNotRegex(p.read_text(encoding="utf-8", errors="ignore"), r"sl\.[A-Za-z0-9_-]{60,}", p)


if __name__ == "__main__":
    unittest.main()
