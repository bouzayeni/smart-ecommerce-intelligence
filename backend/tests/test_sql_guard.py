"""SQL guard for the assistant's query_warehouse tool (no database needed)."""

import pytest

from app.assistant.sql_guard import MAX_ROWS, UnsafeQueryError, check_query

SAFE = [
    "select count(*) from marts.fact_orders where is_revenue_order",
    "with m as (select date_trunc('month', purchased_at) m, sum(gmv) g from marts.fact_orders "
    "group by 1) select * from m order by m",
    "select p.category_name, sum(i.price) from marts.fact_order_items i "
    "join marts.dim_products p using (product_id) group by 1 order by 2 desc limit 5",
    "select segment, count(*) from ml.customer_rfm group by 1",
]

UNSAFE = [
    ("delete from marts.fact_orders", "only"),
    ("update marts.fact_orders set gmv = 0", "only"),
    ("insert into marts.fact_orders select * from marts.fact_orders", "only"),
    ("drop table marts.fact_orders", "only"),
    ("create table marts.x as select 1", "only"),
    ("select 1; drop table marts.fact_orders", "one"),
    ("select * from app.users", "not allowed"),
    ("select * from users", "not allowed"),
    ("select * from pg_catalog.pg_roles", "not allowed"),
    ("select * from information_schema.tables", "not allowed"),
    ("select * from raw.orders", "not allowed"),
    ("select pg_sleep(10)", "not allowed"),
    ("select pg_read_file('/etc/passwd')", "not allowed"),
    ("select current_setting('server_version')", "not allowed"),
    ("select set_config('search_path', 'app', false)", "not allowed"),
    ("select * from dblink('host=x', 'select 1') as t(a int)", "not allowed"),
    ("select * from generate_series(1, 1000000000)", "not allowed"),
    ("select * into marts.copy from marts.fact_orders", "not allowed"),
    ("select * from marts.fact_orders for update", "not allowed"),
    ("select review_comment_message from marts.fact_reviews", "not available"),
    ("select * from marts.fact_reviews", "free-text columns"),
    ("copy marts.fact_orders to '/tmp/x'", ""),
    ("set role etl_user", ""),
    ("", ""),
]


@pytest.mark.parametrize("sql", SAFE)
def test_safe_queries_are_wrapped_with_row_limit(sql):
    checked = check_query(sql)
    assert checked.sql.endswith(f"limit {MAX_ROWS}")
    assert all(t.split(".")[0] in {"marts", "ml"} for t in checked.tables)


@pytest.mark.parametrize(("sql", "fragment"), UNSAFE)
def test_unsafe_queries_are_rejected(sql, fragment):
    with pytest.raises(UnsafeQueryError) as exc:
        check_query(sql)
    assert fragment.lower() in str(exc.value).lower()
