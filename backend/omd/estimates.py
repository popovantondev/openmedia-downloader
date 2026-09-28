"""Dateigrößen ohne Medien-Download schätzen, Unbekanntes nicht erfinden."""
from __future__ import annotations

import math

VIDEO_QUALITIES = ("best", "4320", "2160", "1440", "1080", "720", "540", "480", "360", "240", "144")
MP3_QUALITIES = ("320k", "256k", "192k", "128k")
MODES = ("auto", "direct", "chunks")


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError):
        return None


def protocol_matches(item: dict, mode: str) -> bool:
    protocol = str(item.get("protocol") or "").lower()
    if not protocol:
        url = str(item.get("url") or "").lower()
        protocol = "m3u8" if ".m3u8" in url else "https" if url.startswith("https:") else "http" if url.startswith("http:") else ""
    if mode == "auto":
        return True
    if mode == "direct":
        return protocol in ("https", "http")
    return "m3u8" in protocol or "dash" in protocol


def has_video(item: dict) -> bool:
    return item.get("vcodec") != "none" and bool(number(item.get("height")))


def has_audio(item: dict) -> bool:
    return item.get("acodec") not in (None, "none", "") or (not has_video(item) and number(item.get("abr")) is not None)


def is_aac(item: dict) -> bool:
    codec = str(item.get("acodec") or "").lower()
    return "mp4a" in codec or "aac" in codec or item.get("ext") == "m4a"


def _best_audio(formats: list[dict], aac_only=False):
    audio = [item for item in formats if has_audio(item) and not has_video(item) and (not aac_only or is_aac(item))]
    return max(audio, key=lambda item: (number(item.get("abr")) or number(item.get("tbr")) or 0, item.get("ext") == "m4a"), default=None)


def _best_video(formats: list[dict], quality: str):
    videos = [item for item in formats if has_video(item)]
    if not videos:
        return None
    heights = {int(number(item.get("height")) or 0) for item in videos}
    if quality == "best":
        height = max(heights)
    else:
        wanted = int(quality)
        height = min(heights, key=lambda value: (abs(value - wanted), value > wanted, value))
    return max((item for item in videos if int(item["height"]) == height), key=lambda item: (item.get("ext") == "mp4", number(item.get("tbr")) or number(item.get("vbr")) or 0))


def _stream_bytes(item: dict, duration, audio_only=False):
    """Exakte Bytes haben Vorrang; Bitraten sind Kilobit pro Sekunde."""
    if not audio_only:
        exact = number(item.get("filesize"))
        if exact:
            return int(exact), False
        approximate = number(item.get("filesize_approx"))
        if approximate:
            return int(approximate), True
    bitrate = number(item.get("abr")) if audio_only else number(item.get("tbr"))
    if not bitrate and not audio_only:
        video_rate = number(item.get("vbr"))
        audio_rate = number(item.get("abr"))
        if video_rate or audio_rate:
            bitrate = (video_rate or 0) + (audio_rate or 0)
    if duration and bitrate:
        return int(duration * bitrate * 1000 / 8), True
    return None


def build_estimates(info: dict) -> list[dict]:
    duration = number(info.get("duration"))
    formats = [item for item in info.get("formats", []) if isinstance(item, dict) and not item.get("has_drm")]
    values = []
    for mode in MODES:
        candidates = [item for item in formats if protocol_matches(item, mode)]
        # Vimeo auto nutzt zuerst einen vorhandenen direkten MP4.
        if mode == "auto" and info.get("nativeVimeo"):
            direct = [item for item in candidates if protocol_matches(item, "direct")]
            candidates = direct or candidates
        audio = _best_audio(candidates)
        for quality in VIDEO_QUALITIES:
            video = _best_video(candidates, quality)
            if not video:
                continue
            size = _stream_bytes(video, duration)
            if not size:
                continue
            total, approximate = size
            if not has_audio(video):
                audio_size = _stream_bytes(audio, duration) if audio else None
                if not audio_size:
                    continue
                total += audio_size[0]
                # Zusammenführen ändert Container-Overhead geringfügig.
                approximate = True
            values.append({"media": "video", "quality": quality, "mode": mode, "bytes": total, "approximate": approximate, "actualQuality": str(int(video["height"]))})
        aac = _best_audio(candidates, aac_only=True)
        if aac:
            size = _stream_bytes(aac, duration)
        else:
            muxed_aac = next((item for item in candidates if has_video(item) and is_aac(item)), None)
            size = _stream_bytes(muxed_aac, duration, audio_only=True) if muxed_aac else None
        if size:
            # M4A wird neu verpackt, der AAC-Inhalt bleibt unverändert.
            values.append({"media": "aac", "quality": "best", "mode": mode, "bytes": size[0], "approximate": True})
        if duration and any(has_audio(item) for item in candidates):
            for quality in MP3_QUALITIES:
                values.append({"media": "mp3", "quality": quality, "mode": mode, "bytes": int(duration * int(quality[:-1]) * 1000 / 8), "approximate": True})
    return values


def entry_from_info(info: dict, fallback_url: str) -> dict:
    availability = str(info.get("availability") or "")
    formats = info.get("formats") or []
    restricted = availability in ("private", "needs_auth", "subscriber_only", "premium_only")
    if formats:
        state = "available"
    elif restricted:
        state = "authenticationRequired"
    elif info.get("title") in ("[Deleted video]", "[Private video]"):
        state = "authenticationRequired" if "Private" in info["title"] else "unavailable"
    else:
        state = "unknown"
    url = info.get("webpage_url") or info.get("original_url")
    if not url and info.get("id") and str(info.get("extractor_key", "")).lower().startswith("youtube"):
        url = "https://www.youtube.com/watch?v=" + info["id"]
    entry = {
        "url": url or fallback_url,
        "title": info.get("title") or "Video",
        "availableHeights": sorted({int(item["height"]) for item in formats if number(item.get("height"))}, reverse=True),
        "availability": state,
        "estimates": build_estimates(info),
    }
    duration = number(info.get("duration"))
    if duration:
        entry["duration"] = duration
    return entry
