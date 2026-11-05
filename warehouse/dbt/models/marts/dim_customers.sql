-- One row per person (customer_unique_id). Location = most recent order (BR-01).
-- Order statistics describe the whole extract; they are profile attributes, not KPIs.
select
    p.customer_unique_id,
    p.customer_zip_code_prefix,
    p.customer_city,
    p.customer_state,
    g.latitude,
    g.longitude,
    p.first_order_at,
    p.last_order_at,
    p.order_count::integer          as order_count,
    p.revenue_order_count::integer  as revenue_order_count,
    p.distinct_zip_prefixes::integer as distinct_zip_prefixes,
    p.order_count >= 2              as is_repeat_customer
from {{ ref('int_customers_profile') }} as p
left join {{ ref('int_geolocation_by_zip') }} as g
    on g.zip_code_prefix = p.customer_zip_code_prefix
