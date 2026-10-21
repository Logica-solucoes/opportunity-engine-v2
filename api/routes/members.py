from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import accounts
from api.auth import Ctx, require_role
from api.db import get_db
from api.models import Membership, Role, User

router = APIRouter(prefix="/api/w/{slug}/members")
workspace_admin = require_role("admin")


class MemberIn(BaseModel):
    email: str = Field(pattern=r"^\s*[^@\s]+@[^@\s]+\.[^@\s]+\s*$")
    name: str = Field(min_length=1)
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
def add_member(body: MemberIn, ctx: Ctx = Depends(workspace_admin), db: Session = Depends(get_db)):
    try:
        membership, temp = accounts.add_member(db, ctx.workspace, body.email, body.name, body.role)
    except accounts.Conflict:
        raise HTTPException(409, "Usuário já é membro deste workspace")
    return NewMemberOut(**member_out(membership).model_dump(), temp_password=temp)


@router.patch("/{user_id}", response_model=MemberOut)
def change_role(user_id: int, body: RoleIn, ctx: Ctx = Depends(workspace_admin), db: Session = Depends(get_db)):
    membership = find_member(db, ctx, user_id)
    membership.role = body.role
    db.commit()
    return member_out(membership)


@router.delete("/{user_id}", status_code=204)
def remove_member(user_id: int, ctx: Ctx = Depends(workspace_admin), db: Session = Depends(get_db)):
    db.delete(find_member(db, ctx, user_id))
    db.commit()
