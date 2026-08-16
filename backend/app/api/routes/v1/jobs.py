"""Simple ARQ background-job endpoints."""

from typing import Any
from uuid import uuid4

from arq.jobs import Job
from fastapi import APIRouter, HTTPException, status

from app.api.deps import ArqPool, CurrentUser
from app.schemas.job import DemoJobCreate, JobQueued, JobRead

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _owned_job_id(job_id: str, user_id: Any) -> bool:
    """Keep the demo result endpoint scoped to the user who queued the job."""
    return job_id.startswith(f"demo:{user_id}:")


@router.post("/demo", response_model=JobQueued, status_code=status.HTTP_202_ACCEPTED)
async def create_demo_job(data: DemoJobCreate, queue: ArqPool, user: CurrentUser) -> JobQueued:
    """Queue a slow demo task and immediately return its ID."""
    job_id = f"demo:{user.id}:{uuid4()}"
    job = await queue.enqueue_job(
        "demo_task",
        data.seconds,
        data.fail_attempts,
        _job_id=job_id,
    )
    if job is None:
        raise HTTPException(status_code=409, detail="Job ID already exists")
    return JobQueued(job_id=job.job_id)


@router.get("/{job_id}", response_model=JobRead)
async def get_job(job_id: str, queue: ArqPool, user: CurrentUser) -> JobRead:
    """Read queue state and the retained result of one demo job."""
    if not _owned_job_id(job_id, user.id):
        raise HTTPException(status_code=404, detail="Job not found")

    job = Job(job_id, queue)
    job_status = await job.status()
    result_info = await job.result_info() if job_status.value == "complete" else None

    result: Any | None = None
    success: bool | None = None
    if result_info is not None:
        success = result_info.success
        result = result_info.result if success else str(result_info.result)

    return JobRead(
        job_id=job_id,
        status=job_status.value,
        success=success,
        result=result,
        started_at=result_info.start_time if result_info else None,
        finished_at=result_info.finish_time if result_info else None,
    )
