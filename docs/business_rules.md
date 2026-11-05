# Business rules

Decisions taken in Phase 2 that every later phase (dbt models, KPIs, ML, API) must follow.
Configurable values live in [`config/business_rules.yaml`](../config/business_rules.yaml).
Evidence comes from [data_quality_report.md](data_quality_report.md) and the notebook
[01_exploratory_analysis.ipynb](../notebooks/exploration/01_exploratory_analysis.ipynb).
Figures quoted here are from the full Kaggle extract (manifest hashes in `data/raw/_manifest.json`).

## BR-01 Customer identity

**Rule.** Customer-level analytics use `customer_unique_id`. `customer_id` is a per-order key:
each order gets a new one.

**Evidence.** There are 99,441 `customer_id` values for 96,096 people. 2,997 people have more
than one `customer_id`, and each of them placed more than one order.

**Location.** A customer's current location is the one on their most recent order. Regional
revenue uses the location at order time. Of the 2,997 repeat buyers, 250 changed zip prefix
and 39 changed state between orders.

## BR-02 Analysis window

**Rule.** The window is 2017-01-01 to **2018-08-21**, pinned in `analysis_window.end_override`.
KPIs, time series and models use only orders purchased inside it. Raw data outside the window
stays in the warehouse; it is just excluded from analysis.

**Start.** 2016 is not continuous: 4 orders in Sep, 324 in Oct, 0 in Nov and 1 in Dec (Dec 23).

**End.** Daily volume falls from about 250 orders a day to 1 between 2018-08-22 and 2018-08-31.
Only 16 orders exist in Sep 2018 and 4 in Oct 2018. This looks like an end-of-extract artifact
rather than a fall in demand, but the cause cannot be verified from the data.

Detection rule: the window ends on the last day whose volume is at least 0.7 × the median of the
previous 28 days.
- Weekends normally sit around 0.70 (Sat 2018-08-18: 0.70, Sun 08-19: 0.72).
- Weekday 2018-08-22 (a Wednesday) is already at 0.69, and 08-23 drops to 0.54.
- Across ratio 0.5–0.8 and baseline 14–56 days, the detected end ranges from 08-21 to 08-23.
- The latest clearly complete day is 08-21.

**Consequences.**
- August 2018 is a partial month (21 days). Month-over-month KPIs must flag it, or compare
  complete months only (through 2018-07).
- Anomaly detection must not flag the truncation as a sales drop.
- The forecasting test set ends on 2018-08-21.

## BR-03 Revenue (GMV)

**Rule.** GMV = Σ(`price` + `freight_value`) over **order items**.

**Statuses.**
- Counted: `delivered`, `shipped`, `invoiced`, `processing`, `approved`.
- Excluded: `canceled`, `unavailable`, `created`.

Payments are a separate measure. They are never added to item values, and items are never
joined to payments row by row, because that join multiplies rows.

| Status | Orders | With items | Item value (BRL) | Counted |
|---|---|---|---|---|
| delivered | 96,478 | 96,478 | 15,419,773.75 | yes |
| shipped | 1,107 | 1,106 | 177,129.34 | yes |
| canceled | 625 | 461 | 105,885.72 | no |
| unavailable | 609 | 6 | 2,140.49 | no |
| invoiced | 314 | 312 | 68,988.75 | yes |
| processing | 301 | 301 | 69,394.11 | yes |
| created | 5 | 0 | 0.00 | no |
| approved | 2 | 2 | 241.08 | yes |

Shipped, invoiced, processing and approved orders are counted because they were sold and not
reversed in the extract. Some may have been canceled after the extract date; this cannot be
known.

**Not profit.** GMV is not revenue to Olist and not profit. The dataset has no product cost and
no commission or marketing cost. Freight is billed to the customer. Any "profitability" view is
a labeled proxy.

## BR-04 Payments

**Rule.** Payment totals come only from `order_payments`.
- `payment_type = not_defined` (3 rows) maps to `unknown`.
- Zero-value payments (9 rows) and zero installments (2 rows) are flagged, not removed.

**Reconciliation.** Σ payments (16,008,872.12) exceeds Σ item value (15,843,553.24) by
165,318.88 BRL. The gap is fully explained:

| Component | BRL |
|---|---|
| Payments on 775 orders that have no items (603 unavailable, 164 canceled, …) | +162,591.95 |
| Item value of the 1 order with no payment | −143.46 |
| 295 orders paid more than their item value (> 0.01) | +3,070.45 |
| 87 orders paid less (< −0.01) | −199.56 |
| Rounding within ±0.01 | −0.50 |

98,283 of 98,665 orders that have both items and payments (99.6%) match to the cent.

The overpayments are concentrated in credit card payments: 249 of 264 orders above 0.01 in the
Phase 2 investigation. They look consistent with installment interest, but the dataset does not
document this, so it is a hypothesis.

## BR-05 Order quantity and items

**Rule.** One row in `order_items` is one unit. Quantity = number of rows. `order_item_id` runs
1..n within each order (checked). 7,088 (order, product) pairs appear on more than one row,
which is how quantity above 1 is encoded. Freight is recorded per row.

## BR-06 Reviews

**Grain.** One row per (`review_id`, `order_id`); that pair is unique.

**Shared review IDs.** 789 `review_id` values each cover several orders (1,603 rows). In every
case those orders belong to the same customer, were purchased at the same timestamp, and carry
the same score. They are one review for orders placed together, not duplicates.

**Score per order.** 547 orders have more than one review, and 202 of them have different
scores. The score per order is the **most recently answered** review
(`reviews.per_order_score: latest_answer`). Reviews are reduced to one row per order before
joining them to orders.

**Leakage.** A review is known only from its `review_answer_timestamp`. ML features at cutoff T
may use only reviews answered before T. Review creation happens a median of 11 days after
purchase.

## BR-07 Delivery KPIs

**Population.** Orders with status `delivered`, a customer delivery date, and consistent
timestamps. Two kinds of inconsistent order are excluded and flagged:
- carrier pickup before purchase: 166 orders
- delivery before carrier pickup: 23 orders

This leaves 96,282 orders.

**Late.** An order is late when the delivery **calendar date** is after
`order_estimated_delivery_date`. The estimated date has no time part. Comparing timestamps would
count same-day deliveries as late, giving 8.11% instead of 6.77% in the Phase 2 investigation.

**Lead time.** Delivery days = delivered timestamp − purchase timestamp, in days.
- Median 10.2 days.
- 306 orders took more than 60 days; the longest took 209.6. These are kept and flagged.

**Censoring.** Orders still in transit at the extract date are missing from delivered cohorts,
so recent cohorts look faster than they are. Delivery KPIs exclude purchase cohorts younger than
`delivery.cohort_maturity_days` (30) at the window end.

**Late vs review.** Late orders average a 2.27 review score, against 4.29 for on-time orders.
This is descriptive, not causal.

## BR-08 Products and categories

**Rule.**
- Null category (610 products) maps to `unknown`.
- Two categories have no English translation (13 products), so the project provides labels:
  - `pc_gamer` → `pc_gamer`
  - `portateis_cozinha_e_preparadores_de_alimentos` → `kitchen_portables_and_food_preparers`
- Zero or missing weight (6 products) becomes null in the silver layer.
- The column typos `product_name_lenght` and `product_description_lenght` are renamed in
  staging.

## BR-09 Geolocation

**Rule.** `dim_geolocation` has one row per zip prefix. Its coordinates are the median lat/lng
over points inside the Brazil bounding box (42 points outside it are dropped). City and state
are the most frequent values; 8 prefixes span more than one state.
- Exact duplicate rows (261,831) are irrelevant after aggregation.
- Customers and sellers whose zip prefix has no coordinates (278 and 7 rows) get null
  coordinates.

Zip prefixes are 5-digit strings and must never be cast to integers, because that drops leading
zeros.

## BR-10 Flag, don't drop

Every warn-level check in the quality report becomes a boolean flag column in the silver layer
(for example `is_timestamp_inconsistent` or `has_no_items`). KPIs filter on these flags
explicitly. No source row is deleted between bronze and silver.

## Implications for modeling (Phase 6–8)

**Repurchase instead of churn.** Only 3.12% of customers bought twice, so classic churn would
label about 97% of customers as churned. Phase 6 models P(repurchase within H days of cutoff
T), with churn = no repurchase. Positives are rare; PR-AUC is the primary metric.

**Recommendations.** 54.98% of products sold exactly once. Only 5.72% of customers bought 2+
distinct products. The customer × product matrix density is 0.0032%. Product-level CF metrics
will be low; category-level evaluation and a popularity baseline are required for honest
comparison.

**Forecasting.** 598 daily points include a single Black Friday (2017-11-24, 1,176 orders).
Yearly seasonality is weakly identified.
