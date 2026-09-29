# Shared PostgreSQL consolidation plan

**Plan only: no database consolidation is claimed by this document.** The selected path is database consolidation first and the VM migration later. It keeps both current Container Apps sites and moves PulseExchange into its own database on EventHarbor's existing private B1ms server while VM quota remains pending.

Read the full [EventHarbor shared PostgreSQL plan](../../eventharbor/docs/shared-postgres-plan.md) in the sibling repository. That relative link requires the multi-project workspace; in a standalone checkout, open `docs/shared-postgres-plan.md` in the EventHarbor repository.

The plan includes verified network/capacity observations, separate restricted roles for **both** applications, private connectivity, rehearsal and final-copy checks, a brief write freeze, all API/processor/job and effective GitHub secret updates, rollback after new writes, and 24-48 hours of capacity observation before source retirement. Do not delete the source based only on a short smoke test. A stopped source retains storage charges and automatically restarts after seven days.

The approximately $16.09 per 730-hour month server-retirement comparison is before allowances, traffic, backup changes, discounts, and tax. September's shared free database compute/storage amounts were already consumed across historical servers. The screenshot's service costs are month-to-date amounts, not monthly rates. Database consolidation alone does not deliver the approximately $20 total Azure target while existing Container Apps networking remains.

Keep the original Azure deployment files intact. This plan does not deploy the replacement VMs, change public DNS, remove live networking, or authorize a blind replay of the old production workflow. See [interim-cost-reduction.md](interim-cost-reduction.md) for the already recorded API resize and [azure-economy.md](azure-economy.md) for the separate VM alternative.
