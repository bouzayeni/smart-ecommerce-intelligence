# Dataset card: Brazilian E-Commerce Public Dataset by Olist

## Summary

| | |
|---|---|
| Source | Olist, [*Brazilian E-Commerce Public Dataset by Olist*](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) on Kaggle |
| Download used | 2026-11-05 through the Kaggle API; SHA-256 of every file in `data/raw/_manifest.json` |
| License | **CC BY-NC-SA 4.0** (attribution, non-commercial, share-alike). Check the Kaggle page for current terms |
| Content | Orders placed on the Olist marketplace in Brazil, 2016-09-04 → 2018-10-17 |
| Size | 9 CSV files, about 1.55 million rows in total (1,000,163 of them geolocation points) |
| Personal data | Anonymised by the publisher: hashed customer, seller, product and order ids; no names, no product titles, no demographics. Review text is free text in Portuguese |
| Committed to this repository | No. Only `data/sample/`, a small referentially consistent subset used by tests and CI, under the same license |

## Files

Row counts and keys are in [phase0_findings.md](phase0_findings.md#tables); every column, with
its warehouse type, is in the [data dictionary](data_dictionary.md#raw).

| File | Grain |
|---|---|
| `olist_orders_dataset` | one row per order: status and the five lifecycle timestamps |
| `olist_order_items_dataset` | one row per unit sold: product, seller, price, freight |
| `olist_order_payments_dataset` | one row per payment line: type, instalments, value |
| `olist_order_reviews_dataset` | one row per (review, order): score 1–5, optional title and comment |
| `olist_customers_dataset` | one row per order-level customer id, with `customer_unique_id` (the person) and location |
| `olist_sellers_dataset` | one row per seller with location |
| `olist_products_dataset` | one row per product: Portuguese category, dimensions, photo count |
| `olist_geolocation_dataset` | zip prefix → coordinates (many points per prefix, duplicates) |
| `product_category_name_translation` | Portuguese → English category names |

## Intended use in this project

Portfolio demonstration of data engineering, BI and ML on realistic marketplace data. Every
figure in the repository describes **this historical extract**, not Olist's current business.
Forecasts are predictions for late 2018, which can no longer be checked against the dataset.

## Known issues and how they are handled

Each issue is measured in the [data quality report](data_quality_report.md) and handled by a
numbered rule in [business_rules.md](business_rules.md). Rows are flagged, not silently dropped
(BR-10).

| Issue | Handling |
|---|---|
| `customer_id` is per order; the person is `customer_unique_id` | Customer metrics use `customer_unique_id` (BR-01) |
| Sparse 2016 and truncated Sep–Oct 2018 | Analysis window 2017-01-01 → 2018-08-21 (BR-02) |
| Payments do not always equal items + freight | GMV is defined from items; payments are reported separately (BR-03, BR-04) |
| Orders with several reviews, reviews shared by several orders | One selected review per order (BR-06) |
| Inconsistent delivery timestamps | Excluded from delivery KPIs only (BR-07) |
| Missing or untranslated categories, column typos (`*_lenght`) | `unknown` category, columns renamed in staging (BR-08) |
| Geolocation duplicates and points outside Brazil | Median per zip prefix inside Brazil's bounding box (BR-09) |

## Limitations and biases

- One marketplace, one country, about 20 months of continuous data with a single Black
  Friday.
- No cost or margin data: GMV is not revenue or profit. Predicted spend is not profit either.
- Statuses are as of the extract date. Later cancellations or deliveries are invisible.
- About 97% of customers order once, which caps what customer-level models can learn.
- Customers and sellers are concentrated in the South-East (SP alone is about 37% of GMV), so
  national averages are dominated by one state.
- Review scores exist for almost every order, but titles and comments are optional and
  sparse; the project uses scores only.

## Citation

Olist. *Brazilian E-Commerce Public Dataset by Olist*. Kaggle.
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce (use the citation shown on that
page).
