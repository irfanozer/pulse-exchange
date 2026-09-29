# PulseExchange VM runtime

This additive runtime reuses public GHCR images from the existing production image workflow on one x86-64 Ubuntu 24.04 VM. It does not build images or run a local database. Both projects use separate databases and application roles on a shared Azure PostgreSQL Flexible Server B1ms, reached by private networking and TLS.

## Host and bootstrap contract

- Install Docker Engine, the Compose v2 plugin (minimum 2.20), Python 3, util-linux/flock, and curl. Enable Docker at boot.
- Copy this directory's public runtime files to /opt/pulseexchange/runtime as root, then run `sudo bash /opt/pulseexchange/runtime/install.sh`. The installer sets file ownership/modes and installs the maintenance units. It does not create secret files or start the app.
- The deploy controller's fixed bundle consists of compose.yaml, Caddyfile, nginx.conf.template, README.md, runtime.env.example, validate_env.py, install.sh, deploy.sh, maintenance.sh, pulseexchange-maintenance.service, pulseexchange-maintenance.timer. test_runtime.py is an offline test, not a host requirement.
- All bundle files must use LF line endings. The runtime directory is root:root 0750, scripts 0750, and non-secret configuration 0640. The two possible container-readable bind mounts, nginx.conf.template and worker-health.py, are 0644.
- The NSG allows public TCP 80/443 to Caddy only. SSH is restricted to an operator CIDR. No API, processor, receiver, Docker daemon, or PostgreSQL port is published.
- The Docker edge subnet 172.29.240.0/28 must not overlap the VM VNet or other host routes. Caddy is 172.29.240.2, Nginx is 172.29.240.3. Nginx trusts only that Caddy address for client IP reconstruction. Caddy replaces incoming client identity headers. Existing routes, body/rate limits, and browser headers are preserved in the additive Nginx overlay.
- Private DNS must resolve the Azure PostgreSQL hostname to its private address on this VM. The managed server must disable public access. The application role is restricted to this project's database; do not give it the server admin account. PostgreSQL backup and restore remain managed server operations.

## Secret input and release command

Create /etc/pulseexchange/runtime.env from runtime.env.example through a secure operator channel, owned root:root with mode 0600. It is the canonical editable input. Do not put its contents in VM custom data, command arguments, source control, public deployment outputs, or a storage bundle.

The input permits only PUBLIC_HOSTNAME, ACME_EMAIL, CADDY_IMAGE, and PULSEEXCHANGE_DATABASE_URL. Use raw KEY=value lines with no quoting or interpolation. Percent-encode reserved characters in the username/password. Use the ordinary `<server>.postgres.database.azure.com` hostname, which resolves privately, and the database name pulseexchange. The example requests `ssl=verify-full`. PulseExchange rejects missing TLS, disabled TLS, and sslmode= parameters; asyncpg expects ssl=.

Use the VM's Azure DNS hostname in PUBLIC_HOSTNAME for pre-cutover HTTPS. That hostname must resolve publicly to the VM, with ports 80/443 reachable for ACME. Later replace it with the existing custom hostname and redeploy after the DNS cutover plan is approved. The configured hostname is the only accepted browser origin. Caddy certificate data persists in Docker volumes; the configuration contains no ACME private keys.

Resolve the existing GHCR commit tags to their published digest before deployment. Then run as root:

```sh
/opt/pulseexchange/runtime/deploy.sh \
  ghcr.io/OWNER/REPOSITORY-backend@sha256:BACKEND_DIGEST \
  ghcr.io/OWNER/REPOSITORY-frontend@sha256:FRONTEND_DIGEST \
  /etc/pulseexchange/runtime.env
```

Replace the uppercase placeholders, including OWNER/REPOSITORY, with real lowercase GHCR image names and 64-character digest values. Floating tags and commit tags are rejected. No registry credentials are needed for public images. The Caddy example is pinned to official 2.11.4-alpine index digest sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b, verified against Docker Hub on 2026-09-28. Review and update that digest deliberately for security releases.

Deployment serializes with maintenance using /run/lock/pulseexchange-runtime.lock, validates the dotenv input without evaluating it, pulls images, validates Caddy, disables the timer during changes, runs the existing Alembic migration, briefly stops app containers to avoid duplicate memory usage, and waits for internal health checks, then runs the existing seed command. Application deployment therefore has a short outage. Image builds stay in CI.

On success, /etc/pulseexchange/current.env contains the validated input plus exact release images and becomes the maintenance source. /etc/pulseexchange/previous.env retains the preceding release; /etc/pulseexchange/failed.env retains the last failed candidate. Every file is root:root 0600. These files are secret configurations, not database backups. Copy them only to an approved encrypted operator backup if recovery requirements need it.

Deployment logs are root-only in /var/log/pulseexchange; host commands emit no secret contents. Docker metadata still contains the application connection URL, so root and Docker access are equivalent to secret access. Do not share docker inspect, full Compose config, or raw logs. Logs are bounded: container logs 2 x 5 MiB each; deploy log rotates after 10 MiB and maintenance after 5 MiB, retaining one previous file.

## Maintenance, limits, and recovery

The existing pulseexchange.maintenance command resets fictional market state and reseeds through the internal API. Its PostgreSQL advisory lock coordinates with the processor; identities continue increasing. The API and processor must remain running during reseeding. The timer runs around 04:00 UTC daily with a five-minute randomized delay and catches up after reboot. A held deployment/maintenance flock skips an overlapping timer invocation. Container jobs retain their existing database-level locks as well. Inspect timer failures with `systemctl status pulseexchange-maintenance.service`; root-only logs contain details.

Caddy 64 MiB + Nginx 64 MiB + API 192 MiB + processor 192 MiB = 512 MiB of configured resident-memory limits. One serialized migration, seed, or maintenance container adds at most 128 MiB. These limits are not reservations or measured usage. The deployed 1 GiB B2ats_v2 hosts reported only about 846 MiB usable RAM and 390-404 MiB available before application startup, with Azure agents already running. Therefore, do not assume 384 MiB remains for the host at all container maxima. Image pulls, extraction, health probes, and deployment jobs also need transient headroom. Do not build images on these VMs.

The installer adds a fixed 2 GiB swap file at `/var/lib/azure_economy/swapfile` on the existing ext4 OS filesystem. The deployment controller first stages its validated public files and invokes `install.sh --prepare-swap-only`, which exits after swap verification without copying active runtime files or changing maintenance units. It then pulls and verifies both images before running the full installer and deployment. The installer accepts only no arguments or that single preparation flag. It uses root:root 0600 inside a 0700 directory, verifies the swap signature and size on repeat runs, persists it through `var-lib-azure_economy-swapfile.swap`, and sets `vm.swappiness=10` through its own sysctl file. It never resizes a disk, adds a cloud resource, overwrites a different file, reformats existing swap, edits fstab, or disables another swap. Existing active/fstab swap, conflicting configuration, unexpected filesystem, insufficient disk space, or unsafe permissions stop installation for operator review. It requires 8 GiB to remain free after allocation. A partial failed first allocation is retained for inspection, not silently overwritten on retry. OS disk encryption remains the foundation's responsibility; swap and OS disk snapshots can contain application credentials and require the same access protection as other secrets.

Swap is a slow burst/OOM cushion, not additional RAM capacity or a guarantee against OOM. Low swappiness makes disk swapping less attractive; it is not a percentage threshold. Docker's default with `mem_limit` and no `memswap_limit` permits an additional swap allowance equal to that container's memory limit when host swap exists. Container limits and the 2 GiB host file remain bounded. See [Docker memory and swap limits](https://docs.docker.com/engine/containers/resource_constraints/) and [Linux swappiness](https://docs.kernel.org/admin-guide/sysctl/vm.html#swappiness).

Before DNS cutover, verify the swap unit survives reboot, `swapon --show` reports only the intended file, and `sysctl vm.swappiness` returns 10. Measure actual RSS, available RAM, swap-in/out (`vmstat 1`), pressure (`/proc/pressure/memory`), Docker OOM/restart counts, disk free space, CPU credits, and PostgreSQL connections during image pull, migration, bounded smoke/load tests, and maintenance. Sustained swap traffic, latency regression, OOM, or insufficient headroom fails the soak test; a large unused swap file alone does not prove capacity.

Containers use read-only root filesystems, dropped capabilities, bounded temporary filesystems, PID limits, restart policies, and bounded local logs. Caddy retains only NET_BIND_SERVICE; application images keep their existing non-root users. Jobs are serialized and never enabled as always-running services. Database pools are 2 connections with no overflow per long-running database process, 1 for maintenance.

The processor uses its existing heartbeat-backed /ready probe; API readiness requires a fresh processor heartbeat. Existing /api routes and WebSocket upgrade behavior remain at the same public origin. The application uses only Nginx's overwritten client headers for visitor limits; the API port remains unpublished.

Docker restarts containers after process exit. Docker health state alone does not restart a hung process: monitor health failures and restart deliberately after diagnosis. A failed deployment does not reverse schema changes or silently claim rollback. After a migration/start failure, the maintenance timer stays disabled; inspect the protected logs, check schema compatibility, and rerun deploy.sh with a known-good digest pair and the appropriate saved input. previous.env can be passed as the secret input. Restore the managed database only through a reviewed PostgreSQL restore procedure, then update the connection URL if the restore creates a new server.

Before production DNS changes, verify public HTTPS, the project's existing smoke script including the live WebSocket and order flow, reboot recovery, private database reachability, and managed database restore. Internal Compose readiness is not evidence of browser TLS issuance or an end-to-end cloud deployment.

## Offline validation

Run `python test_runtime.py` here. To parse Compose without a running engine, provide harmless digest-shaped BACKEND_IMAGE and FRONTEND_IMAGE environment values, then run `docker compose --env-file runtime.env.example --profile tasks config --quiet` from this directory. Do not use a real secret file for printed config validation. Bash syntax checks and these offline tests do not verify image architecture, executable imports, production TLS, memory use, or runtime behavior.
