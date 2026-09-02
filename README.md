# dripcloud

GitOps for the labmox homelab cluster.

## BeamRay development

`apps/beamray-dev-workloads.yaml` is the parent Application for the private
BeamRay development environment. It creates the `development` namespace and
applies the app-of-apps manifests from the separate `beamray-dev` repository.
All BeamRay child Applications target that namespace with namespace creation
disabled. Namespace-level workload guardrails live with the parent render;
cluster-scoped admission policies remain in this repository.

## DripCraft

Minecraft is managed through Crafty Controller instead of declaring server
plugins and generated configuration in GitOps.

Argo CD owns:

- the Crafty workload
- the retained PVC
- LAN load balancer services
- the Cilium load balancer IP pool

Crafty owns:

- Minecraft server creation
- plugins, datapacks, and generated config
- server console access
- server file editing and uploads
- Minecraft-level backup schedules

The Crafty panel is exposed at `https://10.1.2.250:8443`.

The Dripcraft portal is exposed through Tailscale as `https://dripcraft`.
It creates Crafty servers and matching Tailscale `LoadBalancer` Services in one
operation. After creating a server, it redirects to Crafty for detailed server
management.

World map viewers are exposed through Tailscale when the matching Minecraft
server plugin is installed and listening inside Crafty:

- BlueMap 3D map: `https://dripcraft-map` -> Crafty port `8100`
- Dynmap 2D/isometric map: `https://dripcraft-dynmap` -> Crafty port `8123`

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
