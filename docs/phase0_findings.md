# Phase 0 — Dataset inspection and design decisions

Numbers below were produced by `data_engineering/scripts/profile_raw.py` on the Kaggle download
of 2026-11-05 (hashes in `data/raw/_manifest.json`). They are a preliminary profile; Phase 2
re-derives and documents the business rules.

## Tables

| File | Rows | Cols | Key | Notes |
|---|---|---|---|---|
| olist_customers_dataset | 99,441 | 5 | `customer_id` | 96,096 distinct `customer_unique_id` |
| olist_orders_dataset | 99,441 | 8 | `order_id` | 8 statuses |
| olist_order_items_dataset | 112,650 | 7 | (`order_id`, `order_item_id`) | max 21 items/order |
| olist_order_payments_dataset | 103,886 | 5 | (`order_id`, `payment_sequential`) | max 29 rows/order |
| olist_order_reviews_dataset | 99,224 | 7 | (`review_id`, `order_id`) | `review_id` alone not unique (814 dup rows) |
| olist_products_dataset | 32,951 | 9 | `product_id` | typo columns `*_lenght` |
| olist_sellers_dataset | 3,095 | 4 | `seller_id` | |
| olist_geolocation_dataset | 1,000,163 | 5 | none | 19,015 zip prefixes; 261,831 exact dup rows |
| product_category_name_translation | 71 | 2 | `product_category_name` | |

## Date coverage

- `order_purchase_timestamp` runs from 2016-09-04 to 2018-10-17.
- 2016 is sparse: 4, 324, 0 and 1 orders in Sep–Dec 2016. Sep–Oct 2018 is truncated: 16 and 4 orders.
- The continuous analysis window is 2017-01-01 to 2018-08-31.
- The peak month is 2017-11 with 7,544 orders (Black Friday).

## Order status

delivered 96,478 · shipped 1,107 · canceled 625 · unavailable 609 · invoiced 314 ·
processing 301 · created 5 · approved 2

## Data quality issues

| Issue | Count |
|---|---|
| Orders without items | 775 |
| Orders without payments | 1 |
| Orders without reviews | 768 |
| Orders with more than one review | 547 |
| \|items + freight − payments\| > 1 BRL | 249 orders |
| `payment_type = not_defined` | 3 rows |
| `payment_value = 0` | 9 rows |
| Products with null category | 610 |
| Categories missing English translation | `pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos` |
| Products with zero weight / null dimensions | 4 / 2 |
| Status delivered but no customer delivery date | 8 |
| Status not delivered but delivery date set | 6 |
| Carrier date before purchase | 166 |
| Customer delivery before carrier date | 23 |
| `shipping_limit_date` outliers | up to 2020-04-09 |
| Geolocation points outside the Brazil bounding box | 42 |
| Customer / seller zip prefixes missing from geolocation | 278 / 7 rows |
| Review comment title / message null | 88.34% / 58.70% |

## Money (all statuses, BRL)

- Σ price = 13,591,643.70
- Σ freight = 2,251,909.54
- Σ payment_value = 16,008,872.12

Payments exceed item value plus freight. Phase 2 explains the difference fully; see BR-04 in
[business_rules.md](business_rules.md#br-04-payments). Most of it (162,591.95 BRL) is payments on
orders that have no items.

## Behavioral facts that shape the ML design

- Only 2,997 of 96,096 customers (3.12%) placed more than one order. The maximum is 17 orders.
- 54.98% of sold products were sold exactly once. Only 5.72% of customers bought 2 or more distinct products.
- Delivered-order lead time: mean 12.56 days, median 10.22, p95 29.27, max 209.6.
  About 6.8% of delivered orders arrived after the estimated date (calendar-date comparison).

## Decisions

1. All customer analytics use `customer_unique_id`. `customer_id` is a per-order key.
2. Churn is reframed as **repurchase propensity within H days** of a cutoff date T, with churn = no repurchase. Training snapshot windows must end before the test cutoff (T_train + H ≤ T_test).
3. Revenue (GMV = price + freight) is computed from order items. Payments are a separate measure and are never summed together with items. Canceled and unavailable orders are excluded from revenue by default.
4. Silver-layer cleaning is implemented as dbt staging models. Python only ingests and validates raw files.

## Limitations

- The data is historical (2016–2018) and covers one marketplace in Brazil.
- No cost data: profit cannot be computed. Freight and GMV metrics are labeled as proxies.
- The data is anonymized: no product names and no customer demographics.
- About 20 months of continuous data includes only one Black Friday, so yearly seasonality is poorly identified.
- Interactions are very sparse, so product-level recommendation metrics are expected to be low. Category-level evaluation is reported alongside.
