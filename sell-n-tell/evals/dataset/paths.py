"""Filesystem locations for dataset curation. No third-party imports, so any
module -- including ones the unit tests load -- can use them."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "evals" / "data" / "raw"
OUT = ROOT / "evals" / "data" / "out"
DISPOSITIONS_YAML = ROOT / "app" / "voice_notes_agent" / "resources" / "dispositions.yaml"
APP_ENV = ROOT / "app" / ".env"
