import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omd import downloads as backend
from omd import inspection
from omd import runtime
import cli


def arguments(folder, **overrides):
    values = {
        "output": str(folder),
        "quality": "240",
        "mode": "auto",
        "workers": 4,
        "ask_overwrite": False,
        "overwrite": False,
        "check": False,
        "media": "video",
        "cookies_browser": None,
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.network_guard = mock.patch.object(backend, "get", side_effect=RuntimeError("Network disabled in unit tests"))
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)

    def test_unlisted_path_hash_is_preserved(self):
        self.assertEqual(
            backend.player_url("https://vimeo.com/123456789/abcDEF0123"),
            "https://player.vimeo.com/video/123456789?h=abcDEF0123",
        )

    def test_existing_query_hash_is_not_replaced(self):
        self.assertEqual(
            backend.player_url("https://vimeo.com/123456789?h=kept"),
            "https://player.vimeo.com/video/123456789?h=kept",
        )

    @mock.patch.object(backend, "player_config")
    @mock.patch.object(backend, "get")
    def test_public_page_hash_retries_old_vimeo_player_401(self, get, player_config):
        get.return_value = b'<iframe src="https://player.vimeo.com/video/170338499?h=40cb7ecd3c"></iframe>'
        expected = {"video": {"title": "Public old video"}}
        player_config.side_effect = [RuntimeError("HTTP 401"), expected]

        resolved, config = backend.resolved_player_config("https://vimeo.com/170338499")

        self.assertEqual(resolved, "https://player.vimeo.com/video/170338499?h=40cb7ecd3c")
        self.assertEqual(config, expected)
        self.assertEqual(player_config.call_args_list, [
            mock.call("https://player.vimeo.com/video/170338499"),
            mock.call("https://player.vimeo.com/video/170338499?h=40cb7ecd3c"),
        ])

    def test_nearest_quality_prefers_lower_on_tie(self):
        items = [{"height": 360}, {"height": 720}]
        self.assertEqual(backend.choose(items, "540")["height"], 360)

    @mock.patch.object(backend, "run_captured")
    @mock.patch.object(backend, "ytdlp_options")
    def test_playlist_preflight_skips_unavailable_items_and_uses_video_urls(self, options, run):
        options.return_value = ["yt-dlp"]
        run.return_value = mock.Mock(
            # yt-dlp can return a non-zero status for one private item while
            # still printing all playable entries from the same playlist.
            returncode=1,
            stdout=(
                "one_720p.mp4\thttps://youtube.com/watch?v=one\tOne\n"
                "two_360p.mp4\thttps://youtube.com/watch?v=two\tTwo\n"
            ),
            stderr="WARNING: one private entry was skipped",
        )

        entries = backend.ytdlp_preflight(
            "https://youtube.com/playlist?list=test", arguments("/tmp")
        )

        self.assertEqual([entry[1] for entry in entries], [
            "https://youtube.com/watch?v=one",
            "https://youtube.com/watch?v=two",
        ])
        command = run.call_args.args[0]
        self.assertIn("--ignore-errors", command)
        self.assertIn("%(filename)s\t%(webpage_url)s\t%(title)s", command)

    @mock.patch.object(backend, "run_captured")
    @mock.patch.object(backend, "ytdlp_options")
    def test_playlist_preflight_still_fails_when_nothing_is_playable(self, options, run):
        options.return_value = ["yt-dlp"]
        run.return_value = mock.Mock(returncode=1, stdout="", stderr="Private video")

        with self.assertRaisesRegex(RuntimeError, "Private video"):
            backend.ytdlp_preflight(
                "https://youtube.com/playlist?list=private", arguments("/tmp")
            )

    @mock.patch.object(backend, "run_captured")
    @mock.patch.object(backend, "ytdlp_options")
    def test_preflight_reports_final_audio_extension(self, options, run):
        options.return_value = ["yt-dlp"]
        run.return_value = mock.Mock(
            returncode=0,
            stdout="Demo_MP3_128k.webm\thttps://youtube.com/watch?v=one\tDemo\n",
            stderr="",
        )

        entries = backend.ytdlp_preflight(
            "https://youtube.com/watch?v=one",
            arguments("/tmp", media="mp3", quality="128k"),
            announce=False,
        )

        self.assertEqual(entries[0][0], Path("Demo_MP3_128k.mp3"))

    def test_confirmed_overwrite_replaces_only_after_download(self):
        cfg = {"video": {"title": "Demo"}, "request": {"files": {"progressive": [
            {"height": 240, "width": 426, "url": "https://cdn.invalid/video.mp4"}
        ]}}}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            target = folder / "Demo_240p.mp4"
            target.write_bytes(b"old")

            def fake_download(_url, path, progress=False):
                self.assertNotEqual(path, target)
                path.write_bytes(b"complete-new-file")

            args = arguments(folder, ask_overwrite=True)
            with mock.patch.object(backend, "player_config", return_value=cfg), \
                    mock.patch.object(backend, "download_one", side_effect=fake_download), \
                    mock.patch("builtins.input", return_value="y"), redirect_stdout(io.StringIO()):
                backend.process("https://vimeo.com/123", args)

            self.assertEqual(target.read_bytes(), b"complete-new-file")
            self.assertEqual(list(folder.glob("*.part.mp4")), [])

    def test_declined_overwrite_keeps_file_and_does_not_download(self):
        cfg = {"video": {"title": "Demo"}, "request": {"files": {"progressive": [
            {"height": 240, "width": 426, "url": "https://cdn.invalid/video.mp4"}
        ]}}}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            target = folder / "Demo_240p.mp4"
            target.write_bytes(b"keep")
            args = arguments(folder, ask_overwrite=True)
            with mock.patch.object(backend, "player_config", return_value=cfg), \
                    mock.patch.object(backend, "download_one") as download, \
                    mock.patch("builtins.input", return_value="n"), redirect_stdout(io.StringIO()):
                backend.process("https://vimeo.com/123", args)

            download.assert_not_called()
            self.assertEqual(target.read_bytes(), b"keep")

    def test_direct_mode_reports_missing_direct_mp4(self):
        cfg = {"video": {"title": "HLS only"}, "request": {"files": {"progressive": []}}}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(backend, "player_config", return_value=cfg):
            with self.assertRaisesRegex(RuntimeError, "прямой MP4"):
                backend.process("https://vimeo.com/123", arguments(directory, mode="direct"))

    def test_inspect_public_vimeo_reports_title_and_known_heights(self):
        cfg = {"video": {"title": "Public demo"}, "request": {"files": {"progressive": [
            {"height": 360}, {"height": 1080}, {"height": 720},
        ]}}}
        with mock.patch.object(backend, "player_config", return_value=cfg):
            result = inspection.inspect_url("https://vimeo.com/123", arguments("/tmp"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["entries"][0]["title"], "Public demo")
        self.assertEqual(result["entries"][0]["availableHeights"], [1080, 720, 360])

    def test_inspect_old_public_vimeo_passes_discovered_hash_to_ytdlp(self):
        metadata = {"title": "Old public", "webpage_url": "https://player.vimeo.com/video/170338499?h=public", "formats": [{"height": 720}]}
        with mock.patch.object(backend, "resolved_player_config", side_effect=RuntimeError("401")), \
                mock.patch.object(backend, "discover_public_player_url", return_value="https://player.vimeo.com/video/170338499?h=public"), \
                mock.patch.object(inspection, "read_ytdlp_metadata", return_value=(metadata, [])) as preflight:
            result = inspection.inspect_url("https://vimeo.com/170338499", arguments("/tmp"))

        self.assertTrue(result["ok"])
        preflight.assert_called_once_with(
            "https://player.vimeo.com/video/170338499?h=public", mock.ANY
        )

    def test_inspect_playlist_returns_each_playable_video_url(self):
        metadata = {"_type": "playlist", "entries": [
            {"webpage_url": "https://youtube.com/watch?v=one", "title": "One", "formats": [{"height": 720}]},
            {"webpage_url": "https://youtube.com/watch?v=two", "title": "Two", "formats": [{"height": 360}]},
        ]}
        with mock.patch.object(inspection, "read_ytdlp_metadata", return_value=(metadata, [])) as preflight:
            result = inspection.inspect_url(
                "https://youtube.com/playlist?list=test", arguments("/tmp")
            )

        self.assertEqual([item["url"] for item in result["entries"]], [
            "https://youtube.com/watch?v=one",
            "https://youtube.com/watch?v=two",
        ])
        preflight.assert_called_once_with(
            "https://youtube.com/playlist?list=test", mock.ANY
        )

    def ytdlp_command(self, **overrides):
        args = arguments("/tmp", **overrides)
        with mock.patch.object(backend, "ytdlp", return_value="/app/bin/yt-dlp"), \
                mock.patch.object(backend, "ffmpeg", return_value="/app/bin/ffmpeg"), \
                mock.patch.object(backend, "deno", return_value=None):
            return backend.ytdlp_options(args)

    def test_aac_uses_only_aac_and_stream_copy_m4a(self):
        command = self.ytdlp_command(media="aac", quality="best")

        self.assertIn("--remux-video", command)
        self.assertEqual(command[command.index("--remux-video") + 1], "m4a")
        self.assertNotIn("--extract-audio", command)
        selector = command[command.index("-f") + 1]
        self.assertIn("acodec^=mp4a", selector)
        self.assertIn("%(title).180B_AAC.%(ext)s", command)

    def test_mp3_uses_requested_supported_bitrate(self):
        command = self.ytdlp_command(media="mp3", quality="256k")

        self.assertIn("--extract-audio", command)
        self.assertEqual(command[command.index("--audio-format") + 1], "mp3")
        self.assertEqual(command[command.index("--audio-quality") + 1], "256K")
        self.assertIn("%(title).180B_MP3_256k.%(ext)s", command)

    def test_mp3_unknown_quality_defaults_to_320k(self):
        self.assertEqual(backend.mp3_bitrate("best"), "320K")
        self.assertEqual(backend.mp3_bitrate("720"), "320K")
        self.assertEqual(backend.mp3_bitrate("128k"), "128K")

    def test_explicit_mode_suffix_does_not_change_auto_names(self):
        self.assertEqual(backend.explicit_mode_suffix(arguments("/tmp", mode="auto")), "")
        self.assertEqual(backend.explicit_mode_suffix(arguments("/tmp", mode="direct")), "_direct")
        self.assertEqual(backend.explicit_mode_suffix(arguments("/tmp", mode="chunks")), "_chunks")

    def test_ytdlp_output_names_distinguish_direct_and_chunks_variants(self):
        cases = [
            ("video", "720", "%(height)sp"),
            ("aac", "best", "_AAC"),
            ("mp3", "192k", "_MP3_192k"),
        ]
        for mode in ("direct", "chunks"):
            for media, quality, quality_suffix in cases:
                with self.subTest(mode=mode, media=media):
                    command = self.ytdlp_command(mode=mode, media=media, quality=quality)
                    template = command[command.index("--output") + 1]
                    self.assertIn(f"{quality_suffix}_{mode}.%(ext)s", template)

    def test_ytdlp_auto_output_names_remain_backwards_compatible(self):
        expected_templates = {
            "video": "%(title).180B_%(height)sp.%(ext)s",
            "aac": "%(title).180B_AAC.%(ext)s",
            "mp3": "%(title).180B_MP3_192k.%(ext)s",
        }
        for media, expected in expected_templates.items():
            with self.subTest(media=media):
                command = self.ytdlp_command(media=media, quality="192k")
                self.assertEqual(command[command.index("--output") + 1], expected)

    def test_cookie_browser_and_bundled_deno_are_forwarded(self):
        for browser in ("safari", "chrome", "opera"):
            with self.subTest(browser=browser):
                args = arguments("/tmp", cookies_browser=browser)
                with mock.patch.object(backend, "ytdlp", return_value="/app/bin/yt-dlp"), \
                        mock.patch.object(backend, "ffmpeg", return_value="/app/bin/ffmpeg"), \
                        mock.patch.object(backend, "deno", return_value="/app/bin/deno"):
                    command = backend.ytdlp_options(args)

                self.assertEqual(command[command.index("--cookies-from-browser") + 1], browser)
                self.assertEqual(command[command.index("--js-runtimes") + 1], "deno:/app/bin/deno")

    def test_cookie_store_failures_are_recognized_for_supported_browsers(self):
        failures = [
            (
                "ERROR: [Errno 1] Operation not permitted: "
                "'/Users/example-user/Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies'"
            ),
            (
                "ERROR: Could not copy Chrome cookie database "
                "'/Users/alice/Library/Application Support/Google/Chrome/Default/Cookies': database is locked"
            ),
            (
                "ERROR: could not find firefox cookies database in "
                "'/Users/bob/Library/Application Support/Firefox/Profiles/default/cookies.sqlite'"
            ),
            (
                "ERROR: Failed to decrypt Brave cookies from "
                "'/Users/carol/Library/Application Support/BraveSoftware/Default/Cookies'"
            ),
            "ERROR: Safari cookies database does not exist",
            "ERROR: Failed to decrypt Opera cookies",
        ]

        for detail in failures:
            with self.subTest(detail=detail):
                self.assertTrue(backend.is_cookie_access_error(detail))

    def test_extractor_cookie_advice_is_not_a_cookie_store_failure(self):
        extractor_errors = [
            "ERROR: Sign in to confirm your age. Use --cookies-from-browser",
            "ERROR: This video is private; browser cookies may be required",
            "ERROR: Failed to decrypt the video signature. Try cookies",
            (
                "ERROR: Operation not permitted for this video\n"
                "INFO: Use --cookies-from-browser if you are signed in"
            ),
        ]

        for detail in extractor_errors:
            with self.subTest(detail=detail):
                self.assertFalse(backend.is_cookie_access_error(detail))

    def test_cookie_database_paths_are_sanitized_even_when_they_contain_spaces(self):
        details = [
            (
                "ERROR: Permission denied: '/Users/secret-user/Library/Containers/"
                "com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies'"
            ),
            (
                'ERROR: locked "/Users/chrome-user/Library/Application Support/'
                'Google/Chrome/Profile 1/Cookies"'
            ),
            (
                "ERROR: missing /Users/firefox-user/Library/Application Support/"
                "Firefox/Profiles/a b.default/cookies.sqlite"
            ),
        ]

        sanitized = "\n".join(backend.sanitized_ytdlp_detail(item) for item in details)

        self.assertNotIn("/Users/", sanitized)
        self.assertNotIn("secret-user", sanitized)
        self.assertNotIn("chrome-user", sanitized)
        self.assertNotIn("firefox-user", sanitized)
        self.assertNotIn("Cookies.binarycookies", sanitized)
        self.assertNotIn("cookies.sqlite", sanitized)
        self.assertEqual(sanitized.count("<cookie database>"), 3)

    @mock.patch.object(backend, "run_captured")
    def test_inspect_retries_public_url_without_inaccessible_safari_cookies(self, run):
        cookie_failure = mock.Mock(
            returncode=1,
            stdout="",
            stderr=(
                "ERROR: [Errno 1] Operation not permitted: "
                "'/Users/example/Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies'"
            ),
        )
        public_success = mock.Mock(
            returncode=0,
            stdout=json.dumps({"title": "Public demo", "webpage_url": "https://youtube.com/watch?v=demo", "formats": [{"height": 720}]}),
            stderr="",
        )
        run.side_effect = [cookie_failure, public_success]
        args = arguments("/tmp", cookies_browser="safari")

        with mock.patch.object(backend, "ytdlp", return_value="/app/bin/yt-dlp"), \
                mock.patch.object(backend, "ffmpeg", return_value="/app/bin/ffmpeg"), \
                mock.patch.object(backend, "deno", return_value=None):
            result = inspection.inspect_url("https://youtube.com/watch?v=demo", args)

        self.assertTrue(result["ok"])
        self.assertTrue(result["cookieFallbackUsed"])
        self.assertEqual(result["warnings"], [{
            "code": "browserCookieAccessDenied",
            "browser": "safari",
            "fallback": "withoutCookies",
        }])
        self.assertEqual(result["entries"][0]["title"], "Public demo")
        first_command, second_command = [call.args[0] for call in run.call_args_list]
        self.assertIn("--cookies-from-browser", first_command)
        self.assertNotIn("--cookies-from-browser", second_command)
        self.assertNotIn("/Users/example", json.dumps(result))

    @mock.patch.object(backend, "run_captured")
    @mock.patch.object(backend, "ytdlp_options", return_value=["yt-dlp"])
    def test_cookie_fallback_classifies_login_requirement(self, _options, run):
        run.side_effect = [
            mock.Mock(
                returncode=1,
                stdout="",
                stderr="ERROR: Operation not permitted: /private/Cookies.binarycookies",
            ),
            mock.Mock(
                returncode=1,
                stdout="",
                stderr="ERROR: Sign in to confirm your age. Use --cookies-from-browser",
            ),
        ]

        with self.assertRaises(backend.AuthenticationRequiredError) as raised:
            backend.ytdlp_preflight(
                "https://youtube.com/watch?v=age", arguments("/tmp", cookies_browser="safari"), announce=False
            )

        self.assertEqual(raised.exception.code, "authenticationRequired")
        self.assertEqual(raised.exception.warnings[0]["code"], "browserCookieAccessDenied")
        self.assertIn("Нужна авторизация", str(raised.exception))
        self.assertNotIn("/private/Cookies.binarycookies", str(raised.exception))
        self.assertEqual(run.call_count, 2)

    @mock.patch.object(backend, "run_captured")
    @mock.patch.object(backend, "ytdlp_options", return_value=["yt-dlp"])
    def test_unrelated_preflight_error_is_not_retried_without_cookies(self, _options, run):
        run.return_value = mock.Mock(
            returncode=1,
            stdout="",
            stderr="ERROR: This video is not available in your country",
        )

        with self.assertRaises(backend.YTDLPError):
            backend.ytdlp_preflight(
                "https://youtube.com/watch?v=geo", arguments("/tmp", cookies_browser="safari"), announce=False
            )

        self.assertEqual(run.call_count, 1)

    def test_download_retries_without_cookies_after_cookie_permission_failure(self):
        denied = backend.YTDLPError(
            "cookie failure",
            raw_detail="ERROR: [Errno 1] Operation not permitted: /private/Cookies.binarycookies",
        )
        output = io.StringIO()
        args = arguments("/tmp", cookies_browser="safari")

        with mock.patch.object(
                backend, "_run_ytdlp_download_attempt", side_effect=[denied, None]
            ) as attempt, redirect_stdout(output):
            backend.run_ytdlp_download(
                "https://youtube.com/watch?v=public", Path("/tmp/Public_720p.mp4"), args
            )

        self.assertEqual(attempt.call_count, 2)
        self.assertTrue(attempt.call_args_list[0].kwargs["use_browser_cookies"])
        self.assertFalse(attempt.call_args_list[1].kwargs["use_browser_cookies"])
        self.assertIn(
            '"code":"browserCookieAccessDenied","browser":"safari","fallback":"withoutCookies"',
            output.getvalue(),
        )
        self.assertNotIn("Cookies.binarycookies", output.getvalue())

    def test_download_cookie_fallback_classifies_authentication_required(self):
        denied = backend.YTDLPError(
            "cookie failure",
            raw_detail="ERROR: Permission denied: /private/Cookies.binarycookies",
        )
        login = backend.YTDLPError(
            "login failure",
            raw_detail="ERROR: This video is private. Sign in to view it.",
        )

        with mock.patch.object(
                backend, "_run_ytdlp_download_attempt", side_effect=[denied, login]
            ), redirect_stdout(io.StringIO()), self.assertRaises(backend.AuthenticationRequiredError) as raised:
            backend.run_ytdlp_download(
                "https://youtube.com/watch?v=private",
                Path("/tmp/Private_720p.mp4"),
                arguments("/tmp", cookies_browser="safari"),
            )

        self.assertEqual(raised.exception.code, "authenticationRequired")
        self.assertEqual(raised.exception.warnings[0]["fallback"], "withoutCookies")

    def test_download_unrelated_error_is_not_retried_without_cookies(self):
        unrelated = backend.YTDLPError(
            "geo restriction",
            raw_detail="ERROR: This video is not available in your country",
        )

        with mock.patch.object(
                backend, "_run_ytdlp_download_attempt", side_effect=unrelated
            ) as attempt, self.assertRaises(backend.YTDLPError):
            backend.run_ytdlp_download(
                "https://youtube.com/watch?v=geo",
                Path("/tmp/Geo_720p.mp4"),
                arguments("/tmp", cookies_browser="safari"),
            )

        attempt.assert_called_once()

    def test_inspect_json_auth_error_has_stable_machine_readable_fields(self):
        warning = backend.cookie_access_warning("safari")
        failure = backend.AuthenticationRequiredError("Нужна авторизация", warnings=[warning])
        output = io.StringIO()
        argv = ["vimeo_downloader.py", "--inspect-json", "https://youtube.com/watch?v=private"]

        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(cli, "inspect_url", side_effect=failure), \
                redirect_stdout(output):
            code = cli.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errorCode"], "authenticationRequired")
        self.assertTrue(payload["authenticationRequired"])
        self.assertTrue(payload["cookieFallbackUsed"])
        self.assertEqual(payload["warnings"], [warning])

    def test_inspect_json_never_exposes_cookie_database_path(self):
        failure = backend.BackendError(
            "Cannot read /Users/private-name/Library/Application Support/Chrome/Default/Cookies"
        )
        output = io.StringIO()
        argv = ["vimeo_downloader.py", "--inspect-json", "https://youtube.com/watch?v=private"]

        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(cli, "inspect_url", side_effect=failure), \
                redirect_stdout(output):
            code = cli.main()

        payload_text = output.getvalue()
        self.assertEqual(code, 1)
        self.assertNotIn("/Users/", payload_text)
        self.assertNotIn("private-name", payload_text)
        self.assertNotIn("/Default/Cookies", payload_text)

    def test_direct_youtube_selects_direct_http_files(self):
        command = self.ytdlp_command(mode="direct")
        selector = command[command.index("-f") + 1]

        self.assertIn("protocol=https", selector)
        self.assertIn("protocol=http", selector)
        self.assertNotIn("protocol^=http", selector)
        self.assertNotIn("http_dash_segments", selector)
        self.assertIn("bv*", selector)
        self.assertIn("ba", selector)
        self.assertIn("+", selector)
        self.assertIn("/b[protocol=https]", selector)

    def test_direct_audio_selectors_only_allow_exact_http_protocols(self):
        for media in ("aac", "mp3"):
            with self.subTest(media=media):
                command = self.ytdlp_command(mode="direct", media=media)
                selector = command[command.index("-f") + 1]
                self.assertIn("protocol=https", selector)
                self.assertIn("protocol=http", selector)
                self.assertNotIn("protocol^=http", selector)
                self.assertNotIn("protocol*=", selector)

    def test_chunks_youtube_selects_adaptive_video_and_audio(self):
        command = self.ytdlp_command(mode="chunks", workers=9)

        self.assertEqual(command[command.index("--concurrent-fragments") + 1], "9")
        selector = command[command.index("-f") + 1]
        self.assertIn("bv[protocol*=m3u8]+ba[protocol*=m3u8]", selector)
        self.assertIn("bv[protocol*=dash]+ba[protocol*=dash]", selector)
        self.assertNotIn("bv+ba", selector)

    def test_chunks_audio_selectors_have_no_unqualified_direct_fallback(self):
        for media in ("aac", "mp3"):
            with self.subTest(media=media):
                command = self.ytdlp_command(mode="chunks", media=media)
                selector = command[command.index("-f") + 1]
                for alternative in selector.split("/"):
                    self.assertIn("protocol*=", alternative)
                self.assertNotIn("/ba/", f"/{selector}/")
                self.assertNotIn("/b/", f"/{selector}/")

    def test_ytdlp_is_offline_self_contained(self):
        command = self.ytdlp_command()

        self.assertIn("--no-remote-components", command)

    def test_ytdlp_fragments_use_private_temp_directory(self):
        command = self.ytdlp_command()

        path_values = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "--paths"]
        self.assertTrue(any(value.startswith("temp:") for value in path_values))
        configured = Path(next(value for value in path_values if value.startswith("temp:")).removeprefix("temp:"))
        self.assertTrue(configured.is_relative_to(Path(tempfile.gettempdir())))

    def test_audio_vimeo_goes_through_ytdlp(self):
        args = arguments("/tmp", media="aac")
        with mock.patch.object(backend, "process_ytdlp") as process_ytdlp, \
                mock.patch.object(backend, "process") as native_process:
            backend.process_with_fallback("https://vimeo.com/123", args)

        process_ytdlp.assert_called_once_with("https://player.vimeo.com/video/123", args)
        native_process.assert_not_called()

    def test_aac_native_vimeo_fallback_copies_stream_to_m4a(self):
        cfg = {"video": {"title": "Audio demo"}, "request": {"files": {"progressive": [
            {"height": 720, "url": "https://cdn.invalid/high.mp4"},
            {"height": 240, "url": "https://cdn.invalid/low.mp4"},
        ]}}}
        with tempfile.TemporaryDirectory() as directory:
            args = arguments(directory, media="aac", quality="best")

            def fake_download(url, path, progress=False):
                self.assertEqual(url, "https://cdn.invalid/low.mp4")
                path.write_bytes(b"source")

            def fake_ffmpeg(command):
                self.assertIn("copy", command)
                self.assertNotIn("libmp3lame", command)
                Path(command[-1]).write_bytes(b"original-aac")

            with mock.patch.object(backend, "player_config", return_value=cfg), \
                    mock.patch.object(backend, "download_one", side_effect=fake_download), \
                    mock.patch.object(backend, "run_ffmpeg", side_effect=fake_ffmpeg), \
                    redirect_stdout(io.StringIO()):
                backend.process_vimeo_audio_native("https://vimeo.com/123", args)

            results = list(Path(directory).glob("*.m4a"))
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].read_bytes(), b"original-aac")

    def test_mp3_native_vimeo_fallback_uses_selected_bitrate(self):
        cfg = {"video": {"title": "Audio demo"}, "request": {"files": {"progressive": [
            {"height": 360, "url": "https://cdn.invalid/video.mp4"},
        ]}}}
        with tempfile.TemporaryDirectory() as directory:
            args = arguments(directory, media="mp3", quality="192k")

            def fake_download(_url, path, progress=False):
                path.write_bytes(b"source")

            def fake_ffmpeg(command):
                self.assertIn("libmp3lame", command)
                self.assertEqual(command[command.index("-b:a") + 1], "192K")
                Path(command[-1]).write_bytes(b"encoded-mp3")

            with mock.patch.object(backend, "player_config", return_value=cfg), \
                    mock.patch.object(backend, "download_one", side_effect=fake_download), \
                    mock.patch.object(backend, "run_ffmpeg", side_effect=fake_ffmpeg), \
                    redirect_stdout(io.StringIO()):
                backend.process_vimeo_audio_native("https://vimeo.com/123", args)

            results = list(Path(directory).glob("*.mp3"))
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].read_bytes(), b"encoded-mp3")

    def test_native_vimeo_audio_explicit_direct_names_include_mode(self):
        cfg = {"video": {"title": "Audio demo"}, "request": {"files": {"progressive": [
            {"height": 360, "url": "https://cdn.invalid/video.mp4"},
        ]}}}
        cases = [
            ("aac", "best", "Audio demo_AAC_direct.m4a"),
            ("mp3", "192k", "Audio demo_MP3_192k_direct.mp3"),
        ]
        for media, quality, expected_name in cases:
            with self.subTest(media=media), tempfile.TemporaryDirectory() as directory:
                args = arguments(directory, media=media, quality=quality, mode="direct")

                def fake_download(_url, path, progress=False):
                    path.write_bytes(b"source")

                def fake_ffmpeg(command):
                    Path(command[-1]).write_bytes(b"audio")

                with mock.patch.object(backend, "player_config", return_value=cfg), \
                        mock.patch.object(backend, "download_one", side_effect=fake_download), \
                        mock.patch.object(backend, "run_ffmpeg", side_effect=fake_ffmpeg), \
                        redirect_stdout(io.StringIO()):
                    backend.process_vimeo_audio_native("https://vimeo.com/123", args)

                self.assertTrue((Path(directory) / expected_name).exists())

    def test_native_vimeo_video_direct_and_chunks_names_do_not_collide(self):
        cfg = {"video": {"title": "Same video"}, "request": {"files": {"progressive": [
            {"height": 720, "width": 1280, "url": "https://cdn.invalid/video.mp4"},
        ]}}}
        with tempfile.TemporaryDirectory() as directory:
            direct_args = arguments(directory, quality="720", mode="direct")
            chunks_args = arguments(directory, quality="720", mode="chunks")

            def fake_direct_download(_url, path, progress=False):
                path.write_bytes(b"direct")

            def fake_hls_download(_cfg, path, _quality, _workers):
                path.write_bytes(b"chunks")

            with mock.patch.object(backend, "resolved_player_config", return_value=("player", cfg)), \
                    mock.patch.object(backend, "download_one", side_effect=fake_direct_download), \
                    redirect_stdout(io.StringIO()):
                backend.process("https://vimeo.com/123", direct_args)

            with mock.patch.object(backend, "resolved_player_config", return_value=("player", cfg)), \
                    mock.patch.object(backend, "hls_url", return_value="https://cdn.invalid/master.m3u8"), \
                    mock.patch.object(backend, "playlist", return_value=({"height": 720}, None)), \
                    mock.patch.object(backend, "download_hls", side_effect=fake_hls_download), \
                    redirect_stdout(io.StringIO()):
                backend.process("https://vimeo.com/123", chunks_args)

            direct = Path(directory) / "Same video_720p_direct.mp4"
            chunks = Path(directory) / "Same video_720p_chunks.mp4"
            self.assertEqual(direct.read_bytes(), b"direct")
            self.assertEqual(chunks.read_bytes(), b"chunks")

    def test_failed_vimeo_audio_only_route_uses_native_fallback(self):
        args = arguments("/tmp", media="aac")
        with mock.patch.object(backend, "process_ytdlp", side_effect=RuntimeError("no audio")), \
                mock.patch.object(backend, "process_vimeo_audio_native") as native, \
                redirect_stdout(io.StringIO()):
            backend.process_with_fallback("https://vimeo.com/123", args)

        native.assert_called_once_with("https://vimeo.com/123", args, None)

    def test_terminate_all_children_terminates_process_group(self):
        process = mock.Mock(pid=4321)
        process.poll.return_value = None
        process.wait.return_value = 0
        runtime._ACTIVE_PROCESSES.add(process)
        with mock.patch.object(runtime.os, "killpg") as killpg:
            runtime.terminate_all_children()

            killpg.assert_any_call(4321, runtime.signal.SIGTERM)
            # Ein Kind, das im Mock nach TERM weiterläuft, wird nach der Frist
            # auch mit KILL beendet. Der neue Test prüft echte Prozesse separat.
            killpg.assert_any_call(4321, runtime.signal.SIGKILL)
        self.assertNotIn(process, runtime._ACTIVE_PROCESSES)

    def test_cleanup_cancelled_ytdlp_fragments_is_confined_to_private_runtime(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as private_directory, \
                tempfile.TemporaryDirectory() as other_private_directory:
            folder = Path(directory)
            private = Path(private_directory)
            other_private = Path(other_private_directory)
            target = folder / "Demo_2160p.mp4"
            finished = folder / "Demo_2160p.webm"
            # A different parallel backend may legitimately own same-stem
            # files elsewhere; cleanup must not infer ownership from the stem
            # in the user's output directory.
            foreign_output_partial = folder / "Demo_2160p.f642.mp4.part"
            foreign_runtime_partial = other_private / "Demo_2160p.f642.mp4.part"
            owned_temporary = [
                private / "Demo_2160p.f642.mp4.part",
                private / "Demo_2160p.f642.mp4.part-Frag3.part",
                private / "Demo_2160p.f642.mp4.ytdl",
            ]
            unrelated_temporary = private / "Other_2160p.f642.mp4.part"
            old_output_temporaries = [
                folder / "Demo_2160p.f642.mp4.part",
                folder / "Demo_2160p.f642.mp4.part-Frag3.part",
                folder / "Demo_2160p.f642.mp4.ytdl",
            ]
            target.write_bytes(b"finished-mp4")
            finished.write_bytes(b"finished-webm")
            foreign_runtime_partial.write_bytes(b"other-process")
            unrelated_temporary.write_bytes(b"different-job")
            for item in owned_temporary + old_output_temporaries:
                item.write_bytes(b"partial")

            with mock.patch.object(runtime, "_RUNTIME_TEMP_DIR", private):
                backend.cleanup_ytdlp_partials(target)

            self.assertTrue(target.exists())
            self.assertTrue(finished.exists())
            self.assertTrue(foreign_output_partial.exists())
            self.assertTrue(foreign_runtime_partial.exists())
            self.assertTrue(unrelated_temporary.exists())
            self.assertFalse(any(item.exists() for item in owned_temporary))


if __name__ == "__main__":
    unittest.main()
