-- One row per order with customer identity, per-order totals and every business-rule flag.
-- Every order is kept (BR-10); KPIs filter on the flags.
with orders as (
    select * from {{ ref('stg_orders') }}
),

customers as (
    select * from {{ ref('stg_customers') }}
)

select
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    -- Location at order time (BR-01): regional KPIs use this, not the latest address.
    c.customer_zip_code_prefix,
    c.customer_city,
    c.customer_state,
    o.order_status,
    o.purchased_at,
    o.purchase_date,
    o.approved_at,
    o.delivered_to_carrier_at,
    o.delivered_to_customer_at,
    o.estimated_delivery_date,

    coalesce(i.item_count, 0)        as item_count,
    coalesce(i.distinct_sellers, 0)  as distinct_sellers,
    coalesce(i.price_total, 0)       as price_total,
    coalesce(i.freight_total, 0)     as freight_total,
    coalesce(i.gmv, 0)               as gmv,
    coalesce(p.payment_count, 0)     as payment_count,
    coalesce(p.payment_total, 0)     as payment_total,
    p.max_installments,
    p.primary_payment_type,
    r.selected_review_id,
    r.review_score,
    r.review_answered_at,
    coalesce(r.review_count, 0)      as review_count,

    -- Delivery (BR-07)
    case when o.delivered_to_customer_at is not null
        then extract(epoch from o.delivered_to_customer_at - o.purchased_at) / 86400.0
    end                              as delivery_days,
    case when o.delivered_to_customer_at is not null
        then o.delivered_to_customer_at::date > o.estimated_delivery_date
    end                              as is_late,
    (o.estimated_delivery_date - o.purchase_date) as estimated_lead_days,

    -- Flags
    o.order_status in {{ sql_list(var('revenue_statuses')) }}  as is_revenue_order,
    o.purchase_date between '{{ var("analysis_start") }}'::date
                        and '{{ var("analysis_end") }}'::date  as is_in_analysis_window,
    (
        o.order_status = 'delivered'
        and o.delivered_to_customer_at is not null
        and not o.is_carrier_before_purchase
        and not o.is_delivery_before_carrier
        and o.purchase_date <= '{{ var("analysis_end") }}'::date
            - {{ var('delivery_cohort_maturity_days') }}
    )                                as is_delivery_kpi_eligible,
    (i.order_id is not null)         as has_items,
    (p.order_id is not null)         as has_payment,
    case when i.order_id is not null and p.order_id is not null
        then abs(p.payment_total - i.gmv) <= {{ var('payment_reconciliation_tolerance_brl') }}
    end                              as is_payment_reconciled,
    o.is_delivered_without_date,
    o.is_undelivered_with_date,
    o.is_carrier_before_purchase,
    o.is_delivery_before_carrier
from orders as o
join customers as c using (customer_id)
left join {{ ref('int_order_item_totals') }}    as i using (order_id)
left join {{ ref('int_order_payment_totals') }} as p using (order_id)
left join {{ ref('int_order_reviews') }}        as r using (order_id)
