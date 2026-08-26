# PulseExchange

PulseExchange is a deterministic real-time exchange simulator built to make
concurrency, ordering, matching, and live delivery inspectable. It is an
engineering demonstration using fictional instruments and simulated orders;
it is not connected to money, brokerages, or real markets.

## What this milestone proves

- Limit orders match with deterministic price-time priority.
- PostgreSQL assigns every accepted command a durable monotonic sequence.
- A deliberately single-writer processor applies commands in that order.
- Retrying the same client operation with the same idempotency key returns the
  original command instead of creating another order.
- Orders, trades, and market events commit together.
- WebSocket clients receive an initial book snapshot and subsequent updates.
- A processor restart resumes the earliest durable queued command.
- Reconnecting clients recover missed outcomes from PostgreSQL by event ID.
- The React terminal displays the live book, trade tape, sequence, and
  connection state without inventing market data.

The current build covers project stages 1 through 7: system rules, repository
structure, matching engine, persistence and API, concurrency-safe sequencing,
real-time WebSocket updates, and crash/reconnect recovery. Load evidence,
observability, and public Azure deployment are later milestones.

## Run the complete system

Requirements: Docker Desktop with the Linux engine running.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Then open:

- Live terminal: http://localhost:3001
- API documentation: http://localhost:8001/docs
- Readiness: http://localhost:8001/health/ready

Stop the stack with `docker compose down`. Add `-v` only when you intentionally
want to delete the local PostgreSQL data.

## Run the services separately

Start PostgreSQL:

```powershell
docker compose up -d db
```

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn pulseexchange.main:app --reload --port 8000
```

Frontend, from another terminal:

```powershell
cd frontend
npm install
npm run dev
```

The Vite development server runs at http://localhost:5173 and proxies API and
WebSocket traffic to the backend.

## Verify the project

With the Docker stack running, exercise one complete order match and a
disconnect/reconnect replay through the same Nginx entry point used by the
browser:

```powershell
backend\.venv\Scripts\python.exe scripts\smoke.py
```

Then run the isolated backend and frontend suites:

```powershell
cd backend
ruff format --check .
ruff check .
mypy src
pytest

cd ..\frontend
npm test
npm run build
```

## API surface

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/orders` | Queue a limit order using `Idempotency-Key` |
| `DELETE` | `/api/v1/orders/{order_id}` | Queue a cancellation |
| `GET` | `/api/v1/orders/{order_id}` | Inspect durable order state |
| `GET` | `/api/v1/commands/{command_id}` | Inspect command processing state |
| `GET` | `/api/v1/markets/{symbol}/book` | Read the current aggregated book |
| `GET` | `/api/v1/markets/{symbol}/trades` | Read the latest trades |
| `WS` | `/api/v1/markets/{symbol}/stream?after_event_id=N` | Receive current state and optionally replay missed durable outcomes |

Supported fictional symbols are `NOVA` and `ORBIT`. Prices and quantities are
integers so matching never depends on binary floating-point behavior.

## Repository map

```text
backend/
  src/pulseexchange/engine/  Pure matching domain
  src/pulseexchange/         API, database, processor, and stream hub
  alembic/                   PostgreSQL migrations
  tests/                     Unit and opt-in integration tests
frontend/
  src/                       React real-time terminal
docs/
  architecture.md            Runtime and transaction design
  domain-contract.md         Matching rules and invariants
compose.yaml                 Complete local environment
```

## Recovery guarantees

Stage 7 makes the database commit the recovery boundary. A crash before commit
rolls back order, trade, event, and command changes together, leaving the
command queued. A crash after commit cannot reprocess that command. If its
in-memory WebSocket notification was lost, clients reconnect with their last
event ID and receive a current snapshot plus the missed durable outcomes.

The processor still runs in the API process and one backend replica is
expected. A later deployment milestone can separate it and add cross-process
notifications without changing the matching or recovery contracts.

## License

MIT
