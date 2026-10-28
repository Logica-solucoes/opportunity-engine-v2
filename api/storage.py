import os
import shutil
from pathlib import Path

# ponytail: local dir only; GCS comes in B11, chosen by env here, with path() downloading to a temp file
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
