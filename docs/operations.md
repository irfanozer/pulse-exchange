# Operations guide

This guide covers the local application runtime and application-level incident
checks. Azure provisioning, DNS, certificates, releases, and production
verification are documented in [deployment.md](deployment.md).

## Service roles

The Compose environment contains five services:

| Service | Responsibility | Durable state |
| --- | --- | --- |
| `db` | PostgreSQL command journal, market state, events, and heartbeats | Project Docker volume |
| `migrate` | Apply Alembic migrations before application startup | None after completion |
| `api` | FastAPI writes, reads, diagnostics, metrics, and WebSockets | None; reads/writes PostgreSQL |
| `processor` | Consume the ordered command journal and run the matching engine | None; commits to PostgreSQL |
| `frontend` | Serve React and proxy REST/WebSocket traffic to `api` | None |

The API and processor are separate processes. Restarting either one does not
delete accepted commands or market state.

## Start and stop

From the repository root:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Use `docker compose up --build -d` to run in the background, then inspect all
service states with:

```powershell
docker compose ps
docker compose logs --tail 100
```

Stop containers without deleting PostgreSQL data:

```powershell
docker compose down
```

> **Data warning:** `docker compose down -v` also deletes the project's local
> PostgreSQL volume. Use it only when a clean database is intentional.

## Runtime checks

| Check | URL | Expected result |
| --- | --- | --- |
| API liveness | http://localhost:8001/health/live | API process responds `ok` |
| API readiness | http://localhost:8001/health/ready | API can query the migrated schema and its event relay is connected |
| Processor status | http://localhost:8001/api/v1/diagnostics/summary | `services.processor.status` is `online` |
| Queue | same diagnostics URL | Depth returns to zero after a small command run |
| Metrics | http://localhost:8001/metrics | Prometheus text is returned |
| Browser stream | http://localhost:3001 | Header reports a live WebSocket |

Readiness covers the API, database schema, and PostgreSQL notification relay.
The independent processor's heartbeat is reported separately so an operator
can distinguish "the API can serve consistent state" from "the command
consumer is advancing writes."

## Diagnostics fields

`GET /api/v1/diagnostics/summary` combines live process observations and
durable database evidence:

- `services.api.status` — the API generating the snapshot is online;
- `services.processor.status` — online, stale, or offline based on its
  database heartbeat;
- `services.processor.age_ms` — age of the last processor heartbeat;
- `queue.depth` and `queue.oldest_age_ms` — waiting command pressure;
- `commands` — accepted, completed, and rejected totals plus recent completion
  latency p50, p95, and p99;
- `market` — durable order, trade, and event counts, latest sequence, and
  sequence-integrity result;
- `streams` — active connections, recovered events, and resynchronizations
  observed by this API process.

A normal PostgreSQL notification produces a live snapshot refresh. Recovery
counters increase only when a connection gap or subscriber backpressure means
the API must reconstruct outcomes from durable events.

Database counts survive an API restart. Stream counters are process-local and
reset when the API restarts.

## Correlation workflow

Every HTTP response includes `X-Correlation-ID`. For a write:

1. Copy the correlation ID from the HTTP response.
2. Follow the `Location` header to
   `/api/v1/commands/{command_id}`.
3. Compare the command's status and correlation identifier.
4. Search structured service logs for the same identifier.

A caller may send a valid `X-Correlation-ID`; otherwise the API creates one.
Use `Idempotency-Key`, not the correlation ID, when retrying a mutation.

## Common incidents

### The API is ready but orders stay queued

Check `services.processor.status`, queue depth, and oldest age. A stale or
offline heartbeat with a growing queue indicates the processor is not
advancing the journal.

```powershell
docker compose logs --tail 100 processor
docker compose restart processor
```

Accepted commands are already in PostgreSQL. The restarted processor resumes
the smallest queued sequence; do not resubmit commands with new idempotency
keys just to make the queue move.

### Readiness returns 503

Inspect `db` and `migrate` first:

```powershell
docker compose ps
docker compose logs --tail 100 db migrate api
```

The API does not report ready until it can query the migrated application
schema.

### The browser says reconnecting

Check `/health/ready`, then the API logs. The client reconnects automatically
with its last durable event ID. After reconnection, a snapshot is authoritative
for the current book and recent trades; recovered events explain outcomes
committed during the gap.

If a PostgreSQL notification was missed while the connection remained open,
the WebSocket heartbeat compares event cursors and requests the same durable
resynchronization.

### A mutation returns HTTP 429

The public-demo rate limit is working. Wait for the response's retry window
before sending more mutations. For controlled local load evidence, reduce the
scenario size or raise the limit only in the local environment.

### A mutation is rejected before it reaches the processor

Check for:

- a missing or too-short `Idempotency-Key`;
- an unsupported symbol;
- a non-positive or out-of-range price or quantity;
- a request body larger than the configured maximum;
- a full command queue.

Validation and capacity rejection happen before matching and are different
from a command that the processor marks rejected for a domain reason.

### Diagnostics show a sequence-integrity problem

Stop generating new test traffic, save the diagnostics JSON and recent `api`,
`processor`, and `db` logs, then run the backend integration tests against a
dedicated database. Do not repair sequence or event rows manually; that would
destroy the evidence needed to diagnose the invariant failure.

## Verification after a change

Run the end-to-end smoke scenario against the complete stack:

```powershell
backend\.venv\Scripts\python.exe scripts\smoke.py
```

It verifies a real crossing match, WebSocket update, disconnect/reconnect
recovery, cancellation, and REST persistence.

Run code-level checks:

```powershell
cd backend
ruff format --check .
ruff check .
mypy src
pytest

cd ..
backend\.venv\Scripts\ruff.exe format --check scripts
backend\.venv\Scripts\ruff.exe check scripts

cd frontend
npm test
npm run build
```

Generate performance evidence only after correctness checks and against a
known database state. The procedure and interpretation are in
[performance.md](performance.md).

## Configuration groups

Environment variables use the `PULSEEXCHANGE_` prefix. The main operational
groups are:

- database URL and allowed CORS origins;
- processor poll, retry-backoff, and heartbeat intervals;
- WebSocket heartbeat, replay, queue, and connection limits;
- mutation rate and time window;
- maximum request body and queued-command limits;
- optional embedded-processor and event-relay switches for local testing.

Compose supplies separate-service defaults: `api` runs without an embedded
processor, `processor` runs `python -m pulseexchange.worker`, and `frontend`
proxies application traffic to `http://api:8000`.
