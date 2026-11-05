# Limitations and future improvements

All known limitations in one place. Details stay in the linked documents; this page is the
index, grouped by what each limitation affects.

## Data

| Limitation | Effect | Where |
|---|---|---|
| Historical extract (2016–2018), one Brazilian marketplace | Findings describe that period only; forecasts cannot be checked | [dataset card](dataset_card.md) |
| About 20 continuous months, one Black Friday | Yearly seasonality not modelled | [forecasting card](model_cards/sales_forecasting.md#limitations) |
| No costs or margins | GMV and predicted spend are not profit | [KPI dictionary](kpi_dictionary.md) |
| Anonymised products and customers | No product names, no demographics | [phase0_findings.md](phase0_findings.md#limitations) |
| Statuses as of the extract | Later cancellations are invisible; small look-ahead in repurchase features | [repurchase card](model_cards/repurchase_propensity.md) |
| ~97% one-time customers | Weak signal for every customer-level model | [business findings](business_findings.md) |

## Models

| Limitation | Evidence |
|---|---|
| Repurchase model not distinguishable from the frequency rule on test | [repurchase card](model_cards/repurchase_propensity.md) |
| 90-day spend model no better than the training mean on RMSE | [spend card](model_cards/customer_spend_90d.md) |
| Backtest-selected forecast (Prophet) worse than seasonal naive on test; intervals too narrow (33% coverage of an 80% band) | [forecasting card](model_cards/sales_forecasting.md) |
| Recommendation hit rates are low for every model; only 417 returning buyers evaluable | [recommendations card](model_cards/recommendations.md#limitations) |
| Anomaly detection is unsupervised: no labelled incidents, so no precision or recall | [anomaly card](model_cards/anomaly_detection.md#limitations) |
| No live drift monitoring (static dataset) | [Model monitoring page](screenshots/models.png) |

The selections were not changed after seeing test results; reporting a weak model honestly was
preferred to re-selecting on the test set.

## Platform and operations

| Limitation | Status |
|---|---|
| Docker images and the CI workflow have never run (no Docker on the development machine, no git remote) | [deployment.md](deployment.md) |
| Live LLM answers not verified (no `ANTHROPIC_API_KEY` configured); tools-only mode is tested | [assistant.md](assistant.md#limitations) |
| Power BI DAX values not yet checked in Desktop (the SQL reconciliation targets exist) | [report spec](../powerbi/documentation/report_spec.md) |
| No TLS, no MFA or lockout, in-memory per-process rate limits, secrets from environment variables | [security.md](security.md#known-gaps) |
| `/api/auth/refresh` shares the 10/minute auth limit, so more than 10 full page reloads in a minute end the session until the next minute | Found in Phase 14; the client now keeps the token on a 429, so a later reload restores the session (`test_transient_refresh_failure_does_not_end_the_session`) |
| Warehouse, journey and browser tests need the loaded warehouse, so they run locally, not in CI | [deployment.md](deployment.md#test-layers) |
| ETL, dbt and training run on the host, not in containers or an orchestrator | [deployment.md](deployment.md#docker) |
| No CD stage, no hosted demo | [deployment.md](deployment.md) |

## Future improvements

Ordered by value for effort.

1. **Run CI and the Docker stack** on a GitHub remote: fixes the two biggest "not verified"
   items with no code change expected.
2. **Verify the assistant with a real key** and add a small evaluation set of business
   questions with expected tool calls and figures.
3. **Separate rate limit for token refresh** (or exempt it), so reloads cannot hit the login
   limit.
4. **Orchestrate the batch pipeline** (e.g. Dagster or Airflow): ETL → dbt → train → promote →
   re-score → export, with the consistency tests as the final gate.
5. **Forecast intervals:** conformal calibration on backtests to fix under-coverage; revisit
   model selection with more origins.
6. **Customer models:** treat the problem as "first repurchase" with survival models, and add
   category-level recommendations to the UI next to product-level ones.
7. **Security hardening:** httpOnly refresh cookie with CSRF protection, Redis rate limits,
   TLS proxy with HSTS, secret manager.
8. **Hosted demo** with the sample data and a read-only demo account.
