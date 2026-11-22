from typing import Literal

from pydantic import BaseModel


class VersionResponse(BaseModel):
    service: Literal["backend"]
    sha: str
    built_at: str | None
    version: str
    tag: str | None
