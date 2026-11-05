# Smart E-Commerce Intelligence Platform

End-to-end analytics, machine learning and BI platform built on the
[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce):
ETL into a PostgreSQL warehouse, dbt star schema, Power BI reporting, customer / forecasting /
anomaly / recommendation models tracked in MLflow, a FastAPI backend, a React frontend and a
permission-controlled AI business assistant.

> **Historical data.** The dataset covers Olist marketplace orders from 2016-09 to 2018-10
> (usable continuous period 2017-01 to 2018-08). Nothing in this project is live transactional
> data, and "forecasts" are predictions of late-2018 periods.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Requirements, dataset inspection, architecture | Done — see [docs/phase0_findings.md](docs/phase0_findings.md) |
| 1 | Repository and development environment | Done |
| 2 | Data exploration and quality assessment | Done — [business rules](docs/business_rules.md), [quality report](docs/data_quality_report.md), [notebook](notebooks/exploration/01_exploratory_analysis.ipynb) |
| 3 | ETL and PostgreSQL warehouse | Bronze done — [ETL docs](docs/etl_bronze.md); silver/gold are built by dbt in Phase 4 |
| 4 | dbt transformations and tests | Done — [star schema](docs/star_schema.md) |
| 5 | SQL analytics and Power BI | Done — [KPI dictionary](docs/kpi_dictionary.md), [Power BI](powerbi/documentation/report_spec.md); DAX value check pending a refresh in Desktop |
| 6 | RFM, repurchase propensity and CLV | Done — model cards: [repurchase](docs/model_cards/repurchase_propensity.md), [90-day spend](docs/model_cards/customer_spend_90d.md), [RFM](docs/model_cards/rfm_segmentation.md) |
| 7 | Sales forecasting and anomaly detection | Done — model cards: [forecasting](docs/model_cards/sales_forecasting.md), [anomalies](docs/model_cards/anomaly_detection.md) |
| 8 | Recommendations | Done — [model card](docs/model_cards/recommendations.md) |
| 9 | FastAPI backend | Done — [API docs](docs/api.md) |
| 10 | React frontend | Not started |
| 11 | AI business assistant | Not started |
| 12 | MLflow, Docker, CI/CD, security | Not started |
| 13 | Integration and end-to-end tests | Not started |
| 14 | Documentation and portfolio | Not started |

## Repository layout

```
backend/            FastAPI service (Phase 9)
frontend/           React + TypeScript app (Phase 10)
data/raw/           Downloaded Olist CSVs + _manifest.json (git-ignored)
data/processed/     Generated intermediates (git-ignored)
data/sample/        Small, referentially consistent fixture used by tests and CI (committed)
data_engineering/   Settings, source-file spec, ETL, validation, scripts
warehouse/          SQL scripts and dbt project
notebooks/          Exploration and modeling notebooks
models/  mlflow/    Model artifacts and experiment tracking (git-ignored outputs)
powerbi/            Power BI project (PBIP) and DAX documentation
infrastructure/     Docker init scripts and deployment config
docs/               Architecture, data dictionary, model and dataset cards
tests/              Python tests
```

Deviation from the original brief: GitHub only runs workflows from `.github/workflows/`, so the
CI workflow lives there rather than in `infrastructure/github-actions/`.

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.5+ | Python 3.11 toolchain, virtualenv, lockfile |
| Docker Desktop (WSL2 backend on Windows) | recent | PostgreSQL and, later, the full stack |
| Node.js | 20 LTS or newer | Frontend (Phase 10) |
| Git | 2.30+ | |

Python is pinned to **3.11** (`.python-version`) because TensorFlow and Prophet, needed in
Phase 7, do not reliably support newer interpreters. uv installs 3.11 without affecting any
system Python.

**Low disk space on the system drive?** Everything large can live on another drive. The
development machine uses `K:`, set up as follows:

| What | Size | How |
|---|---|---|
| Virtualenv (all groups, incl. TensorFlow) | ~2.9 GB | user env var `UV_PROJECT_ENVIRONMENT=K:\...\venv` (`uv run` / `uv sync` use it) |
| uv package cache | grows | user env vars `UV_CACHE_DIR=K:\...\uv-cache`, `UV_LINK_MODE=copy` (no cross-drive hardlinks) |
| Warehouse database | ~0.6 GB, grows | PostgreSQL tablespace: `CREATE TABLESPACE olist_k LOCATION 'K:/...'` then `ALTER DATABASE olist_dw SET TABLESPACE olist_k` (the folder must grant the service account, `NetworkService`, full control) |
| PostgreSQL WAL | capped | `ALTER SYSTEM SET max_wal_size = '256MB'` on a small dev machine |

## Setup

```bash
# 1. Python environment from uv.lock (.venv, or $UV_PROJECT_ENVIRONMENT if set).
#    Groups: dev (default), notebooks, dbt, ml, dl (TensorFlow, Prophet, statsmodels)
uv sync --all-groups

# 2. Secrets: copy the template and replace every "change-me" value
cp .env.example .env

# 3. Dataset: downloads from Kaggle, extracts the 9 CSVs to data/raw, writes SHA-256 manifest.
#    Re-running is a no-op when hashes match. If Kaggle refuses anonymous access, download the
#    archive manually and pass it with --from-zip path/to/archive.zip
uv run python -m data_engineering.scripts.download_dataset

# 4a. Database with Docker: PostgreSQL 16, roles + schemas created on first start
docker compose up -d postgres
docker compose ps                      # wait for "healthy"

# 4b. Or native PostgreSQL 16 (no Docker). On Windows:
#       winget install -e --id PostgreSQL.PostgreSQL.16 --override "--mode unattended
#         --superpassword <POSTGRES_SUPERUSER_PASSWORD from .env> --serverport 5432
#         --enable-components server,commandlinetools --disable-components pgAdmin,stackbuilder"
#     then create the database, roles and schemas (idempotent, safe to re-run):
uv run python -m data_engineering.scripts.setup_local_db

# Either way, verify:
uv run python -m data_engineering.scripts.check_db
uv run pytest -m db

# 5. Bronze load: manifest + pandera contract + quality gate, then COPY into raw.*
uv run python -m data_engineering.etl.load_bronze

# 6. Silver + gold with dbt: staging -> intermediate -> marts (star schema), 70 tests
uv sync --group dbt
uv run --group dbt python -m data_engineering.scripts.run_dbt build

# 7. Power BI model (TMDL) + SQL reconciliation targets; then open powerbi/OlistIntelligence.pbip,
#    refresh with analytics_ro, and run: powershell -File powerbi	ools\Invoke-DaxChecks.ps1
uv run python -m data_engineering.scripts.build_powerbi_model

# 8. Customer models: RFM, repurchase propensity (churn), 90-day spend; MLflow in mlflow/
uv sync --group ml
uv run --group ml python -m ml.train_customer_models
uv run --group ml mlflow ui --backend-store-uri sqlite:///mlflow/mlflow.db   # browse runs

# 9. Sales forecasting (30/60/90 days) and daily anomaly detection
uv run --all-groups python -m ml.train_forecasting
uv run --all-groups python -m ml.detect_anomalies

# 10. Product recommendations (temporal evaluation, serving tables in ml.*)
uv run --all-groups python -m ml.train_recommendations

# 11. API: migrate the app schema, create an admin, run (docs at /docs)
uv run --all-groups alembic -c backend/alembic.ini upgrade head
uv run --all-groups python backend/scripts/create_admin.py --email you@example.com --name "You"
uv run --all-groups uvicorn app.main:app --app-dir backend --reload

# 12. Git hooks (ruff, large-file guard, private-key detection)
uv run pre-commit install
```

## Development commands

```bash
uv run pytest                                          # all tests (DB tests need step 4)
uv run pytest -m "not db"                              # what CI runs
uv run ruff check . && uv run ruff format --check .    # lint
uv run python -m data_engineering.scripts.profile_raw  # Phase 0 raw-data profile report
uv run python -m data_engineering.scripts.make_sample  # regenerate data/sample from data/raw

# Data quality: 79 checks; exits 1 if any error-level check fails
uv run python -m data_engineering.scripts.assess_quality --write-report   # full data -> docs/data_quality_report.md
uv run python -m data_engineering.scripts.assess_quality --raw-dir data/sample   # what CI runs

# Exploration notebook (optional dependency group)
uv sync --group notebooks
uv run --group notebooks jupyter nbconvert --to notebook --execute --inplace notebooks/exploration/01_exploratory_analysis.ipynb
```

## Database roles

Defined once in `infrastructure/postgres/init_roles_schemas.sql`. It is applied by the Docker
init script or by `setup_local_db.py`. Passwords are read from environment variables via psql
`\getenv`, so they never appear on a command line.

| Role | Access |
|---|---|
| `etl_user` | Owns `raw`, `staging`, `intermediate`, `marts`, `ml`. Runs ingestion, dbt, ML scoring. |
| `analytics_ro` | `SELECT` on `marts` and `ml` only; read-only transactions; 15 s statement timeout. Used by BI and the AI assistant. |
| `app_user` | Reads `marts` and `ml`; owns `app` (users, refresh tokens, audit log). |

With Docker, the init script runs only when the data volume is empty. To re-run it, use
`docker compose down -v`, which **deletes** the database volume. On a native install, re-run
`setup_local_db.py`. For a native install, also set `listen_addresses = 'localhost'` (the EDB
installer defaults to `*`) to match the Docker setup, which binds to localhost only.

## License

Code: [MIT](LICENSE). The MIT license covers the code only, not the data.

## Dataset and license

Source: Olist, *Brazilian E-Commerce Public Dataset by Olist*, Kaggle.
Distributed under **CC BY-NC-SA 4.0** (attribution, non-commercial, share-alike); check the
Kaggle page for the current terms. Raw files are not committed; `data/sample/` is a small
derived subset under the same license.

Known limitations are listed in [docs/phase0_findings.md](docs/phase0_findings.md#limitations).
