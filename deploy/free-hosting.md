# Proposed zero-cost hosting: Oracle Always Free + DuckDNS

Checked against official sources on 2026-10-12. This is a deployment proposal; no account, VM, hostname or public service has been provisioned.

## Choice and cost boundary

Use one Always Free eligible OCI Ampere A1 VM in the account's home region, with 2 OCPUs, up to 12 GB RAM and a 100 GB boot volume to leave backup/build headroom. Oracle's current free-tenancy A1 allowance is 1,500 OCPU-hours/9,000 GB-hours per month (equivalent to 2 OCPUs/12 GB), and 200 GB combined boot/block storage. The earlier 4 CPU/24 GB allowance is not the allowance assumed here. Check the account's console before provisioning. [Oracle limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)

This is the best architectural fit among the evaluated free options because a VM can keep SQLite on persistent local disk and run the queue continuously. That is an engineering inference, not a tested uptime promise. Free capacity can be unavailable and idle VMs may be reclaimed. Oracle requires card verification, may place a temporary authorization hold, and provides no Free Tier SLA. The user must handle identity/payment/contract steps. Remain within Always Free eligible resources and do not upgrade/create paid resources to bypass a capacity problem. [Oracle Free Tier FAQ](https://www.oracle.com/cloud/free/faq/)

For a free hostname, register a DuckDNS subdomain and point it at the VM public IP. DuckDNS provides free dynamic DNS; account creation and chosen hostname remain user steps. Keep its update token private and out of source. [DuckDNS](https://www.duckdns.org/)

Render Free was evaluated and rejected for the current architecture: it sleeps after 15 idle minutes and discards local filesystem changes; its free database also expires after 30 days. It requires a different external durable database and cannot promise continuous webhook delivery. [Render free limits](https://render.com/docs/free)

## Deployment steps

1. Create the OCI account yourself and choose a home region with available Always Free A1 capacity. Choose an Always Free eligible Ubuntu ARM image. Keep total A1/storage allocation within the current allowance; review the estimated price and eligibility labels before creating anything.
2. Create the VM with SSH-key access and persistent boot volume. Preserve the private key locally. Permit public HTTP/HTTPS and restrict SSH to your address through OCI and host firewall rules. No firewall changes have been made by this project.
3. Register your DuckDNS name, set its public IP and verify DNS resolution. HTTPS certificate validation needs the hostname to reach this server on ports 80/443.
4. Install Docker Engine/Compose using [Docker's official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/). Copy the release source bundle into your chosen server folder. Exclude local backend/data, .venv, node_modules and real environment files from source transfer.
5. Configure the domain/encryption key, backups and operator account using operations.md. Build on the VM so base images and native wheels target ARM. ARM image and full container smoke passed locally under emulation; native OCI runtime, storage/network behavior and resource capacity still require target checks.
6. Run the prepared production compose stack only after intentionally approving that deployment, then complete the launch gate in operations.md. Keep the image digest/key/backup together as a recovery record; retain off-VM backups to handle reclamation.

If account/card verification or capacity prevents provisioning, do not call the deployment free/complete. A reliable production deployment may require paid hosting; no free provider guarantees both availability and a commercial uptime SLA. Do not manufacture activity to evade idle-reclamation rules.
