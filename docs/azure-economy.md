# Lower-cost Azure deployment

The selected route is now the [combined economy migration](economy-migration.md)
after West US 2 quota approval. Both source databases move directly to the new
shared server; the earlier database-only move into EventHarbor's old server is
historical. Foundation provisioning alone does not establish successful cutover.

The existing Container Apps deployment remains available under `infra/azure`, `scripts/azure`, and its existing production workflow. No legacy deployment files are replaced by this option.

The new runtime is in `infra/azure-economy/runtime`. `scripts/azure-economy/deploy.ps1` deploys verified image digests to a separately provisioned PulseExchange VM. `.github/workflows/deploy-economy.yml` is manual-only, requires the protected `azure-economy` environment, and stays blocked until `ECONOMY_DEPLOYMENT_ENABLED=true` is explicitly set.

The shared foundation and full migration runbook live in the EventHarbor repository at `infra/azure-economy/foundation.bicep`, `scripts/azure-economy`, and `docs/azure-economy.md`. Provision the shared foundation once, not once per project. It contains one VM per project and one private PostgreSQL server with separate databases and application users. The portfolio remains on its existing Cloudflare host.

## Current foundation status

Azure approved four Standard Basv2 family vCPUs in West US 2. The shared foundation has been provisioned in `rg-demos-economy`, including two B2ats_v2 VMs and the private PostgreSQL server. The earlier zero-quota blocker is resolved. The two VMs use all four approved cores; approval is not capacity for another pair. Continue with the combined migration runbook rather than provisioning a duplicate foundation.

The selected two-B2ats_v2 layout uses explicit `-AcknowledgeSharedVmHours`. Their hours share one 750-hour allowance; they are not both entirely free. Verified compute pricing plus planning IP/DNS rates gives a subtotal around $14.47 in a 730-hour month, only if the VM allowance applies and before uncovered database/disks, transfer, overages and tax. See the full runbook for the calculation and eligibility gates. Foundation provisioning does not establish that data migration, application deployment, public cutover, or source retirement is complete.

## Attach restored data, or initialize a fresh deployment

For the current migration, complete and verify both final database copies using the [combined migration runbook](economy-migration.md). Then use the EventHarbor checkout's `scripts/azure-economy/attach-restored-runtime.ps1 -Project pulseexchange` with the retained `pulseexchange_app` password and the new VM preview hostname. Attach verifies role isolation, ownership, and TLS with read-only queries, then writes root-only runtime configuration. It does not create or rotate the restored role, and it does not start the application.

`initialize-runtime.ps1 -Project pulseexchange` is only for a deliberately fresh, empty deployment. It creates a new application role and password and does not copy old history. Do not use it for the restored migration database. See EventHarbor's `docs/azure-economy-attach-restored-runtime.md` for the attach parameters and checks.

## Safety and cost checklist

- Keep the existing site live until the replacement passes public HTTPS, order matching, REST persistence, WebSocket, reboot, and memory/CPU soak checks.
- The template retains B1s plus B2ats_v2 as a distinct-type option for other reviewed deployments. The current foundation uses two B2ats_v2 VMs, which share that type's monthly allowance; free usage is not per instance.
- The target below $20/month is conditional on the VM, disk and PostgreSQL allowances applying. Two Standard public IPs, private DNS, transfer and excess usage can still be charged. Old/new overlap adds cost.
- Use the new shared server's restored `pulseexchange` database and its isolated `pulseexchange_app` role. Attach the retained role after both final copies are verified. Never point both the old and new processors at the same live database.
- Database TLS, public rate limits, order limits, live-update origin checks, and maintenance remain enabled. Do not share runtime environment files or raw Docker metadata.
- Before a migration-related push, explicitly disable the old `AZURE_DEPLOYMENT_ENABLED` flag without deleting the old workflow or stopping the running site.
- Back up and restore-test the old database, agree on a final write freeze/copy, and verify the replacement before moving DNS or deleting old resources.
- Nothing here automatically migrates history, changes DNS, deletes old resources, or guarantees a free bill. See the full shared runbook before executing cloud operations.

For host details and offline checks, see `infra/azure-economy/runtime/README.md`. The current local checks are not proof of a deployed or load-tested replacement.
