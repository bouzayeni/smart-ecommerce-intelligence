-- One row per payment type for revenue orders in the window.
with payments as (
    select * from {{ ref('fact_payments') }}
    where is_in_analysis_window and is_revenue_order
)

select
    p.payment_type,
    t.payment_type_label,
    count(*)::integer                                              as payment_lines,
    count(distinct p.order_id)::integer                            as orders,
    sum(p.payment_value)::numeric(14, 2)                           as payment_value,
    (sum(p.payment_value) / sum(sum(p.payment_value)) over ())::numeric(8, 6) as share_of_payment_value,
    avg(p.payment_installments)::numeric(6, 3)                     as avg_installments
from payments as p
join {{ ref('dim_payment_type') }} as t using (payment_type)
group by p.payment_type, t.payment_type_label
