# REST API (FastAPI)

Code: [`backend/app`](../backend/app). The interactive OpenAPI docs are served by the running
API at `/docs`.

```bash
uv sync --all-groups
uv run --all-groups alembic -c backend/alembic.ini upgrade head          # app schema
uv run --all-groups python backend/scripts/create_admin.py --email you@example.com --name "You"
uv run --all-groups uvicorn app.main:app --app-dir backend --reload       # http://localhost:8000/docs
```

Every number the API returns is read from the warehouse (`marts.*`, `ml.*`); nothing is
computed from assumptions. Analytical responses carry a `meta` block with the source, the
analysis window and the filters applied.

## Architecture

```
routes (api/routes) ─► services (auth, predictions, audit) ─► repositories (SQL) ─► engines
                                                                                 ├─ read_engine: analytics_ro  (marts, ml; read-only, 15 s timeout)
                                                                                 └─ app_engine:  app_user      (app schema: users, tokens, audit, predictions)
```

- **Least privilege.** The API cannot write to the warehouse or read `raw` or `staging`. The
  `app` schema is managed by Alembic (`backend/alembic`).
- **SQL injection.**
  - Every value is a bound parameter.
  - Sort columns and filters come from allowlists that map to fixed SQL (`SORTS` in
    `repositories/customers.py`).
  - Path and query parameters are validated with patterns: 32-hex ids, `YYYY-MM` months,
    two-letter states, `snake_case` categories.

## Authentication

| Step | Endpoint | Notes |
|---|---|---|
| Sign up | `POST /api/auth/register` | Creates a **viewer**. Password: 12–128 characters with upper- and lower-case letters and a digit; hashed with **Argon2id** |
| Log in | `POST /api/auth/login` | Returns an access JWT (**15 min**, HS256) and an opaque refresh token (**7 days**, stored as SHA-256). The message is identical for an unknown email and a wrong password, and both take equal time (a dummy hash is checked) |
| Refresh | `POST /api/auth/refresh` | **Rotates** the refresh token. **Presenting an already-rotated token revokes the whole token family** (treated as theft) |
| Log out | `POST /api/auth/logout` | Revokes the token family |
| Me | `GET /api/auth/me` | |
| Change a role | `PATCH /api/auth/users/{id}/role` | Admin only; audited |

Access tokens must be type `access`; `alg: none` and tampered or expired tokens are rejected.
The first admin is created with `backend/scripts/create_admin.py`. The password comes from
`ADMIN_PASSWORD` or a prompt, never from a command-line argument.

## Authorization (roles)

| Endpoint group | viewer | analyst | admin |
|---|---|---|---|
| Dashboard (overview, sales, operations, filters) | ✓ | ✓ | ✓ |
| Customer segments (aggregates), forecast, anomalies, model metrics, similar products | ✓ | ✓ | ✓ |
| Customer list, Customer 360, churn-risk list, predictions, per-customer recommendations | — | ✓ | ✓ |
| Model registry status, data quality, role changes | — | — | ✓ |

Denied requests return 403 and are written to `app.audit_log`.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/dashboard/overview` | Headline KPIs (`marts.kpi_overview`) |
| GET | `/api/dashboard/sales` | Monthly GMV, orders, customers, AOV and MoM growth (complete months only), plus top categories and states. Filters: `date_from`, `date_to` (YYYY-MM), `state`, `category` (switches to item-level GMV) |
| GET | `/api/dashboard/operations` | Monthly cancellation and delivery KPIs (eligible orders), review distribution, delivery by state. Filters: months, `state` |
| GET | `/api/dashboard/filters` | Valid months, states and categories |
| GET | `/api/customers` | Paginated (`page`, `page_size` ≤ 100). Filters: `segment`, `state`, `risk_band`, `search` (id prefix). `sort`: monetary, recency, frequency, churn_risk, repurchase_probability, predicted_spend, last_order |
| GET | `/api/customers/segments` | RFM segment sizes, value and predicted spend |
| GET | `/api/customers/churn-risk` | Customers in a risk `band` (propensity deciles), highest value first |
| GET | `/api/customers/{id}` | Customer 360: profile, RFM, churn score with top SHAP reasons, 90-day spend, last 50 orders, recommendations |
| POST | `/api/predictions/churn` | `{"customer_unique_id"}` returns the stored batch score; `{"features": {...}}` runs the latest registered model on demand. Logged to `app.prediction_log` |
| POST | `/api/predictions/clv` | Same two modes for 90-day spend |
| GET | `/api/predictions/forecast` | `horizon` 1–90 days, optional `model`. Every model's daily forecast with intervals, totals, recent history and the selected model |
| GET | `/api/recommendations/{customer_id}` | Personalised top-k (k ≤ 10). Unknown customers get the cold-start popular list for `state` (or all states) |
| GET | `/api/recommendations/products/{product_id}/similar` | "Customers also bought" |
| GET | `/api/anomalies` | Flagged days with explanations and calendar events, plus sustained-shift episodes. Filters: `date_from`, `date_to` (ISO dates), `only_flagged` |
| GET | `/api/models/metrics` | Test metrics of the customer models, forecasting and recommendations |
| GET | `/api/models/status` | MLflow registry versions and freshness of the `ml.*` tables |
| GET | `/api/data-quality` | Latest results of the 79-check catalog (`assess_quality.py`) |
| GET | `/api/assistant/status` | Whether the LLM is configured (`mode`: assistant or tools_only), model, effort, example questions |
| GET | `/api/assistant/tools` | Assistant tools available to the caller's role, with argument schemas |
| POST | `/api/assistant/tools/{name}` | Run one tool directly (no LLM), same validation and role checks. 403 above role, 422 invalid arguments or rejected SQL |
| POST | `/api/assistant/query` | `{"question", "history"?}`: answer from read-only tools, with every tool call (metric, window, filters, rows) and token usage. 503 without an API key. See [assistant.md](assistant.md) |
| GET | `/api/health`, `/api/health/ready` | Liveness; readiness (both database roles reachable) |

## Errors, logging, limits

- **One error format:**
  `{"error": {"code", "message", "request_id", "details"}}`.
  - Validation errors are 422, with field locations in `details`.
  - Unhandled errors return a generic 500. SQL and stack traces stay in the server log.
- **Request ids:** `X-Request-ID` is echoed (or generated) on every response and included in
  errors and logs.
- **Structured logs:** JSON lines to stdout, one access line per request (method, path,
  status, duration, user id).
- **Rate limits** (slowapi, per client IP): `RATE_LIMIT_DEFAULT` (120/minute) everywhere and
  `RATE_LIMIT_AUTH` (10/minute) on register, login and refresh, and
  `RATE_LIMIT_ASSISTANT` (20/minute) on assistant queries and tool runs; 429 when exceeded.
  The in-memory store suits a single process; with several workers, use Redis.
- **CORS:** only `CORS_ALLOWED_ORIGINS`; methods GET, POST and PATCH; no credentialed
  cookies (bearer tokens).
- **Security headers:** `nosniff`, `X-Frame-Options: DENY`, `no-referrer`, `no-store`, and a
  strict CSP (relaxed on `/docs` for Swagger UI assets).

## Tests

`backend/tests` (`pytest -m db`; assistant tests are described in [assistant.md](assistant.md)) run against an isolated `test_app_*` schema,
migrated with Alembic and dropped afterwards. Analytics reads use the real marts. They cover:
- the auth flow, password rules, token rotation and reuse revocation
- tampered, expired, wrong-type and `alg: none` tokens
- admin-only role changes, login rate limiting, and the audit trail
- a full role × endpoint authorization matrix
- API values against independent SQL (overview, filtered sales, category GMV, anomalies)
- pagination and sorting, and rejection of injection-style parameters
- stored and on-demand predictions, prediction logging
- forecast horizons, warm and cold recommendations
- the error format and security headers
- training/API feature-contract parity
