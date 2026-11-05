-- One row per product sold in the analysis window, ranked by GMV ("top products").
-- Products are anonymised in Olist: identify them by product_id and category only.
with items as (
    select * from {{ ref('fact_order_items') }}
    where is_in_analysis_window and is_revenue_order
)

select
    i.product_id,
    p.category_name,
    sum(i.gmv)::numeric(14, 2)                         as gmv,
    count(*)::integer                                  as units_sold,
    count(distinct i.order_id)::integer                as orders,
    avg(i.price)::numeric(12, 2)                       as avg_unit_price,
    rank() over (order by sum(i.gmv) desc)::integer    as gmv_rank
from items as i
join {{ ref('dim_products') }} as p using (product_id)
group by i.product_id, p.category_name
