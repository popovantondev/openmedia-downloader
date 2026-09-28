"""Manueller Abbruchtest: ein öffentlicher HLS-Auftrag, keine Cookies."""
import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cli = Path(__file__).resolve().parents[1] / "cli.py"
    process = subprocess.Popen([sys.executable, str(cli), "-o", str(output), "--mode", "chunks", "-q", "240", "https://vimeo.com/272406014"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    lines = []
    signaled = False
    cancel_started = None
    for line in process.stdout:
        lines.append(line)
        if line.startswith("OMD_EVENT:") and json.loads(line.removeprefix("OMD_EVENT:")).get("type") == "progress":
            if not signaled:
                signaled = True
                cancel_started = time.monotonic()
                os.killpg(process.pid, signal.SIGTERM)
    code = process.wait(timeout=10)
    leftover = list(Path(tempfile.gettempdir()).glob(f"openmedia-downloader-{process.pid}-*"))
    summary = {"exit": code, "signaled": signaled, "cancelSeconds": round(time.monotonic() - cancel_started, 3) if cancel_started else None, "temporaryDirectoriesRemaining": len(leftover), "mediaFilesRemaining": len(list(output.glob("*.mp4")))}
    (output / "cancel.log").write_text("".join(lines))
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
    return 0 if signaled and code != 0 and not leftover and not list(output.glob("*.mp4")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
