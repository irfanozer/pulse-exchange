# Combined economy migration

The selected route is two separate application VMs and one new shared private
PostgreSQL 17 server in `rg-demos-economy`, West US 2. Each application retains its
own database and restricted application account. The user approved discarding
the old demo history and starting both replacement databases with fresh
fictional data. No final copy of the old databases is required for this route.
Retain the verified rehearsal backups while testing the replacement. The earlier
[database-only alternative](shared-postgres-plan.md) is superseded.

The authoritative [combined migration runbook lives in EventHarbor](https://github.com/irfanozer/eventharbor/blob/main/docs/economy-migration.md).
EventHarbor owns the one shared foundation, migration image, private access and
copy controllers. Run those shared helpers from that repository with explicit
`-Project pulseexchange` when applicable. Do not provision another shared
foundation from this repository. PulseExchange retains its own runtime, images,
and manual `.github/workflows/deploy-economy.yml` deployment workflow.

These instructions describe the approved route, not proof of completed
application deployment, public cutover, or old-resource retirement.

## Current route: fresh demo data

1. Preserve protected original settings, revisions, schedules, and verified
   rehearsal backups.
   Keep original and shared-Container-Apps deployment profiles disabled.
2. Inspect the current state. If still active, pause old scheduled jobs, stop
   APIs, then stop workers/processors within the approved outage. Verify a
   complete writer freeze. Do not run two processors against authoritative data.
3. Run EventHarbor's `scripts/azure-economy/initialize-runtime.ps1 -Project pulseexchange`
   with the exact new server and project VM preview hostname. Supply retained
   `-PostgresAdministratorPassword` and `-AppPassword` as `SecureString` values.
   The guarded initializer requires an untouched empty database, creates the
   isolated application role, transfers schema and database ownership, revokes
   PUBLIC access, and writes root-owned runtime configuration. It refuses
   existing roles, data, or configuration and never resets a database.
4. Initialize both projects before starting either application. Do not run
   `FinalCopy`, attach a rehearsal database, or use the restored-runtime helper
   for this fresh-data route. Inspect partial failures before retrying.
5. Deploy immutable PulseExchange images. Deployment runs schema migrations and
   seeds fictional starter markets through the API. Test matching, persistence,
   WebSockets, recovery, and HTTPS on the preview host. Use the separate
   [hostname helper](https://github.com/irfanozer/eventharbor/blob/main/docs/azure-economy-runtime-hostname.md)
   for the final hostname and coordinate DNS and final HTTPS checks. Configure
   the independent [VM-scoped GitHub identity](https://github.com/irfanozer/eventharbor/blob/main/docs/azure-economy-oidc.md)
   for this repository's `azure-economy` environment.
6. Observe shared database and VM capacity, correctness, retained backups, and maintenance
   before separately approving exact source retirement. Retaining old paid
   environments and load balancers means their charges continue.

## Alternative: preserve full history in a future migration

The authoritative EventHarbor runbook retains the complete copy procedure.
Use reviewed temporary private access and a tested, digest-pinned migration
image. Rehearse both sources and verify their backups and restored data. Freeze
all source writers, make final copies into untouched empty destination
databases, and independently verify both copies including sequence state.
Then use EventHarbor's [restored-runtime attachment helper](https://github.com/irfanozer/eventharbor/blob/main/docs/azure-economy-attach-restored-runtime.md)
with retained application passwords before deploying either replacement.
Never run the fresh initializer on restored data, and never bypass an
existing-target guard. This is an alternative, not an additional step for the
currently approved fresh demo deployment.

## Recovery and cost boundaries

For a future full-history move, the shared controller's narrowly guarded
rehearsal recovery procedure is documented in the EventHarbor runbook linked
above. Do not rerun ordinary rehearsal against an existing target or replace
its saved backup. The current fresh-data route does not require another
rehearsal or a final source copy.

Before replacement applications accept writes, the preserved source revisions
and schedules provide a controlled recovery path. After new writes, the new
databases are authoritative: switching back to stale sources would lose data.
Freeze and reconcile before rollback. No helper automatically deletes sources,
backup archives, or old Azure networking.

Two B2ats_v2 VMs share one eligible monthly allowance, not one allowance per VM.
VM quota approval and a new PostgreSQL server do not reset billing benefits.
Public IPv4, DNS, transfer, overages, and migration overlap may be billed. These
instructions do not claim completed cutover, free hosting, or achieved savings.
