# Power BI report specification

The semantic model is generated: tables, relationships, measures and Power Query sources. The
**report pages are created empty**. Lay out the visuals in Power BI Desktop from this spec,
because the report visual format is too fragile to generate reliably by script.

Measures are in display folders (Sales, Customers, Operations, Payments, Profitability
proxies). Definitions are in [kpi_dictionary.md](../../docs/kpi_dictionary.md).

**Global rules**

- **Canvas and slicers.** Canvas is 1280 × 720. Put one slicer row at the top:
  - `dim_date[year_month]`, as a between or list slicer
  - `fact_orders[customer_state_at_order]`
  - `dim_products[category_name]`, on product pages only
- **Data note.** Add a text box in the page footer: *"Olist public dataset, purchases
  2017-01-01 → 2018-08-21. Historical data. GMV is not profit."*
- **Partial months.** Do not show month-over-month change for 2018-08. The measure returns
  blank there.
- **Colours.** One accent colour for single-series visuals. Status colours (red/amber) only
  for late or cancelled.

## 1. Executive Overview

| Visual | Fields |
|---|---|
| KPI cards (6) | `GMV (BRL)`, `Revenue Orders`, `Average Order Value (BRL)`, `Customers`, `On-Time Delivery Rate %`, `Avg Review Score` |
| Line chart | Axis `dim_date[year_month]`; value `GMV (BRL)` |
| Column chart | Axis `dim_date[year_month]`; value `GMV MoM Growth %` |
| Bar chart (top 10) | Axis `dim_products[category_name]`; value `Item GMV (BRL)` |
| Filled map or bar | `fact_orders[customer_state_at_order]`; `GMV (BRL)` |

## 2. Sales Performance

| Visual | Fields |
|---|---|
| Cards | `GMV (BRL)`, `Merchandise Value (BRL)`, `Avg Freight per Order (BRL)`, `Freight Share of GMV % (proxy)` |
| Line chart (daily) | `dim_date[date_day]`; `GMV (BRL)`. Annotate 2017-11-24 (Black Friday) |
| Matrix | Rows `dim_date[year]`, `dim_date[month_name]`; values `GMV (BRL)`, `Revenue Orders`, `Average Order Value (BRL)`, `GMV MoM Growth %` |
| Donut or bar | `dim_payment_type[payment_type_label]`; `Payment Value (BRL)` |
| Bar | `dim_date[day_name]`; `Revenue Orders` (weekday pattern) |

## 3. Customer Analytics

| Visual | Fields |
|---|---|
| Cards | `Customers`, `Repeat Customers`, `Repeat Purchase Rate %`, `Avg Orders per Customer`, `Top 10% Customers GMV Share %` |
| Column chart | `kpi_customer_concentration[gmv_decile]`; `share_of_gmv` (sum) |
| Matrix (cohort heatmap) | Rows `kpi_customer_cohorts[cohort]`; columns `months_since_first_order` (filter ≤ 12); values `retention_rate` (sum), with conditional formatting |
| Bar | `fact_orders[customer_state_at_order]`; `Customers` |

The repeat rate is about 3%. Say so explicitly in a text box; do not hide it.

## 4. Product Analytics

| Visual | Fields |
|---|---|
| Treemap | `dim_products[category_name]`; `Item GMV (BRL)` |
| Table | `dim_products[product_id]`, `dim_products[category_name]`, `Item GMV (BRL)`, `Units Sold`, `Product GMV Rank`. Top N filter = 20 by `Item GMV (BRL)` |
| Scatter | Details `dim_products[category_name]`; X `Units Sold`; Y `Item GMV (BRL)` |
| Bar | `dim_sellers[seller_state]`; `Item GMV (BRL)` |

Products are anonymised: there are no names, only ids and categories.

## 5. Logistics & Operations

| Visual | Fields |
|---|---|
| Cards | `Avg Delivery Days`, `Median Delivery Days`, `Late Delivery Rate %`, `Cancellation Rate %`, `Delivery-Eligible Orders` |
| Line chart | `dim_date[year_month]`; `Late Delivery Rate %`. Months after 2018-07 have no eligible orders (maturity rule) |
| Bar | `fact_orders[customer_state_at_order]`; `Avg Delivery Days`, sorted descending |
| Clustered column | `fact_reviews[review_score]` (filter `is_selected_for_order` = true); count, split by `fact_reviews[is_order_late]` |
| Column | `dim_date[year_month]`; `Cancellation Rate %` |

## Saving

- **Save as PBIP** (File → Save as → Power BI project). The `.pbix` format is git-ignored.
- **Credentials are never saved** in the PBIP.
- **Re-running `build_powerbi_model.py` overwrites the semantic model and the empty report
  shell.** After you have built visuals, commit the report first, and then regenerate only
  the semantic model (`--model-only`).
