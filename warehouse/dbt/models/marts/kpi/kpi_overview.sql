-- One row: headline KPIs for the analysis window. Definitions: docs/kpi_dictionary.md.
with orders as (
    select * from {{ ref('fact_orders') }} where is_in_analysis_window
),

revenue as (
    select * from orders where is_revenue_order
),

customers as (
    select customer_unique_id, count(*) as orders
    from revenue
    group by customer_unique_id
),

delivery as (
    select * from orders where is_delivery_kpi_eligible
)

select
    '{{ var("analysis_start") }}'::date                               as window_start,
    '{{ var("analysis_end") }}'::date                                 as window_end,
    (select sum(gmv) from revenue)::numeric(14, 2)                    as gmv,
    (select sum(price_total) from revenue)::numeric(14, 2)            as merchandise_value,
    (select sum(freight_total) from revenue)::numeric(14, 2)          as freight_value,
    (select count(*) from revenue)::integer                           as revenue_orders,
    ((select sum(gmv) from revenue) / nullif((select count(*) from revenue), 0))::numeric(12, 2)
                                                                      as avg_order_value,
    ((select sum(freight_total) from revenue) / nullif((select count(*) from revenue), 0))::numeric(12, 2)
                                                                      as avg_freight_per_order,
    ((select sum(freight_total) from revenue) / nullif((select sum(gmv) from revenue), 0))::numeric(8, 6)
                                                                      as freight_share_of_gmv,
    (select count(*) from customers)::integer                         as customers,
    (select count(*) from customers where orders >= 2)::integer       as repeat_customers,
    ((select count(*) from customers where orders >= 2)::numeric
        / nullif((select count(*) from customers), 0))::numeric(8, 6) as repeat_purchase_rate,
    ((select count(*) from revenue)::numeric
        / nullif((select count(*) from customers), 0))::numeric(8, 4) as avg_orders_per_customer,
    (select count(*) from orders)::integer                            as all_orders,
    ((select count(*) from orders where order_status in ('canceled', 'unavailable'))::numeric
        / nullif((select count(*) from orders), 0))::numeric(8, 6)    as cancellation_rate,
    (select count(*) from delivery)::integer                          as delivery_eligible_orders,
    (select avg(delivery_days) from delivery)::numeric(8, 4)          as avg_delivery_days,
    (select percentile_cont(0.5) within group (order by delivery_days) from delivery)::numeric(8, 4)
                                                                      as median_delivery_days,
    (select avg(is_late::integer) from delivery)::numeric(8, 6)       as late_delivery_rate,
    (1 - (select avg(is_late::integer) from delivery))::numeric(8, 6) as on_time_delivery_rate,
    (select avg(review_score) from orders where review_score is not null)::numeric(6, 4)
                                                                      as avg_review_score
