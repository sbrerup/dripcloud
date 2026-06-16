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
