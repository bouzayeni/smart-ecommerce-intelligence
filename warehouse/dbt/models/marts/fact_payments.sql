-- Grain: one row per payment line (order_id, payment_sequential). Payment totals come only
-- from here or fact_orders.payment_total, never from joining items to payments (BR-03/04).
-- depends_on: {{ ref('fact_orders') }} {{ ref('dim_payment_type') }}
select
    p.order_id,
    p.payment_sequential,
    p.payment_type,
    p.payment_type_source,
    o.customer_unique_id,
    {{ date_key('o.purchase_date') }}       as purchase_date_key,
    p.payment_installments,
    p.payment_value::numeric(12, 2)         as payment_value,
    p.is_non_positive_value,
    p.is_zero_installments,
    o.order_status,
    o.is_revenue_order,
    o.is_in_analysis_window
from {{ ref('stg_order_payments') }} as p
join {{ ref('int_orders_enriched') }} as o using (order_id)
