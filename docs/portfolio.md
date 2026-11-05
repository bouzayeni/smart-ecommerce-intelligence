# Portfolio overview

A one-page tour for reviewers: what was built, what it found, how well the models work, and
where to look in the code. Numbers are copied from generated documents (linked); none are
estimates.

## In one paragraph

An end-to-end platform on 99,441 real (historical, anonymised) marketplace orders: a tested
ETL into PostgreSQL, a dbt star schema with enforced contracts, KPI views shared by Power BI,
the API and an AI assistant, six model families each compared with a simple baseline, and a
secured FastAPI + React application to use them. The emphasis is on **correctness and
honesty**: every KPI has one definition, every model is evaluated chronologically against a
baseline with confidence intervals, and weak results are reported as weak.

## Where to look, by role

| Role | Start here | What it shows |
|---|---|---|
| Data Analyst | [business_findings.md](business_findings.md), [kpi_dictionary.md](kpi_dictionary.md), [notebook](../notebooks/exploration/01_exploratory_analysis.ipynb) | KPI definitions with formulas, findings with evidence vs hypotheses, cohort and concentration analysis |
| BI Analyst | [Power BI report spec](../powerbi/documentation/report_spec.md), [star_schema.md](star_schema.md), `powerbi/` | Semantic model (TMDL) over a star schema, DAX measures reconciled to SQL |
| Data Engineer | [etl_bronze.md](etl_bronze.md), [data_quality_report.md](data_quality_report.md), [star_schema.md](star_schema.md), [data_dictionary.md](data_dictionary.md), [architecture.md](architecture.md) | Idempotent, hash-checked ingestion; 79 data-quality checks; dbt contracts and tests; least-privilege roles; cross-layer consistency tests |
| Junior ML Engineer | [model cards](model_cards/), [deployment.md](deployment.md), `ml/` | Point-in-time features, chronological splits, baselines, CIs, calibration, SHAP, MLflow registry with a promotion gate, serving bundles |
| Software / full-stack | [api.md](api.md), [frontend.md](frontend.md), [security.md](security.md), [assistant.md](assistant.md) | JWT with rotating refresh tokens, RBAC tested as a matrix, audit log, CSP, tool-grounded LLM assistant, Playwright E2E |

## Key business findings

From [business_findings.md](business_findings.md) (analysis window 2017-01-01 → 2018-08-21):

- GMV R$ 15.6 M from 97,222 revenue orders and 94,046 customers; average order R$ 160.
- **Only 3.03% of customers buy again**: growth came from acquisition, not loyalty.
- **Late deliveries are strongly associated with bad reviews**: average score 2.21 for late
  orders vs 4.28 on time; 55.3% of late orders get 1 star (6.7% on time).
- SP, RJ and MG are 62.4% of GMV; late-delivery rates range from 4.1% (SP) to 18.2% (MA).
- The top 10% of customers are 38.3% of GMV, and 90.6% of them ordered only once.

## Results against baselines

From the model cards (held-out test periods, untouched until final evaluation):

| Model | Selected model on test | Baseline on test | Verdict |
|---|---|---|---|
| [Repurchase propensity](model_cards/repurchase_propensity.md) (90 days) | calibrated logistic regression, PR-AUC 0.0139 (CI 0.0108–0.0200) | frequency rule, PR-AUC 0.0199 (CI 0.0134–0.0325) | Not distinguishable from the rule; both above the 0.0062 base rate |
| [90-day spend](model_cards/customer_spend_90d.md) | RMSE 17.45 (CI 15.09–19.90); top-decile capture 19.9% | training mean RMSE 17.46; business rule capture 21.2% | No meaningful improvement |
| [Sales forecast](model_cards/sales_forecasting.md) (90 days) | Prophet (selected on backtests), WAPE 32.2% | seasonal naive, WAPE 28.6% | Worse than the baseline on test; LSTM was best on test (17.3%) but was not re-selected after seeing the test |
| [Recommendations](model_cards/recommendations.md) (returning buyers) | content-based, hit rate@10 0.060 (CI 0.038–0.084) | popularity, 0.014 (CI 0.005–0.028) | Better than popularity, on only 417 evaluable buyers |
| [Anomaly detection](model_cards/anomaly_detection.md) | Isolation Forest: 12 anomaly days, 6 on calendar events; 6 sustained-shift episodes | z-rule: 164 days | Unsupervised: no labels to compute precision |
| [RFM segmentation](model_cards/rfm_segmentation.md) | Quintile R and M scores, rule-based F (97% have one order), ordered segment rules | — | Descriptive, no target to evaluate |

The main lesson is about the data, not the algorithms: with about 97% one-time buyers,
customer-level ML barely beats simple rules, and the project shows that rather than hiding it.

## Screenshots

Captured from the running application with real warehouse data by
`backend/scripts/capture_screenshots.py` (admin account, light theme).

| | |
|---|---|
| ![Executive dashboard](screenshots/executive.png) Executive dashboard | ![Sales analytics](screenshots/sales.png) Sales analytics with filters |
| ![Sales forecasting](screenshots/forecast.png) Forecast with intervals and model comparison | ![Anomaly detection](screenshots/anomalies.png) Anomaly detection |
| ![Customer 360](screenshots/customer-360.png) Customer 360 with SHAP reasons | ![Segmentation](screenshots/segments.png) RFM segmentation |
| ![Churn prediction](screenshots/churn.png) Churn risk | ![CLV prediction](screenshots/clv.png) 90-day spend |
| ![Recommendations](screenshots/recommendations.png) Recommendations | ![AI assistant](screenshots/assistant.png) AI assistant (tools-only mode, no API key configured) |
| ![Model monitoring](screenshots/models.png) Model registry and metrics | ![Data quality](screenshots/data-quality.png) Data quality checks |
| ![Customers](screenshots/customers.png) Customer list (analyst+) | ![Login](screenshots/login.png) Sign-in |

## Engineering practices shown

- **One definition per KPI**, implemented in SQL views and DAX and reconciled
  ([KPI dictionary](kpi_dictionary.md)).
- **Tests at every layer**: unit and contract tests in CI; pipeline, cross-layer consistency,
  API journey and browser E2E tests locally ([test layers](deployment.md#test-layers)).
  These tests found and fixed real bugs, for example audit denials lost to a rollback, a
  model-version type mismatch, and a refresh-token loss on a transient 429.
- **Least privilege** in the database (three roles), the API (three application roles) and
  the assistant (role-filtered, read-only tools, SQL allowlist).
- **Reproducibility**: locked dependencies (`uv.lock`, `package-lock.json`), hashed raw files,
  generated documentation (data dictionary, findings, model cards, quality report).

## Honest status

What is not verified, and what would come next, is listed in [limitations.md](limitations.md).
The three biggest gaps are: CI and Docker images never run (no remote, no Docker locally), the
live Claude path not run (no API key), and Power BI values not yet checked in Desktop.
