import hashlib
import logging
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.db import get_db
from api.models import Membership, User, UserSession, Workspace
from api.passwords import dummy_hash, verify_password

log = logging.getLogger(__name__)

COOKIE = "gem_session"
IDLE_TIMEOUT = timedelta(hours=8)
MAX_AGE = timedelta(days=7)
TOUCH_EVERY = timedelta(minutes=1)
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
RANK = {"viewer": 0, "analyst": 1, "admin": 2}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


class InvalidCredentials(Exception):
    pass


class AccountLocked(Exception):
    def __init__(self, retry_after_s: int):
        self.retry_after_s = retry_after_s


def check_lock(user: User) -> None:
    t = now()
    if user.locked_until is not None and user.locked_until > t:
        log.info("auth.login_locked user_id=%s", user.id)
        raise AccountLocked(math.ceil((user.locked_until - t).total_seconds()))


def register_failure(db: Session, user: User) -> None:
    user.failed_logins += 1
    if user.failed_logins >= MAX_FAILED_LOGINS:
        user.failed_logins = 0
        user.locked_until = now() + LOCKOUT
        log.warning("auth.locked user_id=%s", user.id)
    db.commit()


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is not None:
        check_lock(user)
    stored = user.password_hash if user is not None else dummy_hash()
    # end the read first: scrypt takes ~0.3 s and must not sit on a pooled connection or a row lock
    db.commit()
    ok = verify_password(password, stored)

    if user is None:
        log.info("auth.login_failed email=%r", email)
        raise InvalidCredentials

    db.refresh(user, with_for_update={"key_share": True})
    check_lock(user)
    if not ok or user.password_hash != stored:
        register_failure(db, user)
        log.info("auth.login_failed email=%r", email)
        raise InvalidCredentials

    if not user.active:
        log.info("auth.login_failed email=%r", email)
        raise InvalidCredentials

    user.failed_logins = 0
    user.locked_until = None
    return user


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    t = now()
    # sessions whose cookie never comes back would otherwise live forever
    db.execute(
        delete(UserSession).where(
            (UserSession.last_seen_at < t - IDLE_TIMEOUT) | (UserSession.created_at < t - MAX_AGE)
        )
    )
    db.add(UserSession(token_hash=hash_token(token), user_id=user.id, created_at=t, last_seen_at=t))
    db.commit()
    log.info("auth.login_ok user_id=%s", user.id)
    return token


def drop_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(UserSession).where(UserSession.user_id == user_id))


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, httponly=True, secure=True, samesite="lax", path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True, secure=True, samesite="lax")


def current_session(
    token: str | None = Cookie(default=None, alias=COOKIE), db: Session = Depends(get_db)
) -> UserSession:
    session = db.get(UserSession, hash_token(token)) if token else None
    if session is None:
        raise HTTPException(401, "not_authenticated")

    t = now()
    if not session.user.active or t - session.last_seen_at >= IDLE_TIMEOUT or t - session.created_at >= MAX_AGE:
        db.delete(session)
        db.commit()
        raise HTTPException(401, "not_authenticated")

    if t - session.last_seen_at > TOUCH_EVERY:
        session.last_seen_at = t
        db.commit()
    return session


def current_user(session: UserSession = Depends(current_session)) -> User:
    return session.user


def active_user(user: User = Depends(current_user)) -> User:
    if user.must_change_password:
        raise HTTPException(403, "password_change_required")
    return user


@dataclass
class Ctx:
    user: User
    workspace: Workspace
    role: str


def require_role(min_role: str):
    def dependency(slug: str, user: User = Depends(active_user), db: Session = Depends(get_db)) -> Ctx:
        workspace = db.scalar(select(Workspace).where(Workspace.slug == slug))
        if workspace is None:
            raise HTTPException(404)

        if user.is_platform_admin:
            role = "admin"
        else:
            membership = db.get(Membership, (user.id, workspace.id))
            # not a member looks exactly like "doesn't exist": 403 would confirm the workspace exists
            if membership is None:
                raise HTTPException(404)
            role = membership.role

        if RANK[role] < RANK[min_role]:
            raise HTTPException(403)
        return Ctx(user, workspace, role)

    return dependency


def require_platform_admin(user: User = Depends(active_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(403)
    return user


async def check_origin(request: Request, call_next):
    # host only, not scheme: Cloud Run terminates TLS, so the app sees http while the browser sends https
    origin = request.headers.get("origin")
    if (
        request.method in UNSAFE_METHODS
        and request.url.path.startswith("/api/")
        and origin is not None
        and urlsplit(origin).netloc != request.headers.get("host")
    ):
        return JSONResponse({"detail": "bad_origin"}, status_code=403)
    return await call_next(request)
