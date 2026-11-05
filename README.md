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
| 2 | Data exploration and quality assessment | Not started |
| 3 | ETL and PostgreSQL warehouse | Not started |
| 4 | dbt transformations and tests | Not started |
| 5 | SQL analytics and Power BI | Not started |
| 6 | RFM, repurchase propensity and CLV | Not started |
| 7 | Sales forecasting and anomaly detection | Not started |
| 8 | Recommendations | Not started |
| 9 | FastAPI backend | Not started |
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

## Setup

```bash
# 1. Python environment (creates .venv from uv.lock)
uv sync

# 2. Secrets: copy the template and replace every "change-me" value
cp .env.example .env

# 3. Dataset: downloads from Kaggle, extracts the 9 CSVs to data/raw, writes SHA-256 manifest.
#    Re-running is a no-op when hashes match. If Kaggle refuses anonymous access, download the
#    archive manually and pass it with --from-zip path/to/archive.zip
uv run python -m data_engineering.scripts.download_dataset

# 4. Database: PostgreSQL 16 with roles + schemas created on first start
docker compose up -d postgres
docker compose ps                      # wait for "healthy"
uv run python -m data_engineering.scripts.check_db

# 5. Git hooks (ruff, large-file guard, private-key detection)
uv run pre-commit install
```

## Development commands

```bash
uv run pytest                                          # all tests (DB tests need step 4)
uv run pytest -m "not db"                              # what CI runs
uv run ruff check . && uv run ruff format --check .    # lint
uv run python -m data_engineering.scripts.profile_raw  # Phase 0 raw-data profile report
uv run python -m data_engineering.scripts.make_sample  # regenerate data/sample from data/raw
```

## Database roles

Created by `infrastructure/docker/postgres/init/01_init_roles_schemas.sh` on first start:

| Role | Access |
|---|---|
| `etl_user` | Owns `raw`, `staging`, `intermediate`, `marts`, `ml`. Runs ingestion, dbt, ML scoring. |
| `analytics_ro` | `SELECT` on `marts` and `ml` only; read-only transactions; 15 s statement timeout. Used by BI and the AI assistant. |
| `app_user` | Reads `marts` and `ml`; owns `app` (users, refresh tokens, audit log). |

The init script runs only when the data volume is empty. To re-run it:
`docker compose down -v` (this **deletes** the database volume).

## License

Code: [MIT](LICENSE). The MIT license covers the code only, not the data.

## Dataset and license

Source: Olist, *Brazilian E-Commerce Public Dataset by Olist*, Kaggle.
Distributed under **CC BY-NC-SA 4.0** (attribution, non-commercial, share-alike); check the
Kaggle page for the current terms. Raw files are not committed; `data/sample/` is a small
derived subset under the same license.

Known limitations are listed in [docs/phase0_findings.md](docs/phase0_findings.md#limitations).
