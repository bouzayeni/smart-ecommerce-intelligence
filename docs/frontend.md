# Web application (React)

Code: [`frontend/`](../frontend). The stack is Vite 8, React 19, TypeScript 6, Tailwind CSS 4,
Recharts 3, React Router 8 and Axios.

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173 — proxies /api to the FastAPI server on :8000
npm run build      # type-check + production bundle in frontend/dist
npm run lint
```

Requires Node `^20.19 || >=22.12` (`engines` in `package.json`). The development machine uses a
portable Node LTS on another drive; any Node in that range works.

## Pages

| Page | Route | Minimum role | Data |
|---|---|---|---|
| Login / Register | `/login`, `/register` | — | `POST /auth/login`, `/auth/register` (new accounts are viewers) |
| Executive dashboard | `/` | viewer | overview KPIs, monthly GMV, MoM growth, top categories, states |
| Sales analytics | `/sales` | viewer | month / state / category filters; item-level GMV when a category is chosen |
| Sales forecasting | `/forecast` | viewer | 30/60/90-day horizon, every model, interval band, backtest and test accuracy |
| Anomaly detection | `/anomalies` | viewer | actual vs expected GMV, anomaly days with explanations, sustained shifts |
| Customer segmentation | `/segments` | viewer (customer list: analyst) | RFM segment sizes, value, predicted spend |
| Customer 360 | `/customers`, `/customers/:id` | analyst | server-side pagination and sort; profile, SHAP drivers, orders, recommendations |
| Churn prediction | `/churn` | analyst | risk-band list, model metrics with CIs, what-if prediction (on-demand model) |
| CLV prediction | `/clv` | analyst | predicted 90-day spend by segment, top predicted spenders, what-if |
| Recommendations | `/recommendations` | analyst | per-customer (cold start by state), "customers also bought", offline metrics |
| AI business assistant | `/assistant` | viewer | placeholder until Phase 11; shows no simulated answers |
| Model monitoring | `/models` | viewer (registry: admin) | MLflow registry, table freshness, held-out metrics |
| Data quality | `/data-quality` | admin | the 79-check catalog, with the dataset it ran on |
| Settings | `/settings` | viewer | profile, role, session, data scope |

Navigation shows only the pages the user's role can open. A page reached without the role
explains which role it needs. The API enforces the same rules, so hiding links is a
convenience, not the security boundary.

## Data and state

- **No hard-coded figures.** Every number comes from the API through `useApi`, a typed GET
  hook that aborts stale requests, keeps previous data while new filters load, and derives
  `loading` instead of setting it in an effect.
- **State handling.** Each panel has loading (skeleton), error (message, request id, retry;
  403 says access is missing) and empty states.
- **Data notes.** Analytical panels show the API's `meta` note: source, window and filters.

## Authentication

- **Access token:** in memory only.
- **Refresh token:** in `sessionStorage`, so it survives reloads and ends when the tab closes.
  httpOnly cookies would be stronger, but the API returns tokens in JSON, so this is the
  least-exposed option and the trade-off is documented in `services/api.ts`.
- **Single-flight refresh.** Every caller shares one in-flight refresh. The API rotates refresh
  tokens and revokes the session when an old one is reused, so two concurrent refreshes would
  log the user out. This happened during browser testing, with React StrictMode running the
  startup effect twice, and it is fixed.
- **Retry on 401.** A 401 triggers one refresh and one retry; if that fails, the user is signed
  out.

## Design

- **Tokens.** Colours are CSS variables on `:root`, with separately chosen dark-mode values
  (system preference, or the toggle in the top bar). Series colours come from the same
  validated palette as the Python charts.
- **Charts.** Single-axis only: two measures of different units are never put on one chart.
  Interval bands are used for forecasts, and anomalies are drawn as points over the expected
  line.
- **Accessibility.**
  - a skip link, landmark regions and `aria-sort` on sortable headers
  - visible focus rings, labelled form fields and keyboard-operable controls
  - tables carry captions for screen readers
- **Responsive layout.** The sidebar collapses into a menu below `lg`, and tables scroll
  horizontally inside their card.

## Verified (2026-11-05)

- `tsc --noEmit`, `eslint` (0 errors, 0 warnings) and `vite build` pass. Every page is a
  separate chunk: the main bundle is 109 kB gzipped, the chart library 120 kB.
- **In Chrome against the running API,** as the demo admin:
  - sign-in, and session restore after a full reload (after the single-flight fix)
  - the Executive KPIs match `marts.kpi_overview`: GMV R$15,595,580, 97,222 orders,
    94,046 customers
  - Forecast with all five models; Churn list of 47,023 customers in the high band
    (deciles 1–5 of 94,046)
  - Customer 360 detail with SHAP drivers and recommendations
  - a what-if prediction through the registered MLflow model
  - Model monitoring (registry and freshness), Data quality (full extract, 99,441 orders) and
    Anomalies (12 days, 6 shifts)
- **Screenshots** could not be captured: the browser's screen capture timed out, while the
  page tree stayed readable. They are listed for Phase 14.
