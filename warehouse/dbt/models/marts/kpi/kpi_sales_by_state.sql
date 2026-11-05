-- One row per customer state (location at order time, BR-01): sales and delivery KPIs.
with orders as (
    select * from {{ ref('fact_orders') }} where is_in_analysis_window
),

sales as (
    select
        customer_state_at_order                as state,
        sum(gmv)                               as gmv,
        count(*)                               as revenue_orders,
        count(distinct customer_unique_id)     as customers
    from orders
    where is_revenue_order
    group by 1
),

delivery as (
    select
        customer_state_at_order                as state,
        count(*)                               as delivery_eligible_orders,
        avg(delivery_days)                     as avg_delivery_days,
        avg(is_late::integer)                  as late_delivery_rate
    from orders
    where is_delivery_kpi_eligible
    group by 1
)

select
    s.state,
    s.gmv::numeric(14, 2)                                      as gmv,
    s.revenue_orders::integer                                  as revenue_orders,
    s.customers::integer                                       as customers,
    (s.gmv / s.revenue_orders)::numeric(12, 2)                 as avg_order_value,
    (s.gmv / sum(s.gmv) over ())::numeric(8, 6)                as share_of_gmv,
    coalesce(d.delivery_eligible_orders, 0)::integer           as delivery_eligible_orders,
    d.avg_delivery_days::numeric(8, 4)                         as avg_delivery_days,
    d.late_delivery_rate::numeric(8, 6)                        as late_delivery_rate,
    rank() over (order by s.gmv desc)::integer                 as gmv_rank
from sales as s
left join delivery as d using (state)
