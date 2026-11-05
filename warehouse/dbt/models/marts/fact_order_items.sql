-- Grain: one row per unit sold (order_id, order_item_id). Revenue by product, category and
-- seller comes from here. Order-level flags are denormalised so KPIs filter without a join.
-- depends_on: {{ ref('fact_orders') }} {{ ref('dim_products') }} {{ ref('dim_sellers') }}
select
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    o.customer_unique_id,
    {{ date_key('o.purchase_date') }}             as purchase_date_key,
    i.shipping_limit_at,
    i.price::numeric(12, 2)                       as price,
    i.freight_value::numeric(12, 2)               as freight_value,
    i.gmv::numeric(12, 2)                         as gmv,
    o.order_status,
    o.is_revenue_order,
    o.is_in_analysis_window,
    coalesce(
        i.shipping_limit_at > o.purchased_at
            + interval '{{ var("shipping_limit_max_days_after_purchase") }} days',
        false
    )                                             as is_shipping_limit_outlier
from {{ ref('stg_order_items') }} as i
join {{ ref('int_orders_enriched') }} as o using (order_id)
