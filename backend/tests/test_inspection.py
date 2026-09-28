import contextlib
import hashlib
import io
import json
import subprocess
import sys
import types
import threading
import http.server
import socket
import tempfile
import urllib.request
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cli
from omd import runtime, inspection


FIXTURES = Path(__file__).parent / "fixtures" / "inspection"


def fake_process(children, stderr=""):
    class FakeProcess:
        def __init__(self):
            rows = []
            for child in children:
                row = dict(child)
                row.setdefault("playlist_id", "fixture-list")
                row.setdefault("playlist_title", "Fixture playlist")
                rows.append(json.dumps(row) + "\n")
            self.stdout = io.StringIO("".join(rows))
            self.stderr = io.StringIO(stderr)
            self.returncode = 0
        def wait(self): return self.returncode
        def poll(self): return self.returncode

    return FakeProcess()


class StreamingInspectionTests(unittest.TestCase):
    def setUp(self):
        self.args = types.SimpleNamespace(
            request_id="request-7", generation=12, cookies_browser=None,
            cookies_file=None, media="video", quality="best", mode="auto",
        )

    def capture(self, operation):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            ok = operation()
        events = [json.loads(line.removeprefix("OMD_EVENT:")) for line in output.getvalue().splitlines()]
        return ok, events

    def test_playlist_entries_precede_per_item_probes_and_bad_item_does_not_stop_rest(self):
        payload = json.loads((FIXTURES / "flat_playlist.json").read_text())
        def detail(url, _args):
            if url.endswith("one"):
                raise RuntimeError("temporary extractor failure")
            return {"entries": [{"url": url, "title": "Second fixture video", "availability": "available", "estimates": []}]}
        with mock.patch.object(cli.downloads, "ytdlp_options", return_value=["yt-dlp"]), \
             mock.patch.object(cli.runtime, "start_process", return_value=fake_process(payload["entries"])), \
             mock.patch.object(cli.runtime, "_unregister_process"), \
             mock.patch.object(cli, "inspect_url", side_effect=detail):
            ok, events = self.capture(lambda: cli._stream_inspection("https://video.invalid/list", self.args))
        self.assertTrue(ok)
        self.assertEqual([event["type"] for event in events[:3]], ["title", "playlistEntry", "playlistEntry"])
        self.assertIn("discoveryComplete", [event["type"] for event in events])
        self.assertEqual(events[-1]["type"], "inspectionComplete")
        self.assertTrue(all(event["requestId"] == "request-7" and event["generation"] == 12 for event in events))
        self.assertEqual(events[1]["availability"], "unknown")

    def test_deterministic_playlist_size_and_mixed_availability_fixtures(self):
        # Generate rows from a stable synthetic pattern so large playlists stay
        # compact in source control and never need account or network data.
        for count in (0, 1, 100, 1000):
            with self.subTest(count=count):
                children = [
                    {"id": f"fixture-{index:04d}", "title": f"Synthetic video {index:04d}",
                     "url": f"https://video.invalid/watch/fixture-{index:04d}"}
                    for index in range(count)
                ]
                def detail(url, _args):
                    if url.endswith(("fixture-0001", "fixture-0003")):
                        raise RuntimeError("synthetic unavailable item")
                    return {"entries": [{"url": url, "title": "Synthetic playable item", "availability": "available", "estimates": []}]}
                with mock.patch.object(cli.downloads, "ytdlp_options", return_value=["yt-dlp"]), \
                     mock.patch.object(cli.runtime, "start_process", return_value=fake_process(children)), \
                     mock.patch.object(cli.runtime, "_unregister_process"), \
                     mock.patch.object(cli, "inspect_url", side_effect=detail) as inspect:
                    ok, events = self.capture(lambda: cli._stream_inspection("https://www.youtube.com/playlist?list=synthetic-fixture", self.args))
                rows = [event for event in events if event["type"] == "playlistEntry"]
                self.assertTrue(ok)
                self.assertEqual(len(rows), count)
                self.assertEqual([row["index"] for row in rows], list(range(count)))
                self.assertEqual(inspect.call_count, count)
                self.assertEqual(events[-1]["type"], "inspectionComplete")
                self.assertEqual(events[-1]["count"], count)
                self.assertIsNone(self.args.cookies_browser)
                self.assertIsNone(self.args.cookies_file)
                if count >= 4:
                    errors = [event for event in events if event["type"] == "inspectionError"]
                    self.assertEqual(sorted(event["index"] for event in errors), [1, 3])

    def test_duplicate_playlist_rows_remain_distinct_fixture_entries(self):
        shared = "https://video.invalid/watch/synthetic-duplicate"
        children = [
            {"id": "fixture-a", "title": "Synthetic duplicate A", "url": shared},
            {"id": "fixture-b", "title": "Synthetic duplicate B", "url": shared},
        ]
        detail = {"entries": [{"url": shared, "title": "Synthetic media", "availability": "available", "estimates": []}]}
        with mock.patch.object(cli.downloads, "ytdlp_options", return_value=["yt-dlp"]), \
             mock.patch.object(cli.runtime, "start_process", return_value=fake_process(children)), \
             mock.patch.object(cli.runtime, "_unregister_process"), \
             mock.patch.object(cli, "inspect_url", return_value=detail) as inspect:
            ok, events = self.capture(lambda: cli._stream_inspection("https://www.youtube.com/playlist?list=synthetic-fixture", self.args))
        self.assertTrue(ok)
        self.assertEqual([event["index"] for event in events if event["type"] == "playlistEntry"], [0])
        self.assertEqual(inspect.call_count, 1)

    def test_streams_rows_before_eof_while_first_metadata_is_blocked(self):
        output = io.StringIO()
        emitted_first = threading.Event()
        detail_started = threading.Event()
        release_detail = threading.Event()
        state = {"eof": False}
        lines = [json.dumps({"url": f"https://video.invalid/{n}", "title": str(n), "playlist_id": "p"}) + "\n" for n in range(3)]
        class Stdout:
            def __iter__(self):
                yield lines[0]
                current = [json.loads(line.removeprefix("OMD_EVENT:")) for line in output.getvalue().splitlines()]
                assert any(event["type"] == "playlistEntry" for event in current)
                emitted_first.set()
                assert detail_started.wait(2)
                assert not release_detail.is_set()
                yield lines[1]
                yield lines[2]
                state["eof"] = True
            def close(self): pass
        class Process:
            stdout = Stdout()
            stderr = io.StringIO()
            returncode = 0
            def wait(self):
                assert state["eof"]
                return self.returncode
            def poll(self): return self.returncode
        def detail(url, _args):
            if url.endswith("/0"):
                detail_started.set()
                self.assertTrue(emitted_first.wait(2))
                self.assertFalse(release_detail.is_set())
                release_detail.wait(2)
            return {"entries": [{"url": url, "title": "detail", "availability": "available", "estimates": []}]}
        def run():
            with contextlib.redirect_stdout(output), \
                 mock.patch.object(cli.downloads, "ytdlp_options", return_value=["yt-dlp"]), \
                 mock.patch.object(cli.runtime, "start_process", return_value=Process()), \
                 mock.patch.object(cli.runtime, "_unregister_process"), \
                 mock.patch.object(cli, "inspect_url", side_effect=detail):
                result.append(cli._stream_inspection("https://www.youtube.com/playlist?list=fixture", self.args))
        result = []
        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(emitted_first.wait(2))
        # The fake stdout continues through every row while inspect_url(0) is blocked.
        for _ in range(100):
            if state["eof"]: break
            threading.Event().wait(0.01)
        self.assertTrue(state["eof"])
        release_detail.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        events = [json.loads(line.removeprefix("OMD_EVENT:")) for line in output.getvalue().splitlines()]
        row_positions = [i for i, event in enumerate(events) if event["type"] == "playlistEntry"]
        metadata_positions = [i for i, event in enumerate(events) if event["type"] == "metadata"]
        self.assertEqual(len(row_positions), 3)
        self.assertTrue(all(row < min(metadata_positions) for row in row_positions))
        self.assertGreater(next(i for i, e in enumerate(events) if e["type"] == "discoveryComplete"), max(row_positions))
        self.assertTrue(result[0], output.getvalue())

    def test_priority_moves_queued_item_ahead_with_four_workers_occupied(self):
        output = io.StringIO()
        started = []
        active = 0
        max_active = 0
        started_lock = threading.Lock()
        four_started = threading.Event()
        release = threading.Event()
        command_sent = threading.Event()
        priority_processed = threading.Event()
        ids = {f"https://video.invalid/{n}": hashlib.sha256(f"https://video.invalid/{n}".encode()).hexdigest()[:24] for n in range(6)}
        class Input:
            def __init__(self): self.lines = queue.Queue()
            def readline(self): return self.lines.get()
        import queue
        input_stream = Input()
        class Stdout:
            def __iter__(self):
                for n in range(4):
                    yield json.dumps({"url": f"https://video.invalid/{n}", "playlist_id": "p"}) + "\n"
                assert four_started.wait(2)
                input_stream.lines.put(json.dumps({"type": "prioritize", "itemId": ids["https://video.invalid/5"]}) + "\n")
                input_stream.lines.put(json.dumps({"type": "prioritize", "itemId": ids["https://video.invalid/5"]}) + "\n")
                input_stream.lines.put("legacy text\n")
                command_sent.set()
                yield json.dumps({"url": "https://video.invalid/4", "playlist_id": "p"}) + "\n"
                # The queued item must be prioritized before it is discovered.
                assert priority_processed.wait(2)
                yield json.dumps({"url": "https://video.invalid/5", "playlist_id": "p"}) + "\n"
                assert command_sent.wait(2)
                input_stream.lines.put("")
            def close(self): pass
        class Process:
            stdout = Stdout()
            stderr = io.StringIO()
            returncode = 0
            def wait(self): return 0
            def poll(self): return 0
        def detail(url, _args):
            nonlocal active, max_active
            with started_lock:
                started.append(url)
                active += 1
                max_active = max(max_active, active)
                if len(started) == 4: four_started.set()
            release.wait(3)
            with started_lock:
                active -= 1
            return {"entries": [{"url": url, "title": "detail", "availability": "available", "estimates": []}]}
        result = []
        original_prioritize = cli._MetadataScheduler.prioritize
        def prioritized(scheduler, item_id):
            original_prioritize(scheduler, item_id)
            priority_processed.set()
        def run():
            with contextlib.redirect_stdout(output), mock.patch.object(sys, "stdin", input_stream), \
                 mock.patch.object(cli.downloads, "ytdlp_options", return_value=["yt-dlp"]), \
                 mock.patch.object(cli.runtime, "start_process", return_value=Process()), \
                 mock.patch.object(cli.runtime, "_unregister_process"), mock.patch.object(cli, "inspect_url", side_effect=detail), \
                 mock.patch.object(cli._MetadataScheduler, "prioritize", prioritized):
                result.append(cli._stream_inspection("https://www.youtube.com/playlist?list=p", self.args))
        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(four_started.wait(2))
        # Discovery must reach all six rows while every metadata slot is occupied.
        for _ in range(100):
            rows = [json.loads(line.removeprefix("OMD_EVENT:")) for line in output.getvalue().splitlines() if "playlistEntry" in line]
            if len(rows) == 6: break
            threading.Event().wait(0.01)
        self.assertEqual(len(rows), 6)
        self.assertTrue(priority_processed.is_set())
        release.set()
        thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertTrue(result[0])
        self.assertEqual(len(started), 6)
        self.assertEqual(max_active, 4)
        self.assertEqual(started[4], "https://video.invalid/5")
        events = [json.loads(line.removeprefix("OMD_EVENT:")) for line in output.getvalue().splitlines()]
        outcomes = [event for event in events if event["type"] in ("metadata", "inspectionError")]
        self.assertEqual(len(outcomes), 6)
        self.assertEqual({event["itemId"] for event in outcomes}, set(ids.values()))

    def test_positions_survive_duplicate_and_missing_rows(self):
        shared = "https://video.invalid/shared"
        children = [
            {"url": shared, "title": "first"}, {"url": shared, "title": "duplicate"},
            {"title": "missing"}, {"url": "https://video.invalid/last", "title": "last"},
        ]
        detail = lambda url, _args: {"entries": [{"url": url, "title": "detail", "availability": "available", "estimates": []}]}
        with mock.patch.object(cli.downloads, "ytdlp_options", return_value=["yt-dlp"]), \
             mock.patch.object(cli.runtime, "start_process", return_value=fake_process(children)), \
             mock.patch.object(cli.runtime, "_unregister_process"), \
             mock.patch.object(cli, "inspect_url", side_effect=detail):
            ok, events = self.capture(lambda: cli._stream_inspection("https://www.youtube.com/playlist?list=synthetic", self.args))
        rows = [e for e in events if e["type"] == "playlistEntry"]
        self.assertTrue(ok)
        self.assertEqual([e["index"] for e in rows], [0, 2, 3])
        self.assertEqual([e["playlistPosition"] for e in rows], [0, 2, 3])
        self.assertEqual(rows[0]["itemId"], hashlib.sha256(shared.encode()).hexdigest()[:24])
        metadata = [e for e in events if e["type"] == "metadata"]
        expected_ids = {hashlib.sha256(e["url"].encode()).hexdigest()[:24] for e in rows if e["url"]}
        self.assertEqual({e["itemId"] for e in metadata}, expected_ids)
        self.assertTrue(all(e["entry"]["url"] in {row["url"] for row in rows} for e in metadata))

    def test_standalone_known_video_is_inspected_once(self):
        detail = {"entries": [{"url": "https://www.youtube.com/watch?v=abc", "title": "Video", "availability": "available", "estimates": []}]}
        with mock.patch.object(cli, "inspect_url", return_value=detail) as inspect, \
             mock.patch.object(cli.runtime, "start_process") as start:
            ok, events = self.capture(lambda: cli._stream_inspection("https://www.youtube.com/watch?v=abc", self.args))
        self.assertTrue(ok)
        inspect.assert_called_once()
        start.assert_not_called()
        self.assertEqual([e["type"] for e in events], ["title", "discoveryComplete", "metadata", "inspectionComplete"])
        self.assertEqual(events[2]["itemId"], hashlib.sha256(detail["entries"][0]["url"].encode()).hexdigest()[:24])

    def test_cancelled_generation_emits_no_late_metadata_or_completion(self):
        cancelled = runtime._CANCELLED
        cancelled.set()
        try:
            ok, events = self.capture(lambda: cli._stream_inspection("https://video.invalid/watch/one", self.args))
        finally:
            cancelled.clear()
        self.assertFalse(ok)
        self.assertEqual(events, [])

    def test_discovers_only_literal_standard_players_from_fixture(self):
        fixture = (FIXTURES / "embedded_players.html").read_bytes()
        response = mock.MagicMock()
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.read.return_value = fixture
        response.__enter__.return_value = response
        with mock.patch.object(inspection, "build_opener") as opener:
            opener.return_value.open.return_value = response
            players = inspection.discover_embedded_players("https://publisher.invalid/article", self.args)
        self.assertEqual(players, [
            "https://www.youtube.com/embed/yt-one?start=12",
            "https://player.vimeo.com/video/12345?h=fixture-secret",
        ])

    def test_multiple_embeds_use_playlist_choice_events_with_source_context(self):
        players = ["https://www.youtube.com/embed/one", "https://player.vimeo.com/video/2"]
        origin = "https://redirected.publisher.invalid:8443/"
        detail = {"entries": [{"url": "embed", "title": "Video", "availability": "available", "estimates": []}]}
        def inspect_player(player, args, embed_referer_origin=None):
            return {"entries": [dict(detail["entries"][0], url=player, embedRefererOrigin=embed_referer_origin)]}
        with mock.patch.object(cli, "discover_embedded_players", return_value=(players, "https://redirected.publisher.invalid:8443/path?secret=x")), \
             mock.patch.object(cli, "inspect_url", side_effect=inspect_player):
            ok, events = self.capture(lambda: cli._stream_inspection("https://publisher.invalid/article", self.args))
        self.assertTrue(ok)
        self.assertEqual([e["type"] for e in events], ["title", "playlistEntry", "playlistEntry", "metadata", "metadata", "inspectionComplete"])
        self.assertTrue(all(e["source"] == "https://publisher.invalid/article" for e in events))
        self.assertEqual([e["entry"]["embedRefererOrigin"] for e in events if e["type"] == "metadata"], [origin, origin])
        self.assertTrue(events[-1]["isPlaylist"])

    def test_embed_metadata_gets_origin_only_referer(self):
        source = "https://alice:secret@publisher.invalid:8443/story/path?token=hidden#frag"
        players = ["https://www.youtube.com/embed/one", "https://player.vimeo.com/video/2"]
        detail = {"entries": [{"url": "embed", "title": "Video", "availability": "available", "estimates": []}]}
        with mock.patch.object(inspection, "discover_embedded_players", return_value=players), \
             mock.patch.object(inspection, "read_ytdlp_metadata", return_value=(detail, [])) as read:
            result = inspection.inspect_url(source, self.args)
        self.assertEqual([call.args[1].referer for call in read.call_args_list], ["https://publisher.invalid:8443/", "https://publisher.invalid:8443/"])
        serialized = repr([call.args[1].referer for call in read.call_args_list])
        self.assertNotIn("token", serialized); self.assertNotIn("secret", serialized); self.assertNotIn("story", serialized)
        for entry in result["entries"]:
            self.assertEqual(entry["embedRefererOrigin"], "https://publisher.invalid:8443/")
        self.assertNotIn("secret", repr(result["entries"]))

    def test_direct_media_metadata_has_no_embed_origin(self):
        detail = {"formats": [], "title": "Direct"}
        with mock.patch.object(inspection, "read_ytdlp_metadata", return_value=(detail, [])):
            result = inspection.inspect_url("https://www.youtube.com/watch?v=abc", self.args)
        self.assertNotIn("embedRefererOrigin", result["entries"][0])

    def test_script_built_page_gets_direct_player_guidance(self):
        with mock.patch.object(inspection, "discover_embedded_players", return_value=[]):
            with self.assertRaisesRegex(Exception, "copy the direct YouTube or Vimeo player URL"):
                inspection.inspect_url("https://publisher.invalid/article", self.args)

    def test_redirect_relative_players_dedup_and_cookie_scope_on_loopback(self):
        seen = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get("Cookie")))
                if self.path == "/start?token=source-secret":
                    self.send_response(302); self.send_header("Location", f"http://final.publisher.invalid:{self.server.server_port}/stories/final/page"); self.end_headers(); return
                body = b'''<iframe src="//www.youtube.com/embed/relative" />
                    <iframe src="https://www.youtube.com/embed/abc" />
                    <iframe src="https://www.youtube.com/embed/abc" />
                    <embed src="https://player.vimeo.com/video/42" />
                    <object data="https://player.vimeo.com/video/42"></object>
                    <iframe src="https://evil.invalid/embed/nope"></iframe>
                    <iframe src="https://youtube.com/watch?v=unsupported"></iframe>'''
                self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(body)
            def log_message(self, *_args):
                pass
        try:
            server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        except PermissionError as error:
            self.skipTest(f"sandbox does not permit loopback fixtures: {error}")
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            source = f"http://source.publisher.invalid:{server.server_port}/start?token=source-secret"
            final_url = f"http://final.publisher.invalid:{server.server_port}/stories/final/page"
            final_origin = f"http://final.publisher.invalid:{server.server_port}/"
            real_getaddrinfo = socket.getaddrinfo
            real_build_opener = urllib.request.build_opener
            def local_dns(host, port, *args, **kwargs):
                if host in {"source.publisher.invalid", "final.publisher.invalid"}:
                    host = "127.0.0.1"
                return real_getaddrinfo(host, port, *args, **kwargs)
            def local_opener(*handlers):
                return real_build_opener(urllib.request.ProxyHandler({}), *handlers)
            with tempfile.NamedTemporaryFile(mode="w", encoding="ascii") as cookies:
                cookies.write("# Netscape HTTP Cookie File\n.publisher.invalid\tTRUE\t/\tFALSE\t4102444800\tsource_fixture\tsynthetic-value\n")
                cookies.flush()
                args = types.SimpleNamespace(cookies_file=cookies.name)
                with mock.patch("socket.getaddrinfo", side_effect=local_dns), \
                        mock.patch.object(inspection, "build_opener", side_effect=local_opener), \
                        mock.patch.object(inspection, "read_ytdlp_metadata", return_value=(
                            {"entries": [{"url": "embed", "title": "Fixture", "formats": [{"height": 240, "vcodec": "h264", "acodec": "mp4a"}]}]}, [])) as read:
                    players, discovered_url = inspection.discover_embedded_players(source, args, include_source_url=True)
                    result = inspection.inspect_url(source, args)
                    media_jar = inspection.http.cookiejar.MozillaCookieJar(cookies.name)
                    media_jar.load(ignore_discard=True, ignore_expires=True)
                    media_request = urllib.request.Request(players[0])
                    media_jar.add_cookie_header(media_request)
                    self.assertIsNone(media_request.get_header("Cookie"))
            self.assertEqual(discovered_url, final_url)
            self.assertEqual(players, ["http://www.youtube.com/embed/relative",
                "https://www.youtube.com/embed/abc", "https://player.vimeo.com/video/42"])
            self.assertEqual(seen[0], ("/start?token=source-secret", "source_fixture=synthetic-value"))
            self.assertEqual(seen[1], ("/stories/final/page", "source_fixture=synthetic-value"))
            self.assertEqual(read.call_args_list[0].args[0], players[0])
            self.assertTrue(all(call.args[1].referer == final_origin for call in read.call_args_list))
            self.assertEqual(result["entries"][0]["availability"], "available")
            self.assertNotIn("source-secret", read.call_args_list[0].args[1].referer)
            self.assertTrue(all("synthetic-value" not in player for player in players))
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == "__main__":
    unittest.main()
