"""Real bundled-tool media checks against loopback-only synthetic files."""
from __future__ import annotations

import http.server
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from omd import downloads, runtime
from omd.runtime import ffprobe
from omd.stream_recording import record


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FFMPEG = PROJECT_ROOT / "vendor" / "bin" / "ffmpeg"
FIXTURE_GENERATOR = Path(__file__).with_name("generate_media_fixture.swift")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass


class LoopbackMediaServer:
    def __init__(self, directory: Path, *, live_playlist=None, segment_requested=None, segment_counter=None, fail_after_segments=None, segment_failed=None):
        class Handler(QuietHandler):
            def do_GET(self):
                from urllib.parse import urlsplit
                path = urlsplit(self.path).path
                if path == "/live.m3u8" and live_playlist is not None:
                    content = live_playlist() if callable(live_playlist) else live_playlist
                    if content is None:
                        self.send_error(503, "synthetic source interruption")
                        return
                    payload = content.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if path.startswith("/live-segment-") and segment_counter is not None:
                    if fail_after_segments is not None and segment_counter[0] >= fail_after_segments:
                        if segment_failed is not None:
                            segment_failed.set()
                        self.send_error(503, "synthetic media segment interruption")
                        return
                    index = int(Path(path).stem.rsplit("-", 1)[1])
                    source_segments = sorted(directory.glob("segment-*.ts"))
                    source = source_segments[index % len(source_segments)]
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp2t")
                    self.send_header("Content-Length", str(source.stat().st_size))
                    self.end_headers()
                    with source.open("rb") as stream:
                        shutil.copyfileobj(stream, self.wfile)
                    segment_counter[0] += 1
                    if segment_requested is not None:
                        segment_requested.set()
                    return
                is_segment = path.endswith(".ts") and segment_requested is not None
                super().do_GET()
                if is_segment:
                    segment_requested.set()

        handler = lambda *args, **kwargs: Handler(*args, directory=str(directory), **kwargs)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class RealMediaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FFMPEG.is_file() or not shutil.which("swift"):
            raise RuntimeError("This opt-in macOS integration suite needs bundled ffmpeg and Swift.")
        cls.temp = tempfile.TemporaryDirectory(prefix="omd-media-integration-")
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "source"
        cls.source.mkdir()
        cls.mp4 = cls.source / "tone.mp4"
        cls._run([shutil.which("swift"), str(FIXTURE_GENERATOR), str(cls.mp4)])
        cls._run([
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-i", str(cls.mp4),
            "-map", "0:v:0", "-c:v", "copy", "-f", "hls", "-hls_time", "1",
            "-hls_list_size", "0", "-hls_playlist_type", "vod", "-hls_segment_type", "mpegts",
            "-hls_segment_filename", str(cls.source / "segment-%03d.ts"), str(cls.source / "index.m3u8"),
        ])
        if not list(cls.source.glob("segment-*.ts")):
            raise RuntimeError("Bundled ffmpeg did not produce HLS media segments.")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def _run(command):
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", "replace")[-2000:])

    def _record(self, url: str, task_id: str):
        destination = self.root / f"output-{task_id}"
        config = SimpleNamespace(
            referer=None, workers=2, quality="best", mode="auto", task_id=task_id,
            cookies_file=None, cookies_browser=None, auth_domain=[],
        )
        events = []
        processes = []
        with patch("omd.stream_recording.emit_event", side_effect=lambda kind, **data: events.append((kind, data))), \
             patch("omd.stream_recording.sys.stdin") as stdin:
            stdin.__iter__.return_value = iter(())
            status = record(url, str(destination), media="video", task_args=config)
        self.assertEqual(status, 0, events)
        completed = next(data for kind, data in events if kind == "completed")
        path = Path(completed["path"])
        self.assertTrue(path.is_file())
        self.assertGreater(path.stat().st_size, 0)
        self.assertFalse((destination / f".omd-recording-{task_id}").exists())
        probe = subprocess.run(
            [ffprobe(), "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name", "-of", "json", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True,
        )
        report = json.loads(probe.stdout)
        self.assertGreater(float(report["format"]["duration"]), 1.0)
        self.assertTrue(any(item.get("codec_type") == "video" and item.get("codec_name") == "h264" for item in report["streams"]))
        return path

    def test_direct_video_source_downloads_and_validates(self):
        with LoopbackMediaServer(self.source) as server:
            result = self._record(f"{server.base_url}/tone.mp4", "integration_direct_video")
        self.assertEqual(result.suffix, ".mp4")

    def test_hls_video_segments_download_and_validate(self):
        with LoopbackMediaServer(self.source) as server:
            result = self._record(f"{server.base_url}/index.m3u8", "integration_hls_video")
        self.assertEqual(result.suffix, ".mp4")

    def test_corrupt_hls_segments_never_report_a_completed_recording(self):
        damaged_source = self.root / "damaged-source"
        shutil.copytree(self.source, damaged_source)
        for segment in damaged_source.glob("segment-*.ts"):
            segment.write_bytes(b"intentionally damaged HLS segment")

        destination = self.root / "output-damaged-hls"
        task_id = "integration_damaged_hls"
        config = SimpleNamespace(
            referer=None, workers=2, quality="best", mode="auto", task_id=task_id,
            cookies_file=None, cookies_browser=None, auth_domain=[],
        )
        events = []
        processes = []
        real_start_process = runtime.start_process

        def capture_process(*args, **kwargs):
            process = real_start_process(*args, **kwargs)
            processes.append(process)
            return process

        with LoopbackMediaServer(damaged_source) as server, \
             patch("omd.stream_recording.emit_event", side_effect=lambda kind, **data: events.append((kind, data))), \
             patch("omd.stream_recording.start_process", side_effect=capture_process), \
             patch("omd.stream_recording.sys.stdin") as stdin:
            stdin.__iter__.return_value = iter(())
            result = record(f"{server.base_url}/index.m3u8", str(destination), media="video", task_args=config)

        self.assertEqual(result, 1, events)
        self.assertTrue((destination / f".omd-recording-{task_id}" / "recovery-manifest.json").is_file())
        self.assertFalse(list(destination.glob("*.mp4")))
        self.assertNotIn("completed", [kind for kind, _ in events])
        self.assertTrue(processes)
        self.assertTrue(all(process.poll() is not None for process in processes))

    def test_live_hls_stop_finalizes_the_captured_part(self):
        source_playlist = (self.source / "index.m3u8").read_text(encoding="utf-8").splitlines()
        durations = [float(line.partition(":")[2].partition(",")[0]) for line in source_playlist if line.startswith("#EXTINF:")]
        segment_requested = threading.Event()
        segment_counter = [0]
        manifest_requests = [0]
        commands = queue.Queue()
        result = []
        errors = []
        events = []
        processes = []

        class ControlledInput:
            def __iter__(self):
                while True:
                    command = commands.get()
                    if command is None:
                        return
                    yield command

        destination = self.root / "output-live-stop"
        config = SimpleNamespace(
            referer=None, workers=2, quality="best", mode="auto", task_id="integration_live_stop",
            cookies_file=None, cookies_browser=None, auth_domain=[],
        )
        real_start_process = runtime.start_process
        def live_playlist():
            manifest_requests[0] += 1
            visible_count = min(20, max(2, manifest_requests[0] + 1))
            lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:2", "#EXT-X-MEDIA-SEQUENCE:0"]
            for index in range(visible_count):
                lines.extend((f"#EXTINF:{durations[index % len(durations)]:.6f},", f"live-segment-{index:04d}.ts"))
            return "\n".join(lines) + "\n"

        def capture_process(*args, **kwargs):
            process = real_start_process(*args, **kwargs)
            processes.append(process)
            return process

        def terminate_recording_processes():
            for process in processes:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        process.kill()

        with LoopbackMediaServer(self.source, live_playlist=live_playlist, segment_requested=segment_requested, segment_counter=segment_counter) as server, \
             patch("omd.stream_recording.emit_event", side_effect=lambda kind, **data: events.append((kind, data))), \
             patch("omd.stream_recording.start_process", side_effect=capture_process), \
             patch("omd.stream_recording.sys.stdin", ControlledInput()):
            def capture():
                try:
                    result.append(record(f"{server.base_url}/live.m3u8", str(destination), media="video", task_args=config))
                except Exception as error:  # surface worker failures in the unittest thread
                    errors.append(error)

            worker = threading.Thread(target=capture, daemon=True)
            worker.start()
            if not segment_requested.wait(timeout=20):
                commands.put("stop\n")
                worker.join(timeout=8)
                if worker.is_alive():
                    terminate_recording_processes()
                    worker.join(timeout=5)
                self.fail(f"The live HLS fixture did not deliver a segment in time; events={events}, processStatus={[p.poll() for p in processes]}.")
            recovery = destination / ".omd-recording-integration_live_stop"
            part_deadline = time.monotonic() + 20
            while time.monotonic() < part_deadline and (segment_counter[0] < 2 or not any(path.is_file() and path.stat().st_size > 0 for path in recovery.glob("*.part"))):
                time.sleep(0.05)
            part_size = sum(path.stat().st_size for path in recovery.glob("*.part") if path.is_file())
            if segment_counter[0] < 2 or part_size <= 0:
                commands.put("stop\n")
                worker.join(timeout=8)
                if worker.is_alive():
                    terminate_recording_processes()
                    worker.join(timeout=5)
                self.fail(f"The live HLS fixture did not capture at least two segments into a non-empty staging file; segments={segment_counter[0]}, partialBytes={part_size}, events={events}, processStatus={[p.poll() for p in processes]}.")
            commands.put("stop\n")
            worker.join(timeout=30)
            if worker.is_alive():
                terminate_recording_processes()
                worker.join(timeout=5)
                self.fail(f"Recording did not finish after the stop command; partialBytes={part_size}, events={events}, files={[p.name for p in recovery.glob('*')]}, processStatus={[p.poll() for p in processes]}, result={result}, errors={errors}.")
        self.assertEqual(errors, [])
        self.assertEqual(result, [0], events)
        saved = list(destination.glob("*.mp4"))
        self.assertEqual(len(saved), 1)
        self.assertGreater(saved[0].stat().st_size, 0)
        self.assertFalse((destination / ".omd-recording-integration_live_stop").exists())
        probe = subprocess.run(
            [ffprobe(), "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name", "-of", "json", str(saved[0])],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True,
        )
        report = json.loads(probe.stdout)
        self.assertGreater(float(report["format"]["duration"]), 0)
        self.assertTrue(any(item.get("codec_type") == "video" for item in report["streams"]))

    def test_live_hls_segment_failure_force_cancel_retains_recovery(self):
        source_playlist = (self.source / "index.m3u8").read_text(encoding="utf-8").splitlines()
        durations = [float(line.partition(":")[2].partition(",")[0]) for line in source_playlist if line.startswith("#EXTINF:")]
        segment_requested = threading.Event()
        segment_failed = threading.Event()
        segment_counter = [0]
        manifest_requests = [0]
        result = []
        errors = []
        events = []
        process_refs = []
        destination = self.root / "output-live-interruption"
        task_id = "integration_live_interruption"
        config = SimpleNamespace(
            referer=None, workers=2, quality="best", mode="auto", task_id=task_id,
            cookies_file=None, cookies_browser=None, auth_domain=[],
        )
        real_start_process = runtime.start_process

        def interrupted_playlist():
            manifest_requests[0] += 1
            visible_count = min(20, max(2, manifest_requests[0] + 1))
            lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:2", "#EXT-X-MEDIA-SEQUENCE:0"]
            for index in range(visible_count):
                lines.extend((f"#EXTINF:{durations[index % len(durations)]:.6f},", f"live-segment-{index:04d}.ts"))
            return "\n".join(lines) + "\n"

        def capture_process(*args, **kwargs):
            process = real_start_process(*args, **kwargs)
            process_refs.append(process)
            return process

        options = downloads.ytdlp_runtime_options
        def bounded_retry_options(*args, **kwargs):
            return options(*args, **kwargs) + ["--retries", "0", "--fragment-retries", "0", "--extractor-retries", "0", "--socket-timeout", "2"]

        commands = queue.Queue()
        class ControlledInput:
            def __iter__(self):
                while True:
                    command = commands.get()
                    if command is None:
                        return
                    yield command

        with LoopbackMediaServer(self.source, live_playlist=interrupted_playlist, segment_requested=segment_requested, segment_counter=segment_counter, fail_after_segments=2, segment_failed=segment_failed) as server, \
             patch("omd.stream_recording.emit_event", side_effect=lambda kind, **data: events.append((kind, data))), \
             patch("omd.stream_recording.start_process", side_effect=capture_process), \
             patch("omd.stream_recording.downloads.ytdlp_runtime_options", side_effect=bounded_retry_options), \
             patch("omd.stream_recording.sys.stdin", ControlledInput()):
            def capture():
                try:
                    result.append(record(f"{server.base_url}/live.m3u8", str(destination), media="video", task_args=config))
                except Exception as error:
                    errors.append(error)

            worker = threading.Thread(target=capture, daemon=True)
            worker.start()
            if not segment_requested.wait(timeout=20) or not segment_failed.wait(timeout=20):
                for process in process_refs:
                    if process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError, OSError):
                            process.kill()
                worker.join(timeout=5)
                self.fail(f"The synthetic media source did not interrupt after captured segments; segments={segment_counter[0]}, manifests={manifest_requests[0]}, events={events}.")
            recovery = destination / f".omd-recording-{task_id}"
            commands.put("stop\n")
            worker.join(timeout=8)
            if worker.is_alive():
                runtime.terminate_all_children()
                worker.join(timeout=5)
                if worker.is_alive():
                    self.fail(f"The recorder did not stop after an HLS segment failure or force cancellation; segments={segment_counter[0]}, events={events}, processStatus={[p.poll() for p in process_refs]}, errors={errors}, recoveryFiles={[p.name for p in (destination / f'.omd-recording-{task_id}').glob('*')]}.")

        self.assertEqual(errors, [])
        self.assertEqual(result, [1], events)
        self.assertGreaterEqual(segment_counter[0], 2)
        self.assertTrue((recovery / "recovery-manifest.json").is_file())
        self.assertTrue(any(path.is_file() for path in recovery.glob("*.part")))
        self.assertFalse(list(destination.glob("*.mp4")))
        self.assertNotIn("completed", [kind for kind, _ in events])

    def test_packaged_backend_live_stop_works_with_minimal_path(self):
        backend = os.environ.get("OMD_PACKAGED_BACKEND")
        if not backend:
            self.skipTest("Set OMD_PACKAGED_BACKEND to the built app's backend executable to run the package check.")
        backend_path = Path(backend).resolve()
        self.assertTrue(backend_path.is_file() and os.access(backend_path, os.X_OK), backend_path)
        environment = {"PATH": "/usr/bin:/bin", "HOME": str(self.root), "TMPDIR": str(self.root), "LANG": "en_US.UTF-8"}
        version = subprocess.run([str(backend_path), "--version"], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), "OpenMedia Downloader 5.5.0")
        help_result = subprocess.run([str(backend_path), "--help"], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--record-stream", help_result.stdout)

        source_playlist = (self.source / "index.m3u8").read_text(encoding="utf-8").splitlines()
        durations = [float(line.partition(":")[2].partition(",")[0]) for line in source_playlist if line.startswith("#EXTINF:")]
        segment_counter = [0]
        manifest_requests = [0]
        destination = self.root / "output-packaged-live"
        task_id = "integration_packaged_live"
        output_lines = []

        def growing_playlist():
            manifest_requests[0] += 1
            visible_count = min(20, max(2, manifest_requests[0] + 1))
            lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:2", "#EXT-X-MEDIA-SEQUENCE:0"]
            for index in range(visible_count):
                lines.extend((f"#EXTINF:{durations[index % len(durations)]:.6f},", f"live-segment-{index:04d}.ts"))
            return "\n".join(lines) + "\n"

        with LoopbackMediaServer(self.source, live_playlist=growing_playlist, segment_counter=segment_counter) as server:
            process = subprocess.Popen(
                [str(backend_path), "--record-stream", "--task-id", task_id, "--output", str(destination), "--quality", "best", "--workers", "2", "--media", "video", f"{server.base_url}/live.m3u8"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=environment,
            )
            reader = threading.Thread(target=lambda: output_lines.extend(process.stdout), daemon=True)
            reader.start()
            recovery = destination / f".omd-recording-{task_id}"
            segment_deadline = time.monotonic() + 25
            while time.monotonic() < segment_deadline and segment_counter[0] < 2:
                if process.poll() is not None:
                    break
                time.sleep(0.05)
            if segment_counter[0] < 2 or process.poll() is not None:
                process.terminate()
                try:
                    process.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                reader.join(timeout=2)
                process.stdin.close()
                process.stdout.close()
                self.fail(f"Packaged backend failed before capturing live HLS data with minimal PATH; segments={segment_counter[0]}, output={output_lines}.")
            # Give the live demuxer a moment to flush packets; do not confuse a
            # staging-file flush delay with failure to fetch HLS segments.
            flush_deadline = time.monotonic() + 5
            while time.monotonic() < flush_deadline and not any(path.is_file() and path.stat().st_size > 0 for path in recovery.glob("*.part")):
                if process.poll() is not None:
                    break
                time.sleep(0.05)
            process.stdin.write("stop\n")
            process.stdin.flush()
            process.stdin.close()
            try:
                status = process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    status = process.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    process.kill()
                    status = process.wait(timeout=3)
                reader.join(timeout=2)
                process.stdout.close()
                self.fail(f"Packaged backend did not stop normally under minimal PATH; status={status}, output={output_lines}.")
            reader.join(timeout=3)
            process.stdout.close()

        self.assertEqual(status, 0, output_lines)
        payloads = [json.loads(line.split("OMD_EVENT:", 1)[1]) for line in output_lines if "OMD_EVENT:" in line]
        completed = [item for item in payloads if item.get("type") == "completed"]
        self.assertEqual(len(completed), 1, payloads)
        saved = Path(completed[0]["path"])
        self.assertTrue(saved.is_file())
        bundled_ffprobe = backend_path.parent / "_internal" / "bin" / "ffprobe"
        probe = subprocess.run([str(bundled_ffprobe), "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(saved)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=True)
        report = json.loads(probe.stdout)
        self.assertGreater(float(report["format"]["duration"]), 0)
        self.assertTrue(any(item.get("codec_type") == "video" for item in report["streams"]))
        self.assertFalse(recovery.exists())


if __name__ == "__main__":
    unittest.main()
