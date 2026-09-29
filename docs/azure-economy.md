# Lower-cost Azure deployment

The selected route uses the new shared server and two VMs after West US 2 quota
approval. The user approved starting with fresh demo data, so no final copy of
old demo history is required. Verified rehearsal backups remain available. The
[combined migration runbook](economy-migration.md) also retains the full-history
route for future use. Foundation provisioning alone does not establish successful cutover.

The existing Container Apps deployment remains available under `infra/azure`, `scripts/azure`, and its existing production workflow. No legacy deployment files are replaced by this option.

The new runtime is in `infra/azure-economy/runtime`. `scripts/azure-economy/deploy.ps1` deploys verified image digests to a separately provisioned PulseExchange VM. `.github/workflows/deploy-economy.yml` is manual-only, requires the protected `azure-economy` environment, and stays blocked until `ECONOMY_DEPLOYMENT_ENABLED=true` is explicitly set.

The shared foundation and full migration runbook live in the EventHarbor repository at `infra/azure-economy/foundation.bicep`, `scripts/azure-economy`, and `docs/azure-economy.md`. Provision the shared foundation once, not once per project. It contains one VM per project and one private PostgreSQL server with separate databases and application users. The portfolio remains on its existing Cloudflare host.

## Current foundation status

Azure approved four Standard Basv2 family vCPUs in West US 2. The shared foundation has been provisioned in `rg-demos-economy`, including two B2ats_v2 VMs and the private PostgreSQL server. The earlier zero-quota blocker is resolved. The two VMs use all four approved cores; approval is not capacity for another pair. Continue with the combined migration runbook rather than provisioning a duplicate foundation.

The selected two-B2ats_v2 layout uses explicit `-AcknowledgeSharedVmHours`. Their hours share one 750-hour allowance; they are not both entirely free. Verified compute pricing plus planning IP/DNS rates gives a subtotal around $14.47 in a 730-hour month, only if the VM allowance applies and before uncovered database/disks, transfer, overages and tax. See the full runbook for the calculation and eligibility gates. Foundation provisioning does not establish that data migration, application deployment, public cutover, or source retirement is complete.

## Initialize the approved fresh demo deployment

Use the EventHarbor checkout's `scripts/azure-economy/initialize-runtime.ps1 -Project pulseexchange` with the exact new server and PulseExchange VM preview hostname. Pass retained `SecureString` credentials as `-PostgresAdministratorPassword` and `-AppPassword`; omitting the latter generates a new app password. The initializer atomically checks the empty foundation database, creates a restricted isolated role, transfers Azure public-schema ownership before database ownership, and revokes PUBLIC access. It refuses existing roles, data, or runtime configuration and never resets a database.

Initialize both projects before starting either app. The deployment runs schema migrations and seeds fictional starter markets through the API. Preserve the verified rehearsal backups until the new public sites pass their checks.

For a future full-history move, verify both final copies first and use `attach-restored-runtime.ps1` with retained credentials instead of the initializer. See EventHarbor's `docs/azure-economy-attach-restored-runtime.md` for that alternative; do not initialize a restored database.

## Safety and cost checklist

- Keep the existing site live until the replacement passes public HTTPS, order matching, REST persistence, WebSocket, reboot, and memory/CPU soak checks.
- The template retains B1s plus B2ats_v2 as a distinct-type option for other reviewed deployments. The current foundation uses two B2ats_v2 VMs, which share that type's monthly allowance; free usage is not per instance.
- The target below $20/month is conditional on the VM, disk and PostgreSQL allowances applying. Two Standard public IPs, private DNS, transfer and excess usage can still be charged. Old/new overlap adds cost.
- Use the new shared server's `pulseexchange` database and its isolated `pulseexchange_app` role. The current approved route initializes fresh demo data, while the alternative attaches a verified final copy. Never point both the old and new processors at the same live database.
- Database TLS, public rate limits, order limits, live-update origin checks, and maintenance remain enabled. Do not share runtime environment files or raw Docker metadata.
- Before a migration-related push, explicitly disable the old `AZURE_DEPLOYMENT_ENABLED` flag without deleting the old workflow or stopping the running site.
- Retain the already verified rehearsal backups and verify the fresh replacement before moving DNS or deleting old resources. Only a future full-history move requires a final write freeze/copy.
- Nothing here automatically migrates history, changes DNS, deletes old resources, or guarantees a free bill. See the full shared runbook before executing cloud operations.

For host details and offline checks, see `infra/azure-economy/runtime/README.md`. The current local checks are not proof of a deployed or load-tested replacement.
