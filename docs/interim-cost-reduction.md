# Interim Azure API sizing

The additive `scripts/azure-economy/resize-existing-api.ps1` script reduces the existing API from 0.5 vCPU / 1 GiB to 0.25 vCPU / 0.5 GiB without changing its image, warm replica count, database, secrets, domain, or worker. It requires PowerShell 7.4 or later.

Inspect without changes:

```powershell
.\scripts\azure-economy\resize-existing-api.ps1 `
  -SubscriptionId "83099284-9ad4-4140-b8fe-8388b6d98a98" `
  -Project pulseexchange
```

Add `-Apply` to resize. Add `-Apply -Restore` to restore the previous allocation on a healthy app. A failed or unhealthy rollout requires reviewing its active revisions before recovery, not blindly repeating an update.

The previous Azure templates and production workflow remain unchanged. A future run of that workflow can restore its larger default size. Reapply this optional interim resize afterward if appropriate.

Applied September 29, 2026 UTC: the API moved from `pulseexchange-api-prod--0000006` to `pulseexchange-api-prod--0000007`. The new revision was Healthy, with one warm replica and the same immutable image. The real REST/WebSocket/reconnect/cancellation smoke test passed after the resize. No worker, database, domain, or old deployment file was changed.

This does not deploy the replacement VMs or switch databases to a different service. The existing databases are already B1ms/32 GiB. September billing records show the shared PostgreSQL free compute and data-storage allowances were consumed; creating another server would not reset them. The later consolidated database design, separate application roles, verified data migration, and removal of old resources are still needed.

After applying, check the live health and readiness endpoints and run the existing real-demo smoke test:

```powershell
$env:PULSEEXCHANGE_SMOKE_URL = "https://pulseexchange.irfanburakozer.com"
python .\scripts\smoke.py
```

This places fictional demo orders, verifies a stored match and WebSocket updates, and cancels its resting test order. It is not a read-only check.

The shared [EventHarbor interim runbook](../../eventharbor/docs/interim-cost-reduction.md) in the multi-project workspace records the usage evidence, cost assumptions, safeguards, and rollout checks. Its relative link is only available when the sibling project is present.
