from typing import Annotated

from fastapi import Path
from pydantic import StringConstraints

UserId = Annotated[int, Path(ge=1, le=2**63 - 1)]
SimulationId = Annotated[int, Path(ge=1, le=2**63 - 1)]
RunId = Annotated[int, Path(ge=1, le=2**63 - 1)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# scrypt runs over the whole input: an unbounded password is a free CPU burner
Password = Annotated[str, StringConstraints(max_length=1024)]
