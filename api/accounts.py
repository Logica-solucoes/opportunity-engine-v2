import logging

from sqlalchemy.orm import Session

from api.auth import drop_sessions
from api.models import UserSession
from api.passwords import hash_password, verify_password

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
