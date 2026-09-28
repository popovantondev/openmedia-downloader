"""Live recording with isolated, recoverable output handling."""
from __future__ import annotations

import json
import math
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from .events import emit_event
from . import downloads
from .runtime import ffmpeg, ffprobe, start_process, unregister_process

_TASK_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_MARKER = "OMD_FINAL_PATH:"


def inspect_hls(text: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != "#EXTM3U":
        return {"supported": False, "reason": "invalidPlaylist"}
    ended = "#EXT-X-ENDLIST" in lines
    has_segments = any(not line.startswith("#") for line in lines)
    return {"ended": ended, "hasSegments": has_segments, "fromStartSupported": False, "reason": "archiveUnavailable"}


def _recovery(task_dir: Path, task_id: str, media: str, quality: str) -> None:
    manifest = {"taskId": task_id, "media": media, "quality": quality, "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (task_dir / "recovery-manifest.json").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")


def _available_destination(output_dir: Path, name: str) -> Path:
    candidate = output_dir / name
    if not candidate.exists() and not candidate.is_symlink():
        return candidate
    source = Path(name)
    for index in range(1, 10000):
        candidate = output_dir / f"{source.stem} ({index}){source.suffix}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise OSError("no available destination filename")


def record(url: str, output: str, start: str = "now", from_start_supported: bool = False, media: str = "video", referer: str | None = None, task_args=None) -> int:
    if start == "from-start" and not from_start_supported:
        emit_event("error", code="fromStartUnavailable", message="The stream archive does not support recording from the beginning.")
        return 2
    config = task_args or type("RecordingConfig", (), {"referer": referer, "workers": 4, "output": output, "quality": "best", "mode": "auto"})()
    config.referer = referer if referer is not None else getattr(config, "referer", None)
    task_id = getattr(config, "task_id", None)
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        task_id = uuid.uuid4().hex
    output_dir = Path(output)
    task_dir = output_dir / f".omd-recording-{task_id}"
    quality = str(getattr(config, "quality", "best") or "best")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        if output_dir.is_symlink() or task_dir.is_symlink() or task_dir.exists():
            raise FileExistsError("recording task directory already exists or is a symlink")
        task_dir.mkdir(mode=0o700)
        _recovery(task_dir, task_id, media, quality)
    except OSError:
        emit_event("error", code="recordingFinalizeFailed", message=f"Recording recovery folder unavailable: {task_dir}")
        return 1
    try:
        args = downloads.ytdlp_runtime_options(config)
    except RuntimeError:
        _recovery(task_dir, task_id, media, quality)
        emit_event("error", code="backendDependencyMissing", message=f"yt-dlp is unavailable. Recovery data: {task_dir}")
        return 1
    template = str(task_dir / "%(title)s.%(ext)s")
    args += ["--no-playlist", "--no-simulate", "--progress-template", "download:OMD_PROGRESS:%(progress.downloaded_bytes)s|%(progress.speed)s|%(progress.elapsed)s", "-o", template,
             "--print", f"after_move:{_MARKER}%(filepath)s"]
    args += ["--concurrent-fragments", str(max(1, min(getattr(config, "workers", 4), 16)))]
    if media == "aac": args += ["-f", "ba[acodec^=mp4a]/ba[ext=m4a]/ba[acodec*=aac]"]
    elif media == "mp3": args += ["-f", "ba"]
    elif media == "video":
        wanted = "".join(c for c in quality.lower() if c.isdigit()) if quality.lower() not in {"best", "auto", "list"} else ""
        args += ["-S", f"res~{wanted},ext:mp4:m4a" if wanted else "res,ext:mp4:m4a"]
    args.append("--live-from-start" if start == "from-start" else "--no-live-from-start")
    args.append(url)
    emit_event("stage", stage="live")
    process = None
    try:
        process = start_process(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        stop_requested = threading.Event()
        finalizing_lock = threading.Lock()
        finalizing_emitted = False

        def emit_finalizing_once():
            nonlocal finalizing_emitted
            with finalizing_lock:
                if finalizing_emitted:
                    return
                finalizing_emitted = True
            emit_event("stage", stage="finalizing")

        def stdin_dispatcher():
            for command in sys.stdin:
                if command.strip().lower() == "stop":
                    stop_requested.set()
                    emit_finalizing_once()
                    if process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGINT)
                        except (ProcessLookupError, PermissionError, OSError):
                            try:
                                process.send_signal(signal.SIGINT)
                            except ProcessLookupError:
                                # The recorder may exit between poll() and signal delivery.
                                pass
                    return
        dispatcher = threading.Thread(target=stdin_dispatcher, daemon=True)
        dispatcher.start()
        exact_path = None
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if line.startswith(_MARKER):
                exact_path = Path(line[len(_MARKER):])
            elif line.startswith("OMD_PROGRESS:"):
                parts = line[len("OMD_PROGRESS:"):].split("|")
                try: emit_event("progress", downloadedBytes=int(float(parts[0])), speedBytesPerSecond=float(parts[1]), elapsedSeconds=float(parts[2]))
                except (IndexError, ValueError): pass
            elif line:
                emit_event("diagnostic", message=line)
        close_stdout = getattr(process.stdout, "close", None)
        if close_stdout:
            close_stdout()
        status = process.wait()
        unregister_process(process)
        dispatcher.join(timeout=0.05)
        emit_finalizing_once()
        if exact_path is None or not exact_path.is_file() or not exact_path.resolve().is_relative_to(task_dir.resolve()):
            raise RuntimeError("yt-dlp did not report an exact task output")
        if status != 0 and not (status == 130 and stop_requested.is_set()):
            raise RuntimeError("recording process failed")
        path = exact_path
        if media == "mp3":
            ffmpeg_path = ffmpeg()
            target = path.with_suffix(".mp3")
            result = subprocess.run([ffmpeg_path, "-y", "-i", str(path), "-vn", "-codec:a", "libmp3lame", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if result.returncode: raise RuntimeError("recording conversion failed")
            path = target
        probe = ffprobe()
        validation = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name", "-of", "json", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        payload = json.loads(validation.stdout.decode() if isinstance(validation.stdout, bytes) else validation.stdout)
        duration = float(payload.get("format", {}).get("duration", 0))
        streams = payload.get("streams", [])
        if media == "video": valid_stream = any(s.get("codec_type") == "video" for s in streams)
        elif media == "aac": valid_stream = any(s.get("codec_type") == "audio" and s.get("codec_name") == "aac" for s in streams)
        else: valid_stream = any(s.get("codec_type") == "audio" and s.get("codec_name") == "mp3" for s in streams)
        if validation.returncode or not math.isfinite(duration) or duration <= 0 or not valid_stream or not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("final media validation failed")
        destination = _available_destination(output_dir, path.name)
        # Hard-link creation is atomic and fails if another task wins the name race.
        suffix = 0
        while True:
            try:
                destination.hardlink_to(path)
                break
            except FileExistsError:
                suffix += 1
                stem = Path(path.name)
                destination = output_dir / f"{stem.stem} ({suffix}){stem.suffix}"
        shutil.rmtree(task_dir, ignore_errors=True)
        emit_event("file", path=str(destination))
        emit_event("completed", path=str(destination))
        return 0
    except Exception as exc:
        try: _recovery(task_dir, task_id, media, quality)
        except OSError: pass
        emit_event("error", code="recordingFinalizeFailed", message=f"Recording could not be finalized ({type(exc).__name__}). Recovery data: {task_dir}")
        return 1
    finally:
        if process is not None:
            unregister_process(process)
