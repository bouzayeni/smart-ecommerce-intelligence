-- Retention by acquisition cohort: customers grouped by the month of their first revenue
-- order in the window; retention_rate = share of the cohort ordering again N months later.
-- Later cohorts have fewer observable months (right-censored at the window end).
with orders as (
    select customer_unique_id, date_trunc('month', purchased_at)::date as order_month
    from {{ ref('fact_orders') }}
    where is_in_analysis_window and is_revenue_order
),

first_order as (
    select customer_unique_id, min(order_month) as cohort_month
    from orders
    group by customer_unique_id
),

activity as (
    select distinct
        f.cohort_month,
        o.customer_unique_id,
        ((extract(year from o.order_month) - extract(year from f.cohort_month)) * 12
          + extract(month from o.order_month) - extract(month from f.cohort_month))::integer
            as months_since_first_order
    from orders as o
    join first_order as f using (customer_unique_id)
),

cohort_size as (
    select cohort_month, count(*) as cohort_customers from first_order group by cohort_month
)

select
    to_char(a.cohort_month, 'YYYY-MM')                                   as cohort,
    a.months_since_first_order,
    c.cohort_customers::integer                                          as cohort_customers,
    count(*)::integer                                                    as active_customers,
    (count(*)::numeric / c.cohort_customers)::numeric(8, 6)              as retention_rate
from activity as a
join cohort_size as c using (cohort_month)
group by a.cohort_month, a.months_since_first_order, c.cohort_customers
