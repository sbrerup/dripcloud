# Dripcraft Portal

Small portal for creating Crafty Minecraft servers and matching Tailscale
`LoadBalancer` Services.

## Configuration

Create a Crafty API key with server creation permissions, then put it in the
cluster:

```powershell
kubectl -n dripcraft create secret generic dripcraft-portal-crafty `
  --from-literal=apiToken='CRAFTY_API_TOKEN'
```

Optional portal lock:

```powershell
kubectl -n dripcraft create secret generic dripcraft-portal-crafty `
  --from-literal=apiToken='CRAFTY_API_TOKEN' `
  --from-literal=portalToken='PORTAL_SHARED_TOKEN'
```

The portal uses these defaults:

- Crafty API: `https://crafty-headless:8443`
- Crafty panel link: `https://10.1.2.250:8443`
- Crafty TLS verification: disabled, because Crafty usually uses a self-signed
  certificate in this setup
- Minecraft backend port range: `25565-25585`
- Tailnet external Minecraft port: `25565`

Set `TAILSCALE_DOMAIN` in the `dripcraft-portal-config` ConfigMap if you want
the UI to show full MagicDNS names.

Servers created directly in Crafty can be exposed from the portal. Use the
`Sync` button to create missing Tailscale Services for Crafty servers that have
known Minecraft ports, or use `Expose` on a single row.
