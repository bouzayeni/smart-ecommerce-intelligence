-- One row per English product category: item-level GMV in the analysis window.
with items as (
    select i.*, p.category_name
    from {{ ref('fact_order_items') }} as i
    join {{ ref('dim_products') }} as p using (product_id)
    where i.is_in_analysis_window and i.is_revenue_order
)

select
    category_name,
    sum(gmv)::numeric(14, 2)                                   as gmv,
    sum(price)::numeric(14, 2)                                 as merchandise_value,
    sum(freight_value)::numeric(14, 2)                         as freight_value,
    count(*)::integer                                          as units_sold,
    count(distinct order_id)::integer                          as orders,
    count(distinct product_id)::integer                        as products_sold,
    avg(price)::numeric(12, 2)                                 as avg_unit_price,
    (sum(gmv) / sum(sum(gmv)) over ())::numeric(8, 6)          as share_of_gmv,
    rank() over (order by sum(gmv) desc)::integer              as gmv_rank
from items
group by category_name
