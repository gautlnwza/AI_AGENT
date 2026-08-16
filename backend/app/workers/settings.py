"""ARQ worker configuration.

Run locally with::

    uv run arq app.workers.settings.WorkerSettings
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from arq.connections import RedisSettings
from arq.worker import Retry, func

from app.core.config import settings


def get_arq_redis_settings() -> RedisSettings:
    """Build ARQ connection settings from the application's Redis settings."""
    return RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        database=settings.REDIS_DB,
        password=settings.REDIS_PASSWORD,
    )


async def demo_task(ctx: dict[str, Any], seconds: int, fail_attempts: int = 0) -> dict[str, Any]:
    """A small task used to demonstrate queueing, results, and retries.

    ``fail_attempts`` deliberately retries the task that many times. In a real
    task, raise ``Retry`` only for transient errors such as rate limits or
    upstream timeouts.
    """
    attempt = int(ctx["job_try"])
    if attempt <= fail_attempts:
        raise Retry(defer=min(2**attempt, 10))

    await asyncio.sleep(seconds)
    return {
        "message": f"Worker slept for {seconds} second(s)",
        "attempt": attempt,
        "finished_at": datetime.now(UTC).isoformat(),
    }


class WorkerSettings:
    """Settings consumed by the ``arq`` command-line worker."""

    functions = [func(demo_task, keep_result=3600, timeout=60, max_tries=4)]
    redis_settings = get_arq_redis_settings()
    health_check_interval = 30
