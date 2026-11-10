import logging

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import storage
from api.auth import check_lock, drop_sessions, normalize_email, register_failure
from api.models import ACTIVE_RUN_STATUSES, Membership, Run, User, UserSession, Workspace
from api.passwords import hash_password, temp_password, verify_password

log = logging.getLogger(__name__)


class Conflict(Exception):
    pass


class SlugInTrash(Exception):
    pass


class WrongPassword(Exception):
    pass


class SamePassword(Exception):
    pass


class AccountNotFound(Exception):
    pass


class NameRequired(Exception):
    pass


class LastAdmin(Exception):
    pass


class ActiveRun(Exception):
    pass


TRASH_DAYS = 7


def active_workspaces():
    return select(Workspace).where(Workspace.deleted_at.is_(None))


def commit_or_conflict(db: Session) -> None:
    # two concurrent creates both pass the existence check; the unique constraint catches the loser
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict


def confirm_password(db: Session, user: User, password: str) -> None:
    # same lock and failure count as the login: a stolen session must not be a free password oracle
    db.refresh(user, with_for_update={"key_share": True})
    if not user.active:
        raise WrongPassword
    check_lock(user)
    if not verify_password(password, user.password_hash):
        register_failure(db, user)
        raise WrongPassword


def change_password(db: Session, session: UserSession, current: str, new: str) -> None:
    user = session.user
    confirm_password(db, user, current)
    if new == current:
        raise SamePassword
    user.failed_logins = 0
    user.locked_until = None
    user.password_hash = hash_password(new)
    user.must_change_password = False
    drop_sessions(db, user.id)
    db.commit()
    log.info("auth.password_changed user_id=%s", user.id)


def add_member(
    db: Session, workspace: Workspace, email: str, name: str | None, role: str, by: User
) -> tuple[Membership, str | None]:
    email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == email))
    temp = None
    if user is None:
        # accounts are the platform admin's: one minted by brand A's admin could later be linked to brand B
        if not by.is_platform_admin:
            raise AccountNotFound
        if name is None:
            raise NameRequired
        temp = temp_password()
        user = User(email=email, name=name, password_hash=hash_password(temp), must_change_password=True)
        db.add(user)
        db.flush()
    elif db.get(Membership, (user.id, workspace.id)) is not None:
        raise Conflict

    membership = Membership(user_id=user.id, workspace_id=workspace.id, role=role)
    db.add(membership)
    commit_or_conflict(db)
    log.info("auth.member_added user_id=%s workspace_id=%s role=%s by=%s", user.id, workspace.id, role, by.id)
    return membership, temp


def ensure_another_admin(db: Session, membership: Membership) -> None:
    # the row lock serializes two admins demoting each other at the same time
    admins = db.scalars(
        select(Membership.user_id)
        .where(Membership.workspace_id == membership.workspace_id, Membership.role == "admin")
        .with_for_update()
    ).all()
    if admins == [membership.user_id]:
        raise LastAdmin


def change_role(db: Session, membership: Membership, role: str, by: User) -> None:
    if role != "admin":
        ensure_another_admin(db, membership)
    membership.role = role
    db.commit()
    log.info(
        "auth.member_role_changed user_id=%s workspace_id=%s role=%s by=%s",
        membership.user_id,
        membership.workspace_id,
        role,
        by.id,
    )


def remove_member(db: Session, membership: Membership, by: User) -> None:
    ensure_another_admin(db, membership)
    db.delete(membership)
    db.commit()
    log.info("auth.member_removed user_id=%s workspace_id=%s by=%s", membership.user_id, membership.workspace_id, by.id)


def create_workspace(db: Session, name: str, slug: str) -> Workspace:
    existing = db.scalar(select(Workspace).where(Workspace.slug == slug))
    if existing is not None:
        raise SlugInTrash if existing.deleted_at is not None else Conflict
    workspace = Workspace(name=name, slug=slug)
    db.add(workspace)
    commit_or_conflict(db)
    log.info("auth.workspace_created workspace_id=%s slug=%s", workspace.id, slug)
    return workspace


def ensure_no_active_run(db: Session, workspace: Workspace) -> None:
    # FOR UPDATE: a run being created waits for this commit
    db.refresh(workspace, with_for_update=True)
    active = select(Run.id).where(Run.workspace_id == workspace.id, Run.status.in_(ACTIVE_RUN_STATUSES))
    if db.scalar(active.limit(1)) is not None:
        raise ActiveRun


def trash_workspace(db: Session, workspace: Workspace, by: User) -> None:
    ensure_no_active_run(db, workspace)
    workspace.deleted_at = func.now()
    workspace.deleted_by = by.id
    db.commit()
    log.info("auth.workspace_trashed workspace_id=%s slug=%s by=%s", workspace.id, workspace.slug, by.id)


def restore_workspace(db: Session, workspace: Workspace, by: User) -> None:
    workspace.deleted_at = None
    workspace.deleted_by = None
    db.commit()
    log.info("auth.workspace_restored workspace_id=%s slug=%s by=%s", workspace.id, workspace.slug, by.id)


def purge_workspace(db: Session, workspace: Workspace, by: str) -> None:
    ensure_no_active_run(db, workspace)
    wid, slug = workspace.id, workspace.slug
    # memberships, simulations, files, runs and run logs go with it through ON DELETE CASCADE; users stay
    db.execute(sql_delete(Workspace).where(Workspace.id == wid))
    db.commit()
    log.info("auth.workspace_purged workspace_id=%s slug=%s by=%s", wid, slug, by)
    # rows first: files gone with rows still standing would leave runs pointing at nothing
    prefix = f"ws/{wid}"
    try:
        storage.delete_prefix(prefix)
    except OSError:
        log.exception("workspace.files_orphaned prefix=%s", prefix)


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
    was_active = user.active
    user.active = active
    if not active:
        drop_sessions(db, user.id)
        log.info("auth.user_deactivated user_id=%s by=%s", user.id, by.id)
    elif not was_active:
        user.failed_logins = 0
        user.locked_until = None
        log.info("auth.user_reactivated user_id=%s by=%s", user.id, by.id)
    db.commit()


def create_platform_admin(db: Session, email: str, name: str) -> str:
    email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name, password_hash="")
        db.add(user)
    user.is_platform_admin = True
    user.active = True
    db.flush()
    return reset_password(db, user, by=None)
