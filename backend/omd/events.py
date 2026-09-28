"""Kleine JSON-Ereignisse statt unsicherem Parsen von Bildschirmtext."""
from __future__ import annotations

import json
import math
import threading
import time

from .errors import COOKIE_ACCESS_WARNING_CODE, sanitized_ytdlp_detail

EVENT_PREFIX = "OMD_EVENT:"
_OUTPUT_LOCK = threading.Lock()


def emit_event(kind: str, **values) -> None:
    payload = {"type": kind, **{key: value for key, value in values.items() if value is not None}}
    if "message" in payload:
        payload["message"] = sanitized_ytdlp_detail(payload["message"])
    with _OUTPUT_LOCK:
        print(EVENT_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), flush=True)


def emit_backend_event(payload: dict) -> None:
    """Die bewährten Rückfallwege benutzen dieselben sicheren Ereignisse."""
    if payload.get("code") == COOKIE_ACCESS_WARNING_CODE:
        emit_event("stage", stage="preparing", message="Cookies недоступны: повторяю публичную ссылку без авторизации.", **payload)
    else:
        emit_event(payload.get("type", "error"), **{key: value for key, value in payload.items() if key != "type"})


def positive_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


class ProgressAccumulator:
    """Bytewerte mehrerer Audio-/Videospuren addieren."""

    def __init__(self):
        self.expected_bytes = None
        self.tracks = {}
        self.started = time.monotonic()

    def set_metadata(self, metadata: dict) -> None:
        formats = metadata.get("formats") or []
        sizes = [positive_number(item.get("filesize") or item.get("filesize_approx")) for item in formats if isinstance(item, dict)]
        if sizes and all(size for size in sizes):
            self.expected_bytes = int(sum(sizes))
        else:
            self.expected_bytes = positive_number(metadata.get("filesize") or metadata.get("filesizeApprox"))

    def update(self, data: dict) -> dict:
        key = str(data.get("filename") or data.get("tmpfilename") or "media")
        downloaded = positive_number(data.get("downloaded_bytes"))
        total = positive_number(data.get("total_bytes") or data.get("total_bytes_estimate"))
        if downloaded is not None:
            self.tracks[key] = max(downloaded, self.tracks.get(key, 0))
        combined = sum(self.tracks.values())
        result = {"downloadedBytes": int(combined)}
        if self.expected_bytes:
            result.update(totalBytes=int(self.expected_bytes), progress=min(0.99, combined / self.expected_bytes))
        elif total and len(self.tracks) == 1:
            # Ohne Gesamtgröße ist das nur die aktuelle Spur. Die UI sieht
            # weiter die Phase „downloading“, nicht fälschlich „completed“.
            result.update(totalBytes=int(total), progress=min(0.99, combined / total))
        for source, destination in (("speed", "speedBytesPerSecond"), ("eta", "etaSeconds"), ("fragment_index", "fragmentIndex"), ("fragment_count", "fragmentCount")):
            value = positive_number(data.get(source))
            if value is not None:
                result[destination] = int(value) if destination.startswith("fragment") else value
        return result
