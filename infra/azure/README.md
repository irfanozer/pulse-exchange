# Azure infrastructure contract

PulseExchange is deployed as five runtime resources inside one Azure Container
Apps environment:

- a warm public React/Nginx web app running unprivileged on port 8080;
- a warm internal FastAPI app;
- one continuously running matching service;
- a manual Alembic migration job and a manual starter-market seed job;
- a scheduled reset-and-reseed job for the disposable public demo.

`foundation.bicep` creates the VNet-integrated Container Apps environment,
Log Analytics workspace, private DNS, and private PostgreSQL Flexible Server.
`migration.bicep` defines the pre-release database job. `apps.bicep` defines
the application topology, explicit health probes, fixed production scaling,
resource limits, and the custom-domain certificate binding.

Only the web app has public ingress. The database has no public network path.
The API is reached from Nginx through Container Apps service discovery, and
the matching service has no ingress. Images are immutable GHCR digests built
from the Git commit that passed CI.

The database URL is always supplied as a secure deployment parameter and then
stored as a Container Apps secret. It must contain `?ssl=require`. Never place
it in `parameters.example.json` or any committed file.

The custom hostname and managed-certificate resource ID are parameters on
every normal deployment and rollback. The release workflow discovers an
existing binding before mutation and can be configured to fail closed if the
binding disappears.
