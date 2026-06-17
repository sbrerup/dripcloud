# dripcloud

GitOps for the labmox homelab cluster.

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

Operational notes:

- Keep the Crafty image pinned and take a data backup before bumping it.
- Create and delete Minecraft servers through the Dripcraft portal when you want
  Tailscale networking to follow the server lifecycle automatically.
- Servers created directly in Crafty can be pulled into Tailnet exposure with
  the portal's `Sync` button.
- Create the Skyblock server on port `25565`; add more Service ports if you
  want Crafty-managed secondary servers reachable from the LAN.
- Keep Minecraft's configured max heap below the pod memory limit. With the
  current `8Gi` pod limit, `6Gi` is a safer ceiling for the Java heap.
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
