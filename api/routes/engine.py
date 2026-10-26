from fastapi import APIRouter, Depends

from api.auth import active_user
from api.engine_config import ParamsIn
from api.models import User

router = APIRouter(prefix="/api/engine")


@router.get("/config-schema")
def config_schema(_: User = Depends(active_user)) -> dict:
    return ParamsIn.model_json_schema()
