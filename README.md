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

Minecraft is managed through Crafty Controller instead of declaring server
plugins and generated configuration in GitOps.

Argo CD owns:

- the Crafty workload
- the retained PVC
- LAN load balancer services (game ports only)
- the Tailscale Ingress for the Crafty panel
- the Cilium load balancer IP pool
- NetworkPolicies isolating Crafty from the LAN and the rest of the cluster

Crafty owns:

- Minecraft server creation
- plugins, datapacks, and generated config
- server console access
- server file editing and uploads
- Minecraft-level backup schedules

The Crafty panel is exposed only on the tailnet at `https://crafty`. It is not
on the LAN load balancer (`10.1.2.250`), which carries game and map ports only.

The Dripcraft portal is exposed through Tailscale as `https://dripcraft`.
It creates Crafty servers and matching Tailscale `LoadBalancer` Services in one
operation. After creating a server, it redirects to Crafty for detailed server
management.

World map viewers are exposed through Tailscale when the matching Minecraft
server plugin is installed and listening inside Crafty:

- BlueMap 3D map: `https://dripcraft-map` -> Crafty port `8100`
- Dynmap 2D/isometric map: `https://dripcraft-dynmap` -> Crafty port `8123`

Browser gameplay runs at `https://dripcraft-play` through `apps/dripcraft-play.yaml`:
the open-source Minecraft Web Client plus a relay with Microsoft login, in the
`dripcraft-play` namespace. See [Dripcraft Play](manifests/dripcraft-play/README.md).

Operational notes:

- Keep the Crafty image pinned and take a data backup before bumping it.
- Create and delete Minecraft servers through the Dripcraft portal when you want
  Tailscale networking to follow the server lifecycle automatically.
- Servers created directly in Crafty can be pulled into Tailnet exposure with
  the portal's `Sync` button.
- Create the Skyblock server on port `25565`; add more Service ports if you
  want Crafty-managed secondary servers reachable from the LAN.
- Keep Minecraft's configured max heap below the pod memory limit. With the
  current `11Gi` pod limit, leave headroom for Crafty, plugins, and native
  memory instead of assigning the whole pod limit to the Java heap.
- BlueMap/Dynmap are map viewers, not full browser gameplay. Install and
  configure the chosen plugin through Crafty for the server you want to view;
  only one server can use each configured web-map port unless you add more
  Service ports and Ingresses.
- Crafty backups live on the same retained local PVC as the server data. For a
  true forever server, also back up `/crafty/servers`, `/crafty/backups`, and
  `/crafty/app/config` off the Kubernetes node.

Portal setup:

```powershell
kubectl -n dripcraft create secret generic dripcraft-portal-crafty `
  --from-literal=apiToken='CRAFTY_API_TOKEN'
```

If GHCR publishes the portal image as private, either make the package public or
add an image pull secret for `ghcr.io/sbrerup/dripcraft-portal:latest`.

## Updates

- **Proxmox host:** Debian security updates install automatically every day
  (`/etc/apt/apt.conf.d/52unattended-upgrades-labmox`; no automatic reboots).
  Proxmox packages and kernels stay manual: once a month run
  `apt update && apt full-upgrade` on labmox and reboot if a new kernel came in.
- **Cluster:** Renovate (`renovate.json5`) opens weekly PRs for container images,
  Helm charts and GitHub Actions. Nothing auto-merges, because Argo CD deploys
  `main` as soon as it changes. Major updates and Crafty bumps wait for approval
  on the Dependency Dashboard issue.
- **Talos and Kubernetes:** upgraded by hand with `talosctl`.
