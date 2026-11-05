-- One row per unit sold: (order_id, order_item_id). Quantity = number of rows (BR-05).
select
    order_id,
    order_item_id::integer             as order_item_id,
    product_id,
    seller_id,
    shipping_limit_date::timestamp     as shipping_limit_at,
    price::numeric(12, 2)              as price,
    freight_value::numeric(12, 2)      as freight_value,
    (price::numeric(12, 2) + freight_value::numeric(12, 2)) as gmv
from {{ source('raw', 'order_items') }}
