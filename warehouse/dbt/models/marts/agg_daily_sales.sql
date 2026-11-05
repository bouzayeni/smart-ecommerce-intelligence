{#
  Grain: one row per calendar day of the analysis window, including days without orders
  (needed by forecasting). Incremental: each run re-processes the last
  incremental_lookback_days days before the current max date and anything newer, then
  replaces those days (delete+insert). The Olist extract is static, so this demonstrates the
  pattern; a --full-refresh rebuilds every day.
#}
{{ config(
    materialized='incremental',
    unique_key='date_day',
    incremental_strategy='delete+insert',
    on_schema_change='fail'
) }}

with days as (
    select date_key, date_day
    from {{ ref('dim_date') }}
    where is_in_analysis_window
    {% if is_incremental() %}
      and date_day >= (select max(date_day) from {{ this }})
                      - {{ var('incremental_lookback_days') }}
    {% endif %}
),

orders as (
    select * from {{ ref('fact_orders') }}
    where is_in_analysis_window
)

select
    d.date_key,
    d.date_day,
    count(o.order_id) filter (where o.is_revenue_order)::integer          as revenue_orders,
    count(o.order_id)::integer                                             as all_orders,
    count(o.order_id) filter (where o.order_status = 'canceled')::integer  as canceled_orders,
    coalesce(sum(o.gmv) filter (where o.is_revenue_order), 0)::numeric(14, 2)          as gmv,
    coalesce(sum(o.freight_total) filter (where o.is_revenue_order), 0)::numeric(14, 2) as freight,
    coalesce(sum(o.item_count) filter (where o.is_revenue_order), 0)::integer          as items,
    count(distinct o.customer_unique_id) filter (where o.is_revenue_order)::integer    as customers,
    now()                                                                  as _built_at
from days as d
left join orders as o on o.purchase_date_key = d.date_key
group by d.date_key, d.date_day
