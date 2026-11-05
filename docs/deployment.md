# Deployment, MLOps and CI/CD

## Model lifecycle (MLflow)

```
train (registers vN) ──> promote (gate) ──> @champion ──> export bundle ──> API serves it
```

1. **Train.** `python -m ml.train_customer_models` logs runs, metrics and artifacts to the
   local MLflow store (`mlflow/mlflow.db` plus `mlflow/artifacts/`) and registers a new
   version of `repurchase_propensity` and `customer_spend_90d`. Registering does **not**
   change what is served.
2. **Promote.** `python -m ml.promote_model <model> [--version N] [--dry-run]` compares the
   candidate's held-out test metric with the current champion's and moves the `champion`
   alias only if the candidate passes the gate. Use `--force` to skip the gate; the version
   is then tagged `promotion_gate=forced`.

   | Model | Gate metric | Direction | Tolerance |
   |---|---|---|---|
   | `repurchase_propensity` | `test_pr_auc` | higher is better | 0.005 |
   | `customer_spend_90d` | `test_rmse` | lower is better | 0.5 BRL |

   Each promotion tags the version with `promoted_at`, `promoted_by`, `promotion_gate` and
   `promotion_reason`. Exit code 1 means the gate failed, which lets a pipeline stop there.
3. **Serve.** The API loads `models:/<name>@champion`. If a model has no champion, it falls
   back to the latest version, logs a warning, and `/api/models/status` shows
   `serving_source: latest (no champion alias)`. Models are cached per process, so restart
   the API after a promotion.
4. **Export for containers.** The registry records absolute artifact paths from the training
   machine, which a container cannot resolve.
   `python -m ml.export_serving_models` copies each champion to
   `models/serving/<name>/` with a `manifest.json` (version, run id, test metrics). With
   `SERVING_MODELS_DIR` set, the API loads from these bundles.

State on 2026-11-05: v1 of both models is the champion (first promotion, no previous
champion). Bundles are exported, and loading them through the API code was checked
(`CalibratedClassifierCV` and `Pipeline`).

Batch-scored tables (`ml.customer_repurchase_scores`, …) record the `model_version` that
wrote them. After retraining, re-score and promote together, or the stored scores and
on-demand predictions will come from different versions.

## Docker

```bash
cp .env.example .env    # set passwords, JWT_SECRET_KEY (≥ 32 chars), optional ANTHROPIC_API_KEY
docker compose up -d postgres
# load the warehouse: ETL -> dbt -> ML scripts (see README), then:
python -m ml.export_serving_models
docker compose --profile app up -d --build      # http://localhost:8080
docker compose --profile mlflow up mlflow       # http://localhost:5000 (MLflow UI)
```

| Service | Image | Notes |
|---|---|---|
| `postgres` | `postgres:16-alpine` | Roles and schemas created by the init scripts; bound to 127.0.0.1 |
| `migrate` | `sei-api:local` | `alembic upgrade head` for the `app` schema, then exits |
| `api` | `sei-api:local` (`infrastructure/docker/api/Dockerfile`) | Multi-stage build with uv; runtime groups `backend` + `ml` only; uid 10001; read-only filesystem; health check `/api/health` |
| `web` | `sei-web:local` (`infrastructure/docker/web/Dockerfile`) | Vite build served by nginx-unprivileged on :8080, `/api` proxied to `api`, CSP and security headers, source maps not served |
| `mlflow` | `ghcr.io/mlflow/mlflow:v3.18.0` | Optional UI over `./mlflow` (same version as `uv.lock`) |

The containers only read the warehouse. The ETL, dbt and training pipelines still run from
the host environment (`uv`), as in the README.

**Not verified:** Docker is not installed on the development machine (PostgreSQL runs
natively), so none of the images has been built or run here. The CI `docker` job builds both
images, starts the API and checks `/api/health`, then runs Trivy. That job has never run,
because the repository has no remote yet.

## Test layers

| Layer | Where | Runs | What it proves |
|---|---|---|---|
| Unit and contract | `tests/`, `backend/tests/test_sql_guard.py`, … | CI (`-m "not db and not llm"`, 135 tests) | Business rules, ETL contracts, feature logic, SQL guard, promotion gate, Power BI model |
| Pipeline on the sample fixture | `tests/test_bronze_load.py`, `tests/test_dbt_build.py` | Local (`-m db`) | Bronze load and `dbt build` in isolated schemas match an independent Python implementation |
| Cross-layer consistency | `tests/test_warehouse_consistency.py` (12) | Local (`-m db`) | raw → marts → ml → serving agree: row counts, per-order totals, KPI sums, RFM coverage, score coverage, forecast horizon, batch scores from the champion, bundles = champion |
| API journeys | `backend/tests/test_journeys.py` (4) | Local (`-m db`) | Multi-step sessions: pages agree with each other and with SQL; promotion and demotion take effect on the next request; refresh then logout; bundle and registry give the same prediction |
| Browser end-to-end | `backend/tests/test_e2e_browser.py` (4) | Opt-in: `RUN_E2E=1 pytest -m e2e` | Built frontend + real API in Edge or Chrome via Playwright: login, dashboard value equals the warehouse, role gate, reload keeps the session, logout, Customer 360, assistant tools-only mode, no console errors |
| Live LLM | `backend/tests/test_assistant.py::test_live_top_category` | Opt-in: `RUN_LLM_TESTS=1 pytest -m llm` | Real Claude answer is grounded in tool results (not yet run: no API key) |

Full local run on 2026-11-05: 238 passed, 5 skipped (4 browser tests and 1 live LLM test,
which are opt-in). The browser suite was run separately with `RUN_E2E=1`: 4 passed in 30 s.

```bash
uv run --all-groups pytest                        # everything except opt-in suites
npm --prefix frontend run build
RUN_E2E=1 uv run --all-groups pytest -m e2e       # needs ports 8000/4173 free, Edge or Chrome
```

The browser tests start their own API (against an isolated `test_app_*` schema) and a
`vite preview` of the built frontend. They use an installed Edge or Chrome, so no browser
download is needed. They are not in CI, because they need the loaded warehouse.

## CI (`.github/workflows/ci.yml`)

| Job | Steps |
|---|---|
| `python` | `uv sync --locked`, ruff lint and format check, `pytest -m "not db and not llm"` (135 tests; `db`, `llm` and `e2e` suites are local), data quality on the sample fixture, `dbt parse` |
| `frontend` | `npm ci`, tsc, eslint (0 warnings), production build |
| `security` | pip-audit (runtime lock), bandit (medium+), `npm audit --omit=dev --audit-level=high`, gitleaks (full history) |
| `docker` | Build both images (GitHub Actions cache), API smoke test, Trivy scan of both images |

Dependabot (`.github/dependabot.yml`) checks uv and npm weekly, and GitHub Actions and the
Docker base images monthly.

Tests marked `db` (108 tests, including the opt-in browser suite) need the loaded warehouse. The Kaggle data cannot be committed
(license and size), so those tests run locally only.

There is **no deploy (CD) stage**: no target environment or registry is configured.
Publishing images to a registry (for example GHCR, on tags) and deploying them is the next
step once a host exists.
