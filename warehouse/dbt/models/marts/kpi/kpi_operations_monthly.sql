-- One row per purchase month: delivery performance (eligible orders, BR-07) and
-- cancellations (all orders). Months younger than the maturity window have no
-- delivery-eligible orders.
with orders as (
    select to_char(purchased_at, 'YYYY-MM') as year_month, *
    from {{ ref('fact_orders') }}
    where is_in_analysis_window
)

select
    year_month,
    count(*)::integer                                                       as all_orders,
    count(*) filter (where order_status = 'canceled')::integer              as canceled_orders,
    count(*) filter (where order_status = 'unavailable')::integer           as unavailable_orders,
    (count(*) filter (where order_status in ('canceled', 'unavailable'))::numeric
        / count(*))::numeric(8, 6)                                          as cancellation_rate,
    count(*) filter (where is_delivery_kpi_eligible)::integer               as delivery_eligible_orders,
    (avg(delivery_days) filter (where is_delivery_kpi_eligible))::numeric(8, 4) as avg_delivery_days,
    (percentile_cont(0.5) within group (order by delivery_days)
        filter (where is_delivery_kpi_eligible))::numeric(8, 4)             as median_delivery_days,
    (avg(is_late::integer) filter (where is_delivery_kpi_eligible))::numeric(8, 6) as late_delivery_rate,
    (avg(estimated_lead_days) filter (where is_delivery_kpi_eligible))::numeric(8, 4) as avg_estimated_lead_days,
    (sum(freight_total) filter (where is_revenue_order)
        / nullif(count(*) filter (where is_revenue_order), 0))::numeric(12, 2) as avg_freight_per_order
from orders
group by year_month
