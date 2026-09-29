# Combined economy migration

The selected route is two separate application VMs and one new shared private
PostgreSQL 17 server in `rg-demos-economy`, West US 2. Each application retains its
own database and restricted application account. The original EventHarbor and
PulseExchange databases are copied directly to that new server. The earlier
[database-only alternative](shared-postgres-plan.md) is superseded.

The authoritative [combined migration runbook lives in EventHarbor](https://github.com/irfanozer/eventharbor/blob/main/docs/economy-migration.md).
EventHarbor owns the one shared foundation, migration image, private access and
copy controllers. Run those shared helpers from that repository with explicit
`-Project pulseexchange` when applicable. Do not provision another shared
foundation from this repository. PulseExchange retains its own runtime, images,
and manual `.github/workflows/deploy-economy.yml` deployment workflow.

## Required order

1. Preserve protected original settings, revisions, schedules, and backups.
   Keep original and shared-Container-Apps deployment profiles disabled.
2. Establish temporary private access and use a tested, digest-pinned migration
   image. Rehearse each source and independently Verify its protected backup and
   restored data before freezing writers.
3. Pause old scheduled jobs, stop APIs, then stop workers/processors. Verify a
   complete writer freeze. Do not run two processors against authoritative data.
4. Make and verify both final copies into the empty foundation databases before
   starting either replacement application. Refuse existing target data rather
   than cleaning or reseeding it. Final verification includes sequence state.
5. Use EventHarbor's [restored-runtime attachment helper](https://github.com/irfanozer/eventharbor/blob/main/docs/azure-economy-attach-restored-runtime.md),
   not the fresh-database initializer. Attach the retained `pulseexchange_app`
   password without exposing it in source, arguments, or logs.
6. Deploy immutable PulseExchange images and test matching, persistence,
   WebSockets, recovery, and HTTPS on the preview host. Use the separate
   [hostname helper](https://github.com/irfanozer/eventharbor/blob/main/docs/azure-economy-runtime-hostname.md)
   for the final hostname and coordinate DNS and final HTTPS checks. Configure
   the independent [VM-scoped GitHub identity](https://github.com/irfanozer/eventharbor/blob/main/docs/azure-economy-oidc.md)
   for this repository's `azure-economy` environment.
7. Observe shared database and VM capacity, correctness, backups, and maintenance
   before separately approving exact source retirement. Retaining old paid
   environments and load balancers means their charges continue.

## Recovery and cost boundaries

For the shared controller's narrowly guarded rehearsal recovery procedure, see
the EventHarbor runbook linked above. Do not rerun ordinary rehearsal against an
existing target or replace its saved backup.

Before replacement applications accept writes, the preserved source revisions
and schedules provide a controlled recovery path. After new writes, the new
databases are authoritative: switching back to stale sources would lose data.
Freeze and reconcile before rollback. No helper automatically deletes sources,
backup archives, or old Azure networking.

Two B2ats_v2 VMs share one eligible monthly allowance, not one allowance per VM.
VM quota approval and a new PostgreSQL server do not reset billing benefits.
Public IPv4, DNS, transfer, overages, and migration overlap may be billed. These
instructions do not claim completed cutover, free hosting, or achieved savings.
