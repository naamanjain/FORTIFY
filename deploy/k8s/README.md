# FORTIFY prototype — Kubernetes deployment

Reference manifests for running the FORTIFY prototype on a cluster. They are
demonstration-grade: single replica per component, SQLite on a
ReadWriteOnce volume, no autoscaling, and — importantly — **the prototype has
no authentication**; it trusts the `X-Fortify-Role` / `X-Fortify-Purpose`
headers (see `SECURITY_MODEL.md`). Only deploy on trusted networks.

## Layout

| File | Contents |
|---|---|
| `00-namespace.yaml` | `fortify` namespace |
| `10-configmap.yaml` | `FORTIFY_*` environment (mirrors `backend/.env.example`) |
| `15-pvc.yaml` | one RWO volume for generated data, runtime state, artifacts |
| `20-pipeline-job.yaml` | suspended Job that regenerates the seed-42 demo environment |
| `30-backend.yaml` | FastAPI Deployment + Service (`fortify-backend:8000`) |
| `40-frontend.yaml` | nginx Deployment + Service serving the SPA + API proxy |
| `50-ingress.yaml` | optional ingress-nginx route |

## Usage

The manifests reference local image tags (`fortify-backend:latest`,
`fortify-frontend:latest`). Build them from the repository root and load them
into your cluster first:

```bash
docker build -f backend/Dockerfile -t fortify-backend:latest .
docker build -t fortify-frontend:latest frontend/
# kind:  kind load docker-image fortify-backend:latest fortify-frontend:latest
# minikube: minikube image load fortify-backend:latest fortify-frontend:latest

kubectl apply -f deploy/k8s/

# Regenerate the deterministic demo environment (seed 42) into the PVC:
kubectl -n fortify patch job fortify-pipeline -p '{"spec":{"suspend":false}}'

# Wait for it to finish, then port-forward the frontend:
kubectl -n fortify wait --for=condition=complete job/fortify-pipeline --timeout=30m
kubectl -n fortify port-forward svc/fortify-frontend 8080:80
```

The backend boots even before the pipeline job has populated the volume:
`/health` responds and data endpoints return `503` with regeneration
guidance. The pipeline job is created suspended so applying the manifests
does not immediately trigger a 10+ minute computation.

The API is reachable directly via `svc/fortify-backend:8000` for smoke tests.
