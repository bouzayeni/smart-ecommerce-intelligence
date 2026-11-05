# Sample fixture

A small, referentially consistent subset of the Olist dataset, used by tests and CI so they do
not depend on the full 125 MB download.

Generated with:

```bash
uv run python -m data_engineering.scripts.make_sample --customers 400 --repeat-customers 60 --per-status 3 --geo-per-zip 3 --seed 42
```

- Customers are sampled by `customer_unique_id`, and all of their orders are kept, so repeat buyers are included.
- All 8 `order_status` values are present.
- Items, payments, reviews, products, sellers and geolocation rows are restricted to the sampled orders. Geolocation keeps at most 3 rows per zip prefix.
- Values are copied as raw strings, so source-data quirks are preserved.

Source: *Brazilian E-Commerce Public Dataset by Olist* (Kaggle), CC BY-NC-SA 4.0.
This fixture is a derived subset under the same license.
