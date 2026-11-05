-- One row per order. Timestamps are Olist local times (no time zone in source).
-- Row-level quality issues are flagged, never removed (BR-10).
with typed as (
    select
        order_id,
        customer_id,
        order_status,
        order_purchase_timestamp::timestamp      as purchased_at,
        order_approved_at::timestamp             as approved_at,
        order_delivered_carrier_date::timestamp  as delivered_to_carrier_at,
        order_delivered_customer_date::timestamp as delivered_to_customer_at,
        -- Source value is always midnight: it is a date (BR-07).
        order_estimated_delivery_date::date      as estimated_delivery_date
    from {{ source('raw', 'orders') }}
)

select
    *,
    purchased_at::date as purchase_date,
    (order_status = 'delivered' and delivered_to_customer_at is null)
        as is_delivered_without_date,
    (order_status <> 'delivered' and delivered_to_customer_at is not null)
        as is_undelivered_with_date,
    coalesce(delivered_to_carrier_at < purchased_at, false)
        as is_carrier_before_purchase,
    coalesce(delivered_to_customer_at < delivered_to_carrier_at, false)
        as is_delivery_before_carrier
from typed
