from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import accounts
from api.auth import require_platform_admin
from api.db import get_db
from api.models import User, Workspace
from api.routes import UserId

router = APIRouter(prefix="/api/admin")


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1)
    slug: str = Field(pattern=r"^[a-z0-9-]{2,40}$")


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    created_at: datetime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    active: bool
    is_platform_admin: bool
    locked_until: datetime | None


class ActiveIn(BaseModel):
    active: bool


class TempPasswordOut(BaseModel):
    temp_password: str


def find_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404)
    return user


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(_: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return db.scalars(select(Workspace).order_by(Workspace.name)).all()


@router.post("/workspaces", status_code=201, response_model=WorkspaceOut)
def create_workspace(body: WorkspaceIn, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    try:
        return accounts.create_workspace(db, body.name, body.slug)
    except accounts.Conflict:
        raise HTTPException(409, "Já existe um workspace com esse slug")


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.email)).all()


@router.post("/users/{user_id}/reset-password", response_model=TempPasswordOut)
def reset_password(user_id: UserId, admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return TempPasswordOut(temp_password=accounts.reset_password(db, find_user(db, user_id), by=admin))


@router.patch("/users/{user_id}", response_model=UserOut)
def set_active(
    user_id: UserId, body: ActiveIn, admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)
):
    user = find_user(db, user_id)
    accounts.set_active(db, user, body.active, by=admin)
    return user
