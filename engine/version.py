import importlib.metadata
import os
import subprocess
from pathlib import Path


def engine_version() -> str:
    """ENGINE_VERSION (set at image build, which has no .git), else the git sha, else the package version."""
    if os.environ.get("ENGINE_VERSION"):
        return os.environ["ENGINE_VERSION"]
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
