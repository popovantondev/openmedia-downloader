#!/usr/bin/env python3
"""JSON-Schnittstelle zwischen nativer Oberfläche und Download-Modulen."""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
import sys
import subprocess
import threading
import queue
import types
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from omd.auth import prepare_authentication
from omd.downloads import process_with_fallback, rss_items
from omd.errors import BackendError, classify_error, sanitized_ytdlp_detail
from omd.events import emit_event
from omd.inspection import discover_embedded_players, inspect_url
from omd.stream_recording import record as record_stream
from omd import downloads, runtime
from omd.runtime import establish_process_group, install_signal_handlers, cleanup_runtime_temp_dir
from omd.version import VERSION


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=f"OpenMedia Downloader {VERSION}")
    result.add_argument("--version", action="version", version=f"OpenMedia Downloader {VERSION}")
    result.add_argument("urls", nargs="*")
    result.add_argument("-o", "--output", default=str(Path.home() / "Downloads"))
    result.add_argument("-q", "--quality", default="best")
    result.add_argument("--media", choices=("video", "aac", "mp3"), default="video")
    result.add_argument("--mode", choices=("auto", "direct", "chunks"), default="auto")
    result.add_argument("--workers", type=int, default=4)
    result.add_argument("--overwrite", action="store_true")
    result.add_argument("--ask-overwrite", action="store_true")
    result.add_argument("--inspect-json", action="store_true")
    result.add_argument("--inspect-stream", action="store_true", help="emit progressive inspection events")
    result.add_argument("--request-id", help="caller supplied inspection request identity")
    result.add_argument("--generation", type=int, help="caller supplied inspection generation")
    result.add_argument("--no-playlist", action="store_true", help="select only the video when a URL also identifies a playlist")
    result.add_argument("--auth-check-json", action="store_true")
    result.add_argument("--cookies-browser", choices=("safari", "chrome", "opera", "firefox", "edge", "brave", "chromium"))
    result.add_argument("--cookies-file")
    result.add_argument("--referer", help="HTTP(S) page origin for embedded media")
    result.add_argument("--session-dir")
    result.add_argument("--auth-url")
    result.add_argument("--auth-domain", action="append", default=[], metavar="HOST",
                        help="retain cookies for this explicitly approved website host (repeatable)")
    result.add_argument("--check", action="store_true")
    result.add_argument("--first", action="store_true")
    result.add_argument("--record-stream", action="store_true")
    result.add_argument("--task-id", help="stable recording task identity")
    result.add_argument("--stream-start", choices=("now", "from-start"), default="now")
    result.add_argument("--from-start-supported", action="store_true")
    return result


def _error_payload(error: Exception, source=None) -> dict:
    code = classify_error(error)
    warnings = list(getattr(error, "warnings", []))
    return {
        "ok": False, "source": source, "entries": [], "errorCode": code,
        "error": sanitized_ytdlp_detail(str(error)), "warnings": warnings,
        "authenticationRequired": code == "authenticationRequired", "cookieFallbackUsed": bool(warnings),
    }


class _MetadataScheduler:
    """Four-worker metadata queue with reprioritization of queued identities."""
    def __init__(self, args, workers=4):
        self._args = args
        self._condition = threading.Condition()
        self._pending = []
        self._jobs = {}
        self._prioritized = set()
        self._sequence = 0
        self._closed = False
        self._results = queue.Queue()
        self._threads = [threading.Thread(target=self._worker, daemon=True) for _ in range(workers)]
        for thread in self._threads:
            thread.start()

    def submit(self, item_id, row, url, selected=False):
        with self._condition:
            if self._closed or item_id in self._jobs:
                return
            selected = selected or item_id in self._prioritized
            job = {"row": row, "url": url, "priority": 0 if selected else 1, "queued": True}
            self._jobs[item_id] = job
            self._sequence += 1
            heapq.heappush(self._pending, (job["priority"], self._sequence, item_id))
            self._condition.notify()

    def prioritize(self, item_id):
        with self._condition:
            self._prioritized.add(item_id)
            job = self._jobs.get(item_id)
            if job and job["queued"] and job["priority"] != 0:
                job["priority"] = 0
                self._sequence += 1
                heapq.heappush(self._pending, (0, self._sequence, item_id))
                self._condition.notify()

    def _worker(self):
        while True:
            with self._condition:
                while not self._pending and not self._closed:
                    self._condition.wait()
                if self._closed and not self._pending:
                    return
                priority, _, item_id = heapq.heappop(self._pending)
                job = self._jobs.get(item_id)
                if not job or not job["queued"] or job["priority"] != priority:
                    continue
                job["queued"] = False
            try:
                outcome = (True, inspect_url(job["url"], self._args))
            except Exception as error:
                outcome = (False, error)
            self._results.put((item_id, job["row"], outcome))

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def results(self):
        return self._results


def _stream_inspection(url: str, args) -> bool:
    """Emit a quick flat discovery first, then enrich each row independently."""
    request_id = args.request_id or "default"
    generation = args.generation if args.generation is not None else 0
    identity = {"requestId": request_id, "generation": generation, "source": url}
    try:
        runtime.check_cancelled()
        host = (urlparse(url).hostname or "").lower()
        parts = urlparse(url)
        path = parts.path.rstrip("/").lower()
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        youtube = host == "youtube.com" or host.endswith(".youtube.com") or host == "youtu.be"
        vimeo = host == "vimeo.com" or host.endswith(".vimeo.com")
        standalone_youtube = youtube and ((host == "youtu.be" and bool(path.strip("/"))) or
            (path == "/watch" and bool(query.get("v")) and not query.get("list")) or
            (path.startswith(("/shorts/", "/live/", "/embed/")) and bool(path.split("/")[-1])))
        standalone_vimeo = vimeo and ((host == "player.vimeo.com" and path.startswith("/video/") and bool(path.split("/")[-1])) or
            (host == "vimeo.com" and path.count("/") == 1 and path.strip("/").isdigit()))
        if standalone_youtube or standalone_vimeo:
            item_id = hashlib.sha256(urlunparse(parts._replace(fragment="")).encode("utf-8")).hexdigest()[:24]
            try:
                runtime.check_cancelled()
                detail = inspect_url(url, args)
                runtime.check_cancelled()
                entries = detail["entries"]
                emit_event("title", **identity, title=(entries[0].get("title") if entries else "") or "")
                emit_event("discoveryComplete", **identity, isPlaylist=False, count=1)
                emit_event("metadata", **identity, itemId=item_id, index=0, playlistPosition=0, entry=entries[0])
                emit_event("inspectionComplete", **identity, ok=True, isPlaylist=False, count=1)
                return True
            except InterruptedError:
                return False
            except Exception as error:
                emit_event("title", **identity, title="")
                emit_event("discoveryComplete", **identity, isPlaylist=False, count=1)
                emit_event("inspectionError", **identity, itemId=item_id, index=0, playlistPosition=0, error=sanitized_ytdlp_detail(str(error)))
                emit_event("inspectionComplete", **identity, ok=False, count=0)
                return False
        if not (host == "youtube.com" or host.endswith(".youtube.com") or host == "youtube-nocookie.com" or host.endswith(".youtube-nocookie.com") or host == "vimeo.com" or host.endswith(".vimeo.com")):
            try:
                discovery = discover_embedded_players(url, args, include_source_url=True)
                if isinstance(discovery, tuple):
                    players, final_source_url = discovery
                else:
                    players, final_source_url = discovery, url
            except Exception:
                players, final_source_url = [], url
            if players:
                emit_event("title", **identity, title="Embedded videos")
                if len(players) > 1:
                    for index, player in enumerate(players):
                        runtime.check_cancelled()
                        emit_event("playlistEntry", **identity, index=index, url=player, title=player, availability="unknown")
                for index, player in enumerate(players):
                    runtime.check_cancelled()
                    try:
                        player_args = types.SimpleNamespace(**vars(args))
                        player_args.referer = downloads.origin_referer(final_source_url)
                        detail = inspect_url(player, player_args, embed_referer_origin=downloads.origin_referer(final_source_url))
                        emit_event("metadata", **identity, index=index, entry=detail["entries"][0])
                    except Exception as error:
                        emit_event("inspectionError", **identity, index=index, error=sanitized_ytdlp_detail(str(error)))
                emit_event("inspectionComplete", **identity, ok=True, isPlaylist=len(players) > 1, count=len(players))
                return True
            try:
                inspect_url(url, args)
            except Exception as error:
                emit_event("inspectionError", **identity, error=sanitized_ytdlp_detail(str(error)))
                emit_event("inspectionComplete", **identity, ok=False, count=0)
                return False
        # Flat playlist extraction resolves identity and titles without fetching
        # each media's formats. This lets the UI render selectable rows early.
        probe_args = types.SimpleNamespace(**vars(args))
        probe_args.media, probe_args.quality, probe_args.mode = "video", "best", "auto"
        command = downloads.ytdlp_options(probe_args, simulate=True) + [
            "--ignore-errors", "--skip-download", "--flat-playlist",
            "--dump-json", "--socket-timeout", "25", url,
        ]
        process = runtime.start_process(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        stderr_chunks = []
        stderr_thread = threading.Thread(target=lambda: stderr_chunks.extend(process.stderr), daemon=True)
        stderr_thread.start()
        rows, seen = [], set()
        scheduler = _MetadataScheduler(args, workers=4)
        stop_reader = threading.Event()
        stdin_stream = getattr(sys, "stdin", None)
        def read_priorities():
            if stdin_stream is None or not hasattr(stdin_stream, "readline"):
                return
            while not stop_reader.is_set():
                try:
                    line = stdin_stream.readline()
                except Exception:
                    return
                if not line:
                    return
                try:
                    message = json.loads(line)
                    if isinstance(message, dict) and message.get("type") == "prioritize" and isinstance(message.get("itemId"), str):
                        item_id = message["itemId"]
                        scheduler.prioritize(item_id)
                except (ValueError, TypeError):
                    continue
        priority_thread = threading.Thread(target=read_priorities, daemon=True)
        priority_thread.start()
        missing_rows = []
        first = None
        single = False
        try:
            extractor_position = 0
            for line in process.stdout:
                runtime.check_cancelled()
                if not line.strip():
                    continue
                child = json.loads(line)
                if first is None:
                    first = child
                    if child.get("_type") not in ("playlist", "multi_video") and not child.get("playlist_id"):
                        single = True
                if single:
                    continue
                if len(rows) == 0 and child is first:
                    emit_event("title", **identity, title=child.get("playlist_title") or child.get("playlist") or "")
                raw_url = child.get("webpage_url") or child.get("original_url") or child.get("url") or ""
                if raw_url and not urlparse(raw_url).scheme:
                    raw_url = f"https://www.youtube.com/watch?v={raw_url}"
                position = extractor_position
                extractor_position += 1
                if raw_url:
                    parts = urlparse(raw_url)
                    canonical = urlunparse(parts._replace(fragment=""))
                    if canonical in seen:
                        continue
                    seen.add(canonical)
                    item_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
                else:
                    item_id = hashlib.sha256(f"{url}\0missing\0{position}".encode()).hexdigest()[:24]
                row = {"itemId": item_id, "index": position, "playlistPosition": position, "url": raw_url, "title": child.get("title") or ""}
                rows.append(row)
                emit_event("playlistEntry", **identity, **row, availability="unknown")
                if raw_url:
                    scheduler.submit(item_id, row, raw_url)
                else:
                    missing_rows.append(row)
            return_code = process.wait()
            stderr_thread.join()
            if single:
                runtime.check_cancelled()
                title = first.get("title") or ""
                emit_event("title", **identity, title=title)
                try:
                    detailed = inspect_url(url, args)
                    for index, entry in enumerate(detailed["entries"]):
                        emit_event("metadata", **identity, index=index, entry=entry)
                    emit_event("inspectionComplete", **identity, ok=True, isPlaylist=detailed.get("isPlaylist", False), count=len(detailed["entries"]))
                    return True
                except Exception as error:
                    emit_event("inspectionError", **identity, error=sanitized_ytdlp_detail(str(error)))
                    emit_event("inspectionComplete", **identity, ok=False, count=0)
                    return False
            emit_event("discoveryComplete", **identity, isPlaylist=True, count=len(rows))
            ok = return_code == 0
            scheduler.close()
            for _ in range(sum(1 for row in rows if row["url"])):
                runtime.check_cancelled()
                item_id, row, (succeeded, value) = scheduler.results().get(timeout=0.1)
                try:
                    if not succeeded:
                        raise value
                    entry = value["entries"][0]
                    emit_event("metadata", **identity, itemId=row["itemId"], index=row["index"], playlistPosition=row["playlistPosition"], entry=entry)
                except InterruptedError:
                    raise
                except Exception as error:
                    emit_event("inspectionError", **identity, itemId=row["itemId"], index=row["index"], playlistPosition=row["playlistPosition"], error=sanitized_ytdlp_detail(str(error)))
            for row in missing_rows:
                emit_event("inspectionError", **identity, itemId=row["itemId"], index=row["index"], playlistPosition=row["playlistPosition"], error="Playlist entry has no URL.")
            emit_event("inspectionComplete", **identity, ok=ok, isPlaylist=True, count=len(rows))
            return ok
        finally:
            stop_reader.set()
            scheduler.close()
            for stream in (process.stdout, process.stderr):
                if stream: stream.close()
            if process.poll() is None:
                runtime.terminate_process(process)
            runtime._unregister_process(process)
        # Single item: title-only yt-dlp output is emitted before format probing.
        title_command = downloads.ytdlp_options(probe_args, simulate=True) + [
            "--skip-download", "--no-warnings", "--no-playlist", "--print", "%(title)s",
            "--socket-timeout", "25", url,
        ]
        title_result = downloads.run_captured(title_command, timeout=180)
        runtime.check_cancelled()
        title = (title_result.stdout or "").strip().splitlines()
        emit_event("title", **identity, title=title[0] if title else "")
        try:
            detailed = inspect_url(url, args)
            runtime.check_cancelled()
            for index, entry in enumerate(detailed["entries"]):
                emit_event("metadata", **identity, index=index, entry=entry)
            emit_event("inspectionComplete", **identity, ok=True, isPlaylist=detailed.get("isPlaylist", False), count=len(detailed["entries"]))
            return True
        except InterruptedError:
            raise
        except Exception as error:
            emit_event("inspectionError", **identity, error=sanitized_ytdlp_detail(str(error)))
            emit_event("inspectionComplete", **identity, ok=False, count=0)
            return False
    except InterruptedError:
        # A cancelled request never emits a completion that could revive UI rows.
        return False
    except Exception as error:
        emit_event("inspectionError", **identity, error=sanitized_ytdlp_detail(str(error)))
        emit_event("inspectionComplete", **identity, ok=False, count=0)
        return False


def main(argv=None) -> int:
    install_signal_handlers()
    args = parser().parse_args(argv)
    if args.auth_check_json:
        response = prepare_authentication(args)
        print(json.dumps(response, ensure_ascii=False), flush=True)
        return 0 if response["ok"] else 1
    if not args.urls:
        parser().error("Нужна ссылка на видео или плейлист.")
    failed = False
    for url in args.urls:
        try:
            if urlparse(url).scheme not in ("http", "https"):
                raise ValueError("Поддерживаются только ссылки http/https.")
            if args.inspect_json and not args.inspect_stream:
                inspection_url = url
                # yt-dlp treats watch?v=...&list=... as a playlist unless
                # asked otherwise. Remove only the playlist selector; keep
                # video identity and all other service parameters intact.
                if args.no_playlist:
                    parts = urlparse(url)
                    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() != "list"]
                    inspection_url = urlunparse(parts._replace(query=urlencode(query)))
                response = inspect_url(inspection_url, args)
                response["source"] = url
                print(json.dumps(response, ensure_ascii=False), flush=True)
                continue
            if args.inspect_stream:
                inspection_url = url
                if args.no_playlist:
                    parts = urlparse(url)
                    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() != "list"]
                    inspection_url = urlunparse(parts._replace(query=urlencode(query)))
                if not _stream_inspection(inspection_url, args):
                    failed = True
                continue
            if args.record_stream:
                status = record_stream(url, args.output, args.stream_start, args.from_start_supported, args.media, args.referer, task_args=args)
                failed = failed or status != 0
                continue
            emit_event("stage", stage="preparing")
            if "videos/rss" in url.lower():
                entries = rss_items(url)
                for child_url, title in entries[:1] if args.first else entries:
                    process_with_fallback(child_url, args, title)
            else:
                process_with_fallback(url, args)
        except Exception as error:
            failed = True
            payload = _error_payload(error, url)
            if args.inspect_json and not args.inspect_stream:
                print(json.dumps(payload, ensure_ascii=False), flush=True)
            else:
                emit_event("error", code=payload["errorCode"], message=payload["error"])
    return 1 if failed else 0


if __name__ == "__main__":
    os.umask(0o077)
    establish_process_group()
    try:
        raise SystemExit(main())
    finally:
        cleanup_runtime_temp_dir()
