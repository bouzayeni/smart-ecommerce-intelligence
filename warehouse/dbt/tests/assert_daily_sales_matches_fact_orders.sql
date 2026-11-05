-- agg_daily_sales covers every day of the window exactly once and its GMV and order counts
-- equal fact_orders filtered by the same rules.
with agg as (
    select count(*) as days, min(date_day) as first_day, max(date_day) as last_day,
           sum(gmv) as gmv, sum(revenue_orders) as revenue_orders
    from {{ ref('agg_daily_sales') }}
),

expected as (
    select sum(gmv) filter (where is_revenue_order) as gmv,
           count(*) filter (where is_revenue_order) as revenue_orders
    from {{ ref('fact_orders') }}
    where is_in_analysis_window
)

select *
from agg cross join expected as e
where agg.days <> ('{{ var("analysis_end") }}'::date - '{{ var("analysis_start") }}'::date + 1)
   or agg.first_day <> '{{ var("analysis_start") }}'::date
   or agg.last_day <> '{{ var("analysis_end") }}'::date
   or abs(agg.gmv - coalesce(e.gmv, 0)) > 0.005
   or agg.revenue_orders <> e.revenue_orders
