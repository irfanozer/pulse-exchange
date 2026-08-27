# Performance evidence

PulseExchange reports measurements produced by a repeatable API scenario. It
does not include invented throughput or latency claims. Run the scenario in the
environment you want to describe, then keep the generated Markdown and JSON as
the evidence for that run.

## What the scenario does

`scripts/load_evidence.py` uses the same public HTTP routes as the browser:

1. Read diagnostics before the run.
2. Submit a concurrent wave of unit BUY orders at one price.
3. Wait until every BUY command reaches a terminal state.
4. Submit an equal concurrent wave of crossing unit SELL orders.
5. Wait until every SELL command reaches a terminal state.
6. Read diagnostics after the run.
7. Calculate latency and throughput from client-observed timestamps.
8. Fail the run if any expected correctness invariant is false.

The two-wave shape is intentional. It creates known resting liquidity before
crossing it, so the expected number of trades is deterministic.

## Measurements

The generated report contains:

- API acceptance latency p50, p95, p99, and maximum;
- end-to-end command latency p50, p95, p99, and maximum;
- total scenario duration;
- commands completed per second;
- commands completed and rejected;
- durable market events created;
- trades created;
- diagnostics before and after the scenario;
- sample command sequence and correlation identifiers.

**Acceptance latency** starts immediately before `POST /api/v1/orders` and ends
when the API returns the durable command receipt.

**End-to-end latency** starts at the same point and ends when
`GET /api/v1/commands/{id}` first reports a terminal state. It includes HTTP,
journal acceptance, queue wait, processor work, database commit, and polling
resolution.

**Throughput** is submitted commands divided by the wall-clock duration of the
two command waves. It is a scenario result, not a general capacity limit.

## Correctness gates

A report receives `passed: true` only when all of these checks pass:

- every submitted command reaches a terminal state;
- every command completes without domain rejection;
- accepted command sequences are unique;
- the run creates one durable market event per command;
- the expected number of unit trades is created;
- diagnostics report sequence integrity;
- the independent processor reports healthy.

The script exits unsuccessfully if any gate fails. A fast run with a failed
invariant is not valid evidence.

## Reproduce a local run

Install the backend development dependencies and start the full stack. For the
cleanest trade-count comparison, use a fresh local project database.

> **Data warning:** `docker compose down -v` deletes this project's local
> PostgreSQL volume. Do not run it if you need the existing local demo data.

```powershell
docker compose down -v
docker compose up --build -d
backend\.venv\Scripts\python.exe scripts\load_evidence.py --pairs 20 --concurrency 8
```

The default output prefix creates:

- `docs/load-evidence.md` — concise human-readable result;
- `docs/load-evidence.json` — raw measurements, diagnostics, and samples.

Change the scenario without editing the script:

```powershell
backend\.venv\Scripts\python.exe scripts\load_evidence.py `
  --pairs 40 `
  --concurrency 12 `
  --symbol NOVA `
  --price 30000 `
  --output-prefix docs/load-evidence-40-pairs
```

The public-demo mutation limit can intentionally reject a larger local run.
Either lower `--pairs`, wait for the rate-limit window to expire, or raise
`PULSEEXCHANGE_MUTATION_RATE_LIMIT` only in the controlled local load-test
environment. Do not disable safety limits on an internet-facing demo merely to
produce a larger number.

## Reading the generated report

Compare p50 with p95 and p99 rather than quoting only an average. A much larger
p99 can reveal queueing, connection setup, host contention, or polling delay.
Check the before/after queue depth and processor heartbeat before treating a
latency change as matching-engine work.

Always report the scenario shape with the number. A useful statement is:

> In a local Docker run of N commands at client concurrency C, the measured
> end-to-end p95 was X ms and all correctness gates passed.

Fill `N`, `C`, and `X` only from a generated report.

## Limitations

- Timings are measured by one client process, not by distributed tracing.
- Command completion is polled, so end-to-end latency includes up to one poll
  interval of measurement error.
- Docker Desktop, host hardware, database state, and background load affect the
  result.
- The global single writer optimizes deterministic behavior, not horizontal
  write throughput.
- The scenario is bounded and does not establish long-duration stability,
  multi-region latency, or production capacity.
- The result does not measure external brokers, real exchanges, or financial
  traffic because the simulator has no such integrations.

For those reasons, generated evidence should be presented as a reproducible
engineering measurement, not as a universal benchmark.
