-- One row per review score (per-order selected review, BR-06) for orders in the window,
-- with the split by delivery outcome for delivery-eligible orders. Descriptive, not causal.
with orders as (
    select * from {{ ref('fact_orders') }}
    where is_in_analysis_window and review_score is not null
)

select
    review_score,
    count(*)::integer                                                       as orders,
    (count(*)::numeric / sum(count(*)) over ())::numeric(8, 6)              as share_of_orders,
    count(*) filter (where is_delivery_kpi_eligible and not is_late)::integer as on_time_orders,
    count(*) filter (where is_delivery_kpi_eligible and is_late)::integer   as late_orders
from orders
group by review_score
