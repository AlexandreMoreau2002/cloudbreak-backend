from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HeartbeatRequest(BaseModel):
    status: Literal["ok", "fail"]
    duration_s: float | None = Field(default=None, ge=0)
    detail: str | None = Field(default=None, max_length=200)


class ServerMetricsRequest(BaseModel):
    sampled_at: datetime
    cpu_load_1m: float = Field(ge=0)
    cpu_count: int = Field(ge=0)
    mem_total_mb: float = Field(ge=0)
    mem_available_mb: float = Field(ge=0)
    swap_total_mb: float = Field(ge=0)
    swap_used_mb: float = Field(ge=0)
    disk_total_gb: float = Field(ge=0)
    disk_used_gb: float = Field(ge=0)
