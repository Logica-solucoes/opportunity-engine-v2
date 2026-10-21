import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import drop_sessions, normalize_email
from api.models import Membership, User, UserSession, Workspace
from api.passwords import hash_password, temp_password, verify_password

log = logging.getLogger(__name__)


class Conflict(Exception):
    pass


class WrongPassword(Exception):
    pass


class SamePassword(Exception):
    pass


def change_password(db: Session, session: UserSession, current: str, new: str) -> None:
    user = session.user
    if not verify_password(current, user.password_hash):
        raise WrongPassword
    if new == current:
        raise SamePassword
    user.password_hash = hash_password(new)
    user.must_change_password = False
    drop_sessions(db, user.id, keep=session.token_hash)
    db.commit()
    log.info("auth.password_changed user_id=%s", user.id)


def add_member(db: Session, workspace: Workspace, email: str, name: str, role: str) -> tuple[Membership, str | None]:
    email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == email))
    temp = None
    if user is None:
        temp = temp_password()
        user = User(email=email, name=name, password_hash=hash_password(temp), must_change_password=True)
        db.add(user)
        db.flush()
    elif db.get(Membership, (user.id, workspace.id)) is not None:
        raise Conflict

    membership = Membership(user_id=user.id, workspace_id=workspace.id, role=role)
    db.add(membership)
    db.commit()
    log.info("auth.member_added user_id=%s workspace_id=%s role=%s", user.id, workspace.id, role)
    return membership, temp


def create_workspace(db: Session, name: str, slug: str) -> Workspace:
    if db.scalar(select(Workspace.id).where(Workspace.slug == slug)) is not None:
        raise Conflict
    workspace = Workspace(name=name, slug=slug)
    db.add(workspace)
    db.commit()
    log.info("auth.workspace_created workspace_id=%s slug=%s", workspace.id, slug)
    return workspace


def reset_password(db: Session, user: User, by: User | None) -> str:
    temp = temp_password()
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None
    drop_sessions(db, user.id)
    db.commit()
    log.info("auth.password_reset user_id=%s by=%s", user.id, by.id if by else "cli")
    return temp


def set_active(db: Session, user: User, active: bool, by: User) -> None:
    user.active = active
    if not active:
        drop_sessions(db, user.id)
        log.info("auth.user_deactivated user_id=%s by=%s", user.id, by.id)
    db.commit()
