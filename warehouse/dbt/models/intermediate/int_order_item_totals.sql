-- One row per order that has items. Aggregating here keeps item rows from fanning out
-- when joined to orders (BR-03).
select
    order_id,
    count(*)                    as item_count,
    count(distinct product_id)  as distinct_products,
    count(distinct seller_id)   as distinct_sellers,
    sum(price)                  as price_total,
    sum(freight_value)          as freight_total,
    sum(gmv)                    as gmv
from {{ ref('stg_order_items') }}
group by order_id
