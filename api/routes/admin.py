from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import accounts, google_import, runs, usage
from api.auth import require_platform_admin
from api.db import get_db
from api.models import User, Workspace
from api.routes import Name, UserId, WorkspaceId

router = APIRouter(prefix="/api/admin")


class WorkspaceIn(BaseModel):
    name: Name
    slug: str = Field(pattern=r"^[a-z0-9-]{2,40}$")


class WorkspaceOut(BaseModel):
    id: int
    name: str
    slug: str
    created_at: datetime
    google: google_import.GoogleConfig | None


def workspace_out(w: Workspace) -> WorkspaceOut:
    return WorkspaceOut(id=w.id, name=w.name, slug=w.slug, created_at=w.created_at, google=w.settings.get("google"))


def find_workspace(db: Session, workspace_id: int) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(404)
    return workspace


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


Month = Annotated[str | None, Query(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]


class UsageRow(BaseModel):
    month: str
    workspace_id: int
    workspace_name: str
    user_id: int
    user_name: str
    user_email: str
    succeeded: int
    inconclusive: int
    failed: int
    active: int
    total: int
    run_seconds: int


def find_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404)
    return user


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(_: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return [workspace_out(w) for w in db.scalars(select(Workspace).order_by(Workspace.name))]


@router.post("/workspaces", status_code=201, response_model=WorkspaceOut)
def create_workspace(body: WorkspaceIn, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    try:
        return workspace_out(accounts.create_workspace(db, body.name, body.slug))
    except accounts.Conflict:
        raise HTTPException(409, "Já existe um workspace com esse slug")


@router.put("/workspaces/{workspace_id}/google", response_model=WorkspaceOut)
def set_google(
    workspace_id: WorkspaceId,
    body: google_import.GoogleConfig,
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    workspace = find_workspace(db, workspace_id)
    google_import.configure(db, workspace, body, by=admin)
    return workspace_out(workspace)


@router.delete("/workspaces/{workspace_id}/google", status_code=204)
def remove_google(
    workspace_id: WorkspaceId, admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)
):
    google_import.configure(db, find_workspace(db, workspace_id), None, by=admin)


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.email)).all()


@router.post("/users/{user_id}/reset-password", response_model=TempPasswordOut)
def reset_password(
    user_id: UserId, response: Response, admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)
):
    response.headers["Cache-Control"] = "no-store"
    return TempPasswordOut(temp_password=accounts.reset_password(db, find_user(db, user_id), by=admin))


@router.patch("/users/{user_id}", response_model=UserOut)
def set_active(
    user_id: UserId, body: ActiveIn, admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)
):
    if user_id == admin.id and not body.active:
        raise HTTPException(400, "cannot_deactivate_self")
    user = find_user(db, user_id)
    accounts.set_active(db, user, body.active, by=admin)
    return user


@router.get("/usage", response_model=list[UsageRow])
def list_usage(month: Month = None, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    runs.fail_stale(db)
    return usage.rows(db, month)


@router.get("/usage.csv")
def export_usage(month: Month = None, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    runs.fail_stale(db)
    name = f"uso-{month}.csv" if month else "uso.csv"
    return Response(
        usage.to_csv(usage.rows(db, month)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
