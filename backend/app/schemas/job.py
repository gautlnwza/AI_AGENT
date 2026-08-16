"""Schemas for the background-job demo endpoints."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.base import BaseSchema


class DemoJobCreate(BaseSchema):
    """Input for a deliberately slow example task."""

    seconds: int = Field(default=5, ge=1, le=30)
    fail_attempts: int = Field(
        default=0,
        ge=0,
        le=2,
        description="Number of attempts to fail before succeeding (retry demo).",
    )


class JobQueued(BaseSchema):
    job_id: str
    status: Literal["queued"] = "queued"


class JobRead(BaseSchema):
    job_id: str
    status: Literal["deferred", "queued", "in_progress", "complete", "not_found"]
    success: bool | None = None
    result: Any | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
