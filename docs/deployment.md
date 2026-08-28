# Deploy PulseExchange to Azure

This guide publishes the public repository, builds immutable images in GitHub
Actions, and deploys PulseExchange at
`https://pulseexchange.irfanburakozer.com`.

## What Azure runs

```text
Browser
  |
  v
Cloudflare DNS (DNS only)
  |
  v
Public web Container App (React + unprivileged Nginx, always warm)
  |
  +-- /api/* and WebSocket --> Internal FastAPI Container App (always warm)
                                    |
                                    +--> Private PostgreSQL Flexible Server

Matching service Container App --> Private PostgreSQL (exactly one replica)
Migration job -------------------> Private PostgreSQL (manual per release)
Seed job ------------------------> Internal API (manual per release)
Daily maintenance job ----------> reset fictional rows, then seed through API
```

Only the web app has public ingress. PostgreSQL has public access disabled.
The API is reachable only inside the Container Apps environment, and the
matching service has no ingress. Azure Container Apps terminates TLS and
supports the WebSocket used by the live page.

The application, API, and matching service stay at one warm replica. This is
intentional for a recruiter demo: it prevents a long cold first request and
keeps the process-local public-demo limits from multiplying across replicas.

## Cost boundary

Do not run the foundation script until you intend to create billable Azure
resources. It creates a new PostgreSQL Flexible Server, 32 GiB of storage, a
Container Apps environment, three warm application replicas, private DNS, and
Log Analytics. Azure managed certificates, Cloudflare DNS-only records, public
GHCR packages, and the VNet have no separate expected charge, but compute,
database, storage, logs, and network usage can be billed.

Azure free-service allowances and credits are subscription-wide, not per
project. EventHarbor can already be consuming the same PostgreSQL and Container
Apps allowance. Confirm the remaining benefit under **Azure Portal >
Subscriptions > Free services**, check the Azure pricing calculator for your
region, and create budget alerts before provisioning. Budget alerts notify;
they do not stop resources.

The default templates deliberately create a separate PulseExchange foundation
instead of coupling it to EventHarbor. Reusing the EventHarbor database server
could reduce cost, but is not automated by this repository and increases the
blast radius between portfolio projects.

## Prerequisites

- Public GitHub repository: `irfanozer/pulse-exchange`
- Azure subscription with permission to create resources and role assignments
- `irfanburakozer.com` managed in Cloudflare
- Azure CLI and GitHub CLI installed
- PowerShell 7 recommended

Sign in once:

```powershell
az login
az account list --output table
gh auth login
gh auth status
```

Run the remaining commands from the real Git repository root. Never commit
`.env`, database URLs, passwords, Azure credentials, or tokens.

## 1. Commit and push

```powershell
git remote -v
git status
git add .
git commit -m "Prepare PulseExchange production deployment"
git push -u origin main
```

Wait for **GitHub > Actions > CI** to succeed. The successful CI run triggers
**Publish images and deploy production**. At this point the workflow builds and
publishes images but skips Azure because the bootstrap script leaves
`AZURE_DEPLOYMENT_ENABLED=false`.

## 2. Make the two GHCR packages public once

The workflow publishes:

- `ghcr.io/irfanozer/pulse-exchange-backend:<commit-sha>`
- `ghcr.io/irfanozer/pulse-exchange-frontend:<commit-sha>`

A public repository does not automatically make its container packages public.
Open each package from the repository's **Packages** section, choose **Package
settings**, then **Danger Zone > Change package visibility > Public**.

Azure can then pull the images anonymously. No GitHub password or permanent
container-registry token is stored in Azure.

## 3. Create the Azure foundation

Copy the subscription ID from `az account list --output table`, review the cost
boundary above, then run:

```powershell
.\scripts\azure\bootstrap-foundation.ps1 `
  -SubscriptionId "YOUR_AZURE_SUBSCRIPTION_ID" `
  -GitHubRepository "irfanozer/pulse-exchange" `
  -Location "eastus2" `
  -ConfirmCosts
```

The script:

1. creates `rg-pulseexchange-prod`;
2. deploys the VNet, private DNS, Log Analytics, Container Apps environment,
   private PostgreSQL server, and database;
3. generates a strong database password without printing it;
4. stores the TLS-required URL as the masked GitHub secret
   `PULSEEXCHANGE_DATABASE_URL`;
5. creates the non-secret GitHub Actions variables;
6. leaves deployment disabled until the next steps are complete.

The GitHub secret is not retrievable later. If it is lost, rotate the PostgreSQL
password and replace the secret; do not paste it into source control.

## 4. Configure passwordless GitHub-to-Azure access

```powershell
.\scripts\azure\configure-github-oidc.ps1 `
  -SubscriptionId "YOUR_AZURE_SUBSCRIPTION_ID" `
  -GitHubOwner "irfanozer" `
  -GitHubRepository "pulse-exchange" `
  -ConfigureGitHub
```

This creates the GitHub `production` environment, a dedicated Microsoft Entra
application/service principal, Contributor access only on the PulseExchange
resource group, and a federated credential. It does not create an Azure client
secret or password.

For this repository, the expected immutable GitHub subject is:

```text
repo:irfanozer@56190015/pulse-exchange@1346864837:environment:production
```

The exact owner and repository IDs are read from GitHub by the script. This
avoids the `AADSTS700213` mismatch that occurs when the Azure credential uses a
different owner, repository, branch, or environment subject.

## 5. Enable and run the first deployment

Confirm these values under **GitHub repository > Settings > Secrets and
variables > Actions**:

- Secret: `PULSEEXCHANGE_DATABASE_URL`
- Variables: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
  `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_NAME_PREFIX`,
  `AZURE_ENVIRONMENT_NAME`, `AZURE_CONTAINER_APPS_ENVIRONMENT`,
  `PULSEEXCHANGE_CUSTOM_DOMAIN`, `PULSEEXCHANGE_REQUIRE_CUSTOM_DOMAIN`, and
  `AZURE_DEPLOYMENT_ENABLED`

Enable deployment:

```powershell
gh variable set AZURE_DEPLOYMENT_ENABLED `
  --repo "irfanozer/pulse-exchange" `
  --body "true"
```

Open **GitHub > Actions > Publish images and deploy production > Run workflow**
and select `main`.

The release is serialized and performs this order:

1. publish the tested commit as immutable image digests;
2. sign in to Azure with a short-lived GitHub OIDC token;
3. compile the Bicep templates;
4. deploy, start, and await the private Alembic migration job;
5. preserve any existing custom hostname and certificate;
6. deploy the matching service, internal API, public web app, and maintenance
   jobs;
7. run the idempotent starter-market job;
8. verify health, processor readiness, REST matching, a real WebSocket update,
   reconnect recovery, and cancellation;
9. restore the previous application image digests if live verification fails.

The workflow never runs `alembic downgrade`. Future schema changes must use
backward-compatible expand/contract migrations so the previous application
image remains a safe emergency rollback.

The first workflow summary contains the generated Azure URL. Open that URL and
confirm the live demo before configuring DNS.

## 6. Configure Cloudflare and the managed certificate

Print the exact values from Azure:

```powershell
.\scripts\azure\show-domain-records.ps1 `
  -SubscriptionId "YOUR_AZURE_SUBSCRIPTION_ID"
```

Create the printed records in **Cloudflare > DNS > Records**:

| Type | Name | Target/value | Proxy status |
| --- | --- | --- | --- |
| CNAME | `pulseexchange` | generated `azurecontainerapps.io` hostname | **DNS only** |
| TXT | `asuid.pulseexchange` | Azure verification ID | n/a |

If the zone already contains any CAA record, also allow DigiCert:

| Type | Name | Flags | Tag | CA domain |
| --- | --- | ---: | --- | --- |
| CAA | `@` | `0` | `issue` | `digicert.com` |

Keep the CNAME gray-cloud **DNS only**. Azure requires the CNAME to point
directly to the generated Container Apps hostname for managed-certificate
issuance and renewal.

After DNS resolves:

1. open **Azure Portal > Container Apps > pulseexchange-web-prod**;
2. choose **Networking > Custom domains > Add custom domain**;
3. enter `pulseexchange.irfanburakozer.com`;
4. choose an Azure managed certificate and CNAME validation;
5. wait until the domain shows **Secured**;
6. open the HTTPS URL in a private browser window.

Finally, make future deployments fail closed if the binding disappears:

```powershell
gh variable set PULSEEXCHANGE_REQUIRE_CUSTOM_DOMAIN `
  --repo "irfanozer/pulse-exchange" `
  --body "true"
```

Every later normal deployment and automatic rollback passes the existing
hostname and managed-certificate resource ID back into Bicep. If the required
certificate cannot be found, the workflow stops before changing the web app.

## 7. Verify production yourself

```powershell
$baseUrl = "https://pulseexchange.irfanburakozer.com"
Invoke-RestMethod "$baseUrl/healthz"
Invoke-RestMethod "$baseUrl/health/ready"
Invoke-RestMethod "$baseUrl/api/v1/diagnostics/summary"

$env:PULSEEXCHANGE_SMOKE_URL = $baseUrl
backend\.venv\Scripts\python.exe scripts\smoke.py
```

Expected evidence:

- `/health/ready` returns `status: ok`, `processor_running: true`, and
  `event_relay_running: true`;
- diagnostics reports the matching service online and the queue returning to
  zero;
- the smoke script confirms REST persistence, a matching trade, a WebSocket
  update, disconnect/reconnect recovery, and cancellation;
- the browser shows populated NOVA and ORBIT starter markets.

## Ongoing operations

- The public web, API, and matching service stay warm at one replica.
- The matching service must never use `minReplicas: 0`; it has no external
  event scaler to wake it when a database command arrives.
- At 04:00 UTC, the maintenance job takes the same PostgreSQL advisory lock as
  the matching service, removes only fictional simulator rows without resetting
  sequence identities, and reseeds through the public API.
- A hard 10,000-command database ceiling prevents unbounded growth if scheduled
  maintenance fails.
- `/metrics` is not public. The reduced diagnostics endpoint remains public
  because it supplies evidence shown by the demo and contains no personal or
  financial data.
- Check Azure costs, job failures, database storage, 5xx responses, stale
  processor heartbeat, and queue age.

To pause future releases without deleting Azure resources:

```powershell
gh variable set AZURE_DEPLOYMENT_ENABLED `
  --repo "irfanozer/pulse-exchange" `
  --body "false"
```

This does not stop billing. Deleting `rg-pulseexchange-prod` is the complete
cost stop, but it permanently deletes the database and all PulseExchange Azure
resources. Export anything you need before deleting the group.
