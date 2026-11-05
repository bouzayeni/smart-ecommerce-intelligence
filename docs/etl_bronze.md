# ETL — Bronze layer

The bronze layer is the untouched copy of the source files inside PostgreSQL: schema `raw`,
owned by `etl_user`. Cleaning happens later, in the dbt staging models (Phase 4).

```
data/raw/*.csv ─► 1 manifest ─► 2 contract ─► 3 quality gate ─► 4 COPY per table ─► raw.<table>
                    (SHA-256)     (pandera)     (Phase 2 errors)   (atomic swap)      raw._ingestion_log
```

Run it with:

```bash
uv run python -m data_engineering.etl.load_bronze          # load changed files
uv run python -m data_engineering.etl.load_bronze --force  # reload everything
```

Exit codes: `0` success, `1` a gate failed and nothing was written, `2` one or more tables
failed to load (each failure is logged, and those tables keep their previous data).

## Gates (all run before any write)

| # | Gate | Implementation | Fails when |
|---|---|---|---|
| 1 | Manifest | `bronze.verify_manifest` | a file's SHA-256 differs from `data/raw/_manifest.json`, so the source changed after download |
| 2 | File contract | `validation/contracts.py` (pandera) | header is not exactly the expected columns in order; an ID is not 32-char hex; a zip prefix is not 5 digits; a required value is empty; a timestamp or number has the wrong format |
| 3 | Quality gate | `quality/checks.py` | any error-level check fails: duplicate key, orphan foreign key, unknown status, non-positive price, … |

The contract covers the **structure of each file on its own**. The quality gate covers
**content and relationships between files**. Warn-level findings never block the load; they
become flags in staging (rule BR-10).

A missing **required** file fails gate 0. A missing **optional** file (geolocation,
category translation) logs a warning, and that table is not loaded.

## Tables

DDL: [`warehouse/sql/bronze/001_raw_tables.sql`](../warehouse/sql/bronze/001_raw_tables.sql).
It is generated from `data_engineering/sources.py`, and a test fails if the committed file
drifts from the generator.

| Table | Source file | Grain |
|---|---|---|
| `raw.customers` | olist_customers_dataset.csv | one row per source row |
| `raw.orders` | olist_orders_dataset.csv | ″ |
| `raw.order_items` | olist_order_items_dataset.csv | ″ |
| `raw.order_payments` | olist_order_payments_dataset.csv | ″ |
| `raw.order_reviews` | olist_order_reviews_dataset.csv | ″ |
| `raw.products` | olist_products_dataset.csv | ″ |
| `raw.sellers` | olist_sellers_dataset.csv | ″ |
| `raw.geolocation` | olist_geolocation_dataset.csv | ″ (duplicates kept) |
| `raw.category_translation` | product_category_name_translation.csv | ″ |

- Every source column is `text`, with the source name kept as is, typos included
  (`product_name_lenght`).
- Unquoted empty CSV fields are stored as `NULL`; a quoted `""` stays an empty string.
- No keys or constraints are enforced in bronze. The gates check them, and staging models
  enforce them.

Each table also carries metadata columns:

| Column | Meaning |
|---|---|
| `_batch_id` | UUID of the load run |
| `_source_file` | source filename |
| `_source_sha256` | hash of the exact file loaded |
| `_source_row` | 1-based data row number in the file, so file order can be rebuilt |
| `_ingested_at` | load start time (UTC) |

`raw._ingestion_log` holds one row per table per run, with status `loaded`, `skipped` or
`failed`, the row count, the time window and any error message.

## Load mechanics

1. Inside one transaction per table:
   - the file bytes are streamed with `COPY … FROM STDIN (FORMAT csv, HEADER true)` into a
     temporary table that has an identity column (this gives `_source_row`);
   - then `TRUNCATE raw.<table>` and `INSERT … SELECT` add the metadata;
   - then the log row is written.
2. If anything fails, the transaction rolls back and the previous version of the table stays.
   The failure is logged in a separate transaction.
3. **Idempotency:** a table is skipped when its latest `loaded` log entry has the same file
   hash. `--force` reloads anyway. Reloads replace the table, never append to it.
4. **Schema drift:** if an existing bronze table's columns differ from the contract, the run
   stops with an error instead of loading into the wrong shape.

**Why full refresh, not incremental:** the Olist extract is a static snapshot, and
re-delivering a file replaces it entirely. Change detection is per file, by hash. Row-level
incremental processing would only pretend to handle a feed that doesn't exist here.
Incremental models are demonstrated in dbt (Phase 4).

## Verified on the full extract (2026-11-05)

- All 9 contracts pass; all 56 error-level checks pass.
- Load time is about 13 s for 1,550,926 rows. Geolocation alone (1,000,163 rows) takes 8.2 s.
- **Fidelity:** every table read back in `_source_row` order equals the CSV read as strings,
  for all rows and columns. 3,852 review comments containing embedded CRLF are preserved.
- A second run skips all 9 tables. A failed run (missing `TEMP` privilege, since fixed) logged
  9 failures and changed no data.

## Tests

- `tests/test_contracts.py` (no DB): DDL is in sync with the generator; each kind of contract
  violation is detected; the BOM is handled.
- `tests/test_bronze_load.py` (`pytest -m db`): runs in a throwaway schema and covers:
  - exact values and metadata
  - skipping unchanged files, and `--force` without duplicated rows
  - reloading only a changed file
  - a gate failure writing nothing
  - a failed COPY keeping the previous version
  - schema-drift detection and manifest mismatch
