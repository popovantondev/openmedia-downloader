"""Cookies einmal vorbereiten; Downloads lesen nur private Kopien."""
from __future__ import annotations

import contextlib
import http.cookiejar
import ipaddress
import io
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from . import runtime
from .errors import BackendError, is_cookie_access_error

_MEDIA_DOMAINS = ("youtube.com", "google.com", "googlevideo.com", "youtube-nocookie.com", "vimeo.com")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
AUTHENTICATION_TIMEOUT_SECONDS = 90


class InvalidCookieFileError(BackendError):
    code = "invalidCookieFile"


def _load_cookies(path: Path):
    """MozillaCookieJar versteht das Netscape-Format samt HttpOnly-Zeilen."""
    try:
        if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("invalid file")
        jar = http.cookiejar.MozillaCookieJar(str(path))
        # Der Parser kann eine ungültige Zeile samt Cookie-Wert ausgeben.
        with contextlib.redirect_stderr(io.StringIO()):
            jar.load(ignore_discard=True, ignore_expires=True)
        # Browser-Exporte nutzen 0 häufig für Cookies bis zum Sitzungsende.
        for cookie in jar:
            if cookie.expires == 0:
                cookie.expires = None
                cookie.discard = True
        return jar
    except (OSError, ValueError, http.cookiejar.LoadError):
        raise InvalidCookieFileError("Не удалось прочитать cookies.txt. Нужен файл cookies в формате Netscape.") from None


def _is_media_cookie(cookie) -> bool:
    return _domain_matches(cookie.domain, _MEDIA_DOMAINS)


def normalize_auth_domain(value: str) -> str:
    """Validate a user-approved DNS hostname and return its IDNA ASCII form."""
    if not isinstance(value, str) or not value or any(c in value for c in "/:@*?#\\"):
        raise ValueError("Некорректный домен авторизации.")
    host = value[:-1] if value.endswith(".") else value
    try:
        host = host.encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        raise ValueError("Некорректный домен авторизации.") from None
    if len(host) > 253 or not host or any(not _DNS_LABEL.fullmatch(label) for label in host.split(".")):
        raise ValueError("Некорректный домен авторизации.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise ValueError("Некорректный домен авторизации.")


def _domain_matches(cookie_domain: str, domains) -> bool:
    domain = cookie_domain.lstrip(".").rstrip(".").lower()
    return any(domain == allowed or domain.endswith("." + allowed) for allowed in domains)


def _write_private_snapshot(jar, destination: Path, auth_domains=()) -> int:
    selected = http.cookiejar.MozillaCookieJar(str(destination))
    now = time.time()
    for cookie in jar:
        if (_is_media_cookie(cookie) or _domain_matches(cookie.domain, auth_domains)) and not cookie.is_expired(now):
            selected.set_cookie(cookie)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    selected.save(ignore_discard=True, ignore_expires=False)
    os.chmod(destination, 0o600)
    return len(selected)


def cookie_file_for_job(source: str, auth_domains=()) -> str:
    """Give each download process a private cookie snapshot."""
    try:
        auth_domains = tuple(dict.fromkeys(normalize_auth_domain(value) for value in auth_domains))
    except (TypeError, ValueError):
        raise ValueError("Некорректный домен авторизации.") from None
    source_path = Path(source).expanduser().resolve()
    jar = _load_cookies(source_path)
    destination = runtime.runtime_temp_dir() / f"cookies-{os.getpid()}-{uuid.uuid4().hex}.txt"
    _write_private_snapshot(jar, destination, auth_domains)
    return str(destination)


def _session_directory(parent: str) -> Path:
    path = Path(parent).expanduser()
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Для сессии нужна отдельная локальная папка.")
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)
    if not path.is_dir() or path.stat().st_uid != os.getuid():
        raise ValueError("Папка сессии недоступна.")
    # Права существующей пользовательской папки не меняем.
    return Path(tempfile.mkdtemp(prefix="omd-auth-", dir=str(path)))


def _cookie_decryption_failed(detail: str, browser: str) -> bool:
    """Nur bekannte Cookie-/Keychain-Meldungen erkennen, keine allgemeinen Warnungen."""
    warning = re.compile(
        r"^\s*WARNING:\s*(?:\[Cookies\]\s*)?(?:"
        r"find-generic-password failed\b|"
        r"exception running find-generic-password:|"
        r"cannot decrypt v(?:10|11) cookies:\s*no key found\b|"
        r"failed to decrypt cookie \(AES-(?:CBC|GCM)\))",
        re.I | re.M,
    )
    # yt-dlp kann trotz fehlender verschlüsselter Cookies mit Exit 0 enden.
    incomplete = re.compile(
        rf"^\s*(?:\[Cookies\]\s*)?Extracted\s+\d+\s+cookies from {re.escape(browser)}"
        r"\s+\([1-9]\d*\s+could not be decrypted\)\s*$",
        re.I | re.M,
    )
    return bool(warning.search(detail) or incomplete.search(detail))


def _export_browser(browser: str, destination: Path, auth_url: str | None) -> None:
    tool = runtime.ytdlp()
    if not tool:
        raise RuntimeError("В приложении отсутствует yt-dlp.")
    url = auth_url or "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    if urlparse(url).scheme not in ("https", "http"):
        raise ValueError("Для проверки авторизации нужна веб-ссылка.")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write("# Netscape HTTP Cookie File\n")
    command = [
        tool, "--ignore-config", "--no-remote-components", "--no-color",
        "--skip-download", "--no-playlist", "--ignore-errors", "--socket-timeout", "20",
        "--cookies-from-browser", browser, "--cookies", str(destination),
    ]
    if runtime.deno():
        command.extend(["--js-runtimes", "deno:" + runtime.deno()])
    result = runtime.run_captured(command + [url], timeout=AUTHENTICATION_TIMEOUT_SECONDS)
    detail = (result.stderr or "") + "\n" + (result.stdout or "")
    # Warnungen bleiben im Speicher. Rohtext und Cookie-Werte nie ausgeben.
    if is_cookie_access_error(detail) or _cookie_decryption_failed(detail, browser):
        raise PermissionError("Браузер не разрешил прочитать cookies.")
    if not destination.exists():
        raise RuntimeError("Браузер не предоставил cookies. Войдите в аккаунт в браузере или выберите cookies.txt.")
    if result.returncode and not list(_load_cookies(destination)):
        raise RuntimeError("Не удалось получить cookies из браузера. Публичные видео можно скачать без входа.")


def prepare_authentication(args) -> dict:
    try:
        auth_domains = tuple(normalize_auth_domain(value) for value in (getattr(args, "auth_domain", None) or []))
    except ValueError:
        return {"ok": False, "status": "error", "message": "Некорректный домен авторизации."}
    source = getattr(args, "cookies_file", None)
    browser = getattr(args, "cookies_browser", None)
    if not source and not browser:
        return {"ok": True, "status": "anonymous"}
    directory = None
    keep_snapshot = False
    try:
        if not args.session_dir:
            raise ValueError("Не указана папка сессии.")
        directory = _session_directory(args.session_dir)
        if browser:
            raw_export = directory / "browser-export.txt"
            _export_browser(browser, raw_export, getattr(args, "auth_url", None))
            os.chmod(raw_export, 0o600)
            jar = _load_cookies(raw_export)
        else:
            jar = _load_cookies(Path(source).expanduser())
        target = directory / "cookies.txt"
        count = _write_private_snapshot(jar, target, auth_domains)
        for candidate in directory.iterdir():
            if candidate != target and candidate.is_file():
                candidate.unlink()
        if not count:
            return {"ok": True, "status": "anonymous", "message": "Подходящие действующие cookies не найдены. Публичные видео доступны без входа."}
        keep_snapshot = True
        return {
            "ok": True, "status": "ready", "cookieFile": str(target),
            "loginVerified": False,
            "message": "Cookies подготовлены. Доступ к закрытым видео зависит от аккаунта и проверяется отдельно.",
        }
    except PermissionError:
        return {"ok": False, "status": "browserCookieAccessDenied", "message": "macOS не разрешила прочитать cookies браузера. Выберите другой браузер, cookies.txt или продолжите без входа."}
    except InvalidCookieFileError as error:
        return {"ok": False, "status": "invalidCookieFile", "message": str(error)}
    except TimeoutError:
        return {"ok": False, "status": "authenticationTimedOut", "message": "Проверка cookies не завершилась за 90 секунд. Повторите попытку, выберите другой браузер или продолжите без входа."}
    except (OSError, ValueError, RuntimeError):
        return {"ok": False, "status": "error", "message": "Не удалось подготовить авторизацию. Проверьте браузер или выбранный cookies.txt; публичные видео можно скачать без входа."}
    finally:
        # Готовую сессию удаляет приложение при закрытии, не этот процесс.
        if directory is not None and not keep_snapshot:
            shutil.rmtree(directory, ignore_errors=True)
