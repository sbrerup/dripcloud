# Firecrawl egress isolation

`apps/firecrawl-network.yaml` registers these policies with the existing Argo CD
app-of-apps. This application owns only network policies, not the existing
Firecrawl workloads or the shared `beamray-agent-services` namespace. Commit
and push these files for Argo CD to adopt and reconcile the policies.

Both `firecrawl-api` and `firecrawl-playwright` are egress-isolated:

- Public IPv4 destinations: TCP 80/443 only, excluding private, Tailscale/CGNAT,
  loopback, link-local/metadata, documentation, benchmark, and reserved ranges.
- IPv6: no egress allowance.
- DNS: only kube-system CoreDNS pods, TCP/UDP 53.
- API only: Redis 6379, PostgreSQL 5432, RabbitMQ 5672, Playwright 3000,
  and SearXNG 8080, selected by pod labels within the same namespace.
- Incoming API requests and their replies are unaffected.

Cilium currently enforces Kubernetes NetworkPolicy in this cluster. No other
policies currently grant egress to these two workloads. Kubernetes allow policies
are additive: a future broad egress allowance could weaken this restriction.
Retain these workload labels and policies when replacing the deployment.

## Limits

This is not an absolute block on every internal address: required dependencies
are explicitly allowed, and Kubernetes NetworkPolicy does not isolate a pod
from its own loopback/self-address. Keep Firecrawl's application-level URL checks
enabled. Public reverse proxies or remote scraping services can fetch from their
own networks; this policy controls these pods' network connections only.

## Validation

```sh
kubectl kustomize manifests/firecrawl-network
kubectl apply --dry-run=server -k manifests/firecrawl-network
```

Verified against the running API and Playwright pods after the initial apply:

- Public HTTPS connections succeed from both pods.
- Kubernetes API, node API, Tailscale, and metadata IP connections time out.
- API connections to all five required dependencies succeed.
- Browser connections to Redis, PostgreSQL, RabbitMQ, and SearXNG time out.
- `POST /v2/scrape` for `https://example.com` with `maxAge: 0` returns HTTP 200
  and extracted Markdown.

The policies were initially applied manually before adding them here. Until
these files are pushed and synced, the live policies are not Argo CD-managed.
Removing these policies reopens egress; turn off fresh scraping first if rolling
back. Client-side Pi settings are outside this repository.
