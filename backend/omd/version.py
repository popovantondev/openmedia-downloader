"""Eine Versionsdatei für Quellcode und gepacktes Backend."""
import sys
from pathlib import Path


def application_version():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        return (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "development"


VERSION = application_version()
