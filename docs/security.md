# Security and public-demo boundary

PulseExchange is a public engineering demonstration, not a production trading
or multi-tenant financial system. Its safety controls are designed to keep a
small fictional workload bounded and observable. They do not replace identity,
authorization, abuse prevention, or infrastructure controls required by a
real service.

## Data and trust boundary

- Symbols, orders, prices, and quantities are fictional.
- The application has no accounts, balances, payments, personal information,
  brokerage connection, or external execution venue.
- The browser is untrusted. FastAPI validates every command regardless of
  client-side controls.
- PostgreSQL is trusted durable state and should not be reachable directly from
  the public internet.
- The API does not accept arbitrary callback URLs, SQL, file paths, or network
  destinations.

## Application controls

### Bounded writes

- Mutation routes have a configurable request-rate limit.
- Request bodies have a configured maximum size.
- The durable command queue has a configured maximum depth.
- Price, quantity, symbol, identifier, and pagination inputs have explicit
  bounds.
- Every write requires an `Idempotency-Key` with bounded length.

These controls limit accidental or casual abuse. The rate limiter is
process-local; with multiple API replicas, its effective aggregate allowance
increases. A production edge or shared rate-limit store would be required for
a global policy.

The included public Azure deployment therefore fixes both the public web app
and API at one replica, makes the API internal, applies a second global write
limit at the only public Nginx entry point, enforces a durable command ceiling,
and resets/reseeds the disposable fictional market daily. Those are portfolio
demo boundaries, not a substitute for identity or distributed abuse controls.

Forwarded client-address headers are ignored by default. Compose enables them
only because the API is bound to loopback and Nginx overwrites the forwarded
address before proxying a request. A different runtime must leave
`PULSEEXCHANGE_TRUST_PROXY_HEADERS=false` unless its trusted edge also strips
and replaces client-supplied forwarding headers.

### Bounded streams

- Simultaneous WebSocket connections are capped per API process.
- Each subscriber queue is bounded; a slow consumer receives a durable resync
  rather than unbounded in-memory backlog.
- Reconnect replay is capped. An authoritative snapshot is returned even when
  the historical suffix is truncated.
- Heartbeats detect newer durable events without depending on a notification
  remaining in memory.

### Request integrity

- Pydantic validates request shape and domain ranges before persistence.
- SQLAlchemy issues parameterized database operations.
- Idempotency detects a key reused for a different operation and returns HTTP
  409.
- Correlation identifiers are observability metadata, not authorization or
  command identity.
- CORS allows only configured browser origins. CORS is not authentication and
  does not prevent direct HTTP clients from calling the API.

### Response hardening

The API adds conservative security headers to reduce content-type sniffing and
unnecessary referrer disclosure. The frontend should be served over HTTPS by
its deployment edge. Transport security belongs at that edge; the local
Compose environment intentionally uses HTTP.

## Secrets

Committed database values in `.env.example` are local-development defaults,
not production secrets. Before any internet-facing deployment:

- create a strong database credential in the hosting platform's secret store;
- keep `.env` and provider credentials out of Git;
- use short-lived workload identity for automation when available;
- rotate any credential that was printed, committed, or pasted into a public
  location;
- restrict the database firewall or network policy to application services;
- do not expose the local PostgreSQL port mapping publicly.

No access token is required by the application itself because it does not call
GitHub, cloud control planes, brokerages, or external market APIs.

## Operational endpoints

`/metrics` and `/api/v1/diagnostics/summary` reveal service health, traffic
counts, queue pressure, and data totals. They contain no financial or personal
data in this simulator, but they are still operational information. A real
deployment should restrict them to an operator network or authenticated
monitoring path.

The included deployment blocks `/metrics` at the public Nginx entry point. It
keeps the diagnostics summary public because the page uses its reduced,
non-sensitive evidence to explain the system. A real multi-user system should
authenticate or isolate both endpoints.

Correlation IDs may appear in logs and command responses. They must never be
used to carry secrets, email addresses, tokens, or other sensitive values.

## Before public exposure

Use this checklist in addition to the platform's own security review:

- [ ] HTTPS redirects and certificates are active.
- [ ] PostgreSQL has no public ingress.
- [ ] CORS lists only the intended site origins.
- [ ] Development credentials have been replaced with managed secrets.
- [ ] Mutation, body-size, queue, and WebSocket limits fit the available
      compute and database size.
- [ ] `/metrics`, diagnostics, and API documentation have the intended access
      policy.
- [ ] Container CPU, memory, replica, and restart limits are configured.
- [ ] Logs do not contain secrets or full untrusted payloads.
- [ ] Dependency and container-image scanning runs in CI.
- [ ] PostgreSQL backup and retention behavior is understood.
- [ ] Alerts cover readiness, processor heartbeat, growing queue age, error
      rate, and database capacity.

## Deliberately absent controls

PulseExchange does not implement:

- authentication or user sessions;
- role-based authorization;
- tenant isolation;
- account ownership of orders;
- anti-fraud, market-surveillance, or regulatory controls;
- globally coordinated distributed rate limiting;
- a web application firewall or denial-of-service protection;
- encryption-key lifecycle management;
- production backup restoration testing.

Those omissions are acceptable for a fictional portfolio demo only when the
service remains resource-bounded and contains no sensitive data. Adding real
users, money, or external market connectivity would change the threat model
and require a different security architecture.
