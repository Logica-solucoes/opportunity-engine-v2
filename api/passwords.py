import base64
import hashlib
import hmac
import os
import secrets
import threading
from functools import cache

# OWASP minimum for scrypt; params live in each hash, so raising N later keeps old hashes valid
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
MAXMEM = 2**28
# each run takes ~128 MB: a burst of logins must queue instead of OOM-killing the instance
SLOTS = threading.BoundedSemaphore(4)
# the wait is bounded: queued logins hold worker threads every other route shares
SLOT_WAIT_S = 5


class Busy(Exception):
    pass


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    if not SLOTS.acquire(timeout=SLOT_WAIT_S):
        raise Busy
    try:
        return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=MAXMEM)
    finally:
        SLOTS.release()


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except ValueError:
        return False


@cache
def dummy_hash() -> str:
    """Hash to verify against when the email doesn't exist, so timing doesn't reveal which accounts exist."""
    return hash_password(secrets.token_urlsafe(16))


def temp_password() -> str:
    return secrets.token_urlsafe(12)
