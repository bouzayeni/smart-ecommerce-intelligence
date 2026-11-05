-- One row per person (customer_unique_id). Current location = location on the most recent
-- order (BR-01). Order statistics cover all statuses and all dates in the extract.
with orders as (
    select * from {{ ref('int_orders_enriched') }}
),

latest as (
    select distinct on (customer_unique_id)
        customer_unique_id,
        customer_zip_code_prefix,
        customer_city,
        customer_state
    from orders
    order by customer_unique_id, purchased_at desc, order_id desc
)

select
    l.customer_unique_id,
    l.customer_zip_code_prefix,
    l.customer_city,
    l.customer_state,
    min(o.purchased_at)                       as first_order_at,
    max(o.purchased_at)                       as last_order_at,
    count(*)                                  as order_count,
    count(*) filter (where o.is_revenue_order) as revenue_order_count,
    count(distinct o.customer_zip_code_prefix) as distinct_zip_prefixes
from latest as l
join orders as o using (customer_unique_id)
group by l.customer_unique_id, l.customer_zip_code_prefix, l.customer_city, l.customer_state
