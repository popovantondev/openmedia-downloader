"""Bewährte Vimeo- und yt-dlp-Downloadwege ohne GUI-Abhängigkeit."""
from __future__ import annotations

import concurrent.futures
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
import ipaddress
from urllib.request import Request, urlopen

from . import runtime
from .auth import cookie_file_for_job, normalize_auth_domain, InvalidCookieFileError
from .errors import (
    AUTHENTICATION_REQUIRED_CODE, COOKIE_ACCESS_WARNING_CODE,
    AuthenticationRequiredError, BackendError, PreflightEntries, YTDLPError,
    args_without_browser_cookies, authentication_required_error, cookie_access_warning,
    is_authentication_required_error, is_cookie_access_error, sanitized_ytdlp_detail,
)
from .events import emit_backend_event, emit_event, ProgressAccumulator
from .version import VERSION
from .runtime import (
    deno, ffmpeg, ytdlp, runtime_temp_dir, run_captured, start_process, _unregister_process,
)

UA = f"Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/605.1 OpenMediaDownloader/{VERSION}"

def validate_referer(value):
    if value is None or value == "": return None
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise BackendError("Referer must be a valid HTTP(S) URL without credentials or control characters.")
    try:
        parsed = urlparse(value)
        host = parsed.hostname
        port = parsed.port
        if parsed.scheme.lower() not in ("http", "https") or not host or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        if any(char.isspace() for char in host) or any(char in host for char in "<>\"'\\"):
            raise ValueError()
        try: ipaddress.ip_address(host)
        except ValueError:
            if len(host) > 253 or not all(label and len(label) <= 63 and label[0] != "-" and label[-1] != "-" and all(c.isalnum() or c == "-" for c in label) for label in host.rstrip(".").split(".")): raise ValueError()
        if port is not None and not 1 <= port <= 65535: raise ValueError()
    except (ValueError, UnicodeError):
        raise BackendError("Referer must be a valid HTTP(S) URL without credentials or control characters.")
    return value

def origin_referer(source):
    try:
        parsed = urlparse(source)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname: return None
        host = parsed.hostname
        port = parsed.port
        netloc = f"[{host}]" if ":" in host else host
        if port is not None: netloc += f":{port}"
        return validate_referer(f"{parsed.scheme.lower()}://{netloc}/")
    except (ValueError, TypeError):
        return None

def get(url: str, headers=None) -> bytes:
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "ru,en;q=0.8", "Referer": "https://vimeo.com/"}
    if headers: h.update(headers)
    with urlopen(Request(url, headers=h), timeout=45) as r:
        return r.read()

def player_config(url: str) -> dict:
    raw = get(url).decode("utf-8", "replace")
    marker = re.search(r"window\.playerConfig\s*=", raw)
    if not marker:
        raise RuntimeError("На странице нет playerConfig: видео может быть закрытым или недоступным.")
    decoder = json.JSONDecoder()
    start = raw.find("{", marker.end())
    if start < 0: raise RuntimeError("Не найден JSON-конфиг Vimeo.")
    try: return decoder.raw_decode(raw[start:])[0]
    except json.JSONDecodeError as e: raise RuntimeError(f"Не удалось прочитать конфиг Vimeo: {e}")

def player_url(url: str) -> str:
    p = urlparse(url)
    if "player.vimeo.com" in p.netloc: return url
    parts = [part for part in p.path.split("/") if part]
    position = next((index for index, part in enumerate(parts) if part.isdigit()), None)
    if position is None: raise RuntimeError(f"Не распознан Vimeo URL: {url}")
    video_id = parts[position]
    # Unlisted Vimeo links also occur as /VIDEO_ID/HASH. The player expects
    # that path hash as ?h=HASH; losing it makes an otherwise valid link look
    # private or unavailable.
    query = parse_qsl(p.query, keep_blank_values=True)
    if not any(key == "h" for key, _ in query) and position + 1 < len(parts):
        candidate = parts[position + 1]
        if re.fullmatch(r"[A-Za-z0-9]+", candidate):
            query.append(("h", candidate))
    return urlunparse(("https", "player.vimeo.com", f"/video/{video_id}", "", urlencode(query), ""))

def discover_public_player_url(url: str) -> str:
    """Find Vimeo's public unlisted hash embedded in an ordinary page.

    Some old, still-public videos return 401 from ``player/video/ID`` even
    though their public Vimeo page contains the permitted ``?h=HASH`` player
    URL.  This is not an ID guess or an access bypass: the hash is read from
    the exact page supplied by the user, just as Vimeo's browser player does.
    """
    fallback = player_url(url)
    parsed = urlparse(url)
    if "player.vimeo.com" in parsed.netloc or any(key == "h" and value for key, value in parse_qsl(parsed.query)):
        return fallback
    video_id = Path(urlparse(fallback).path).name
    raw = html.unescape(get(url).decode("utf-8", "replace")).replace("\\/", "/")
    match = re.search(
        rf"https?://player\.vimeo\.com/video/{re.escape(video_id)}\?[^\"'<>\s]*\bh=([A-Za-z0-9]+)",
        raw,
    )
    if not match:
        return fallback
    return f"https://player.vimeo.com/video/{video_id}?h={match.group(1)}"

def resolved_player_config(url: str) -> tuple[str, dict]:
    """Open the normal player URL, then retry a hash published by the page."""
    primary = player_url(url)
    try:
        return primary, player_config(primary)
    except Exception as primary_error:
        try:
            discovered = discover_public_player_url(url)
        except Exception:
            raise primary_error
        if discovered == primary:
            raise primary_error
        return discovered, player_config(discovered)

def safe_name(name: str) -> str:
    name = unicodedata.normalize("NFKC", html.unescape(name or "Vimeo video"))
    name = re.sub(r"[/:\\\0\n\r\t]+", " - ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:180] or "Vimeo video")

def choose(items, quality: str):
    items = sorted(items, key=lambda x: (int(x.get("height") or 0), int(x.get("width") or 0)))
    if not items: raise RuntimeError("Vimeo не отдал доступных вариантов качества.")
    if quality in ("best", "auto"): return items[-1]
    try: wanted = int(re.sub(r"[^0-9]", "", quality))
    except ValueError: return items[-1]
    # Pick the closest available height.  If two options are equally close,
    # prefer the lower one so a requested limit is not exceeded unexpectedly.
    return min(items, key=lambda x: (
        abs(int(x.get("height") or 0) - wanted),
        int(x.get("height") or 0) > wanted,
        int(x.get("height") or 0),
    ))

def progressive(cfg):
    return ((cfg.get("request") or {}).get("files") or {}).get("progressive") or []

def hls_url(cfg):
    h = (((cfg.get("request") or {}).get("files") or {}).get("hls") or {})
    cdns = h.get("cdns") or {}
    if cdns:
        c = cdns.get(h.get("default_cdn")) or next(iter(cdns.values()))
        return c.get("avc_url") or c.get("url")
    return h.get("url")

def attrs(line):
    return {k: v.strip('"') for k,v in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line)}

def playlist(url, quality="best"):
    text = get(url).decode("utf-8", "replace")
    variants, audio = [], None
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:") and i + 1 < len(lines):
            a = attrs(line); res = a.get("RESOLUTION", "0x0").split("x")
            variants.append({"url": urljoin(url, lines[i+1]), "height": int(res[-1] or 0), "width": int(res[0] or 0), "bandwidth": int(a.get("BANDWIDTH", 0) or 0), "codecs": a.get("CODECS", "")})
        elif line.startswith("#EXT-X-MEDIA:") and 'TYPE=AUDIO' in line and 'URI=' in line:
            a = attrs(line); audio = urljoin(url, a.get("URI", ""))
    if variants: return choose(variants, quality), audio
    return {"url": url, "height": 0, "width": 0, "codecs": ""}, None

def media_segments(url):
    text = get(url).decode("utf-8", "replace"); init = None; segs = []
    for line in (x.strip() for x in text.splitlines()):
        if line.startswith("#EXT-X-MAP:"):
            a = attrs(line); init = urljoin(url, a.get("URI", ""))
        elif line and not line.startswith("#"): segs.append(urljoin(url, line))
    return init, segs

def download_one(url, path: Path, progress=False):
    runtime.check_cancelled()
    if path.exists() and path.stat().st_size: return
    if progress:
        emit_event("stage", stage="downloading")
    for attempt in range(5):
        try:
            runtime.check_cancelled()
            path.parent.mkdir(parents=True, exist_ok=True)
            with urlopen(Request(url, headers={"User-Agent": UA}), timeout=60) as r, path.open("wb") as f:
                total = int(r.headers.get("Content-Length", 0) or 0)
                done = 0
                last = -1
                started = time.monotonic()
                while True:
                    runtime.check_cancelled()
                    chunk = r.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        current = int(done * 100 / total) if total else int(done / (1024 * 1024))
                        if current != last:
                            speed = done / max(0.001, time.monotonic() - started)
                            emit_event("progress", downloadedBytes=done, totalBytes=total or None,
                                       progress=min(0.99, done / total) if total else None,
                                       speedBytesPerSecond=speed,
                                       etaSeconds=max(0, total - done) / speed if total and speed else None)
                            last = current
            return
        except Exception:
            if path.exists(): path.unlink()
            runtime.check_cancelled()
            if attempt == 4: raise
            time.sleep(1 + attempt)

def fetch_stream(media_url, out: Path, workers: int, manifest=None, progress_state=None):
    init, segs = manifest or media_segments(media_url); out.parent.mkdir(parents=True, exist_ok=True)
    if not segs: raise RuntimeError("HLS-плейлист не содержит кусочков видео.")
    state = progress_state if progress_state is not None else {"completed": 0, "total": len(segs), "bytes": 0, "started": time.monotonic()}
    with tempfile.TemporaryDirectory(prefix="vimeo-segments-", dir=str(runtime_temp_dir())) as td:
        d = Path(td)
        jobs = [(u, d / f"{i:06d}.bin") for i,u in enumerate(segs)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 16))) as ex:
            futs = [ex.submit(download_one, u, p) for u,p in jobs]
            last_report = 0.0
            for i, future in enumerate(concurrent.futures.as_completed(futs), 1):
                future.result()
                state["completed"] += 1
                now = time.monotonic()
                if i == len(jobs) or now - last_report >= 0.1:
                    current_bytes = sum(path.stat().st_size for _, path in jobs if path.exists())
                    downloaded = state["bytes"] + current_bytes
                    speed = downloaded / max(0.001, now - state["started"])
                    emit_event("progress", progress=min(0.99, state["completed"] / state["total"]),
                               fragmentIndex=state["completed"], fragmentCount=state["total"],
                               downloadedBytes=downloaded, speedBytesPerSecond=speed)
                    last_report = now
        with out.open("wb") as w:
            if init: w.write(get(init))
            for _,p in jobs: w.write(p.read_bytes())
        state["bytes"] += out.stat().st_size

def run_ffmpeg(arguments):
    emit_event("stage", stage="merging")
    command = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostats", *arguments]
    result = run_captured(command)
    if result.returncode:
        detail = (result.stderr or result.stdout or "неизвестная ошибка").strip()
        raise RuntimeError(f"ffmpeg не смог обработать файл: {detail[-2000:]}")

def download_hls(cfg, target: Path, quality: str, workers: int):
    master = hls_url(cfg)
    if not master: raise RuntimeError("В конфиге нет HLS-потока.")
    variant, audio = playlist(master, quality)
    # If audio is not declared on master, the selected variant is usually muxed.
    video_manifest = media_segments(variant["url"])
    audio_manifest = media_segments(audio) if audio else None
    state = {"completed": 0, "total": len(video_manifest[1]) + (len(audio_manifest[1]) if audio_manifest else 0), "bytes": 0, "started": time.monotonic()}
    emit_event("stage", stage="downloading")
    with tempfile.TemporaryDirectory(prefix="vimeo-", dir=str(runtime_temp_dir())) as td:
        d=Path(td); video=d/"video.bin"; fetch_stream(variant["url"], video, workers, video_manifest, state)
        if audio:
            aud=d/"audio.bin"; fetch_stream(audio, aud, workers, audio_manifest, state)
            run_ffmpeg(["-y", "-i", str(video), "-i", str(aud), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-movflags", "+faststart", str(target)])
        else:
            run_ffmpeg(["-y", "-i", str(video), "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", str(target)])

def rss_items(url):
    root=ET.fromstring(get(url)); ns={"media":"http://search.yahoo.com/mrss/"}; out=[]
    for item in root.findall(".//item"):
        title=(item.findtext("title") or "Vimeo video").strip(); link=item.findtext("link") or ""
        pl=item.find("media:player", ns); purl=pl.attrib.get("url") if pl is not None else link
        if purl: out.append((purl, title))
    if not out: raise RuntimeError("В RSS не найдено видео.")
    return out

def unique_target(folder: Path, stem: str, overwrite=False):
    p=folder/(safe_name(stem)+".mp4")
    if overwrite or not p.exists(): return p
    for i in range(1,10000):
        q=folder/(safe_name(stem)+f" ({i}).mp4")
        if not q.exists(): return q


def unique_media_target(folder: Path, stem: str, extension: str, overwrite=False):
    extension = "." + extension.lstrip(".")
    target = folder / (safe_name(stem) + extension)
    if overwrite or not target.exists():
        return target
    for index in range(1, 10000):
        candidate = folder / (safe_name(stem) + f" ({index})" + extension)
        if not candidate.exists():
            return candidate

def quality_label(item, requested):
    height = int(item.get("height") or 0)
    if height > 0:
        return f"{height}p"
    wanted = re.sub(r"[^0-9]", "", str(requested or ""))
    return f"{wanted}p" if wanted else "best"

def temporary_target(target: Path) -> Path:
    return runtime_temp_dir() / f"{target.stem}.{os.getpid()}.part{target.suffix}"

def mp3_bitrate(quality: str | None) -> str:
    value = str(quality or "").strip().lower()
    if value.endswith("k"):
        value = value[:-1]
    return f"{value}K" if value in {"320", "256", "192", "128"} else "320K"


def explicit_mode_suffix(args) -> str:
    """Distinguish explicit direct/chunks variants without renaming auto."""
    mode = str(getattr(args, "mode", "auto") or "auto").lower()
    return f"_{mode}" if mode in {"direct", "chunks"} else ""


def ytdlp_runtime_options(args, use_browser_cookies=True):
    """Validated yt-dlp options shared by downloads and live recordings."""
    tool = ytdlp()
    if not tool: raise RuntimeError("Резервный модуль yt-dlp отсутствует в приложении.")
    command = [tool, "--ignore-config", "--no-color", "--newline", "--no-remote-components", "--ffmpeg-location", ffmpeg()]
    referer = validate_referer(getattr(args, "referer", None))
    if referer: command += ["--referer", referer]

    runtime = deno()
    if runtime:
        command += ["--js-runtimes", f"deno:{runtime}"]
    cookies_browser = getattr(args, "cookies_browser", None)
    cookies_file = getattr(args, "cookies_file", None)
    try:
        auth_domains = tuple(dict.fromkeys(normalize_auth_domain(value) for value in (getattr(args, "auth_domain", None) or [])))
    except (TypeError, ValueError):
        raise BackendError("Некорректный домен авторизации.") from None
    if cookies_file and use_browser_cookies:
        command += ["--cookies", cookie_file_for_job(cookies_file, auth_domains)]
    elif cookies_browser and use_browser_cookies:
        command += ["--cookies-from-browser", cookies_browser]
    return command

def ytdlp_options(args, simulate=False, use_browser_cookies=True):
    command = ytdlp_runtime_options(args, use_browser_cookies=use_browser_cookies) + [
        "--concurrent-fragments", str(max(1, min(args.workers, 16))),
        "--paths", str(Path(args.output).expanduser()),
        "--paths", f"temp:{runtime_temp_dir()}",
    ]

    media = getattr(args, "media", "video")
    quality = str(args.quality or "best")
    mode_suffix = explicit_mode_suffix(args)
    if media == "aac":
        # Only select AAC. Remuxing m4a is stream-copy; unlike audio
        # extraction it never re-encodes the AAC payload.
        selector = "ba[acodec^=mp4a]/ba[ext=m4a]/ba[acodec*=aac]/ba[ext=mp4][protocol*=m3u8]"
        if args.mode == "direct":
            selector = (
                "ba[acodec^=mp4a][protocol=https]/ba[acodec^=mp4a][protocol=http]/"
                "ba[ext=m4a][protocol=https]/ba[ext=m4a][protocol=http]"
            )
        elif args.mode == "chunks":
            selector = (
                "ba[acodec^=mp4a][protocol*=m3u8]/"
                "ba[acodec^=mp4a][protocol*=dash]/"
                "ba[ext=mp4][protocol*=m3u8]/ba[ext=mp4][protocol*=dash]"
            )
        command += [
            "--output", f"%(title).180B_AAC{mode_suffix}.%(ext)s",
            "-f", selector,
            "--remux-video", "m4a",
        ]
    elif media == "mp3":
        bitrate = mp3_bitrate(quality)
        selector = "ba/b"
        if args.mode == "direct":
            selector = "ba[protocol=https]/ba[protocol=http]/b[protocol=https]/b[protocol=http]"
        elif args.mode == "chunks":
            selector = (
                "ba[protocol*=m3u8]/ba[protocol*=dash]/"
                "b[protocol*=m3u8]/b[protocol*=dash]"
            )
        command += [
            "--output", f"%(title).180B_MP3_{bitrate.lower()}{mode_suffix}.%(ext)s",
            "-f", selector,
            "--extract-audio", "--audio-format", "mp3", "--audio-quality", bitrate,
        ]
    else:
        command += [
            "--output", f"%(title).180B_%(height)sp{mode_suffix}.%(ext)s",
            "--merge-output-format", "mp4", "--remux-video", "mp4",
        ]
        if quality not in ("best", "auto", "list"):
            wanted = re.sub(r"[^0-9]", "", quality)
            if wanted:
                command += ["-S", f"res~{wanted},ext:mp4:m4a"]
        else:
            command += ["-S", "res,ext:mp4:m4a"]
        if args.mode == "direct":
            # Direct HTTP files, without an HLS/DASH fragment playlist. Modern
            # YouTube often no longer exposes a single progressive file, so a
            # direct video file and a direct audio file are merged by ffmpeg.
            command += [
                "-f",
                "bv*[protocol=https]+ba[protocol=https]/"
                "bv*[protocol=http]+ba[protocol=http]/"
                "b[protocol=https]/b[protocol=http]",
            ]
        elif args.mode == "chunks":
            # Require an actual manifest/fragment protocol. An unqualified
            # ``bv+ba`` silently selects ordinary HTTPS files on YouTube and
            # makes the explicit "chunks" switch indistinguishable from
            # "direct".
            command += ["-f", "bv[protocol*=m3u8]+ba[protocol*=m3u8]/bv[protocol*=dash]+ba[protocol*=dash]/b[protocol*=m3u8]/b[protocol*=dash]"]
    if simulate: command += ["--simulate", "--no-warnings"]
    return command

def _preflight_entries(result, url, args):
    entries = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0].strip():
            target = Path(parts[0].strip())
            # %(filename)s is evaluated before post-processing. Normalize it
            # to the real final extension so duplicate checks and GUI labels
            # refer to the M4A/MP3/MP4 that will actually remain on disk.
            media = getattr(args, "media", "video")
            target = target.with_suffix({"aac": ".m4a", "mp3": ".mp3"}.get(media, ".mp4"))
            entries.append((target, parts[1].strip() or url, parts[2].strip()))
    return entries


def _ytdlp_failure(detail: str, *, warnings=None):
    if is_authentication_required_error(detail):
        raise authentication_required_error(detail, warnings=warnings)
    safe_detail = sanitized_ytdlp_detail(detail)
    raise YTDLPError(
        f"yt-dlp не смог открыть ссылку: {safe_detail}",
        raw_detail=detail,
        warnings=warnings,
    )


def ytdlp_preflight(url, args, announce=True):
    if announce:
        print("Проверяю YouTube/Vimeo и получаю список файлов…", flush=True)
    tail = [
        # A playlist can legitimately contain removed/private entries between
        # working videos. Skip only those entries instead of rejecting the
        # whole list, and retain each video's own URL for its own process.
        "--ignore-errors", "--print", "%(filename)s\t%(webpage_url)s\t%(title)s", url,
    ]
    browser = getattr(args, "cookies_browser", None) or ("file" if getattr(args, "cookies_file", None) else None)
    try:
        result = run_captured(ytdlp_options(args, simulate=True) + tail, timeout=600)
        raw_detail = "\n".join(part for part in (result.stderr, result.stdout) if part).strip()
    except InvalidCookieFileError:
        result = None
        raw_detail = ""
    warnings = []
    used_cookie_fallback = False

    # macOS can deny access to Safari's protected cookie database before
    # yt-dlp even looks at the URL. Public media must still work, therefore
    # retry exactly this access failure without cookies. Other failures are
    # never retried silently.
    if browser and (result is None or is_cookie_access_error(raw_detail)):
        warning = cookie_access_warning(browser)
        warnings.append(warning)
        used_cookie_fallback = True
        if announce:
            emit_backend_event(warning)
        result = run_captured(ytdlp_options(args, simulate=True, use_browser_cookies=False) + tail, timeout=600)
        raw_detail = "\n".join(part for part in (result.stderr, result.stdout) if part).strip()

    entries = _preflight_entries(result, url, args)
    if not entries:
        detail = raw_detail or "yt-dlp не нашёл видео по этой ссылке"
        if announce and is_authentication_required_error(detail):
            emit_backend_event({"code": AUTHENTICATION_REQUIRED_CODE})
        _ytdlp_failure(detail, warnings=warnings)
    if result.returncode and announce:
        print("В плейлисте есть недоступные элементы — они пропущены.", flush=True)
    return PreflightEntries(
        entries,
        warnings=warnings,
        used_cookie_fallback=used_cookie_fallback,
    )

def cleanup_ytdlp_partials(target: Path) -> None:
    """Remove this process' matching yt-dlp staging files only.

    ``--paths temp:...`` places fragments in a private, per-backend-process
    runtime directory. Never glob beside the final target: two parallel jobs
    may legitimately use the same title/stem in the user's output directory.
    """
    temp_root = runtime.current_temp_dir()
    if temp_root is None or not temp_root.exists():
        return
    prefix = target.stem + "."
    for candidate in temp_root.rglob("*"):
        name = candidate.name.lower()
        if not candidate.name.startswith(prefix):
            continue
        is_temporary = ".part" in name or name.endswith(".ytdl") or name.endswith(".temp")
        if is_temporary and candidate.is_file():
            try:
                candidate.unlink()
            except OSError:
                pass

def _is_http_access_failure(detail: str) -> bool:
    # Frühere Warnungen dürfen einen späteren Formatfehler nicht umdeuten.
    lines = str(detail).splitlines()
    errors = [line for line in lines if "ERROR:" in line.upper()]
    final = errors[-1] if errors else (lines[-1] if lines else "")
    return bool(re.search(r"\bHTTP(?:/\d(?:\.\d)?)?(?:\s+Error)?\s*:?\s*(?:401|403)\b", final, re.I))


def _run_ytdlp_download_attempt(url, target: Path, args, force_overwrite=False, *, use_browser_cookies=True, defer_access_errors=False):
    # Jeder Versuch erhält neue Fragmente, auch wenn sich Formate ändern.
    with tempfile.TemporaryDirectory(prefix="yt-attempt-", dir=runtime_temp_dir()) as staging:
        return _run_ytdlp_in_directory(url, target, args, force_overwrite, use_browser_cookies=use_browser_cookies, defer_access_errors=defer_access_errors, staging=staging)


def _run_ytdlp_in_directory(url, target: Path, args, force_overwrite=False, *, use_browser_cookies, defer_access_errors, staging):
    metadata = '{"filesize":%(filesize|0)j,"filesizeApprox":%(filesize_approx|0)j,"formats":%(requested_formats.:.{filesize,filesize_approx}|[])j}'
    command = ytdlp_options(args, use_browser_cookies=use_browser_cookies) + [
        "--paths", f"home:{target.parent}",
        "--paths", f"temp:{staging}",
        # Dateinamen erst nach der Pfad-Expansion als Daten einsetzen.
        "--parse-metadata", "title:%(omd_output_stem)s",
        "--replace-in-metadata", "omd_output_stem", "(?s)^.*$", target.stem.replace("\\", "\\\\"),
        "--output", "%(omd_output_stem)s.%(ext)s",
        "--no-playlist", "--no-simulate", "--progress",
        "--progress-template", "download:OMD_PROGRESS:%(progress)j",
        "--progress-template", "postprocess:OMD_POSTPROCESS:%(progress)j",
        "--print", "before_dl:OMD_METADATA:" + metadata,
        "--print", "after_move:OMD_FILE:%(filepath)j",
    ]
    if getattr(args, "_confirmed_format", None):
        command += ["-f", args._confirmed_format]
    command += ["--force-overwrites" if force_overwrite else "--no-overwrites", url]
    process_handle = start_process(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    accumulator = ProgressAccumulator()
    diagnostics = []
    final_target = target
    started = False
    try:
        assert process_handle.stdout is not None
        for raw in process_handle.stdout:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("OMD_"):
                kind, _, value = line.partition(":")
                try:
                    data = json.loads(value)
                except (ValueError, TypeError):
                    continue
                if kind == "OMD_METADATA" and isinstance(data, dict):
                    accumulator.set_metadata(data)
                elif kind == "OMD_PROGRESS" and isinstance(data, dict):
                    if not started:
                        emit_event("stage", stage="downloading")
                        started = True
                    emit_event("progress", **accumulator.update(data))
                elif kind == "OMD_POSTPROCESS":
                    emit_event("stage", stage="merging")
                elif kind == "OMD_FILE" and isinstance(data, str):
                    reported = Path(data)
                    if reported.parent.resolve() == target.parent.resolve():
                        final_target = reported
                continue
            diagnostics.append(line)
            diagnostics = diagnostics[-100:]
            if any(marker in line for marker in ("[Merger]", "[ExtractAudio]", "[VideoRemuxer]", "[Fixup")):
                emit_event("stage", stage="merging")
            elif ("ERROR:" in line or "WARNING:" in line) and not is_cookie_access_error(line) and not (defer_access_errors and _is_http_access_failure(line)):
                print(sanitized_ytdlp_detail(line), flush=True)
        code = process_handle.wait()
    except BaseException:
        cleanup_ytdlp_partials(target)
        raise
    finally:
        _unregister_process(process_handle)
    if code:
        cleanup_ytdlp_partials(target)
        detail = "\n".join(diagnostics) or f"yt-dlp завершился с кодом {code}"
        raise YTDLPError(
            f"yt-dlp завершился с кодом {code}: {sanitized_ytdlp_detail(detail)}",
            raw_detail=detail,
        )
    if not final_target.is_file() or final_target.stat().st_size == 0:
        raise RuntimeError("yt-dlp завершился без итогового файла.")
    emit_event("completed", path=str(final_target), downloadedBytes=final_target.stat().st_size)

def run_ytdlp_download(url, target: Path, args, force_overwrite=False, *, allow_public_retry=False):
    """Download once with cookies and retry only a cookie permission failure."""
    browser = getattr(args, "cookies_browser", None) or ("file" if getattr(args, "cookies_file", None) else None)
    try:
        return _run_ytdlp_download_attempt(
            url,
            target,
            args,
            force_overwrite,
            use_browser_cookies=True,
            defer_access_errors=bool(browser and allow_public_retry),
        )
    except (YTDLPError, InvalidCookieFileError) as error:
        if browser and (isinstance(error, InvalidCookieFileError) or is_cookie_access_error(error.raw_detail)):
            warning = cookie_access_warning(browser)
            emit_backend_event(warning)
            try:
                return _run_ytdlp_download_attempt(
                    url,
                    target,
                    args,
                    force_overwrite,
                    use_browser_cookies=False,
                )
            except YTDLPError as fallback_error:
                fallback_error.anonymous_attempted = True
                if is_authentication_required_error(fallback_error.raw_detail):
                    emit_backend_event({"code": AUTHENTICATION_REQUIRED_CODE})
                    raise authentication_required_error(
                        fallback_error.raw_detail,
                        warnings=[warning],
                    ) from fallback_error
                fallback_error.warnings = [warning]
                raise
        if browser and allow_public_retry and isinstance(error, YTDLPError) and _is_http_access_failure(error.raw_detail):
            # Erst der Dispatcher prüft die öffentliche Alternative.
            raise
        if is_authentication_required_error(error.raw_detail):
            emit_backend_event({"code": AUTHENTICATION_REQUIRED_CODE})
            raise authentication_required_error(error.raw_detail) from error
        raise


def _public_retry_entry(url, args):
    """Nur ein öffentliches Einzelvideo im unveränderten Wunschformat zulassen."""
    anonymous = args_without_browser_cookies(args)
    template = '{"filename":%(filename)j,"url":%(webpage_url)j,"title":%(title)j,"availability":%(availability|unknown)j,"formatId":%(format_id)j}'
    command = ytdlp_options(anonymous, simulate=True) + ["--no-playlist", "--skip-download", "--socket-timeout", "20", "--print", template, url]
    runtime.check_cancelled()
    result = run_captured(command, timeout=90)
    runtime.check_cancelled()
    try:
        value = json.loads(result.stdout)
    except (ValueError, TypeError):
        value = None
    availability = value.get("availability") if isinstance(value, dict) else None
    if availability in ("private", "needs_auth", "subscriber_only", "premium_only") or is_authentication_required_error(result.stderr or ""):
        raise authentication_required_error("Authentication required")
    if result.returncode or availability not in ("public", "unlisted"):
        return None
    if not all(isinstance(value.get(key), str) and value[key] for key in ("filename", "url", "formatId")):
        return None
    target = Path(value["filename"]).with_suffix({"aac": ".m4a", "mp3": ".mp3"}.get(getattr(args, "media", "video"), ".mp4"))
    if target.parent.resolve() != Path(args.output).expanduser().resolve():
        return None
    anonymous._confirmed_format = value["formatId"]
    return target, value["url"], anonymous


def _download_prepared_entry(target, url, args, *, allow_public_retry):
    runtime.check_cancelled()
    with runtime.target_lock(target):
        runtime.check_cancelled()
        emit_event("file", path=str(target))
        overwrite = bool(args.overwrite)
        if target.exists() and args.ask_overwrite and not overwrite:
            emit_event("overwrite", path=str(target))
            try: answer = input().strip().lower()
            except EOFError: answer = "n"
            runtime.check_cancelled()
            if answer not in ("y", "yes", "д", "да"):
                emit_event("skipped", path=str(target))
                return
            overwrite = True
        elif target.exists() and not overwrite:
            emit_event("skipped", path=str(target))
            return
        run_ytdlp_download(url, target, args, force_overwrite=overwrite, allow_public_retry=allow_public_retry)


def process_ytdlp(url, args):
    entries = ytdlp_preflight(url, args)
    if getattr(args, "check", False):
        names = ", ".join(title for _, _, title in entries[:3])
        suffix = "…" if len(entries) > 3 else ""
        print(f"Проверка OK: файлов {len(entries)} — {names}{suffix}", flush=True)
        return
    if args.quality == "list":
        print("Для списка/плейлиста варианты качества будут выбраны отдельно для каждого ролика.")
        return
    # When preflight proved that a public URL works only without inaccessible
    # browser cookies, do not repeat the same denied cookie read for download.
    download_args = args_without_browser_cookies(args) if getattr(entries, "used_cookie_fallback", False) else args
    for target, item_url, _title in entries:
        try:
            _download_prepared_entry(target, item_url, download_args, allow_public_retry=True)
        except YTDLPError as error:
            cookies = getattr(download_args, "cookies_browser", None) or getattr(download_args, "cookies_file", None)
            if not cookies or getattr(error, "anonymous_attempted", False) or not _is_http_access_failure(error.raw_detail):
                raise
            runtime.check_cancelled()
            try:
                retry = _public_retry_entry(item_url, download_args)
            except (InterruptedError, AuthenticationRequiredError):
                raise
            except Exception:
                raise error
            if retry is None:
                raise error
            runtime.check_cancelled()
            new_target, public_url, anonymous = retry
            emit_event("stage", stage="preparing", code="publicAccessFallback", fallback="withoutCookies")
            # Der erste Lock ist frei. Neues Ziel braucht eine eigene Entscheidung.
            _download_prepared_entry(new_target, public_url, anonymous, allow_public_retry=False)


def process_vimeo_audio_native(url, args, forced_title=None):
    """Fallback for Vimeo pages that expose MP4 but hide audio-only formats.

    It downloads the smallest progressive rendition and then either copies its
    AAC stream bit-for-bit into M4A or explicitly encodes MP3.  This fallback
    is used only when the much more efficient yt-dlp audio-only route fails.
    """
    _resolved_url, cfg = resolved_player_config(url)
    title = forced_title or ((cfg.get("video") or {}).get("title") or "Vimeo video")
    streams = progressive(cfg)
    if not streams:
        raise RuntimeError("Vimeo не отдал прямой MP4, из которого можно извлечь звук.")
    if getattr(args, "check", False):
        print(f"Проверка OK: {title} (звук из прямого MP4)", flush=True)
        return

    media = getattr(args, "media", "aac")
    if media == "aac":
        suffix, extension = "AAC", "m4a"
    else:
        suffix, extension = f"MP3_{mp3_bitrate(args.quality).lower()}", "mp3"
    folder = Path(args.output).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{title}_{suffix}{explicit_mode_suffix(args)}"
    if args.ask_overwrite and not args.overwrite:
        target = folder / (safe_name(stem) + "." + extension)
    else:
        target = unique_media_target(folder, stem, extension, args.overwrite)
    with runtime.target_lock(target):
        emit_event("file", path=str(target))
        if target.exists() and not args.overwrite:
            if args.ask_overwrite:
                emit_event("overwrite", path=str(target))
                try:
                    answer = input().strip().lower()
                except EOFError:
                    answer = "n"
                if answer not in ("y", "yes", "д", "да"):
                    emit_event("skipped", path=str(target))
                    return
            else:
                emit_event("skipped", path=str(target))
                return

        # Audio is normally identical between renditions, so the smallest direct
        # file saves bandwidth while retaining the original AAC stream.
        selected = min(streams, key=lambda item: int(item.get("height") or 0))
        staging = temporary_target(target)
        if staging.exists():
            staging.unlink()
        with tempfile.TemporaryDirectory(prefix="vimeo-audio-", dir=str(runtime_temp_dir())) as directory:
            source = Path(directory) / "source.mp4"
            try:
                print(f"Извлекаю звук напрямую: {title}", flush=True)
                download_one(selected["url"], source, progress=True)
                if media == "aac":
                    run_ffmpeg(["-y", "-i", str(source), "-vn", "-map", "0:a:0", "-c:a", "copy", "-movflags", "+faststart", str(staging)])
                else:
                    run_ffmpeg(["-y", "-i", str(source), "-vn", "-map", "0:a:0", "-c:a", "libmp3lame", "-b:a", mp3_bitrate(args.quality), str(staging)])
                if not staging.exists() or staging.stat().st_size == 0:
                    raise RuntimeError("Обработка звука завершилась без итогового файла.")
                runtime.publish_file(staging, target)
            finally:
                if staging.exists():
                    staging.unlink()
        emit_event("completed", path=str(target), downloadedBytes=target.stat().st_size)

def process_with_fallback(url, args, forced_title=None):
    if validate_referer(getattr(args, "referer", None)):
        return process_ytdlp(url, args)
    # Non-Vimeo links (most importantly YouTube) go straight to the bundled
    # general extractor instead of first producing a misleading Vimeo error.
    host = urlparse(url).netloc.lower()
    if getattr(args, "media", "video") != "video":
        # Vimeo's public web page extractor may ask for login even when the
        # embeddable player is public. The equivalent player URL exposes the
        # same permitted formats and also preserves unlisted-link hashes.
        if "vimeo.com" not in host:
            return process_ytdlp(url, args)
        try:
            media_url, _cfg = resolved_player_config(url)
        except Exception:
            try:
                media_url = discover_public_player_url(url)
            except Exception:
                media_url = player_url(url)
        try:
            return process_ytdlp(media_url, args)
        except Exception as audio_error:
            if args.mode == "chunks":
                raise
            print(f"Аудиопоток Vimeo недоступен ({sanitized_ytdlp_detail(str(audio_error))}). Пробую прямой MP4…", flush=True)
            try:
                return process_vimeo_audio_native(url, args, forced_title)
            except Exception as native_error:
                if isinstance(audio_error, BackendError):
                    raise audio_error
                raise RuntimeError(f"аудиопоток: {audio_error}; прямой MP4: {native_error}") from native_error
    if "vimeo.com" not in host:
        return process_ytdlp(url, args)
    try:
        return process(url, args, forced_title)
    except Exception as primary_error:
        if not ytdlp(): raise
        print(f"Основной способ недоступен ({sanitized_ytdlp_detail(str(primary_error))}). Пробую резервный модуль…", flush=True)
        try:
            try:
                fallback_url = discover_public_player_url(url)
            except Exception:
                fallback_url = url
            return process_ytdlp(fallback_url, args)
        except Exception as fallback_error:
            if isinstance(fallback_error, BackendError):
                raise
            raise RuntimeError(f"основной способ: {primary_error}; резервный способ: {fallback_error}") from fallback_error

def process(url, args, forced_title=None):
    pu,cfg=resolved_player_config(url); title=forced_title or ((cfg.get("video") or {}).get("title") or "Vimeo video")
    ps=progressive(cfg)
    if getattr(args, "check", False):
        print(f"Проверка OK: {title}", flush=True)
        return
    if args.quality == "list":
        vals=[f"{x.get('quality','?')} ({x.get('height','?')}p)" for x in ps]
        print(title+": "+(", ".join(vals) if vals else "прямого MP4 нет, будет HLS-режим")); return
    if args.mode == "direct" and not ps:
        raise RuntimeError("Vimeo не отдал прямой MP4. Выберите режим auto или chunks.")
    selected = None
    if args.mode != "chunks" and ps:
        selected = choose(ps,args.quality)
        print(f"Скачиваю напрямую: {title} [{selected.get('quality', selected.get('height','?'))}]")
    elif args.mode == "chunks" or not ps:
        master = hls_url(cfg)
        if not master: raise RuntimeError("В конфиге нет HLS-потока.")
        selected, _ = playlist(master, args.quality)
        print(f"Скачиваю кусочками: {title} [{quality_label(selected, args.quality)}]")
    label = quality_label(selected or {}, args.quality)
    named_title = f"{title}_{label}{explicit_mode_suffix(args)}"
    folder = Path(args.output).expanduser()
    if args.ask_overwrite and not args.overwrite:
        target = folder / (safe_name(named_title) + ".mp4")
    else:
        target = unique_target(folder, named_title, args.overwrite)
    target.parent.mkdir(parents=True, exist_ok=True)
    with runtime.target_lock(target):
        emit_event("file", path=str(target))
        if target.exists() and not args.overwrite and not args.ask_overwrite:
            emit_event("skipped", path=str(target))
            return
        if args.ask_overwrite and target.exists() and not args.overwrite:
            emit_event("overwrite", path=str(target))
            try:
                answer = input().strip().lower()
            except EOFError:
                answer = "n"
            if answer not in ("y", "yes", "д", "да"):
                emit_event("skipped", path=str(target))
                return
        # Download to a process-specific staging file. Existing files are only
        # replaced after a complete successful transfer, and interrupted runs
        # cannot masquerade as finished MP4 files.
        staging = temporary_target(target)
        if staging.exists(): staging.unlink()
        try:
            if args.mode != "chunks" and ps:
                download_one(selected["url"], staging, progress=True)
            else:
                download_hls(cfg,staging,args.quality,args.workers)
            if not staging.exists() or staging.stat().st_size == 0:
                raise RuntimeError("Скачивание завершилось без данных; итоговый файл не создан.")
            runtime.publish_file(staging, target)
        finally:
            if staging.exists(): staging.unlink()
        emit_event("completed", path=str(target), downloadedBytes=target.stat().st_size)
