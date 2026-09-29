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

## Verified deployment status on 2026-09-29

- [PulseExchange](https://pulseexchange.irfanburakozer.com) and [EventHarbor](https://eventharbor.irfanburakozer.com) are live with fresh fictional data on `vm-px-demos-economy` and `vm-eh-demos-economy` in `rg-demos-economy`, West US 2. TLS and isolation were verified for their separate databases and 12-connection application roles on the shared private PostgreSQL server.
- Public PulseExchange checks passed for a fictional ORBIT trade confirmed through REST and WebSocket, reconnect replay, and cancellation of the test order. EventHarbor rejection and retry checks also passed, including `429`, `429`, `200` with approximately 5.14-second retry gaps.
- At inspection, all application containers were healthy with zero reported restarts and no current OOM flag. Maintenance timers were enabled. Available memory was approximately 280 MiB on the PulseExchange VM and 250 MiB on EventHarbor; these are observations, not capacity guarantees.
- The [PulseExchange deployment run](https://github.com/irfanozer/pulse-exchange/actions/runs/36580134237) succeeded. Its controller revision was `ac84e6a`; the reused immutable application images still identify application revision `cc0ef0b`. Legacy deployment files remain unchanged, old deployment flags are disabled, and the new manual economy workflow is enabled.
- **Old-resource retirement is complete.** Azure confirmed that `rg-pulseexchange-prod`, `rg-eventharbor-prod`, and both Azure-managed networking groups are absent, including their old databases, Container Apps, jobs, load balancers, and public IPs. Replacement infrastructure and the retained backup account were verified after deletion. Old history was intentionally discarded; retained rehearsal backups are earlier snapshots, not final copies. Already-accrued charges and delayed billing entries can still appear.

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

Recovery from preserved source revisions and schedules was available only while
the original resources and databases still existed. The original database servers
have now been deleted under the approved discard-history route. The replacement
databases are authoritative. Returning to the old profile requires recreating its
infrastructure from preserved files and planning a new data transfer. Rehearsal
backups are earlier snapshots, not a complete rollback of current data. Freeze
and reconcile writes before a future cutover. The repository migration helpers
do not automatically delete sources, backup archives, or old Azure networking;
this migration uses a separately authorized retirement operation.

Two B2ats_v2 VMs share one eligible monthly allowance, not one allowance per VM.
VM quota approval and a new PostgreSQL server do not reset billing benefits.
Public IPv4, DNS, transfer, overages, and migration overlap may be billed.
Retirement was verified separately as recorded above. Public cutover does not
establish free hosting or a measured full month of savings.
See the [dated combined cost estimate and official rate sources](https://github.com/irfanozer/eventharbor/blob/main/docs/economy-migration.md#cost-boundary)
in the authoritative EventHarbor runbook for both projects' shared monthly budget.
