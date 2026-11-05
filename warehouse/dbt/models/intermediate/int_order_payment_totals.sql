-- One row per order that has payments (BR-04).
-- primary_payment_type = type carrying the largest share of the order's payment value.
with by_type as (
    select order_id, payment_type, sum(payment_value) as type_value
    from {{ ref('stg_order_payments') }}
    group by order_id, payment_type
),

primary_type as (
    select distinct on (order_id) order_id, payment_type as primary_payment_type
    from by_type
    order by order_id, type_value desc, payment_type
)

select
    p.order_id,
    count(*)                         as payment_count,
    sum(p.payment_value)             as payment_total,
    max(p.payment_installments)      as max_installments,
    count(distinct p.payment_type)   as distinct_payment_types,
    pt.primary_payment_type
from {{ ref('stg_order_payments') }} as p
join primary_type as pt using (order_id)
group by p.order_id, pt.primary_payment_type
