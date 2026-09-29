# Lower-cost Azure deployment

The selected route is now the [combined economy migration](economy-migration.md)
after West US 2 quota approval. Both source databases move directly to the new
shared server; the earlier database-only move into EventHarbor's old server is
historical. Foundation provisioning alone does not establish successful cutover.

The existing Container Apps deployment remains available under `infra/azure`, `scripts/azure`, and its existing production workflow. No legacy deployment files are replaced by this option.

The new runtime is in `infra/azure-economy/runtime`. `scripts/azure-economy/deploy.ps1` deploys verified image digests to a separately provisioned PulseExchange VM. `.github/workflows/deploy-economy.yml` is manual-only, requires the protected `azure-economy` environment, and stays blocked until `ECONOMY_DEPLOYMENT_ENABLED=true` is explicitly set.

The shared foundation and full migration runbook live in the EventHarbor repository at `infra/azure-economy/foundation.bicep`, `scripts/azure-economy`, and `docs/azure-economy.md`. Provision the shared foundation once, not once per project. It contains one VM per project and one private PostgreSQL server with separate databases and application users. The portfolio remains on its existing Cloudflare host.

## Current blocker

On September 28, 2026, Azure reported both proposed x86 free-eligible sizes as unavailable in East US 2 for this subscription, and the newer VM family's quota was zero. Resolve SKU availability and quota, then verify the actual free-service allowances before provisioning. Do not silently substitute a larger paid VM.

The practical option is two B2ats_v2 VMs in West US 2, where that size is available without a zone pin. It requires a Basv2 quota increase to four cores and explicit `-AcknowledgeSharedVmHours`. Their hours share one 750-hour allowance; they are not both entirely free. Verified compute pricing plus planning IP/DNS rates gives a subtotal around $14.47 in a 730-hour month, only if the VM allowance applies and before uncovered database/disks, transfer, overages and tax. See the full runbook for the calculation and eligibility gates.

## Safety and cost checklist

- Keep the existing site live until the replacement passes public HTTPS, order matching, REST persistence, WebSocket, reboot, and memory/CPU soak checks.
- The proposed B1s and B2ats_v2 types can use distinct eligible allowances. Two VMs of one type share that type's monthly allowance; free usage is not per instance.
- The target below $20/month is conditional on the VM, disk and PostgreSQL allowances applying. Two Standard public IPs, private DNS, transfer and excess usage can still be charged. Old/new overlap adds cost.
- Use the new shared server's `pulseexchange` database and its isolated `pulseexchange_app` role. Initialize this through the EventHarbor checkout's `initialize-runtime.ps1 -Project pulseexchange`. Never point both the old and new processors at the same live database.
- Database TLS, public rate limits, order limits, live-update origin checks, and maintenance remain enabled. Do not share runtime environment files or raw Docker metadata.
- Before a migration-related push, explicitly disable the old `AZURE_DEPLOYMENT_ENABLED` flag without deleting the old workflow or stopping the running site.
- Back up and restore-test the old database, agree on a final write freeze/copy, and verify the replacement before moving DNS or deleting old resources.
- Nothing here automatically migrates history, changes DNS, deletes old resources, or guarantees a free bill. See the full shared runbook before executing cloud operations.

For host details and offline checks, see `infra/azure-economy/runtime/README.md`. The current local checks are not proof of a deployed or load-tested replacement.
