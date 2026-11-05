import os
import shutil
from pathlib import Path

# ponytail: local dir, also in production (own server, no GCP); back it up with the database
# and delete_prefix() listing and deleting the blobs under the prefix
ROOT = Path(os.environ.get("STORAGE_DIR", "data"))


def path(key: str) -> Path:
    return ROOT / key


def put(key: str, src: Path) -> None:
    dest = path(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    shutil.copyfile(src, part)
    os.replace(part, dest)


def delete_prefix(prefix: str) -> None:
    target = path(prefix)
    if target.exists():
        shutil.rmtree(target)
