-- Every KPI view that splits GMV, orders or customers must add back up to kpi_overview.
with o as (select * from {{ ref('kpi_overview') }}),
checks as (
    select 'monthly gmv' as check_name, (select sum(gmv) from {{ ref('kpi_monthly_sales') }}) as actual, o.gmv as expected from o
    union all select 'monthly orders', (select sum(revenue_orders) from {{ ref('kpi_monthly_sales') }}), o.revenue_orders from o
    union all select 'daily gmv', (select sum(gmv) from {{ ref('agg_daily_sales') }}), o.gmv from o
    union all select 'category gmv', (select sum(gmv) from {{ ref('kpi_sales_by_category') }}), o.gmv from o
    union all select 'state gmv', (select sum(gmv) from {{ ref('kpi_sales_by_state') }}), o.gmv from o
    union all select 'state orders', (select sum(revenue_orders) from {{ ref('kpi_sales_by_state') }}), o.revenue_orders from o
    union all select 'product gmv', (select sum(gmv) from {{ ref('kpi_product_ranking') }}), o.gmv from o
    union all select 'decile gmv', (select sum(gmv) from {{ ref('kpi_customer_concentration') }}), o.gmv from o
    union all select 'decile customers', (select sum(customers) from {{ ref('kpi_customer_concentration') }}), o.customers from o
    union all select 'cohort customers', (select sum(active_customers) from {{ ref('kpi_customer_cohorts') }} where months_since_first_order = 0), o.customers from o
    union all select 'operations orders', (select sum(all_orders) from {{ ref('kpi_operations_monthly') }}), o.all_orders from o
    union all select 'operations eligible', (select sum(delivery_eligible_orders) from {{ ref('kpi_operations_monthly') }}), o.delivery_eligible_orders from o
    union all select 'state eligible', (select sum(delivery_eligible_orders) from {{ ref('kpi_sales_by_state') }}), o.delivery_eligible_orders from o
    union all select 'shares sum to 1', (select sum(share_of_gmv) from {{ ref('kpi_sales_by_category') }}), 1 from o
)
select * from checks where abs(coalesce(actual, 0) - expected) > 0.01
