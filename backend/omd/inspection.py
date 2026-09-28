"""Metadaten und Playlist-Einträge vor dem Start einer Warteschlange."""
from __future__ import annotations

import concurrent.futures
import copy
import json
import http.cookiejar
from html.parser import HTMLParser
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from . import downloads
from .auth import InvalidCookieFileError
from .errors import (
    BackendError, args_without_browser_cookies, cookie_access_warning,
    is_cookie_access_error, sanitized_ytdlp_detail,
)
from .estimates import entry_from_info


class _EmbedParser(HTMLParser):
    """Collect only literal player URLs; never interpret page scripts."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        candidate = attrs.get("src") if tag in ("iframe", "embed") else attrs.get("data") if tag == "object" else None
        if candidate:
            self.urls.append(candidate.strip())


def discover_embedded_players(url: str, args, *, include_source_url: bool = False):
    """Fetch ordinary HTML and return deduplicated standard YouTube/Vimeo players.

    Set include_source_url to also return the final URL after redirects.
    """
    jar = None
    cookie_file = getattr(args, "cookies_file", None)
    if cookie_file:
        jar = http.cookiejar.MozillaCookieJar(cookie_file)
        jar.load(ignore_discard=True, ignore_expires=True)
    opener = build_opener(*([HTTPCookieProcessor(jar)] if jar else []))
    request = Request(url, headers={"User-Agent": downloads.UA, "Accept": "text/html"})
    with opener.open(request, timeout=15) as response:
        if "html" not in response.headers.get("Content-Type", "").lower():
            return ([], response.geturl()) if include_source_url else []
        final_url = response.geturl()
        if not isinstance(final_url, str):  # simple response doubles used by legacy callers
            final_url = url
        html = response.read(2_000_001)
    if len(html) > 2_000_000:
        html = html[:2_000_000]
    parser = _EmbedParser()
    parser.feed(html.decode("utf-8", "replace"))
    found, seen = [], set()
    for raw in parser.urls:
        player = urljoin(final_url, raw)
        parts = urlparse(player)
        host = (parts.hostname or "").lower().removeprefix("www.")
        if parts.scheme not in ("http", "https") or not (host == "youtube.com" or host.endswith(".youtube.com") or host == "youtube-nocookie.com" or host.endswith(".youtube-nocookie.com") or host == "vimeo.com" or host.endswith(".vimeo.com")):
            continue
        if host.endswith("youtube.com") and not (parts.path.startswith("/embed/") or parts.path.startswith("/live/")):
            continue
        if host == "youtube-nocookie.com" or host.endswith(".youtube-nocookie.com"):
            if not parts.path.startswith("/embed/"):
                continue
        if host.endswith("vimeo.com") and not (parts.path.startswith("/video/") or parts.path.strip("/").isdigit()):
            continue
        if player not in seen:
            seen.add(player)
            found.append(player)
    return (found, final_url) if include_source_url else found


def _classify_stream(entry: dict, info: dict) -> dict:
    status = str(info.get("live_status") or "").lower()
    state = {
        "is_live": "live",
        "is_upcoming": "scheduled",
        "post_live": "endedProcessing",
        "was_live": "vod",
        "not_live": "vod",
    }.get(status, "regular")
    entry["streamState"] = state
    # Only extractor evidence attached to a specific format proves archive access.
    formats = info.get("formats")
    entry["fromStartSupported"] = bool(
        state == "live"
        and isinstance(formats, list)
        and any(isinstance(fmt, dict) and fmt.get("is_from_start") is True for fmt in formats)
    )
    if state == "live" and not entry["fromStartSupported"]:
        entry["fromStartReason"] = "archiveUnavailable"
    if state == "live":
        entry["estimates"] = []
    return entry


def probe_content_length(url: str) -> int | None:
    """HEAD lädt nur Header; ein unbekannter Wert bleibt unbekannt."""
    try:
        with urlopen(Request(url, method="HEAD", headers={"User-Agent": downloads.UA}), timeout=10) as response:
            if response.status != 200:
                return None
            length = int(response.headers.get("Content-Length") or 0)
            return length if length > 0 else None
    except (OSError, ValueError):
        return None


def _vimeo_metadata(cfg: dict, url: str) -> dict:
    video = cfg.get("video") or {}
    formats = []
    direct = downloads.progressive(cfg)
    def rendition(item):
        result = dict(item, protocol="https", ext="mp4", vcodec="h264", acodec="mp4a.40.2")
        if item.get("url") and not item.get("filesize"):
            size = probe_content_length(item["url"])
            if size:
                result["filesize"] = size
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        formats.extend(executor.map(rendition, direct))
    master = downloads.hls_url(cfg)
    if master:
        try:
            lines = [line.strip() for line in downloads.get(master).decode("utf-8", "replace").splitlines() if line.strip()]
            for index, line in enumerate(lines[:-1]):
                if not line.startswith("#EXT-X-STREAM-INF:"):
                    continue
                attributes = downloads.attrs(line)
                width, height = attributes.get("RESOLUTION", "0x0").split("x")
                formats.append({
                    "url": urljoin(master, lines[index + 1]), "height": int(height), "width": int(width),
                    "protocol": "m3u8_native", "ext": "mp4", "vcodec": "h264", "acodec": "mp4a.40.2",
                    # BANDWIDTH beschreibt die kombinierte HLS-Variante.
                    "tbr": int(attributes.get("AVERAGE-BANDWIDTH") or attributes.get("BANDWIDTH") or 0) / 1000,
                })
        except (OSError, ValueError, RuntimeError):
            pass
    return {"title": video.get("title") or "Vimeo video", "duration": video.get("duration"), "formats": formats, "webpage_url": url, "nativeVimeo": True}


def read_ytdlp_metadata(url: str, args) -> tuple[dict, list[dict]]:
    inspection_args = copy.copy(args)
    inspection_args.media, inspection_args.quality, inspection_args.mode = "video", "best", "auto"
    tail = ["--ignore-errors", "--skip-download", "--dump-single-json", "--socket-timeout", "25", url]
    warnings = []
    try:
        command = downloads.ytdlp_options(inspection_args, simulate=True) + tail
        result = downloads.run_captured(command, timeout=600)
        detail = "\n".join(part for part in (result.stderr, result.stdout) if part)
    except InvalidCookieFileError:
        result = None
        detail = "invalid cookie file"
    cookies = getattr(args, "cookies_browser", None) or getattr(args, "cookies_file", None)
    if cookies and (result is None or is_cookie_access_error(detail)):
        warnings.append(cookie_access_warning(getattr(args, "cookies_browser", None) or "file"))
        anonymous = args_without_browser_cookies(inspection_args)
        anonymous.cookies_file = None
        result = downloads.run_captured(downloads.ytdlp_options(anonymous, simulate=True, use_browser_cookies=False) + tail, timeout=600)
        detail = "\n".join(part for part in (result.stderr, result.stdout) if part)
    try:
        payload = json.loads(result.stdout) if result is not None else None
    except (ValueError, TypeError):
        payload = None
    if not isinstance(payload, dict):
        downloads._ytdlp_failure(detail or "Не удалось получить сведения о видео.", warnings=warnings)
    if not payload.get("entries") and not payload.get("formats") and payload.get("availability") in ("private", "needs_auth", "subscriber_only", "premium_only"):
        downloads._ytdlp_failure("Authentication required", warnings=warnings)
    return payload, warnings


def inspect_url(url: str, args, embed_referer_origin: str | None = None) -> dict:
    if "videos/rss" in url.lower():
        entries, warnings = [], []
        for child_url, title in downloads.rss_items(url):
            try:
                child = inspect_url(child_url, args)
                entries.extend(child["entries"])
                warnings.extend(item for item in child.get("warnings", []) if item not in warnings)
            except Exception as error:
                entries.append({"url": child_url, "title": title, "availability": "unavailable", "error": sanitized_ytdlp_detail(str(error)), "estimates": []})
        return {"ok": True, "source": url, "isPlaylist": True, "entries": entries, "warnings": warnings, "cookieFallbackUsed": bool(warnings)}
    host = (urlparse(url).hostname or "").lower()
    if not (host == "youtube.com" or host.endswith(".youtube.com") or host == "youtube-nocookie.com" or host.endswith(".youtube-nocookie.com") or host == "vimeo.com" or host.endswith(".vimeo.com")):
        try:
            discovery = discover_embedded_players(url, args, include_source_url=True)
            if isinstance(discovery, tuple):
                players, final_source_url = discovery
            else:  # compatibility with callers/tests replacing the legacy API
                players, final_source_url = discovery, url
        except (OSError, URLError, ValueError, http.cookiejar.LoadError):
            players = []
        if players:
            entries, warnings = [], []
            for player in players:
                player_args = copy.copy(args)
                player_args.referer = downloads.origin_referer(final_source_url)
                detail, player_warnings = read_ytdlp_metadata(player, player_args)
                children = detail.get("entries") if isinstance(detail.get("entries"), list) else [detail]
                for item in children:
                    if isinstance(item, dict):
                        entry = _classify_stream(entry_from_info(item, player), item)
                        entry["embedRefererOrigin"] = downloads.origin_referer(final_source_url)
                        entries.append(entry)
                warnings.extend(item for item in player_warnings if item not in warnings)
            if entries:
                return {"ok": True, "source": url, "isPlaylist": len(entries) > 1, "entries": entries, "warnings": warnings, "cookieFallbackUsed": bool(warnings)}
        if not players:
            raise BackendError("No standard YouTube/Vimeo player was found. This page may build its player with JavaScript; copy the direct YouTube or Vimeo player URL and paste it here.")
    if (host == "vimeo.com" or host.endswith(".vimeo.com")) and not downloads.validate_referer(getattr(args, "referer", None)):
        try:
            _resolved, cfg = downloads.resolved_player_config(url)
            metadata = _vimeo_metadata(cfg, url)
            if not metadata["formats"]:
                raise RuntimeError("В конфиге Vimeo нет доступных потоков.")
            entry = entry_from_info(metadata, url)
            entry["streamState"] = "regular"
            entry["fromStartSupported"] = False
            entry["availability"] = "available"
            return {"ok": True, "source": url, "isPlaylist": False, "entries": [entry], "warnings": [], "cookieFallbackUsed": False}
        except Exception:
            try:
                lookup_url = downloads.discover_public_player_url(url)
            except Exception:
                lookup_url = url
    else:
        lookup_url = url
    info, warnings = read_ytdlp_metadata(lookup_url, args)
    is_playlist = info.get("_type") in ("playlist", "multi_video") or isinstance(info.get("entries"), list)
    sources = info.get("entries", []) if is_playlist else [info]
    entries = [_classify_stream(entry_from_info(item, url), item) for item in sources if isinstance(item, dict)]
    if embed_referer_origin and (
        host in {"youtube.com", "youtube-nocookie.com", "vimeo.com"}
        or host.endswith((".youtube.com", ".youtube-nocookie.com", ".vimeo.com"))
    ):
        origin = downloads.origin_referer(embed_referer_origin)
        if origin:
            for entry in entries:
                entry["embedRefererOrigin"] = origin
    if not entries:
        raise BackendError("В плейлисте не найдено доступных видео.")
    return {"ok": True, "source": url, "isPlaylist": is_playlist, "entries": entries, "warnings": warnings, "cookieFallbackUsed": bool(warnings)}
