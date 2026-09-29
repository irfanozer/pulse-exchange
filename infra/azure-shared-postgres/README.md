# Shared PostgreSQL application deployment profile

These additive templates and `.github/workflows/deploy-shared-postgres.yml`
preserve the reviewed shared-server settings on later releases. They do not
create or migrate a database. Complete the EventHarbor shared PostgreSQL
migration procedure and verify the restricted application role before use.

The API uses 0.25 vCPU and 0.5 GiB RAM. API, processor, maintenance, and migration
jobs each use two pooled database connections with no overflow. The processor
checks for idle work every 500 milliseconds. The seed job talks to the API and
does not connect directly to PostgreSQL. Images, secret names, domains, replica
limits, other resource sizes, and the 04:00 UTC maintenance schedule stay the
same. All original Azure deployment files are retained.

## Opt in only after the verified cutover

The profile is off by default. Both image publishing and deployment require the
repository variable `AZURE_SHARED_DEPLOYMENT_ENABLED=true`.

1. Finish and verify the controlled migration. Keep the existing
   `PULSEEXCHANGE_DATABASE_URL` secret in the `production` environment updated
   with the verified application connection string. It must retain `ssl=require`.
   Never commit the connection string. This workflow does not change it.
2. Set `AZURE_DEPLOYMENT_ENABLED=false` in every scope where it is defined,
   including `production`, and disable the original production workflow in
   GitHub Actions. Keep its file. Disabling it also prevents duplicate image
   builds because the original image job is not gated by its deployment flag.
3. Set the shared opt-in variable at repository scope. Run **Publish images and
   deploy shared PostgreSQL** on `main` after its normal CI succeeds.

Keep exactly one deployment profile enabled. Both new jobs reject the old flag
when it is `true` in their effective scope. The existing production environment,
concurrency group, permissions, OIDC settings, domain preservation, migration,
seed, runtime checks, and rollback behavior are retained. Only application and
migration template paths change, including application rollback.

The original profile would restore its original resource sizes and connection
pools if re-enabled. It is not a database rollback procedure. Reduced usage is
not a guarantee of free-tier eligibility or a zero bill.

Offline profile checks do not access Azure:

```sh
python tests/shared_postgres/test_deployment_profile.py
```
