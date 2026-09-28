"""Manueller Netztest mit öffentlichen, vom Nutzer erlaubten Testvideos."""
import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--backend", type=Path, help="Gepacktes omd_backend statt des Quellcode-Backends prüfen")
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    project = Path(__file__).resolve().parents[2]
    cli = project / "backend" / "cli.py"
    ffmpeg = project / "vendor" / "bin" / "ffmpeg"
    backend_command = [sys.executable, str(cli)]
    environment = None
    if args.backend:
        backend = args.backend.resolve()
        backend_command = [str(backend)]
        ffmpeg = backend.parent / "_internal/bin/ffmpeg"
        environment = {"PATH": "/usr/bin:/bin", "TMPDIR": "/private/tmp"}
    jobs = [
        ("youtube-direct", "https://www.youtube.com/watch?v=jNQXAC9IVRw", "video", "144", "direct"),
        ("youtube-chunks", "https://www.youtube.com/watch?v=jNQXAC9IVRw", "video", "144", "chunks"),
        ("youtube-aac", "https://www.youtube.com/watch?v=jNQXAC9IVRw", "aac", "best", "auto"),
        ("youtube-mp3", "https://www.youtube.com/watch?v=jNQXAC9IVRw", "mp3", "192k", "auto"),
        ("vimeo-direct", "https://vimeo.com/272406014", "video", "240", "direct"),
        ("vimeo-chunks", "https://vimeo.com/272406014", "video", "240", "chunks"),
    ]
    def download(job):
        name, url, media, quality, mode = job
        output = root / name
        output.mkdir(exist_ok=True)
        started = time.monotonic()
        result = subprocess.run(backend_command + ["-o", str(output), "--media", media, "-q", quality, "--mode", mode, "--workers", "4", url], capture_output=True, text=True, timeout=480, env=environment)
        (root / (name + ".log")).write_text(result.stdout + result.stderr)
        events = []
        for line in result.stdout.splitlines():
            if line.startswith("OMD_EVENT:"):
                events.append(json.loads(line.removeprefix("OMD_EVENT:")))
        files = [path for path in output.iterdir() if path.suffix in (".mp4", ".m4a", ".mp3")]
        decoded = []
        for path in files:
            check = subprocess.run([str(ffmpeg), "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, timeout=120, env=environment)
            decoded.append({"file": path.name, "bytes": path.stat().st_size, "decodeExit": check.returncode, "decodeErrors": check.stderr[-500:]})
        summary = {"name": name, "exit": result.returncode, "seconds": round(time.monotonic() - started, 2), "stages": sorted({item.get("stage") for item in events if item.get("stage")}), "progressEvents": sum(item["type"] == "progress" for item in events), "completed": any(item["type"] == "completed" for item in events), "files": decoded}
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        return summary
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(download, jobs))
    for name, url in (("vimeo-metadata", "https://vimeo.com/22439234"), ("playlist-metadata", "https://www.youtube.com/playlist?list=PL2aBZuCeDwlSlkI3MBOmbt-FZaAWSNbB2")):
        response = subprocess.run(backend_command + ["--inspect-json", url], capture_output=True, text=True, timeout=480, env=environment)
        (root / (name + ".json")).write_text(response.stdout)
        payload = json.loads(response.stdout)
        item = {"name": name, "exit": response.returncode, "isPlaylist": payload.get("isPlaylist"), "entryCount": len(payload.get("entries", [])), "estimatedVariants": sum(len(entry.get("estimates", [])) for entry in payload.get("entries", [])), "error": payload.get("error")}
        results.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    (root / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["exit"] == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
