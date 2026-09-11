# SearXNG

`apps/searxng.yaml` manages the existing deployment, JSON-enabled settings,
Service, Tailscale Ingress, and encrypted `searxng-runtime` Secret in
`beamray-agent-services`. URL: `https://searxng.turtle-vector.ts.net`.

The image digest, security context, probes, settings, and service identity are
preserved from the running deployment. Cache is intentionally ephemeral.
The shared namespace is not a prunable application resource.

The SealedSecret is scoped to this exact name and namespace and retained on
application deletion. See `../firecrawl/README.md` for adoption, sealing-key
backup, and credential update instructions.

Validate with `kubectl apply --dry-run=server -k manifests/searxng` and
`python -m unittest discover -s tests` from the repository root.
