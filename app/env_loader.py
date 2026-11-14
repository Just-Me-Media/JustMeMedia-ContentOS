"""Optional lightweight .env loader for local development.
Reads key=value pairs from a local .env file into os.environ if present.
Does not overwrite existing environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(env_path: str | Path = ".env") -> bool:
    """Load variables from a .env file into os.environ."""
    path = Path(env_path)
    if not path.is_file():
        # Also check parent directories or user config dir
        path = Path.home() / ".config" / "JustMeMedia" / ".env"
        if not path.is_file():
            return False

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        return True
    except Exception:
        return False
