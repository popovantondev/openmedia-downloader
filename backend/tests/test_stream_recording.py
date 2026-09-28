import errno
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from omd.stream_recording import inspect_hls, record
from omd.inspection import _classify_stream


FIXTURES = Path(__file__).parent / "fixtures" / "hls"


class StreamRecordingTests(unittest.TestCase):
    def _record_fixture(self, root, media="video", quality="720", start="now", from_start_supported=False,
                        probe_stream=None, runtime_args=None):
        task_id = f"fixture_{media}_{quality.replace('p', '')}"
        config = type("Config", (), {
            "referer": "https://publisher.invalid/", "workers": 7, "quality": quality,
            "mode": "auto", "task_id": task_id, "cookies_file": None,
            "cookies_browser": None, "auth_domain": [],
        })()
        extension = {"video": "mp4", "aac": "m4a", "mp3": "webm"}[media]
        probe_stream = probe_stream or {
            "video": [{"codec_type": "video", "codec_name": "h264"}],
            "aac": [{"codec_type": "audio", "codec_name": "aac"}],
            "mp3": [{"codec_type": "audio", "codec_name": "mp3"}],
        }[media]
        probe_result = type("Result", (), {
            "returncode": 0,
            "stdout": json.dumps({"format": {"duration": "12.5"}, "streams": probe_stream}).encode(),
            "stderr": b"",
        })()
        captured = {}

        class Process:
            returncode = 0
            def __init__(self, stdout): self.stdout = iter(stdout)
            def poll(self): return 0
            def wait(self): return 0

        def launch(command, **kwargs):
            work = Path(command[command.index("-o") + 1]).parent
            media_path = work / f"capture.{extension}"
            media_path.write_bytes(b"fixture-media")
            captured.update(command=command, media_path=media_path)
            return Process([f"OMD_FINAL_PATH:{media_path}\n"])

        def run(command, **kwargs):
            if command[0] == "/bundled/ffmpeg":
                Path(command[-1]).write_bytes(b"converted-mp3")
                return type("Result", (), {"returncode": 0, "stdout": b"", "stderr": b""})()
            return probe_result

        patches = [
            patch("omd.stream_recording.downloads.ytdlp_runtime_options", return_value=runtime_args or ["yt-dlp"]),
            patch("omd.stream_recording.start_process", side_effect=launch),
            patch("omd.stream_recording.ffprobe", return_value="/bundled/ffprobe"),
            patch("omd.stream_recording.ffmpeg", return_value="/bundled/ffmpeg"),
            patch("omd.stream_recording.subprocess.run", side_effect=run),
            patch("omd.stream_recording.emit_event"),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as events:
            status = record("https://example.invalid/live", root, start=start,
                            from_start_supported=from_start_supported, media=media, task_args=config)
        return status, captured, events

    def test_live_state_mapping_preserves_extractor_meaning(self):
        expected = {"is_upcoming": "scheduled", "is_live": "live", "post_live": "endedProcessing",
                    "was_live": "vod", "not_live": "vod", "future": "regular"}
        for source, state in expected.items():
            entry = _classify_stream({}, {"live_status": source})
            self.assertEqual(entry["streamState"], state)

    def test_from_start_requires_explicit_live_format_evidence(self):
        supported = _classify_stream({}, {"live_status": "is_live", "formats": [{"is_from_start": True}]})
        unsupported = _classify_stream({}, {"live_status": "is_live", "formats": [{}], "live_from_start_supported": True})
        ended = _classify_stream({}, {"live_status": "was_live", "formats": [{"is_from_start": True}]})
        self.assertTrue(supported["fromStartSupported"])
        self.assertFalse(unsupported["fromStartSupported"])
        self.assertEqual(unsupported["fromStartReason"], "archiveUnavailable")
        self.assertFalse(ended["fromStartSupported"])

    def test_hls_inspection_does_not_infer_full_archive_from_start_tag(self):
        result = inspect_hls("#EXTM3U\n#EXT-X-START:TIME-OFFSET=-60\n#EXTINF:5,\nsegment.ts\n")
        self.assertTrue(result["hasSegments"])
        self.assertFalse(result["fromStartSupported"])

    def test_from_start_is_rejected_without_capability(self):
        with tempfile.TemporaryDirectory() as root, patch("omd.stream_recording.downloads.ytdlp_runtime_options") as runtime:
            self.assertEqual(record("https://example.invalid/live", root, "from-start"), 2)
            runtime.assert_not_called()

    def test_now_and_supported_from_start_use_distinct_ytdlp_flags(self):
        for start, flag in (("now", "--no-live-from-start"), ("from-start", "--live-from-start")):
            with self.subTest(start=start), tempfile.TemporaryDirectory() as root:
                status, captured, _ = self._record_fixture(root, start=start, from_start_supported=True)
                self.assertEqual(status, 0)
                self.assertIn(flag, captured["command"])

    def test_finalizing_is_emitted_once_before_validation_and_completion(self):
        with tempfile.TemporaryDirectory() as root:
            status, _, events = self._record_fixture(root)
            stages = [call.kwargs.get("stage") for call in events.call_args_list if call.args[0] == "stage"]
            kinds = [call.args[0] for call in events.call_args_list]
            self.assertEqual(status, 0)
            self.assertEqual(stages, ["live", "finalizing"])
            self.assertEqual(kinds.index("stage", 1) < kinds.index("file") < kinds.index("completed"), True)

    def test_recording_runtime_keeps_referer_cookies_and_workers(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = ["yt-dlp", "--ffmpeg-location", "/bundled/ffmpeg", "--referer", "https://publisher.invalid/",
                       "--cookies", "/private/task-cookie.txt", "--js-runtimes", "deno:/bundled/deno"]
            status, captured, _ = self._record_fixture(root, runtime_args=runtime)
            self.assertEqual(status, 0)
            command = captured["command"]
            self.assertEqual(command.count("--referer"), 1)
            self.assertEqual(command.count("--cookies"), 1)
            self.assertEqual(command[command.index("--concurrent-fragments") + 1], "7")
            self.assertIn("--js-runtimes", command)

    def test_aac_and_mp3_keep_audio_only_selectors_and_validate_codec(self):
        for media, selector in (("aac", "ba[acodec^=mp4a]/ba[ext=m4a]/ba[acodec*=aac]"), ("mp3", "ba")):
            with self.subTest(media=media), tempfile.TemporaryDirectory() as root:
                status, captured, _ = self._record_fixture(root, media=media)
                command = captured["command"]
                self.assertEqual(status, 0)
                self.assertEqual(command[command.index("-f") + 1], selector)
                self.assertNotIn("-S", command)

    def test_video_recording_uses_nearest_quality_sorting(self):
        for quality, expected in (("720", "res~720,ext:mp4:m4a"), ("best", "res,ext:mp4:m4a")):
            with self.subTest(quality=quality), tempfile.TemporaryDirectory() as root:
                status, captured, _ = self._record_fixture(root, quality=quality)
                self.assertEqual(status, 0)
                command = captured["command"]
                self.assertEqual(command[command.index("-S") + 1], expected)

    def test_mp3_conversion_runs_before_bundled_probe(self):
        with tempfile.TemporaryDirectory() as root:
            status, captured, events = self._record_fixture(root, media="mp3")
            self.assertEqual(status, 0)
            self.assertEqual(Path(events.call_args_list[-1].kwargs["path"]).suffix, ".mp3")

    def test_missing_or_wrong_codec_probe_preserves_recovery_and_never_completes(self):
        with tempfile.TemporaryDirectory() as root:
            status, _, events = self._record_fixture(root, media="aac", probe_stream=[{"codec_type": "audio", "codec_name": "mp3"}])
            self.assertNotEqual(status, 0)
            self.assertNotIn("completed", [call.args[0] for call in events.call_args_list])
            recovery = Path(root) / ".omd-recording-fixture_aac_720"
            self.assertTrue((recovery / "recovery-manifest.json").is_file())

    def test_marker_cannot_claim_a_file_outside_its_private_task_folder(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            external_file = Path(outside) / "unrelated.mp4"
            external_file.write_bytes(b"not-this-task")
            config = type("Config", (), {"referer": None, "workers": 4, "quality": "720", "mode": "auto", "task_id": "outside_marker"})()
            class Process:
                stdout = iter([f"OMD_FINAL_PATH:{external_file}\n"])
                returncode = 0
                def wait(self): return 0
            with patch("omd.stream_recording.downloads.ytdlp_runtime_options", return_value=["yt-dlp"]), \
                 patch("omd.stream_recording.start_process", return_value=Process()), \
                 patch("omd.stream_recording.emit_event") as events:
                self.assertNotEqual(record("https://example.invalid/live", root, task_args=config), 0)
            self.assertEqual(external_file.read_bytes(), b"not-this-task")
            self.assertNotIn("completed", [call.args[0] for call in events.call_args_list])

    def _run(self, root, task_id, unrelated=False):
        config = type("Config", (), {"referer": None, "workers": 4, "quality": "720", "mode": "auto", "task_id": task_id})()
        captured = {}
        class Process:
            returncode = 0
            def poll(self): return 0
            def wait(self): return 0
            def __init__(self, stdout): self.stdout = iter(stdout)
        def launch(args, **kwargs):
            template = args[args.index("-o") + 1]
            work = Path(template).parent
            media = work / "capture.mp4"
            media.write_bytes(b"private-media")
            if unrelated: (Path(root) / "newer.mp4").write_bytes(b"not-this-task")
            captured.update(work=work, media=media, args=args)
            return Process([f"OMD_FINAL_PATH:{media}\n"])
        probe = type("Result", (), {"returncode": 0, "stdout": json.dumps({"format": {"duration": "12.5"}, "streams": [{"codec_type": "video", "codec_name": "h264"}]}).encode(), "stderr": b""})()
        with patch("omd.stream_recording.downloads.ytdlp_runtime_options", return_value=["yt-dlp"]), \
             patch("omd.stream_recording.start_process", side_effect=launch), \
             patch("omd.stream_recording.ffprobe", return_value="ffprobe"), \
             patch("omd.stream_recording.subprocess.run", return_value=probe), \
             patch("omd.stream_recording.emit_event") as events:
            status = record("https://example.invalid/live?token=secret", root, media="video", task_args=config)
        return status, captured, events

    def test_hls_start_hint_does_not_prove_archive(self):
        self.assertFalse(inspect_hls("#EXTM3U\n#EXT-X-START:TIME-OFFSET=-3\nsegment.ts") ["fromStartSupported"])

    def test_task_output_is_exact_and_other_newer_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            statuses = [self._run(root, task, unrelated=True) for task in ("task_a", "task_b")]
            self.assertEqual([x[0] for x in statuses], [0, 0])
            paths = [Path(x[2].call_args_list[-1].kwargs["path"]) for x in statuses]
            self.assertNotEqual(paths[0], paths[1])
            self.assertTrue(all(p.exists() for p in paths))
            self.assertEqual((Path(root) / "newer.mp4").read_bytes(), b"not-this-task")
            self.assertTrue(all("--print" in x[1]["args"] and "after_move:OMD_FINAL_PATH:%(filepath)s" in x[1]["args"] for x in statuses))
            self.assertFalse(any(Path(root).glob(".omd-recording-*")))

    def test_recovery_manifest_exists_before_capture_begins(self):
        with tempfile.TemporaryDirectory() as root:
            config = type("Config", (), {"referer": None, "workers": 4, "quality": "720", "mode": "auto", "task_id": "manifest_first"})()
            class Process:
                returncode = 0
                def poll(self): return 0
                def wait(self): return 0
                def __init__(self, stdout): self.stdout = iter(stdout)
            def launch(command, **kwargs):
                task_dir = Path(command[command.index("-o") + 1]).parent
                manifest = json.loads((task_dir / "recovery-manifest.json").read_text())
                self.assertEqual(manifest["taskId"], "manifest_first")
                self.assertNotIn("url", manifest)
                media = task_dir / "capture.mp4"
                media.write_bytes(b"capture")
                return Process([f"OMD_FINAL_PATH:{media}\n"])
            probe = type("Result", (), {"returncode": 0, "stdout": b'{"format":{"duration":"1"},"streams":[{"codec_type":"video","codec_name":"h264"}]}', "stderr": b""})()
            with patch("omd.stream_recording.downloads.ytdlp_runtime_options", return_value=["yt-dlp"]), \
                 patch("omd.stream_recording.start_process", side_effect=launch), \
                 patch("omd.stream_recording.ffprobe", return_value="ffprobe"), \
                 patch("omd.stream_recording.subprocess.run", return_value=probe), \
                 patch("omd.stream_recording.emit_event"):
                self.assertEqual(record("https://secret.invalid/?token=x", root, task_args=config), 0)

    def test_collision_uses_safe_suffix_without_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "capture.mp4").write_bytes(b"existing")
            status, _, events = self._run(root, "collision")
            self.assertEqual(status, 0)
            saved = Path(events.call_args_list[-1].kwargs["path"])
            self.assertEqual(saved.name, "capture (1).mp4")
            self.assertEqual((Path(root) / "capture.mp4").read_bytes(), b"existing")

    def test_failure_keeps_private_workdir_and_minimal_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            config = type("Config", (), {"referer": None, "workers": 4, "quality": "720", "mode": "auto", "task_id": "recover_me"})()
            class Process:
                stdout = iter([]); returncode = 0
                def wait(self): return 0
            with patch("omd.stream_recording.downloads.ytdlp_runtime_options", return_value=["yt-dlp"]), patch("omd.stream_recording.start_process", return_value=Process()), patch("omd.stream_recording.emit_event") as emit:
                self.assertNotEqual(record("https://secret.invalid/?sig=abc", root, task_args=config), 0)
            work = Path(root) / ".omd-recording-recover_me"
            manifest = json.loads((work / "recovery-manifest.json").read_text())
            self.assertEqual(set(manifest), {"taskId", "media", "quality", "createdAt"})
            self.assertNotIn("secret", json.dumps(manifest))
            self.assertEqual(work.stat().st_mode & 0o777, 0o700)
            self.assertIn(str(work), emit.call_args.kwargs["message"])

    def test_disk_full_during_capture_keeps_partial_and_never_completes(self):
        with tempfile.TemporaryDirectory() as root:
            task_id = "disk_full_capture"
            config = type("Config", (), {"referer": None, "workers": 4, "quality": "720", "mode": "auto", "task_id": task_id})()

            class Process:
                returncode = 1
                def __init__(self, stdout): self.stdout = iter(stdout)
                def wait(self): return 1

            def launch(command, **kwargs):
                task_dir = Path(command[command.index("-o") + 1]).parent
                (task_dir / "capture.mp4.part").write_bytes(b"partial-segment")
                return Process([f"ERROR: [Errno {errno.ENOSPC}] No space left on device\n"])

            with patch("omd.stream_recording.downloads.ytdlp_runtime_options", return_value=["yt-dlp"]), \
                 patch("omd.stream_recording.start_process", side_effect=launch), \
                 patch("omd.stream_recording.emit_event") as events:
                status = record("https://example.invalid/live", root, task_args=config)

            recovery = Path(root) / f".omd-recording-{task_id}"
            self.assertEqual(status, 1)
            self.assertEqual((recovery / "capture.mp4.part").read_bytes(), b"partial-segment")
            self.assertTrue((recovery / "recovery-manifest.json").is_file())
            self.assertNotIn("completed", [call.args[0] for call in events.call_args_list])


if __name__ == "__main__":
    unittest.main()
