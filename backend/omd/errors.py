"""Fehlercodes und sichere Meldungen für die Oberfläche."""
from __future__ import annotations

import copy
import json
import re

COOKIE_ACCESS_WARNING_CODE = "browserCookieAccessDenied"
AUTHENTICATION_REQUIRED_CODE = "authenticationRequired"


class BackendError(RuntimeError):
    """User-facing failure with a stable code for the native application."""

    code = "backendError"

    def __init__(self, message: str, *, warnings=None):
        super().__init__(message)
        self.warnings = list(warnings or [])


class AuthenticationRequiredError(BackendError):
    """The media exists, but an authenticated browser session is required."""

    code = AUTHENTICATION_REQUIRED_CODE


class YTDLPError(BackendError):
    """Internal yt-dlp failure retaining raw text only for classification."""

    code = "extractorError"

    def __init__(self, message: str, *, raw_detail: str = "", warnings=None):
        super().__init__(message, warnings=warnings)
        self.raw_detail = raw_detail


class PreflightEntries(list):
    """A backwards-compatible list with metadata about a cookie fallback."""

    def __init__(self, values=(), *, warnings=None, used_cookie_fallback=False):
        super().__init__(values)
        self.warnings = list(warnings or [])
        self.used_cookie_fallback = bool(used_cookie_fallback)


def cookie_access_warning(browser: str | None) -> dict:
    return {
        "code": COOKIE_ACCESS_WARNING_CODE,
        "browser": str(browser or "unknown"),
        "fallback": "withoutCookies",
    }


def is_cookie_access_error(detail: str) -> bool:
    """Return true only when the browser cookie *store* cannot be read.

    yt-dlp also mentions cookies in ordinary extractor errors (for example,
    ``Use --cookies-from-browser``). Treating those messages as a local file
    access failure would hide the real error behind an anonymous retry. Keep
    the check line-local and require both cookie-store context and a concrete
    file/database failure.
    """
    cookie_store = re.compile(
        r"(?:cookies\.binarycookies|cookies\.sqlite|"
        r"(?:cookie|cookies)\s+(?:database|db)|"
        r"(?:safari|chrome|chromium|opera|firefox|edge|brave)\s+cookies?|"
        r"extract(?:ing)?\s+cookies\s+from|"
        r"[/\\]cookies(?:[\s'\".:),;\]}]|$))",
        re.I,
    )
    access_failure = re.compile(
        r"(?:operation not permitted|permission denied|\berrno\s*(?:1|2|13)\b|"
        r"\beacces\b|\benoent\b|no such file(?: or directory)?|"
        r"file not found|does not exist|database (?:is )?locked|locked database|"
        r"unable to open database|cannot open database|could not open database|"
        r"(?:failed|unable|cannot|can't|could not)\s+to\s+"
        r"(?:access|copy|read|open|find|load|decrypt)|"
        r"(?:failed|unable|cannot|can't|could not)\s+"
        r"(?:access|copy|read|open|find|load|decrypt))",
        re.I,
    )
    return any(
        cookie_store.search(line) and access_failure.search(line)
        for line in str(detail or "").splitlines()
    )


def is_authentication_required_error(detail: str) -> bool:
    lowered = re.sub(r"\s+", " ", str(detail or "").lower())
    markers = (
        "sign in to confirm your age",
        "sign in to confirm you're not a bot",
        "sign in to confirm you’re not a bot",
        "sign in to confirm",
        "login required",
        "log in to view",
        "log in to watch",
        "authentication required",
        "requires authentication",
        "age-restricted",
        "age restricted",
        "private video",
        "this video is private",
        "members-only",
        "members only",
        "only available to registered users",
        "available to this channel's members",
        "available to this channel’s members",
        "join this channel to get access",
        "try signing in",
        "use --cookies-from-browser",
        "use --cookies",
        "401: unauthorized",
        "http error 401",
    )
    return any(marker in lowered for marker in markers)


def sanitized_ytdlp_detail(detail: str, limit: int = 1800) -> str:
    """Remove browser-cookie paths while keeping useful extractor context."""
    value = str(detail or "").strip()
    # Browser profiles commonly contain spaces (``Application Support``), so
    # a whitespace-delimited path expression is not sufficient here. Match
    # through the known database basename and then redact any remaining home
    # prefix as a second privacy boundary.
    value = re.sub(
        r"(?i)(?:'|\")?(?:~|/(?:Users|home)/[^/\r\n'\"]+|/(?:private|Library|Volumes))"
        r"[^\r\n'\"]*?/(?:Cookies\.binarycookies|cookies\.sqlite|Cookies)"
        r"(?=(?:'|\"|$|[\s:;,)\]}]))(?:'|\")?",
        "<cookie database>",
        value,
    )
    value = re.sub(r"(?i)/(?:Users|home)/[^/\s'\",:;]+", "<user home>", value)
    # Sitzungswerte aus HTTP-Meldungen gehören nicht in die Diagnose.
    value = re.sub(r"(?im)\b(?:cookie|set-cookie|authorization)\s*:[^\r\n]*", "<private header>", value)
    value = re.sub(r"(?i)([?&](?:token|access_token|auth|sig|signature|key|jwt|policy|h)=)[^&\s'\"<>]+", r"\1<private>", value)
    return value[-limit:] if value else "неизвестная ошибка yt-dlp"


def classify_error(error: Exception | str) -> str:
    if isinstance(error, BackendError) and error.code not in ("backendError", "extractorError"):
        return error.code
    detail = str(error).lower()
    if is_cookie_access_error(detail):
        return COOKIE_ACCESS_WARNING_CODE
    if is_authentication_required_error(detail):
        return AUTHENTICATION_REQUIRED_CODE
    if any(marker in detail for marker in ("no space left", "disk full", "errno 28")):
        return "diskFull"
    if any(marker in detail for marker in ("permission denied", "operation not permitted")):
        return "permissionDenied"
    if any(marker in detail for marker in ("not available in your country", "geo restricted")):
        return "geographicallyRestricted"
    if any(marker in detail for marker in ("drm", "encrypted media", "encrypted stream")):
        return "protectedMedia"
    if any(marker in detail for marker in ("requested format is not available", "нет прямого", "не отдал прямой")):
        return "formatUnavailable"
    if any(marker in detail for marker in ("404", "removed", "deleted", "video unavailable")):
        return "unavailable"
    if any(marker in detail for marker in ("timed out", "timeout", "network", "name resolution", "urlopen error")):
        return "networkError"
    return error.code if isinstance(error, BackendError) else "backendError"


def args_without_browser_cookies(args):
    clone = copy.copy(args)
    clone.cookies_browser = None
    clone.cookies_file = None
    return clone


def authentication_required_error(detail: str, *, warnings=None) -> AuthenticationRequiredError:
    safe_detail = sanitized_ytdlp_detail(detail, limit=500)
    message = (
        "Нужна авторизация: войдите в аккаунт в браузере и разрешите программе использовать cookies. "
        f"Причина: {safe_detail}"
    )
    return AuthenticationRequiredError(message, warnings=warnings)
