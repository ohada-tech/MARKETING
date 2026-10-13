"""Settings from environment variables (and an optional local .env file)."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader. Real environment variables always win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


_load_dotenv(ROOT / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'outreach.db'}")

# Section 7, gate 1. Stays false unless Ohad explicitly enables it.
SEND_ENABLED = _bool("SEND_ENABLED", False)

# Section 11: listen on localhost only until authentication exists.
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8000"))
