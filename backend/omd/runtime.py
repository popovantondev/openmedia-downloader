"""Private Arbeitsdateien und beendbare Unterprozesse."""
from __future__ import annotations

import atexit
import contextlib
import fcntl
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

_ACTIVE_PROCESSES: set[subprocess.Popen] = set()
_PROCESS_LOCK = threading.RLock()
_RUNTIME_TEMP_DIR: Path | None = None
_CANCELLED = threading.Event()


def check_cancelled() -> None:
    if _CANCELLED.is_set():
        raise InterruptedError("Загрузка отменена.")


def current_temp_dir() -> Path | None:
    return _RUNTIME_TEMP_DIR


def bundled_tool(name: str) -> str | None:
    """Nur mitgelieferte Programme verwenden, nie einen zufälligen PATH-Treffer."""
    roots = []
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(sys._MEIPASS) / "bin")
    roots.extend([
        Path(sys.executable).resolve().parent / "bin",
        Path(__file__).resolve().parents[2] / "vendor" / "bin",
    ])
    for root in roots:
        candidate = root / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def ffmpeg() -> str:
    result = bundled_tool("ffmpeg")
    if not result:
        raise RuntimeError("В приложении отсутствует FFmpeg. Установите приложение заново.")
    return result


def ffprobe() -> str:
    result = bundled_tool("ffprobe")
    if not result:
        raise RuntimeError("В приложении отсутствует FFprobe. Установите приложение заново.")
    return result


def ytdlp() -> str | None:
    return bundled_tool("yt-dlp")


def deno() -> str | None:
    return bundled_tool("deno")


def establish_process_group() -> None:
    """Die Oberfläche kann damit den ganzen Auftrag sicher beenden."""
    try:
        os.setsid()
    except OSError:
        pass


def publish_file(staging: Path, target: Path) -> None:
    """Auch zwischen zwei Datenträgern erst eine vollständige Datei zeigen."""
    local = target.with_name(f".{target.name}.{os.getpid()}.omd-part")
    try:
        try:
            staging.replace(target)
        except OSError as error:
            import errno
            if error.errno != errno.EXDEV:
                raise
            shutil.copyfile(staging, local)
            local.replace(target)
            staging.unlink()
    finally:
        local.unlink(missing_ok=True)


@contextlib.contextmanager
def target_lock(target: Path):
    """Gleiche Zieldateien dürfen nicht gleichzeitig ersetzt werden."""
    root = Path(tempfile.gettempdir()) / f"openmedia-locks-{os.getuid()}"
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid():
        raise RuntimeError("Не удалось безопасно подготовить запись файла.")
    digest = hashlib.sha256(str(target.resolve()).encode()).hexdigest()
    descriptor = os.open(root / (digest + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

def runtime_temp_dir() -> Path:
    """Private staging directory; user folders receive completed files only."""
    global _RUNTIME_TEMP_DIR
    if _RUNTIME_TEMP_DIR is None:
        _RUNTIME_TEMP_DIR = Path(tempfile.mkdtemp(prefix=f"openmedia-downloader-{os.getpid()}-"))
    return _RUNTIME_TEMP_DIR


def cleanup_runtime_temp_dir() -> None:
    global _RUNTIME_TEMP_DIR
    if _RUNTIME_TEMP_DIR is not None:
        shutil.rmtree(_RUNTIME_TEMP_DIR, ignore_errors=True)
        _RUNTIME_TEMP_DIR = None


atexit.register(cleanup_runtime_temp_dir)


def _register_process(process: subprocess.Popen) -> subprocess.Popen:
    with _PROCESS_LOCK:
        _ACTIVE_PROCESSES.add(process)
    return process


def _unregister_process(process: subprocess.Popen) -> None:
    with _PROCESS_LOCK:
        _ACTIVE_PROCESSES.discard(process)


def unregister_process(process: subprocess.Popen) -> None:
    """Release a completed child from the shared cancellation registry."""
    _unregister_process(process)


def start_process(command, **kwargs) -> subprocess.Popen:
    """Start a child in its own process group and remember it for cancellation."""
    kwargs.setdefault("start_new_session", True)
    process = subprocess.Popen(command, **kwargs)
    process._omd_owns_group = bool(kwargs["start_new_session"])
    return _register_process(process)


def run_captured(command, *, timeout=None) -> subprocess.CompletedProcess:
    process = start_process(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate_process(process)
            # Weder private Argumente noch unvollständige Cookie-Daten ausgeben.
            raise TimeoutError("Подготовка превысила время ожидания (timeout). Повторите попытку.") from None
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        _unregister_process(process)


def _group_exists(process: subprocess.Popen) -> bool:
    if not getattr(process, "_omd_owns_group", False):
        return False
    try:
        os.killpg(process.pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def terminate_process(process: subprocess.Popen, grace_seconds: float = 1.5) -> None:
    """Terminate a downloader and everything it spawned (notably ffmpeg)."""
    owns_group = getattr(process, "_omd_owns_group", False)
    if process.poll() is not None and not _group_exists(process):
        return
    try:
        if owns_group:
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.terminate()
        except OSError:
            return
    # Der Elternprozess kann früher enden als ein Kind, das stdout offen hält.
    deadline = time.monotonic() + max(0, grace_seconds)
    while time.monotonic() < deadline:
        if process.poll() is not None and not _group_exists(process):
            return
        time.sleep(0.02)
    try:
        if owns_group:
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def terminate_all_children() -> None:
    with _PROCESS_LOCK:
        processes = list(_ACTIVE_PROCESSES)
    for process in processes:
        terminate_process(process)
        _unregister_process(process)


def _termination_handler(signum, _frame) -> None:
    _CANCELLED.set()
    terminate_all_children()
    cleanup_runtime_temp_dir()
    raise SystemExit(128 + signum)


def install_signal_handlers() -> None:
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _termination_handler)
        signal.signal(signal.SIGINT, _termination_handler)
