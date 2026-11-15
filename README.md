# dripcloud

GitOps for the labmox homelab cluster.

## Web search and scraping

Argo CD manages SearXNG and the complete Firecrawl stack in
`beamray-agent-services` through `apps/searxng.yaml`, `apps/firecrawl.yaml`,
and `apps/firecrawl-network.yaml`. These adopt the existing workloads, storage,
and Tailscale endpoints. Credentials are encrypted with Sealed Secrets; data
claims are protected from automatic pruning.

See [Firecrawl operations](manifests/firecrawl/README.md),
[SearXNG](manifests/searxng/README.md), and
[network isolation](manifests/firecrawl-network/README.md).

## BeamRay development

`apps/beamray-dev-workloads.yaml` is the parent Application for the private
BeamRay development environment. It applies the app-of-apps manifests from the
separate `beamray-dev` repository. All BeamRay child Applications target the
`development` namespace with namespace creation disabled. Namespace-level
workload guardrails live with the parent render.

This repository owns everything that bounds what the `beamray-dev` repository
can do (`infrastructure/beamray-dev-guardrails.yaml` and
`infrastructure/beamray-dev-admissionpolicy.yaml`):

- the `development` Namespace and its restricted Pod Security labels
- the `beamray-dev-parent` AppProject: namespaced kinds only, in `argocd` and
  `development`
- admission policies that only let the parent manage child Applications in
  the `beamray-dev` project and the `beamray-dev` AppProject itself, within
  fixed source, destination and kind limits, and that limit Service/Ingress
  exposure in `development`

## DripCraft

`apps/dripcraft-public.yaml` runs the Minecraft server: a whitelisted Paper
server in its own `dripcraft-public` namespace, reached through a playit.gg
tunnel. Its manifests live in [sbrerup/dripcraft](https://github.com/sbrerup/dripcraft).

`apps/dripcraft-admin.yaml` runs its admin panel, reachable only on the tailnet, in
its own `dripcraft-admin` namespace. The panel changes settings by committing to
sbrerup/dripcraft. Its code and manifests live in
[sbrerup/mc-server-ui](https://github.com/sbrerup/mc-server-ui), whose README covers
the Secret that has to be created by hand.

`apps/dripcraft-ledger.yaml` runs the ledger, which keeps a lasting record of what
members do on the server. It reads the archive in `dripcraft-public` through its feed
and runs in its own `dripcraft-ledger` namespace, with a PostgreSQL of its own made by
the CloudNativePG operator. Its code and manifests live in the private repository
`sbrerup/dripcraft-ledger`. Because that repository and its image are private, Argo CD
needs read access to the repository and the cluster needs a pull Secret for the image.
Both are made by hand and live only in the cluster, and that repository's README covers
them.

## Talos

The cluster runs on [Talos Linux](https://www.talos.dev/), an immutable,
API-managed Linux distribution built for Kubernetes. Nodes have no SSH or shell;
they are configured through machine config and `talosctl`. This layer sits below
Argo CD, so changes to it are applied by hand rather than synced from `main`.

- `clusters/labmox/terraform` creates the node VMs on Proxmox from template VM
  `8000`.
- `clusters/labmox/talos/boostrap.sh` generates the machine config and secrets,
  applies the patches, bootstraps etcd, and fetches the kubeconfig. Generated
  files are ignored by Git.
- `clusters/labmox/talos/patches` allows workloads on the control plane and
  turns off the default CNI and kube-proxy, because Cilium (`values.yaml`)
  replaces both. It also defines `local-volume`, mounted at
  `/var/mnt/local-volume`, which backs the local-path provisioner.

## Read-only access for daedalus

`apps/daedalus-access.yaml` gives daedalus, the VM that Claude Code sessions run on,
an account that can look at the cluster and change nothing. The ServiceAccount
`daedalus` in the `daedalus-access` namespace is bound to two roles:

- `view`, the read-only role built into Kubernetes, in every namespace: workloads, their
  logs, config maps, events. It leaves out Secrets, and it cannot run a command in a pod,
  forward a port or change anything.
- `daedalus-read-extra`, for what `view` leaves out: the node and its storage, the Argo CD
  applications, the CloudNativePG databases and the network rules.

So daedalus can see whether something has rolled out and why it fails, and the things
that change the cluster (a restart, a command in a pod, a sync) stay with a person.
`tests/test_daedalus_access.py` holds the account to reading.

The Secret `daedalus-token` holds the token of the account, which the cluster fills in. It
is copied into the kubeconfig on daedalus by hand and is in no repository. To revoke it,
delete the Secret: Argo CD has a new one made, and the old token stops working.

## Commands a person approves (cerberus)

`apps/cerberus.yaml` runs cerberus, the page where the owner approves single `kubectl`
commands that daedalus asks for. When something has to change, daedalus files a request
with the exact command and the reason. The owner reads it on the page, which only his
own devices can reach on the tailnet, and approves or denies. cerberus runs an approved
command once, as cluster admin, and records who approved it and how it ended on the
request itself (`kubectl -n cerberus get cmdreq`).

Filing and reading those requests is the one thing the daedalus account may do beyond
reading, and that permission lives with cerberus, not here. The code, the manifests and
the reasoning behind each safeguard are in
[sbrerup/cerberus](https://github.com/sbrerup/cerberus).

cerberus is the one workload in this cluster with cluster-admin rights that takes
requests from a machine. Read that repository's README before changing its roles, the
tag on its ingress or its network policies.

## Updates

- **Proxmox host:** Debian security updates install automatically every day
  (`/etc/apt/apt.conf.d/52unattended-upgrades-labmox`; no automatic reboots).
  Proxmox packages and kernels stay manual: once a month run
  `apt update && apt full-upgrade` on labmox and reboot if a new kernel came in.
- **Cluster:** Renovate (`renovate.json5`) opens weekly PRs for container images,
  Helm charts and GitHub Actions. Nothing auto-merges, because Argo CD deploys
  `main` as soon as it changes. Major updates wait for approval
  on the Dependency Dashboard issue.
- **Talos and Kubernetes:** upgraded by hand with `talosctl`.
