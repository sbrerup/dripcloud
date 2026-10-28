# Dripcraft Portal

Small portal for creating Crafty Minecraft servers and matching Tailscale
`LoadBalancer` Services.

## Configuration

Create a Crafty API key with server creation permissions, then put it in the
cluster together with a shared portal token:

```powershell
kubectl -n dripcraft create secret generic dripcraft-portal-crafty `
  --from-literal=apiToken='CRAFTY_API_TOKEN' `
  --from-literal=portalToken='PORTAL_SHARED_TOKEN'
```

`PORTAL_TOKEN` (the secret's `portalToken` key) is required. Without it the
portal fails closed: every `/api/*` request returns `503`
(`PORTAL_TOKEN_NOT_CONFIGURED`) while `/healthz` and the static UI keep
working. The UI asks for the token, sends it as the `X-Portal-Token` header,
and keeps it in `sessionStorage` until you press `Lock` or close the tab.

To add the token to an existing secret, then pick it up (environment variables
are only read at container start):

```powershell
kubectl -n dripcraft patch secret dripcraft-portal-crafty --type merge `
  -p '{"stringData":{"portalToken":"PORTAL_SHARED_TOKEN"}}'
kubectl -n dripcraft rollout restart deployment/dripcraft-portal
```

The portal uses these defaults:

- Crafty API: `https://crafty-headless:8443`
- Crafty panel link: `https://10.1.2.250:8443`
- Crafty TLS verification: disabled, because Crafty usually uses a self-signed
  certificate in this setup
- Minecraft backend port range: `25565-25585`
- Tailnet external Minecraft port: `25565`
- Ports allowed for Tailnet exposure: `25565-25665`
- JAR category/type: `mc_java_servers` / `paper`

Set `TAILSCALE_DOMAIN` in the `dripcraft-portal-config` ConfigMap if you want
the UI to show full MagicDNS names.

### Exposable ports

`EXPOSE_ALLOWED_PORTS` limits which Crafty pod ports the portal will publish as
a Tailscale `LoadBalancer` target port, for create, `Expose` and `Sync`. It is a
comma-separated list of ports and inclusive ranges, for example
`25565-25665,25700`. The default is `25565-25665`, which covers the creation
pool (`PORT_RANGE_START`-`PORT_RANGE_END`) plus Java servers created directly
in Crafty. Keep the creation pool inside this list, or create requests fail.

The Crafty panel/API ports `8443` and `8000` are always refused, even if listed.
The exposure Service is TCP only, so Bedrock (`19132/udp`) cannot be exposed
this way, and the web maps (BlueMap `8100`, Dynmap `8123`) are served by their
own Ingresses; add them here only if you really want them behind a portal
Service. `Sync` skips servers on other ports with reason `port_not_allowed`.

Servers created directly in Crafty can be exposed from the portal. Use the
`Sync` button to create missing Tailscale Services for Crafty servers that have
known Minecraft ports, or use `Expose` on a single row.
