"""Regressionen für den lokalen Release 4.0.1; nur künstliche Kontodaten."""
import contextlib
import io
import json
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omd import auth, runtime, version
import cli


class BoundedProcessTests(unittest.TestCase):
    def test_captured_process_reports_complete_output(self):
        result = runtime.run_captured([sys.executable, "-c", "print('complete')"], timeout=5)
        self.assertEqual((result.returncode, result.stdout), (0, "complete\n"))

    def test_timeout_is_bounded_and_hides_arguments(self):
        started = time.monotonic()
        with self.assertRaises(TimeoutError) as raised:
            runtime.run_captured([sys.executable, "-c", "import time; time.sleep(30)", "SECRET"], timeout=0.1)
        self.assertLess(time.monotonic() - started, 4)
        self.assertNotIn("SECRET", str(raised.exception))
        self.assertFalse(runtime._ACTIVE_PROCESSES)

    def test_cancellation_reaps_terminated_process(self):
        process = runtime.start_process([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            runtime.terminate_process(process, grace_seconds=0.1)
            self.assertIsNotNone(process.poll())
        finally:
            runtime.terminate_process(process, grace_seconds=0)
            runtime._unregister_process(process)

    def test_exited_parent_does_not_leave_child_holding_output(self):
        # Das Kind erbt stdout und ignoriert TERM; sein Elternprozess endet sofort.
        child = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready',flush=True); time.sleep(30)"
        parent = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}])"
        process = runtime.start_process([sys.executable, "-c", parent], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            process.wait(timeout=5)
            started = time.monotonic()
            runtime.terminate_process(process, grace_seconds=0.1)
            process.communicate(timeout=3)
            self.assertLess(time.monotonic() - started, 4)
        finally:
            runtime.terminate_process(process, grace_seconds=0)
            for stream in (process.stdout, process.stderr):
                stream.close()
            runtime._unregister_process(process)


class AuthenticationHardeningTests(unittest.TestCase):
    def args(self, directory):
        return types.SimpleNamespace(cookies_browser="safari", cookies_file=None, session_dir=directory, auth_url=None)

    def test_cli_accepts_safari_chrome_opera_for_auth_and_inspection(self):
        for browser in ("safari", "chrome", "opera"):
            for operation in ("--auth-check-json", "--inspect-json"):
                with self.subTest(browser=browser, operation=operation):
                    args = cli.parser().parse_args([operation, "--cookies-browser", browser])
                    self.assertEqual(args.cookies_browser, browser)

    def test_each_browser_exports_once_into_a_private_filtered_snapshot(self):
        for browser in ("safari", "chrome", "opera"):
            with self.subTest(browser=browser), tempfile.TemporaryDirectory() as directory:
                def captured(command, **kwargs):
                    self.assertEqual(command[command.index("--cookies-from-browser") + 1], browser)
                    self.assertEqual(command[command.index("--js-runtimes") + 1], "deno:/app/bin/deno")
                    for option in ("--ignore-config", "--no-remote-components", "--skip-download", "--no-playlist"):
                        self.assertIn(option, command)
                    self.assertNotIn("--no-warnings", command)
                    self.assertIn("--no-color", command)
                    self.assertEqual(kwargs["timeout"], 90)
                    destination = Path(command[command.index("--cookies") + 1])
                    self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
                    destination.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tSYNTHETIC-MEDIA\n.example.org\tTRUE\t/\tTRUE\t0\tSID\tSYNTHETIC-UNRELATED\n")
                    return subprocess.CompletedProcess(command, 0, "Cookie: SYNTHETIC-HEADER", "Authorization: SYNTHETIC-AUTH")
                args = self.args(directory)
                args.cookies_browser = browser
                with mock.patch.object(runtime, "ytdlp", return_value="/app/bin/yt-dlp"), mock.patch.object(runtime, "deno", return_value="/app/bin/deno"), mock.patch.object(runtime, "run_captured", side_effect=captured) as run:
                    result = auth.prepare_authentication(args)
                run.assert_called_once()
                self.assertEqual(result["status"], "ready")
                self.assertFalse(result["loginVerified"])
                self.assertNotIn("SYNTHETIC", json.dumps(result))
                snapshot = Path(result["cookieFile"])
                self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(snapshot.parent.stat().st_mode), 0o700)
                self.assertIn("SYNTHETIC-MEDIA", snapshot.read_text())
                self.assertNotIn("SYNTHETIC-UNRELATED", snapshot.read_text())
                self.assertEqual(list(snapshot.parent.iterdir()), [snapshot])

    def test_each_browser_permission_failure_is_private_and_cleans_session(self):
        for browser in ("safari", "chrome", "opera"):
            with self.subTest(browser=browser), tempfile.TemporaryDirectory() as directory:
                args = self.args(directory)
                args.cookies_browser = browser
                failure = subprocess.CompletedProcess([], 1, "Cookie: SYNTHETIC-COOKIE", f"ERROR: Failed to read {browser} cookies: /Users/SYNTHETIC-USER/private\nAuthorization: SYNTHETIC-AUTH")
                with mock.patch.object(runtime, "ytdlp", return_value="/app/bin/yt-dlp"), mock.patch.object(runtime, "deno", return_value=None), mock.patch.object(runtime, "run_captured", return_value=failure):
                    result = auth.prepare_authentication(args)
                self.assertEqual(result["status"], "browserCookieAccessDenied")
                self.assertNotIn("SYNTHETIC", json.dumps(result))
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_keychain_and_decryption_warnings_reject_partial_cookie_export(self):
        warnings = [
            "WARNING: find-generic-password failed",
            "WARNING: exception running find-generic-password: SYNTHETIC-SECRET",
            "WARNING: cannot decrypt v10 cookies: no key found",
            "WARNING: [Cookies] cannot decrypt v10 cookies: no key found",
            "WARNING: failed to decrypt cookie (AES-CBC) because UTF-8 decoding failed. Possibly the key is wrong?",
            "WARNING: failed to decrypt cookie (AES-GCM) because the MAC check failed. Possibly the key is wrong?",
        ]
        for browser in ("chrome", "opera"):
            for warning in warnings:
                with self.subTest(browser=browser, warning=warning), tempfile.TemporaryDirectory() as directory:
                    def captured(command, **kwargs):
                        target = Path(command[command.index("--cookies") + 1])
                        target.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tPREF\tSYNTHETIC-COOKIE\n")
                        return subprocess.CompletedProcess(command, 0, "Authorization: SYNTHETIC-HEADER", warning)
                    args = self.args(directory)
                    args.cookies_browser = browser
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with mock.patch.object(runtime, "ytdlp", return_value="test-tool"), mock.patch.object(runtime, "deno", return_value=None), mock.patch.object(runtime, "run_captured", side_effect=captured), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        result = auth.prepare_authentication(args)
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["status"], "browserCookieAccessDenied")
                    self.assertNotIn("cookieFile", result)
                    self.assertNotIn("SYNTHETIC", json.dumps(result) + stdout.getvalue() + stderr.getvalue())
                    self.assertEqual(list(Path(directory).iterdir()), [])

    def test_nonzero_failed_decryption_summary_rejects_export_without_warning(self):
        for browser in ("chrome", "opera"):
            with self.subTest(browser=browser), tempfile.TemporaryDirectory() as directory:
                args = self.args(directory)
                args.cookies_browser = browser
                result = subprocess.CompletedProcess([], 0, f"Extracted 5 cookies from {browser} (42 could not be decrypted)", "")
                with mock.patch.object(runtime, "ytdlp", return_value="test-tool"), mock.patch.object(runtime, "deno", return_value=None), mock.patch.object(runtime, "run_captured", return_value=result):
                    payload = auth.prepare_authentication(args)
                self.assertEqual(payload["status"], "browserCookieAccessDenied")
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_unrelated_warnings_do_not_reject_valid_cookie_export(self):
        for browser in ("chrome", "opera"):
            with self.subTest(browser=browser), tempfile.TemporaryDirectory() as directory:
                def captured(command, **kwargs):
                    target = Path(command[command.index("--cookies") + 1])
                    target.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tSYNTHETIC-COOKIE\n")
                    return subprocess.CompletedProcess(command, 0, f"Extracted 1 cookies from {browser} (0 could not be decrypted)\nVideo title: find-generic-password failed", "WARNING: [youtube] No supported JavaScript runtime could be found\nWARNING: [youtube] Sign in to confirm your age. Use --cookies-from-browser")
                args = self.args(directory)
                args.cookies_browser = browser
                with mock.patch.object(runtime, "ytdlp", return_value="test-tool"), mock.patch.object(runtime, "deno", return_value=None), mock.patch.object(runtime, "run_captured", side_effect=captured):
                    result = auth.prepare_authentication(args)
                self.assertTrue(result["ok"])
                self.assertEqual(result["status"], "ready")
                self.assertFalse(result["loginVerified"])
                self.assertNotIn("SYNTHETIC", json.dumps(result))

    def test_authentication_timeout_cleans_private_session(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(auth, "_export_browser", side_effect=TimeoutError("SECRET")):
                result = auth.prepare_authentication(self.args(directory))
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "authenticationTimedOut")
            self.assertNotIn("SECRET", json.dumps(result))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_failed_export_is_not_reported_as_anonymous_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.CompletedProcess([], 1, "", "Unexpected extractor failure")
            with mock.patch.object(runtime, "ytdlp", return_value="test-tool"), mock.patch.object(runtime, "deno", return_value=None), mock.patch.object(runtime, "run_captured", return_value=result) as run:
                payload = auth.prepare_authentication(self.args(directory))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "error")
            self.assertEqual(run.call_args.kwargs["timeout"], 90)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_successful_empty_browser_export_is_anonymous(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.CompletedProcess([], 0, "", "")
            with mock.patch.object(runtime, "ytdlp", return_value="test-tool"), mock.patch.object(runtime, "deno", return_value=None), mock.patch.object(runtime, "run_captured", return_value=result):
                payload = auth.prepare_authentication(self.args(directory))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "anonymous")

    def test_exported_cookies_survive_an_unavailable_test_video(self):
        with tempfile.TemporaryDirectory() as directory:
            def run(command, **kwargs):
                target = Path(command[command.index("--cookies") + 1])
                target.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tSYNTHETIC\n")
                return subprocess.CompletedProcess(command, 1, "", "Video unavailable")
            with mock.patch.object(runtime, "ytdlp", return_value="test-tool"), mock.patch.object(runtime, "deno", return_value=None), mock.patch.object(runtime, "run_captured", side_effect=run):
                payload = auth.prepare_authentication(self.args(directory))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "ready")
            self.assertFalse(payload["loginVerified"])


class VersionTests(unittest.TestCase):
    def test_cli_and_source_use_one_version_file(self):
        expected = (Path(__file__).resolve().parents[2] / "VERSION").read_text().strip()
        self.assertEqual(version.VERSION, expected)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            cli.parser().parse_args(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"OpenMedia Downloader {expected}")


if __name__ == "__main__":
    unittest.main()
