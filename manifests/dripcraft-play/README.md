# Dripcraft Play

`apps/dripcraft-play.yaml` runs a browser Minecraft client for the Crafty
servers in the `dripcraft-play` namespace. Both endpoints are owner-only on the
tailnet (`tag:k8s-admin`):

- `https://dripcraft-play.turtle-vector.ts.net`: the client
  ([zardoy/minecraft-web-client](https://github.com/zardoy/minecraft-web-client)).
- `https://dripcraft-relay.turtle-vector.ts.net`: the WebSocket-to-TCP relay
  ([zardoy/mwc-proxy](https://github.com/zardoy/mwc-proxy)). Browsers cannot
  open TCP sockets, and the Crafty servers run in online mode, so the relay
  also brokers Microsoft login. Login tokens stay in the browser. Reporting to
  the public relay list (`signal.mcraft.fun`) is disabled.

`config.json` points the client at the relay and lists the Crafty servers by
their in-cluster Service names, which the relay resolves. Add servers there, or
in the client's server list (saved per browser). The relay may reach the Crafty
game ports (`25565`-`25665`) and the public internet, nothing else on the LAN or
in the cluster; `manifests/crafty/network-policies.yaml` admits it to the
secondary server ports.

## Image

Upstream publishes no client image. `.github/workflows/dripcraft-play-image.yaml`
builds the upstream Dockerfile at the commit in `MWC_REF` and pushes
`ghcr.io/sbrerup/dripcraft-play:<MWC_REF>`. To update, set `MWC_REF` to a newer
upstream commit and the same SHA as the image tag in `client.yaml`, in one
commit. The pod waits in `ImagePullBackOff` until the build has pushed.

GHCR creates new packages as private. Make the `dripcraft-play` package public
after the first build, as with the portal image, or the cluster cannot pull it.

The relay image is upstream's and pinned by digest; Renovate updates it.

Validate with `kubectl apply --dry-run=server -k manifests/dripcraft-play` and
`python -m unittest discover -s tests` from the repository root.
