# KPI dictionary

Every KPI has the same definition in three places:
- the **SQL views** (`marts.kpi_*`, dbt models in `warehouse/dbt/models/marts/kpi`)
- the **DAX measures** (`powerbi/measures.yaml` → semantic model)
- the API (Phase 9)

The DAX measures are reconciled against SQL by `powerbi/tools/Invoke-DaxChecks.ps1`.

**Standard filters**

| Scope | Filter |
|---|---|
| Revenue KPIs | `is_revenue_order AND is_in_analysis_window`. Statuses: delivered, shipped, invoiced, processing, approved; window 2017-01-01 → 2018-08-21 (BR-02, BR-03) |
| Delivery KPIs | `is_delivery_kpi_eligible AND is_in_analysis_window`. Delivered, consistent timestamps, cohort at least 30 days old (BR-07) |
| All-order KPIs | `is_in_analysis_window` only |

Money is BRL. Values are from the full extract, built 2026-11-05.

## Sales

| ID | KPI | Definition / formula | SQL view | DAX measure | Value |
|---|---|---|---|---|---|
| S1 | Total revenue (GMV) | Σ(price + freight) of revenue orders. **Gross merchandise value, not Olist revenue and not profit** | `kpi_overview.gmv` | `GMV (BRL)` | 15,595,580.13 |
| S1b | Merchandise value | Σ price (GMV without freight) | `kpi_overview.merchandise_value` | `Merchandise Value (BRL)` | 13,373,379.99 |
| S2 | Total orders | Count of revenue orders | `kpi_overview.revenue_orders` | `Revenue Orders` | 97,222 |
| S3 | Average order value | GMV ÷ revenue orders | `kpi_overview.avg_order_value` | `Average Order Value (BRL)` | 160.41 |
| S4 | Monthly revenue growth | (GMVₘ − GMVₘ₋₁) ÷ GMVₘ₋₁. Only when both months are complete; Aug 2018 is partial, so it is blank | `kpi_monthly_sales.gmv_mom_growth` | `GMV MoM Growth %` | Jul 2018: +1.90% |
| S5 | Revenue by category | Item-level GMV by English category; share = category ÷ total | `kpi_sales_by_category` | `Item GMV (BRL)`, `Category Share of GMV %` | #1 health_beauty 9.09% |
| S6 | Revenue by region | GMV by **customer state at order time** | `kpi_sales_by_state` | `GMV (BRL)` × `fact_orders[customer_state_at_order]` | SP 37.22% |
| S7 | Top products | Products ranked by item GMV. Products are anonymised: id + category only | `kpi_product_ranking` | `Product GMV Rank` | #1 = 66,211.46 |
| S8 | Revenue trend | Daily or monthly GMV (zero-order days included) | `agg_daily_sales`, `kpi_monthly_sales` | `GMV (BRL)` × `dim_date` | 598 days |
| S9 | Payment mix | Payment value and average installments by type. **Payments ≠ GMV** (BR-04) | `kpi_payment_mix` | `Payment Value (BRL)`, `Avg Installments` | — |

## Operations

| ID | KPI | Definition / formula | SQL view | DAX measure | Value |
|---|---|---|---|---|---|
| O1 | Average delivery time | Mean (delivered timestamp − purchase timestamp) in days, eligible orders. The median is also given because the distribution is right-skewed | `kpi_overview.avg_delivery_days` / `median_delivery_days` | `Avg Delivery Days`, `Median Delivery Days` | 13.00 / 10.80 |
| O2 | On-time delivery rate | 1 − late rate, eligible orders | `kpi_overview.on_time_delivery_rate` | `On-Time Delivery Rate %` | 93.09% |
| O3 | Late delivery rate | Eligible orders with delivered **calendar date** > estimated date, ÷ eligible orders | `kpi_overview.late_delivery_rate` | `Late Delivery Rate %` | 6.91% |
| O4 | Order cancellation rate | Orders with status canceled or unavailable ÷ all orders. Uses status at extract time; later cancellations are unknown | `kpi_overview.cancellation_rate`, `kpi_operations_monthly` | `Cancellation Rate %` | 1.18% |
| O5 | Average freight cost | Σ freight ÷ revenue orders. Freight is charged to the customer | `kpi_overview.avg_freight_per_order` | `Avg Freight per Order (BRL)` | 22.86 |
| O6 | Review score distribution | Per-order selected review (BR-06), orders in the window; split by on-time vs late | `kpi_review_distribution` | `Avg Review Score`, `Reviewed Orders` | mean 4.09 |

## Customers

| ID | KPI | Definition / formula | SQL view | DAX measure | Value |
|---|---|---|---|---|---|
| C1 | Total customers | Distinct `customer_unique_id` with 1+ revenue order | `kpi_overview.customers` | `Customers` | 94,046 |
| C2 | Repeat purchase rate | Customers with 2+ revenue orders **within the selected period** ÷ customers | `kpi_overview.repeat_purchase_rate` | `Repeat Customers`, `Repeat Purchase Rate %` | 3.03% (2,852) |
| C3 | Average orders per customer | Revenue orders ÷ customers | `kpi_overview.avg_orders_per_customer` | `Avg Orders per Customer` | 1.0338 |
| C4 | Customer revenue contribution | Share of GMV by customer decile (1 = top 10%) | `kpi_customer_concentration` | `Top 10% Customers GMV Share %` | top 10%: 38.30% |
| C5 | Customer retention | Monthly acquisition cohorts: share of the cohort with a revenue order N months after their first one. Later cohorts are right-censored | `kpi_customer_cohorts` | imported table `kpi_customer_cohorts` | month 1: about 0.5% |

The repeat rate here (3.03%) is lower than the 3.12% quoted in Phase 2. Phase 2 counted all
statuses over the whole extract; this KPI counts revenue orders inside the analysis window.

## Profitability: proxies only

The dataset has **no product cost, commission, marketing or logistics cost**, so no margin or
profit KPI is computed. The only proxy offered is clearly labelled:

| ID | KPI | Definition | SQL | DAX | Value |
|---|---|---|---|---|---|
| P1 | Freight share of GMV (proxy) | Σ freight ÷ GMV. Shows how much of what customers pay is shipping. **Not a margin** | `kpi_overview.freight_share_of_gmv` | `Freight Share of GMV % (proxy)` | 14.25% |

## Using measures correctly in Power BI

- **Category, product or seller slices:** use `Item GMV (BRL)`, which comes from
  `fact_order_items`. `GMV (BRL)` is order-level, and products filter only the items fact;
  facts are not related to each other, which avoids ambiguous paths and double counting.
- **Region:** use `fact_orders[customer_state_at_order]`. `dim_customers[customer_state]` is
  the latest address.
- **Average review score:** use `Avg Review Score`, which uses one review per order. Do not
  average `fact_reviews[review_score]` without filtering `is_selected_for_order`.
