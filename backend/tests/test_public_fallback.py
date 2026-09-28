"""Öffentlicher HTTP-Rückfall: nur künstliche Antworten, keine Kontodaten."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omd import downloads, runtime
from omd.errors import AuthenticationRequiredError, YTDLPError, args_without_browser_cookies


def arguments(folder, **overrides):
    values = dict(output=str(folder), quality="144", mode="auto", media="video", workers=4,
                  cookies_browser="chrome", cookies_file=None, ask_overwrite=False,
                  overwrite=False, check=False)
    values.update(overrides)
    return types.SimpleNamespace(**values)


def denied(code=403):
    return YTDLPError("HTTP access failed", raw_detail=f"ERROR: unable to download video data: HTTP Error {code}: Forbidden")


def events(output):
    return [json.loads(line.removeprefix("OMD_EVENT:")) for line in output.getvalue().splitlines() if line.startswith("OMD_EVENT:")]


class PublicFallbackTests(unittest.TestCase):
    url = "https://www.youtube.com/watch?v=synthetic"

    def setUp(self):
        # Kein versehentlicher Zugriff auf echte Werkzeuge oder das Netzwerk.
        for target in ("start_process", "run_captured"):
            patch = mock.patch.object(downloads, target, side_effect=AssertionError("External process disabled in test"))
            patch.start()
            self.addCleanup(patch.stop)

    def test_cookie_401_403_retry_confirms_public_format_and_locks_new_target(self):
        cases = [(401, "video", "auto", "144"), (403, "video", "auto", "144"),
                 (403, "aac", "direct", "best"), (403, "mp3", "chunks", "192k")]
        for status, media, mode, quality in cases:
            with self.subTest(status=status, media=media), tempfile.TemporaryDirectory() as directory:
                args = arguments(directory, media=media, mode=mode, quality=quality)
                old = Path(directory) / "Private_selection.mp4"
                extension = {"aac": ".m4a", "mp3": ".mp3"}.get(media, ".mp4")
                new = Path(directory) / ("Public_selection" + extension)
                held, lock_order, attempts = [], [], []
                @contextlib.contextmanager
                def lock(target):
                    self.assertEqual(held, [])
                    held.append(target); lock_order.append(target)
                    try: yield
                    finally: held.pop()
                def metadata(command, **kwargs):
                    self.assertEqual(held, [])
                    self.assertEqual(kwargs["timeout"], 90)
                    self.assertIn("--no-playlist", command)
                    return subprocess.CompletedProcess(command, 0, json.dumps(dict(filename=str(new.with_suffix(".webm")), url=self.url, title="Public", availability="public", formatId="134+140")), "")
                def options(anonymous, **kwargs):
                    self.assertIsNone(anonymous.cookies_browser)
                    self.assertIsNone(anonymous.cookies_file)
                    self.assertEqual((anonymous.media, anonymous.mode, anonymous.quality), (media, mode, quality))
                    return ["fake-ytdlp"]
                def attempt(url, target, current, force_overwrite, **kwargs):
                    attempts.append(target)
                    self.assertEqual(held, [target])
                    if len(attempts) == 1:
                        self.assertTrue(kwargs["defer_access_errors"])
                        raise denied(status)
                    self.assertEqual(target, new)
                    self.assertIsNone(current.cookies_browser)
                    self.assertIsNone(current.cookies_file)
                    self.assertEqual(current._confirmed_format, "134+140")
                    self.assertFalse(force_overwrite)
                    downloads.emit_event("completed", path=str(new))
                output = io.StringIO()
                with mock.patch.object(downloads, "ytdlp_preflight", return_value=[(old, self.url, "Original")]), mock.patch.object(downloads, "ytdlp_options", side_effect=options), mock.patch.object(downloads, "run_captured", side_effect=metadata) as probe, mock.patch.object(downloads, "_run_ytdlp_download_attempt", side_effect=attempt), mock.patch.object(runtime, "target_lock", side_effect=lock), contextlib.redirect_stdout(output):
                    downloads.process_ytdlp(self.url, args)
                self.assertEqual(attempts, [old, new])
                self.assertEqual(lock_order, [old, new])
                probe.assert_called_once()
                self.assertEqual(args.cookies_browser, "chrome")
                self.assertFalse(hasattr(args, "_confirmed_format"))
                payloads = events(output)
                self.assertEqual(sum(item.get("code") == "publicAccessFallback" for item in payloads), 1)
                self.assertNotIn("error", [item["type"] for item in payloads])
                self.assertEqual(payloads[-1]["type"], "completed")

    def test_auth_required_anonymous_metadata_never_starts_second_download(self):
        for availability in ("private", "needs_auth", "subscriber_only", "premium_only"):
            with self.subTest(availability=availability), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "Video.mp4"
                result = subprocess.CompletedProcess([], 0, json.dumps(dict(filename=str(target), url=self.url, formatId="18", availability=availability)), "")
                output = io.StringIO()
                with mock.patch.object(downloads, "ytdlp_preflight", return_value=[(target, self.url, "Video")]), mock.patch.object(downloads, "_run_ytdlp_download_attempt", side_effect=denied()) as attempt, mock.patch.object(downloads, "ytdlp_options", return_value=["tool"]), mock.patch.object(downloads, "run_captured", return_value=result), contextlib.redirect_stdout(output), self.assertRaises(AuthenticationRequiredError):
                    downloads.process_ytdlp(self.url, arguments(directory))
                attempt.assert_called_once()
                self.assertFalse(any(item.get("code") == "publicAccessFallback" for item in events(output)))

    def test_unavailable_or_unknown_anonymous_metadata_preserves_original_error(self):
        cases = [(1, "", "ERROR: Video unavailable"), (0, "{}", ""),
                 (0, '{"availability":"unknown"}', ""), (0, '{"availability":"public"}', "")]
        for code, payload, detail in cases:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "Video.mp4"
                failure = denied()
                with mock.patch.object(downloads, "ytdlp_preflight", return_value=[(target, self.url, "Video")]), mock.patch.object(downloads, "_run_ytdlp_download_attempt", side_effect=failure) as attempt, mock.patch.object(downloads, "ytdlp_options", return_value=["tool"]), mock.patch.object(downloads, "run_captured", return_value=subprocess.CompletedProcess([], code, payload, detail)), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(YTDLPError) as raised:
                    downloads.process_ytdlp(self.url, arguments(directory))
                self.assertIs(raised.exception, failure)
                attempt.assert_called_once()

    def test_anonymous_403_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Video.mp4"
            with mock.patch.object(downloads, "ytdlp_preflight", return_value=[(target, self.url, "Video")]), mock.patch.object(downloads, "_run_ytdlp_download_attempt", side_effect=denied()) as attempt, mock.patch.object(downloads, "_public_retry_entry") as probe, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(YTDLPError):
                downloads.process_ytdlp(self.url, arguments(directory, cookies_browser=None))
            attempt.assert_called_once(); probe.assert_not_called()

    def test_final_format_error_does_not_retry_an_earlier_http_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Video.mp4"
            failure = YTDLPError("format unavailable", raw_detail="WARNING: HTTP Error 403: Forbidden\nERROR: Requested format is not available")
            with mock.patch.object(downloads, "ytdlp_preflight", return_value=[(target, self.url, "Video")]), mock.patch.object(downloads, "_run_ytdlp_download_attempt", side_effect=failure) as attempt, mock.patch.object(downloads, "_public_retry_entry") as probe, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(YTDLPError):
                downloads.process_ytdlp(self.url, arguments(directory, mode="chunks"))
            attempt.assert_called_once(); probe.assert_not_called()

    def test_changed_existing_target_requires_its_own_overwrite_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory) / "Old.mp4", Path(directory) / "New.mp4"
            old.write_bytes(b"old-user-file"); new.write_bytes(b"new-user-file")
            args = arguments(directory, ask_overwrite=True)
            output = io.StringIO()
            with mock.patch.object(downloads, "ytdlp_preflight", return_value=[(old, self.url, "Video")]), mock.patch.object(downloads, "_run_ytdlp_download_attempt", side_effect=denied()) as attempt, mock.patch.object(downloads, "_public_retry_entry", return_value=(new, self.url, args_without_browser_cookies(args))), mock.patch("builtins.input", side_effect=["y", "n"]) as answer, contextlib.redirect_stdout(output):
                downloads.process_ytdlp(self.url, args)
            self.assertEqual(answer.call_count, 2)
            attempt.assert_called_once()
            self.assertTrue(attempt.call_args.args[3])
            self.assertEqual(old.read_bytes(), b"old-user-file")
            self.assertEqual(new.read_bytes(), b"new-user-file")
            self.assertEqual([item["path"] for item in events(output) if item["type"] == "overwrite"], [str(old), str(new)])
            self.assertEqual(events(output)[-1]["type"], "skipped")

    def test_anonymous_retry_failure_does_not_start_a_third_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Video.mp4"
            args = arguments(directory)
            with mock.patch.object(downloads, "ytdlp_preflight", return_value=[(target, self.url, "Video")]), mock.patch.object(downloads, "_run_ytdlp_download_attempt", side_effect=[denied(), denied()]) as attempt, mock.patch.object(downloads, "_public_retry_entry", return_value=(target, self.url, args_without_browser_cookies(args))) as probe, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(YTDLPError):
                downloads.process_ytdlp(self.url, args)
            self.assertEqual(attempt.call_count, 2)
            probe.assert_called_once()

    def test_cookie_store_fallback_cannot_trigger_another_anonymous_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Video.mp4"
            cookie_error = YTDLPError("denied", raw_detail="ERROR: Operation not permitted: /private/Cookies.binarycookies")
            with mock.patch.object(downloads, "ytdlp_preflight", return_value=[(target, self.url, "Video")]), mock.patch.object(downloads, "_run_ytdlp_download_attempt", side_effect=[cookie_error, denied()]) as attempt, mock.patch.object(downloads, "_public_retry_entry") as probe, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(YTDLPError):
                downloads.process_ytdlp(self.url, arguments(directory))
            self.assertEqual(attempt.call_count, 2)
            probe.assert_not_called()

    def test_cancellation_before_or_after_public_probe_never_starts_retry(self):
        for cancel_during_probe in (False, True):
            with self.subTest(cancel_during_probe=cancel_during_probe), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "Video.mp4"
                args = arguments(directory)
                cancelled = threading.Event()
                def attempt(*unused, **kwargs):
                    if not cancel_during_probe: cancelled.set()
                    raise denied()
                def probe(*unused):
                    cancelled.set()
                    return target, self.url, args_without_browser_cookies(args)
                output = io.StringIO()
                with mock.patch.object(runtime, "_CANCELLED", cancelled), mock.patch.object(downloads, "ytdlp_preflight", return_value=[(target, self.url, "Video")]), mock.patch.object(downloads, "_run_ytdlp_download_attempt", side_effect=attempt) as run, mock.patch.object(downloads, "_public_retry_entry", side_effect=probe) as check, contextlib.redirect_stdout(output), self.assertRaises(InterruptedError):
                    downloads.process_ytdlp(self.url, args)
                run.assert_called_once()
                self.assertEqual(check.call_count, int(cancel_during_probe))
                self.assertFalse(any(item.get("code") == "publicAccessFallback" for item in events(output)))

    def test_attempt_staging_is_private_unique_cleaned_and_output_is_relative(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            target = folder / "Video_${HOME}_100%_144p.mp4"
            target.write_bytes(b"untouched-user-file")
            foreign = folder / "Video_100%_144p.mp4.part"
            foreign.write_bytes(b"untouched-user-part")
            staging_paths = []
            def start(command, **kwargs):
                paths = [command[i + 1] for i, item in enumerate(command[:-1]) if item == "--paths"]
                staging = Path(next(item.removeprefix("temp:") for item in reversed(paths) if item.startswith("temp:")))
                self.assertIn(f"home:{folder}", paths)
                self.assertNotEqual(staging.parent, folder)
                self.assertEqual(list(staging.iterdir()), [])
                staging_paths.append(staging)
                (staging / "complete-video-track.mp4").write_bytes(b"owned-track")
                (staging / "partial-audio.part").write_bytes(b"owned-part")
                output_name = command[command.index("--output") + 1]
                self.assertFalse(Path(output_name).is_absolute())
                self.assertEqual(output_name, "%(omd_output_stem)s.%(ext)s")
                self.assertEqual(command[command.index("--parse-metadata") + 1], "title:%(omd_output_stem)s")
                replacement = command.index("--replace-in-metadata")
                self.assertEqual(command[replacement + 1:replacement + 4], ["omd_output_stem", "(?s)^.*$", target.stem])
                process = mock.Mock(stdout=io.StringIO("ERROR: HTTP Error 403: Forbidden ?token=SYNTHETIC-SECRET\n"))
                process.wait.return_value = 1
                return process
            captured = io.StringIO()
            with mock.patch.object(downloads, "ytdlp_options", return_value=["tool"]), mock.patch.object(downloads, "start_process", side_effect=start), contextlib.redirect_stdout(captured):
                for _ in range(2):
                    with self.assertRaises(YTDLPError):
                        downloads._run_ytdlp_download_attempt(self.url, target, arguments(folder), defer_access_errors=True)
            self.assertEqual(len(set(staging_paths)), 2)
            self.assertTrue(all(not path.exists() for path in staging_paths))
            self.assertEqual(target.read_bytes(), b"untouched-user-file")
            self.assertEqual(foreign.read_bytes(), b"untouched-user-part")
            self.assertNotIn("SYNTHETIC", captured.getvalue())
            self.assertNotIn("ERROR:", captured.getvalue())
            self.assertFalse(any(item["type"] == "error" for item in events(captured)))


if __name__ == "__main__":
    unittest.main()
