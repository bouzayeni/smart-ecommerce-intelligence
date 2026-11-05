-- One row per purchase month in the analysis window. Month-over-month growth is only
-- computed between two complete months (Aug 2018 is partial: BR-02).
with months as (
    select year_month, min(date_day) as month_start, bool_and(is_complete_month_in_window) as is_complete_month
    from {{ ref('dim_date') }}
    where is_in_analysis_window
    group by year_month
),

orders as (
    select to_char(purchased_at, 'YYYY-MM') as year_month, *
    from {{ ref('fact_orders') }}
    where is_in_analysis_window and is_revenue_order
),

monthly as (
    select
        m.year_month,
        m.month_start,
        m.is_complete_month,
        coalesce(sum(o.gmv), 0)::numeric(14, 2)                   as gmv,
        coalesce(sum(o.freight_total), 0)::numeric(14, 2)         as freight_value,
        count(o.order_id)::integer                                as revenue_orders,
        count(distinct o.customer_unique_id)::integer             as customers
    from months as m
    left join orders as o using (year_month)
    group by m.year_month, m.month_start, m.is_complete_month
)

select
    *,
    (gmv / nullif(revenue_orders, 0))::numeric(12, 2) as avg_order_value,
    case when is_complete_month and lag(is_complete_month) over w
        then ((gmv - lag(gmv) over w) / nullif(lag(gmv) over w, 0))::numeric(10, 6)
    end                                               as gmv_mom_growth
from monthly
window w as (order by month_start)
