# Architecture

The platform is a batch analytics stack with an online serving layer. Data moves once, in
order: CSV → `raw` → dbt (`staging` → `intermediate` → `marts`) → ML scripts (`ml`). The API,
Power BI and the AI assistant only **read** the warehouse; the API writes only its own `app`
schema (users, tokens, logs).

## Components

```mermaid
flowchart LR
    subgraph Source
        K[Kaggle Olist CSVs<br/>9 files, SHA-256 manifest]
    end

    subgraph Batch["Batch pipeline (host, uv)"]
        DQ[Data quality gate<br/>79 checks, pandera]
        ETL[Bronze load<br/>COPY + lineage columns]
        DBT[dbt build<br/>staging → intermediate → marts<br/>contracts + tests]
        ML[ML scripts<br/>RFM, repurchase, spend,<br/>forecast, anomalies, recommenders]
        PROMO[Promotion gate<br/>@champion alias]
    end

    subgraph PG["PostgreSQL 16 · olist_dw"]
        RAW[(raw)]
        MARTS[(marts<br/>star schema + kpi_* views)]
        MLS[(ml<br/>scores, forecasts, recs)]
        APP[(app<br/>users, tokens, audit,<br/>prediction and assistant logs)]
    end

    MLF[(MLflow<br/>runs + model registry)]
    BUNDLE[Serving bundles<br/>models/serving]

    subgraph Online["Online (Docker profile app)"]
        API[FastAPI<br/>JWT, RBAC, rate limits]
        WEB[React SPA<br/>nginx, CSP]
        ASSIST[Assistant loop<br/>read-only tools, SQL guard]
    end

    LLM[[LLM API<br/>Anthropic]]
    PBI[Power BI<br/>PBIP / TMDL]

    K --> DQ --> ETL --> RAW --> DBT --> MARTS --> ML --> MLS
    ML -- log + register --> MLF --> PROMO --> BUNDLE
    MARTS & MLS -- analytics_ro --> API
    APP <-- app_user --> API
    BUNDLE -- on-demand predictions --> API
    API --- ASSIST -- tool calls --> LLM
    WEB -- /api --> API
    MARTS & MLS -- analytics_ro --> PBI
```

| Layer | Technology | Responsibility | Docs |
|---|---|---|---|
| Ingestion | Python, pandera, psycopg `COPY` | Download, hash check, 79-check quality gate, bronze load with lineage | [etl_bronze.md](etl_bronze.md), [data_quality_report.md](data_quality_report.md) |
| Transformation | dbt-postgres | Cleaning rules (BR-01…), star schema with enforced contracts, incremental daily aggregate, KPI views | [star_schema.md](star_schema.md), [business_rules.md](business_rules.md) |
| BI | Power BI (PBIP/TMDL), DAX | Semantic model over `marts`, measures reconciled to SQL | [kpi_dictionary.md](kpi_dictionary.md), [report spec](../powerbi/documentation/report_spec.md) |
| ML | scikit-learn, XGBoost, Prophet, statsmodels, TensorFlow, MLflow | Point-in-time training sets, baselines, confidence intervals, batch scoring into `ml.*`, model registry | [model cards](model_cards/) |
| API | FastAPI, SQLAlchemy, Alembic, slowapi | Auth, RBAC, pagination, on-demand predictions, audit | [api.md](api.md) |
| Frontend | React 19, React Router, Vite, Tailwind, Recharts | 14 pages, role-gated navigation | [frontend.md](frontend.md) |
| Assistant | Anthropic SDK (LLM), sqlglot | Tool-grounded answers; tools-only mode without a key | [assistant.md](assistant.md) |
| Delivery | Docker, compose, GitHub Actions | Images, security scans, CI | [deployment.md](deployment.md), [security.md](security.md) |

## Database roles and schemas

```mermaid
flowchart TB
    etl[etl_user] -- owns, writes --> raw & staging & intermediate & marts & ml
    ro[analytics_ro] -- SELECT, read-only tx, 15 s timeout --> marts & ml
    app[app_user] -- SELECT --> marts & ml
    app -- owns --> appschema[app]
```

Least privilege is enforced in PostgreSQL, not only in code: the assistant and Power BI use
`analytics_ro`, so even a SQL guard bypass could not write or read `app`.

## Request flow (authenticated page)

```mermaid
sequenceDiagram
    participant B as Browser (React)
    participant N as nginx
    participant A as FastAPI
    participant D as PostgreSQL
    B->>N: GET /api/customers (Bearer access token)
    N->>A: proxy
    A->>A: verify JWT (HS256, 15 min)
    A->>D: load user + role (app_user)
    alt role below analyst
        A->>D: insert audit_log denial, commit
        A-->>B: 403
    else allowed
        A->>D: parameterised query (analytics_ro, read-only)
        A-->>B: 200 JSON + X-Request-ID
    end
    Note over B,A: On 401 the client makes one single-flight /auth/refresh<br/>(rotating refresh token), then retries
```

## Assistant flow

```mermaid
sequenceDiagram
    participant U as User
    participant A as FastAPI
    participant C as LLM
    participant D as PostgreSQL (analytics_ro)
    U->>A: POST /api/assistant/query
    A->>C: question + tools allowed for the user's role
    loop until end_turn (max iterations bounded)
        C-->>A: tool_use (e.g. get_sales_by_category)
        A->>A: validate args, role check, SQL guard
        A->>D: read-only query
        A->>C: tool_result (data, framed as untrusted)
    end
    C-->>A: answer
    A->>D: app.assistant_log (no tool data)
    A-->>U: answer + every tool call with its rows
```

## Key design decisions

| Decision | Why | Trade-off |
|---|---|---|
| ELT with dbt in PostgreSQL | Transformations are SQL, tested, documented and versioned; one engine for BI, API and ML | Not suited to data far larger than one server |
| Natural keys in the star schema | Olist ids are stable hashes; simpler Power BI relationships and API lookups | Wider keys than integer surrogates |
| Analysis window 2017-01-01 → 2018-08-21 | 2016 and Sep–Oct 2018 are sparse or truncated (BR-02) | ~20 months of history, one Black Friday |
| Point-in-time ML snapshots, chronological splits | Prevents leakage of future orders, deliveries or reviews | Fewer training rows |
| Every model compared with a simple baseline, with CIs | Shows whether ML adds value; several models do not beat rules | Less flattering headline metrics |
| Batch scores in `ml.*`, on-demand models from MLflow | Fast reads for pages; consistent versions via the `champion` alias | Re-score after each promotion (checked by a test) |
| Serving bundles for containers | The registry stores absolute host paths | Extra export step |
| Assistant uses tools, not free SQL by default | Answers are grounded in the same queries as the dashboards | Questions outside the tool set need the analyst-only guarded SQL tool |
| Native PostgreSQL in development, Docker for the app stack | Docker was not available on the development machine | Images are built only in CI (not yet run) |
