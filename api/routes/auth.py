from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import accounts, auth
from api.db import get_db
from api.models import Membership, Role, User, UserSession, Workspace

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    email: str
    password: str


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=12)


class MyWorkspace(BaseModel):
    slug: str
    name: str
    role: Role


class MeOut(BaseModel):
    id: int
    email: str
    name: str
    is_platform_admin: bool
    must_change_password: bool
    workspaces: list[MyWorkspace]


def me_out(db: Session, user: User) -> MeOut:
    if user.is_platform_admin:
        rows = [(w, "admin") for w in db.scalars(select(Workspace).order_by(Workspace.name))]
    else:
        rows = db.execute(
            select(Workspace, Membership.role)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user.id)
            .order_by(Workspace.name)
        ).all()
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        is_platform_admin=user.is_platform_admin,
        must_change_password=user.must_change_password,
        workspaces=[MyWorkspace(slug=w.slug, name=w.name, role=role) for w, role in rows],
    )


@router.post("/auth/login", response_model=MeOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    try:
        user = auth.authenticate(db, body.email, body.password)
    except auth.AccountLocked as e:
        return JSONResponse({"detail": "locked", "retry_after_s": e.retry_after_s}, status_code=429)
    except auth.InvalidCredentials:
        raise HTTPException(401, "invalid_credentials")
    auth.set_session_cookie(response, auth.create_session(db, user))
    return me_out(db, user)


@router.post("/auth/logout", status_code=204)
def logout(response: Response, session: UserSession = Depends(auth.current_session), db: Session = Depends(get_db)):
    db.delete(session)
    db.commit()
    auth.clear_session_cookie(response)


@router.post("/auth/password", status_code=204)
def change_password(
    body: PasswordIn, session: UserSession = Depends(auth.current_session), db: Session = Depends(get_db)
):
    try:
        accounts.change_password(db, session, body.current, body.new)
    except accounts.WrongPassword:
        raise HTTPException(400, "invalid_current_password")
    except accounts.SamePassword:
        raise HTTPException(422, "password_unchanged")


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    return me_out(db, user)
