# Firecrawl

Argo CD application: `apps/firecrawl.yaml`. Network isolation is owned separately
by `apps/firecrawl-network.yaml`; keep both applications deployed. SearXNG is
managed by `apps/searxng.yaml`.

This adopts the existing resources in `beamray-agent-services` in place:

- API and Playwright browser deployments, with pinned image digests.
- Redis, RabbitMQ, and NUQ PostgreSQL deployments and their existing PVCs.
- Configuration, internal Services, and the Tailscale Ingress at
  `https://firecrawl.turtle-vector.ts.net`.
- `firecrawl-runtime`, encrypted as a strictly name/namespace-scoped SealedSecret.

The shared namespace is not owned or pruned by this application. Argo CD may
create it if absent. The Tailscale and Sealed Secrets operators and
`local-path-retain` storage class must exist first.

## Data and credentials

PVCs and SealedSecrets use `Prune=false,Delete=false` to prevent automatic deletion
when removed from Git or when their application is deleted. This is not a backup:
back up the data volumes and the Sealed Secrets controller's private keys securely.
Database credentials have been preserved, not rotated. The encrypted manifests
cannot be decrypted on a replacement cluster without the original sealing keys.

For the initial adoption only, existing Secrets must be marked for management:

```sh
kubectl -n beamray-agent-services annotate secret firecrawl-runtime searxng-runtime \
  sealedsecrets.bitnami.com/managed=true --overwrite
```

To update credentials, pipe a Secret to `kubeseal --controller-name sealed-secrets
--controller-namespace sealed-secrets --format yaml` without saving plaintext to
Git. Retain the SealedSecret sync-wave and retention annotations. Coordinate
PostgreSQL password rotation with the database; updating the Secret alone does
not change the password of an initialized database.

## Validation

```sh
python -m unittest discover -s tests
kubectl apply --dry-run=server -k manifests/firecrawl
kubeseal --controller-name sealed-secrets --controller-namespace sealed-secrets \
  --validate -f manifests/firecrawl/sealedsecret-firecrawl-runtime.yaml
```

During migration, server dry-run output was compared against the live objects:
all Deployment, Service, PVC, Ingress specs and ConfigMap data were unchanged.
Only management metadata and sealed-secret ownership are intentionally changing.
Do not use replace/force sync or delete and recreate the existing resources.
