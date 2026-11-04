import importlib.metadata
import subprocess
from pathlib import Path


def engine_version() -> str:
    """Short git sha when running from a checkout, else the installed package version, else 'unknown'."""
    try:
        sha = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        if sha:
            return sha
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return importlib.metadata.version("opportunity-engine-v2")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"
