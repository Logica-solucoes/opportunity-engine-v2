from typing import Annotated

from fastapi import Path

UserId = Annotated[int, Path(ge=1, le=2**63 - 1)]
