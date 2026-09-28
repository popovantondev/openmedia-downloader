import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omd import auth, downloads, errors, estimates, events, inspection, runtime
import cli


def cookies_text(domain=".youtube.com", expiry="0", value="synthetic-test-only"):
    return f"# Netscape HTTP Cookie File\n{domain}\tTRUE\t/\tTRUE\t{expiry}\tSID\t{value}\n"


def direct_format(**extra):
    return {"height": 720, "vcodec": "h264", "acodec": "mp4a", "protocol": "https", "ext": "mp4", **extra}


class EstimateTests(unittest.TestCase):
    def find(self, values, media="video", quality="720", mode="direct"):
        return next(value for value in values if (value["media"], value["quality"], value["mode"]) == (media, quality, mode))

    def test_full_direct_content_length_is_exact(self):
        values = estimates.build_estimates({"duration": 100, "formats": [direct_format(filesize=123456)]})
        value = self.find(values)
        self.assertEqual(value["bytes"], 123456)
        self.assertFalse(value["approximate"])

    def test_referer_validation_and_explicit_ytdlp_header(self):
        args = types.SimpleNamespace(workers=1, output="/tmp", quality="best", mode="auto", media="video", referer="https://publisher.invalid:8443/?discard=private")
        with mock.patch.object(downloads, "ytdlp", return_value="tool"), mock.patch.object(downloads, "ffmpeg", return_value="ffmpeg"), mock.patch.object(downloads, "deno", return_value=None):
            options = downloads.ytdlp_options(args)
        self.assertIn("--referer", options)
        self.assertEqual(options[options.index("--referer") + 1], args.referer)
        for invalid in ("file:///tmp/page", "https://user:pass@publisher.invalid/", "https://bad host/", "https://publisher.invalid/\nX: y"):
            with self.assertRaises(errors.BackendError): downloads.validate_referer(invalid)
        args.referer = None
        with mock.patch.object(downloads, "ytdlp", return_value="tool"), mock.patch.object(downloads, "ffmpeg", return_value="ffmpeg"), mock.patch.object(downloads, "deno", return_value=None):
            self.assertNotIn("--referer", downloads.ytdlp_options(args))

    def test_ytdlp_options_passes_validated_auth_domains_to_private_copy(self):
        args = types.SimpleNamespace(workers=1, output="/tmp", quality="best", mode="auto", media="video",
                                     cookies_file="source.txt", auth_domain=["COURSE.Example."])
        with mock.patch.object(downloads, "ytdlp", return_value="tool"), mock.patch.object(downloads, "ffmpeg", return_value="ffmpeg"), mock.patch.object(downloads, "deno", return_value=None), mock.patch.object(downloads, "cookie_file_for_job", return_value="private-copy.txt") as copy:
            options = downloads.ytdlp_options(args)
        copy.assert_called_once_with("source.txt", ("course.example",))
        self.assertEqual(options[options.index("--cookies") + 1], "private-copy.txt")

    def test_separate_video_and_audio_are_added(self):
        values = estimates.build_estimates({"duration": 100, "formats": [direct_format(filesize=9000, acodec="none"), {"vcodec": "none", "acodec": "mp4a", "protocol": "https", "filesize": 1000}]})
        value = self.find(values)
        self.assertEqual(value["bytes"], 10000)
        self.assertTrue(value["approximate"])

    def test_fragmented_bitrate_uses_seconds_and_bits(self):
        value = self.find(estimates.build_estimates({"duration": 80, "formats": [direct_format(protocol="m3u8_native", tbr=1000)]}), mode="chunks")
        self.assertEqual(value["bytes"], 10_000_000)
        self.assertTrue(value["approximate"])

    def test_estimates_are_scoped_to_mode_and_add_separate_audio_once(self):
        formats = [
            direct_format(filesize=5_000_000, acodec="mp4a.40.2"),
            direct_format(vcodec="none", height=None, filesize=960_000, abr=128, acodec="mp4a.40.2"),
            direct_format(protocol="m3u8_native", filesize_approx=2_000_000, tbr=1000, acodec="none"),
            direct_format(protocol="m3u8_native", vcodec="none", height=None, filesize_approx=960_000, abr=128, acodec="mp4a.40.2"),
        ]
        values = estimates.build_estimates({"duration": 60, "formats": formats})
        direct = self.find(values, mode="direct")
        chunks = self.find(values, mode="chunks")
        self.assertEqual(direct["bytes"], 5_000_000)
        self.assertFalse(direct["approximate"])
        self.assertEqual(chunks["bytes"], 2_960_000)
        self.assertTrue(chunks["approximate"])
        self.assertEqual(self.find(values, media="mp3", quality="192k", mode="direct")["bytes"], 1_440_000)

    def test_mp3_target_bitrate_does_not_use_video_size(self):
        values = estimates.build_estimates({"duration": 100, "formats": [direct_format(filesize=99999999)]})
        self.assertEqual(self.find(values, "mp3", "192k")["bytes"], 2_400_000)

    def test_aac_exact_source_still_marks_container_overhead_approximate(self):
        values = estimates.build_estimates({"duration": 10, "formats": [{"vcodec": "none", "acodec": "mp4a", "ext": "m4a", "protocol": "https", "filesize": 12345}]})
        value = self.find(values, "aac", "best")
        self.assertEqual(value["bytes"], 12345)
        self.assertTrue(value["approximate"])

    def test_unknown_never_turns_into_zero_bytes(self):
        values = estimates.build_estimates({"formats": [direct_format()]})
        self.assertEqual(values, [])

    def test_nearest_resolution_prefers_lower_on_tie(self):
        values = estimates.build_estimates({"formats": [direct_format(height=360, filesize=10), direct_format(height=720, filesize=20)]})
        value = self.find(values, quality="540")
        self.assertEqual(value["actualQuality"], "360")
        self.assertEqual(value["bytes"], 10)

    def test_native_vimeo_auto_matches_direct_preference(self):
        values = estimates.build_estimates({"nativeVimeo": True, "formats": [direct_format(height=360, filesize=10), direct_format(protocol="m3u8_native", height=2160, filesize_approx=100)]})
        self.assertEqual(self.find(values, quality="best", mode="auto")["actualQuality"], "360")

    def test_drm_formats_are_not_estimated(self):
        self.assertEqual(estimates.build_estimates({"formats": [direct_format(filesize=100, has_drm=True)]}), [])

    def test_dash_is_not_a_direct_http_file(self):
        self.assertFalse(estimates.protocol_matches({"protocol": "http_dash_segments"}, "direct"))
        self.assertTrue(estimates.protocol_matches({"protocol": "http_dash_segments"}, "chunks"))

    def test_private_playlist_entry_is_not_marked_available(self):
        entry = estimates.entry_from_info({"title": "[Private video]", "availability": "private"}, "https://youtube.com/watch?v=test")
        self.assertEqual(entry["availability"], "authenticationRequired")


class AuthTests(unittest.TestCase):
    def test_explicit_domain_allowlist_is_normalized_and_host_scoped(self):
        self.assertEqual(auth.normalize_auth_domain("Büro.Example."), "xn--bro-hoa.example")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            entries = [
                cookies_text(".youtube.com", value="media"),
                cookies_text("course.example", value="course").replace("course.example\tTRUE", "course.example\tFALSE"),
                cookies_text(".learn.course.example", value="subdomain"),
                cookies_text(".evilcourse.example", value="sibling"),
                cookies_text(".unrelated.test", value="unrelated"),
            ]
            original = "# Netscape HTTP Cookie File\n" + "".join(row.split("\n", 1)[1] for row in entries)
            source.write_text(original)
            source.chmod(0o640)
            result = auth.prepare_authentication(types.SimpleNamespace(cookies_file=str(source), cookies_browser=None, session_dir=directory, auth_domain=["COURSE.Example."]))
            self.assertEqual(result["status"], "ready")
            snapshot = Path(result["cookieFile"]).read_text()
            for value in ("media", "course", "subdomain"):
                self.assertIn(value, snapshot)
            for value in ("sibling", "unrelated"):
                self.assertNotIn(value, snapshot)
            self.assertEqual(source.read_text(), original)
            self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o640)
            self.assertEqual(stat.S_IMODE(Path(result["cookieFile"]).stat().st_mode), 0o600)
            self.assertNotIn("course", json.dumps(result))

    def test_auth_domain_validation_error_is_safe(self):
        invalid = ("https://course.example", "course.example/path", "course.example:443", "*.example", "a..example", "-bad.example", "bad_.example", "")
        for domain in invalid:
            with self.subTest(domain=domain), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "private-cookie-path.txt"
                source.write_text(cookies_text(value="PRIVATE-COOKIE-VALUE"))
                result = auth.prepare_authentication(types.SimpleNamespace(cookies_file=str(source), cookies_browser=None, session_dir=directory, auth_domain=[domain]))
                self.assertEqual(result["status"], "error")
                self.assertNotIn(str(source), json.dumps(result))
                self.assertNotIn("PRIVATE-COOKIE-VALUE", json.dumps(result))
                self.assertEqual(source.read_text(), cookies_text(value="PRIVATE-COOKIE-VALUE"))

    def test_cli_accepts_repeated_auth_domains(self):
        args = cli.parser().parse_args(["--auth-check-json", "--auth-domain", "course.example", "--auth-domain", "learn.example"])
        self.assertEqual(args.auth_domain, ["course.example", "learn.example"])

    def test_import_uses_private_snapshot_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            original = cookies_text(expiry=str(int(time.time()) + 3600))
            source.write_text(original)
            result = auth.prepare_authentication(types.SimpleNamespace(cookies_file=str(source), cookies_browser=None, session_dir=directory))
            self.assertEqual(result["status"], "ready")
            target = Path(result["cookieFile"])
            self.assertNotEqual(target, source)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)
            self.assertEqual(source.read_text(), original)
            self.assertNotIn("synthetic-test-only", json.dumps(result))
            self.assertFalse(result["loginVerified"])

    def test_expired_and_unrelated_cookies_do_not_claim_login(self):
        for content in (cookies_text(expiry="1"), cookies_text(domain=".example.org", expiry=str(int(time.time()) + 3600))):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "source.txt"
                source.write_text(content)
                result = auth.prepare_authentication(types.SimpleNamespace(cookies_file=str(source), cookies_browser=None, session_dir=directory))
                self.assertEqual(result["status"], "anonymous")
                self.assertEqual(list(Path(directory).glob("omd-auth-*")), [])

    def test_session_cookie_without_expiry_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            source.write_text(cookies_text(expiry=""))
            result = auth.prepare_authentication(types.SimpleNamespace(cookies_file=str(source), cookies_browser=None, session_dir=directory))
            self.assertEqual(result["status"], "ready")

    def test_zero_expiry_browser_session_cookie_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            source.write_text(cookies_text(expiry="0"))
            result = auth.prepare_authentication(types.SimpleNamespace(cookies_file=str(source), cookies_browser=None, session_dir=directory))
            self.assertEqual(result["status"], "ready")

    def test_invalid_cookie_file_never_logs_its_value(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            source.write_text("# Netscape HTTP Cookie File\nnot-a-cookie SECRET-VALUE\n")
            captured = io.StringIO()
            with contextlib.redirect_stderr(captured):
                result = auth.prepare_authentication(types.SimpleNamespace(cookies_file=str(source), cookies_browser=None, session_dir=directory))
            self.assertEqual(result["status"], "invalidCookieFile")
            self.assertNotIn("SECRET-VALUE", captured.getvalue() + json.dumps(result))

    def test_job_uses_own_cookie_copy(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as staging:
            source = Path(directory) / "source.txt"
            source.write_text(cookies_text(expiry=""))
            with mock.patch.object(runtime, "_RUNTIME_TEMP_DIR", Path(staging)):
                first = auth.cookie_file_for_job(str(source))
                second = auth.cookie_file_for_job(str(source))
            self.assertNotEqual(first, second)
            self.assertEqual(Path(first).parent, Path(staging))
            self.assertNotEqual(Path(first), source)
            self.assertEqual(stat.S_IMODE(Path(first).stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(Path(second).stat().st_mode), 0o600)

    def test_job_copy_preserves_only_approved_domains_and_media(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as staging:
            source = Path(directory) / "source.txt"
            source.write_text("# Netscape HTTP Cookie File\n" + "".join(row.split("\n", 1)[1] for row in [
                cookies_text(".youtube.com", expiry="", value="media-synthetic"),
                cookies_text(".course.example", expiry="", value="approved-synthetic"),
                cookies_text(".sub.course.example", expiry="", value="subdomain-synthetic"),
                cookies_text(".evilcourse.example", expiry="", value="sibling-synthetic"),
            ]))
            with mock.patch.object(runtime, "_RUNTIME_TEMP_DIR", Path(staging)):
                first = Path(auth.cookie_file_for_job(str(source), ["COURSE.Example."]))
                second = Path(auth.cookie_file_for_job(str(source), ["course.example"]))
            self.assertNotEqual(first, second)
            for snapshot in (first.read_text(), second.read_text()):
                for value in ("media-synthetic", "approved-synthetic", "subdomain-synthetic"):
                    self.assertIn(value, snapshot)
                self.assertNotIn("sibling-synthetic", snapshot)

    def test_browser_export_is_only_requested_explicitly_and_once(self):
        with tempfile.TemporaryDirectory() as directory:
            def export(_browser, destination, _url):
                destination.write_text(cookies_text(expiry=""))
            with mock.patch.object(auth, "_export_browser", side_effect=export) as exporter:
                result = auth.prepare_authentication(types.SimpleNamespace(cookies_file=None, cookies_browser="safari", session_dir=directory, auth_url=None))
            exporter.assert_called_once()
            self.assertEqual(result["status"], "ready")
            self.assertFalse(result["loginVerified"])

    def test_browser_denied_is_actionable_and_cleans_session(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(auth, "_export_browser", side_effect=PermissionError("SECRET")):
            result = auth.prepare_authentication(types.SimpleNamespace(cookies_file=None, cookies_browser="safari", session_dir=directory, auth_url=None))
            self.assertEqual(result["status"], "browserCookieAccessDenied")
            self.assertNotIn("SECRET", json.dumps(result))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_anonymous_never_reads_browser(self):
        with mock.patch.object(auth, "_export_browser") as exporter:
            self.assertEqual(auth.prepare_authentication(types.SimpleNamespace(cookies_file=None, cookies_browser=None)), {"ok": True, "status": "anonymous"})
        exporter.assert_not_called()

    def test_symlink_session_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.mkdir()
            alias = Path(directory) / "alias"
            alias.symlink_to(target)
            with self.assertRaises(ValueError):
                auth._session_directory(str(alias))


class EventAndRuntimeTests(unittest.TestCase):
    def test_progress_preserves_speed_bytes_eta_and_fragments(self):
        result = events.ProgressAccumulator().update({"filename": "one", "downloaded_bytes": 100, "total_bytes": 1000, "speed": 20, "eta": 45, "fragment_index": 1, "fragment_count": 10})
        self.assertEqual(result["progress"], 0.1)
        self.assertEqual(result["downloadedBytes"], 100)
        self.assertEqual(result["speedBytesPerSecond"], 20)
        self.assertEqual(result["fragmentCount"], 10)

    def test_multiple_tracks_accumulate_with_known_total(self):
        tracker = events.ProgressAccumulator()
        tracker.set_metadata({"formats": [{"filesize": 900}, {"filesize": 100}]})
        tracker.update({"filename": "video", "downloaded_bytes": 900, "total_bytes": 900})
        result = tracker.update({"filename": "audio", "downloaded_bytes": 50, "total_bytes": 100})
        self.assertEqual(result["downloadedBytes"], 950)
        self.assertEqual(result["totalBytes"], 1000)
        self.assertEqual(result["progress"], .95)

    def test_nan_metadata_never_enters_json(self):
        value = events.ProgressAccumulator().update({"speed": float("nan"), "eta": float("inf")})
        json.dumps(value, allow_nan=False)
        self.assertNotIn("etaSeconds", value)

    def test_event_message_redacts_headers_and_signed_tokens(self):
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            events.emit_event("error", message="Cookie: SID=SECRET\nhttps://media.invalid/a?token=HIDDEN")
        data = json.loads(captured.getvalue().removeprefix("OMD_EVENT:"))
        self.assertNotIn("SECRET", data["message"])
        self.assertNotIn("HIDDEN", data["message"])

    def test_private_native_staging_is_not_in_downloads(self):
        target = Path("/Users/someone/Downloads/movie.mp4")
        actual = downloads.temporary_target(target)
        self.assertNotEqual(actual.parent, target.parent)
        self.assertEqual(stat.S_IMODE(actual.parent.stat().st_mode), 0o700)

    def test_output_lock_serializes_same_target(self):
        entered = threading.Event()
        released = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "same.mp4"
            def contender():
                with runtime.target_lock(target):
                    entered.set()
                released.set()
            with runtime.target_lock(target):
                thread = threading.Thread(target=contender)
                thread.start()
                self.assertFalse(entered.wait(.05))
            self.assertTrue(released.wait(2))
            thread.join()

    def test_classified_geo_error_is_not_hidden_as_generic_extractor(self):
        error = errors.YTDLPError("This video is not available in your country")
        self.assertEqual(errors.classify_error(error), "geographicallyRestricted")

    def test_metadata_availability_inspection_does_not_read_cookies_browser(self):
        args = types.SimpleNamespace(media="video", quality="best", mode="auto", cookies_file=None, cookies_browser=None)
        with mock.patch.object(downloads, "ytdlp_options", return_value=["tool"]), mock.patch.object(downloads, "run_captured", return_value=types.SimpleNamespace(stdout=json.dumps({"title": "Demo", "formats": [direct_format(filesize=200)]}), stderr="", returncode=0)):
            result = inspection.inspect_url("https://youtube.com/watch?v=demo", args)
        self.assertEqual(result["entries"][0]["availability"], "available")
        self.assertTrue(result["entries"][0]["estimates"])

    def test_ytdlp_metadata_json_uses_valid_defaults_and_aggregate_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Movie.mp4"
            target.write_bytes(b"finished")
            process = mock.Mock()
            process.stdout = io.StringIO("\n".join([
                'OMD_METADATA:{"filesize":0,"filesizeApprox":1000,"formats":[{"filesize":900},{"filesize":100}]}',
                'OMD_PROGRESS:{"filename":"video","downloaded_bytes":900,"total_bytes":900}',
                'OMD_PROGRESS:{"filename":"audio","downloaded_bytes":50,"total_bytes":100}',
                "OMD_FILE:" + json.dumps(str(target)),
            ]))
            process.wait.return_value = 0
            captured = io.StringIO()
            with mock.patch.object(downloads, "ytdlp_options", return_value=["bundled-ytdlp"]), mock.patch.object(downloads, "start_process", return_value=process) as start, contextlib.redirect_stdout(captured):
                downloads._run_ytdlp_download_attempt("https://youtube.com/watch?v=test", target, types.SimpleNamespace())
            command = start.call_args.args[0]
            self.assertTrue(any("%(filesize|0)j" in item for item in command))
            payloads = [json.loads(line.removeprefix("OMD_EVENT:")) for line in captured.getvalue().splitlines()]
            progress = [item for item in payloads if item["type"] == "progress"]
            self.assertEqual([item["progress"] for item in progress], [.9, .95])
            self.assertEqual(payloads[-1]["type"], "completed")

    def test_sigterm_marks_cancellation_and_removes_private_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "private"
            staging.mkdir()
            (staging / "fragment.part").write_bytes(b"test")
            cancelled = threading.Event()
            with mock.patch.object(runtime, "_CANCELLED", cancelled), mock.patch.object(runtime, "_RUNTIME_TEMP_DIR", staging), mock.patch.object(runtime, "terminate_all_children") as children:
                with self.assertRaises(SystemExit):
                    runtime._termination_handler(15, None)
                self.assertTrue(cancelled.is_set())
                children.assert_called_once()
                self.assertFalse(staging.exists())


if __name__ == "__main__":
    unittest.main()
