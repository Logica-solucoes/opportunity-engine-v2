from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import accounts
from api.auth import Ctx, require_role
from api.db import get_db
from api.models import Membership, Role, User
from api.routes import Name, UserId

router = APIRouter(prefix="/api/w/{slug}/members")
workspace_admin = require_role("admin")


class MemberIn(BaseModel):
    email: str = Field(max_length=320, pattern=r"^\s*[^@\s]+@[^@\s]+\.[^@\s]+\s*$")
    name: Name | None = None
    role: Role


class RoleIn(BaseModel):
    role: Role


class MemberOut(BaseModel):
    user_id: int
    email: str
    name: str
    role: Role
    active: bool


class NewMemberOut(MemberOut):
    temp_password: str | None


def member_out(m: Membership) -> MemberOut:
    return MemberOut(user_id=m.user_id, email=m.user.email, name=m.user.name, role=m.role, active=m.user.active)


def find_member(db: Session, ctx: Ctx, user_id: int) -> Membership:
    membership = db.get(Membership, (user_id, ctx.workspace.id))
    if membership is None:
        raise HTTPException(404)
    return membership


@router.get("", response_model=list[MemberOut])
def list_members(ctx: Ctx = Depends(workspace_admin), db: Session = Depends(get_db)):
    memberships = db.scalars(
        select(Membership).join(Membership.user).where(Membership.workspace_id == ctx.workspace.id).order_by(User.email)
    )
    return [member_out(m) for m in memberships]


@router.post("", status_code=201, response_model=NewMemberOut)
def add_member(body: MemberIn, response: Response, ctx: Ctx = Depends(workspace_admin), db: Session = Depends(get_db)):
    try:
        membership, temp = accounts.add_member(db, ctx.workspace, body.email, body.name, body.role, by=ctx.user)
    except accounts.Conflict:
        raise HTTPException(409, "Usuário já é membro deste workspace")
    except accounts.AccountNotFound:
        raise HTTPException(404, "account_not_found")
    except accounts.NameRequired:
        raise HTTPException(422, "name_required")
    response.headers["Cache-Control"] = "no-store"
    return NewMemberOut(**member_out(membership).model_dump(), temp_password=temp)


@router.patch("/{user_id}", response_model=MemberOut)
def change_role(user_id: UserId, body: RoleIn, ctx: Ctx = Depends(workspace_admin), db: Session = Depends(get_db)):
    membership = find_member(db, ctx, user_id)
    try:
        accounts.change_role(db, membership, body.role, by=ctx.user)
    except accounts.LastAdmin:
        raise HTTPException(409, "last_admin")
    return member_out(membership)


@router.delete("/{user_id}", status_code=204)
def remove_member(user_id: UserId, ctx: Ctx = Depends(workspace_admin), db: Session = Depends(get_db)):
    try:
        accounts.remove_member(db, find_member(db, ctx, user_id), by=ctx.user)
    except accounts.LastAdmin:
        raise HTTPException(409, "last_admin")
