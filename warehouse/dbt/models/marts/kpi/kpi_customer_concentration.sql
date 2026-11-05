-- Customer revenue contribution: customers split into GMV deciles (1 = highest spenders).
with customers as (
    select customer_unique_id, sum(gmv) as gmv
    from {{ ref('fact_orders') }}
    where is_in_analysis_window and is_revenue_order
    group by customer_unique_id
),

ranked as (
    select *, ntile(10) over (order by gmv desc, customer_unique_id) as gmv_decile
    from customers
)

select
    gmv_decile,
    count(*)::integer                                                  as customers,
    sum(gmv)::numeric(14, 2)                                           as gmv,
    (sum(gmv) / sum(sum(gmv)) over ())::numeric(8, 6)                  as share_of_gmv,
    (sum(sum(gmv)) over (order by gmv_decile) / sum(sum(gmv)) over ())::numeric(8, 6)
                                                                       as cumulative_share_of_gmv,
    min(gmv)::numeric(12, 2)                                           as min_customer_gmv,
    max(gmv)::numeric(12, 2)                                           as max_customer_gmv
from ranked
group by gmv_decile
