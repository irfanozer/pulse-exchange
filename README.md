# Live Website: https://pulseexchange.irfanburakozer.com/

# PulseExchange

PulseExchange is a deterministic real-time exchange simulator built to make
concurrency, ordering, matching, recovery, and live delivery inspectable. It
uses fictional instruments and simulated orders; it is not connected to
money, brokerages, or real markets.

The project is designed as an engineering case study, not as a trading-game
mockup. Every order shown in the React terminal travels through the public
FastAPI interface, a durable PostgreSQL command journal, an independent
background matching service, and its matching engine before it returns over
WebSocket and REST.

## What the system demonstrates

- Limit orders match with deterministic price-time priority.
- PostgreSQL assigns every accepted command a durable monotonic sequence.
- A deliberately single-writer matching service applies commands in that order.
- Retrying the same operation with the same idempotency key returns the
  original command instead of creating another order.
- Orders, trades, market events, and command completion commit atomically.
- The API and matching service run as separate software services.
- PostgreSQL `LISTEN`/`NOTIFY` wakes connected API instances after a commit;
  durable event cursors and heartbeat checks recover any missed hint.
- Reconnecting WebSocket clients recover outcomes committed while they were
  offline.
- Correlation IDs connect an HTTP request to its durable command and logs.
- `/metrics` and `/api/v1/diagnostics/summary` expose live operating evidence.
- A repeatable load scenario records latency, throughput, and correctness
  checks without bypassing the public API.
- The browser includes one guided demo that creates a trade and exposes the
  exact HTTP, command, REST, and WebSocket evidence behind it.

## Architecture at a glance

```text
Command path:
Browser -> FastAPI -> PostgreSQL journal -> background matching service
                                             | matching transaction
                                             v
                         PostgreSQL orders + trades + market events

Live path:
PostgreSQL -- NOTIFY after commit --> API listener -- refresh --> WebSocket
     ^                                                            |
     |________________ authoritative snapshot query ______________|
                                                                  v
                                                            React terminal
```

PostgreSQL is the source of truth. Notifications reduce delivery latency, but
they are never treated as durable messages. See
[docs/architecture.md](docs/architecture.md) for the transaction and recovery
boundaries.

## Run the complete system

Requirements: Docker Desktop with the Linux engine running.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Then open:

- Live market and 30-second demo: http://localhost:3001
- API documentation: http://localhost:8001/docs
- Readiness: http://localhost:8001/health/ready
- Diagnostics: http://localhost:8001/api/v1/diagnostics/summary
- Prometheus-compatible metrics: http://localhost:8001/metrics

On a fresh Compose volume, a one-shot seed client submits idempotent starter
orders through the public API; every starter trade is processed by the
independent worker and persisted in PostgreSQL. `NOVA` begins with deeper,
tighter liquidity and `ORBIT` with a thinner, wider market. Set
`PULSEEXCHANGE_SEED_MARKET=false` when you intentionally want an empty market.

Stop the stack with `docker compose down`. Add `-v` only when you intentionally
want to delete the local PostgreSQL data.

## Run each service separately

Start PostgreSQL and apply the schema:

```powershell
docker compose up -d db
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
```

Start the API with the embedded processor disabled:

```powershell
$env:PULSEEXCHANGE_PROCESSOR_ENABLED = "false"
uvicorn pulseexchange.main:app --reload --port 8000
```

Start the independent processor from a second activated backend terminal:

```powershell
python -m pulseexchange.worker
```

Start the frontend from a third terminal:

```powershell
cd frontend
npm install
npm run dev
```

The Vite development server runs at http://localhost:5173 and proxies API and
WebSocket traffic to FastAPI.

## Prove it in the browser

Open the terminal and choose **Send this buyer and verify the trade**. The page
first reads a real waiting seller from the selected order book, then submits
one compatible buy order through `POST /api/v1/orders`. It does not report
success until that command is completed and the same new trade identifier has
appeared through both the REST API and the WebSocket stream.

The receipt exposes the HTTP status, correlation and command identifiers,
processed sequence, matched order identifiers, and independent REST/WebSocket
confirmation. The live order book and highlighted trade provide the visual
result. The five-step request path is open directly beneath the demo so a
visitor can immediately connect the button press to the API, database,
matching service, and live page update. Manual order entry is a secondary sandbox;
advanced operating diagnostics remain expandable. A
concise 60-90 second walkthrough is in [docs/demo.md](docs/demo.md).

## Verify the project

With the Docker stack running, exercise an order match and a
disconnect/reconnect replay through the same Nginx entry point used by the
browser:

```powershell
backend\.venv\Scripts\python.exe scripts\smoke.py
```

Run the isolated backend and frontend suites:

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

To generate a measured load report against a fresh local stack:

```powershell
backend\.venv\Scripts\python.exe scripts\load_evidence.py --pairs 20 --concurrency 8
```

The script writes `docs/load-evidence.md` and `docs/load-evidence.json`. It
fails when any correctness check fails; it does not contain prewritten
benchmark results. See [docs/performance.md](docs/performance.md) before using
the numbers in a case study.

## Continuous verification

GitHub Actions runs the Python formatter, linter, strict type checking,
migrations, unit tests, and PostgreSQL integration tests. It separately tests
and builds the React application, then starts the separated API/processor
Compose stack and runs both the end-to-end smoke path and a bounded measured
load scenario. Container logs are retained in the failed job output to make a
cross-service failure diagnosable.

## API surface

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/orders` | Queue a limit order using `Idempotency-Key` |
| `DELETE` | `/api/v1/orders/{order_id}` | Queue a cancellation |
| `GET` | `/api/v1/orders/{order_id}` | Inspect durable order state |
| `GET` | `/api/v1/commands/{command_id}` | Inspect command processing state |
| `GET` | `/api/v1/markets` | Describe the fictional instruments and demo profiles |
| `GET` | `/api/v1/markets/{symbol}` | Read one instrument's metadata |
| `GET` | `/api/v1/markets/{symbol}/book` | Read the current aggregated book |
| `GET` | `/api/v1/markets/{symbol}/trades` | Read the latest trades |
| `WS` | `/api/v1/markets/{symbol}/stream?after_event_id=N` | Receive current state and recover missed outcomes |
| `GET` | `/api/v1/diagnostics/summary` | Read processor, queue, latency, market, and stream evidence |
| `GET` | `/metrics` | Read process metrics in Prometheus text format |
| `GET` | `/health/live` | Confirm that the API process is alive |
| `GET` | `/health/ready` | Confirm that the API and schema are ready |

Supported fictional symbols are `NOVA` and `ORBIT`. They are separate simulated
instruments, not currencies: each has an independent order book and trade
history, and orders cannot match across symbols. `NOVA` is seeded as the more
active, deeper market around 102 ticks; `ORBIT` is intentionally thinner with a
wider spread around 48 ticks. A tick is an arbitrary integer price unit, not a
dollar amount. Integer pricing keeps matching independent of binary
floating-point behavior.

## Repository map

```text
backend/
  src/pulseexchange/engine/  Pure matching domain
  src/pulseexchange/main.py  FastAPI application
  src/pulseexchange/worker.py Independent command-processor entry point
  src/pulseexchange/seed.py  Idempotent public-API starter-market client
  alembic/                   PostgreSQL migrations
  tests/                     Unit and PostgreSQL integration tests
frontend/
  src/                       React terminal and guided proof
scripts/
  smoke.py                   End-to-end match and reconnect verification
  load_evidence.py           Reproducible measured load scenario
docs/
  architecture.md            Runtime, transaction, and recovery design
  domain-contract.md         Matching rules and invariants
  demo.md                    Recruiter-facing walkthrough
  operations.md              Local operation and incident checks
  performance.md             Measurement methodology
  security.md                Public-demo boundary and controls
  deployment.md              Azure, GitHub Actions, DNS, and TLS procedure
compose.yaml                 Complete local environment
```

## Recovery guarantee

The PostgreSQL commit is the recovery boundary. A crash before commit rolls
back order, trade, event, and command changes together, leaving the command
queued. A crash after commit cannot reprocess that command. If a notification
or WebSocket update is lost, the client supplies its last durable event ID and
receives an authoritative snapshot plus a bounded set of missed outcomes.

The API and processor can restart independently. Processor heartbeats make a
stalled worker visible, and a replacement processor continues from the
earliest queued command under the same advisory-lock and transaction rules.

## Public-demo boundary

The API limits mutation rates, request size, queued work, and simultaneous
WebSocket connections. Inputs are validated, writes require idempotency keys,
and no route accepts arbitrary destinations or accesses financial systems.
There are intentionally no accounts, balances, authentication, or real market
connections. Read [docs/security.md](docs/security.md) before exposing the demo
to the internet.

Production packaging is included for Azure Container Apps: private PostgreSQL,
an internal API, a continuously running matching service, migration and seed
jobs, scheduled public-demo maintenance, immutable GHCR images, OIDC release
automation, rollback, and custom-certificate preservation. Follow
[docs/deployment.md](docs/deployment.md) before creating billable resources.

## License

MIT
