# How to: Add a Background Task

## Overview

Background tasks run asynchronously outside the request-response cycle. This project uses
**ARQ** with Redis as the task queue.

## Step-by-Step

### 1. Create the task

Add an async function to `app/workers/settings.py` and register it in
`WorkerSettings.functions`.

### 2. Call it from your API

```python
job = await queue.enqueue_job("demo_task", 5, 0)
```

### 3. Add scheduling (optional)
### 4. Run the worker

```bash
cd backend
uv run arq app.workers.settings.WorkerSettings
```

The example endpoints are:

```text
POST /api/v1/jobs/demo
GET  /api/v1/jobs/{job_id}
```

## Try the demo

Start all services (API, worker, PostgreSQL, and Redis):

```bash
docker compose up --build
```

Log in through `/docs`, authorize with the returned access token, and call
`POST /api/v1/jobs/demo` with:

```json
{"seconds": 5, "fail_attempts": 0}
```

The API returns HTTP 202 with a `job_id`. Pass that ID to
`GET /api/v1/jobs/{job_id}` until the status becomes `complete`.

Set `fail_attempts` to `2` to see two retries before the job succeeds. Watch
the worker output with:

```bash
docker compose logs -f worker
```
