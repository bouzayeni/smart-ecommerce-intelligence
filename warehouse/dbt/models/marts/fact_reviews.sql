-- Grain: one row per (review_id, order_id). is_selected_for_order marks the single review
-- used as the order's score (BR-06); filter on it to average scores per order.
-- depends_on: {{ ref('fact_orders') }} {{ ref('dim_date') }}
select
    r.review_id,
    r.order_id,
    o.customer_unique_id,
    {{ date_key('r.review_created_date') }}     as review_created_date_key,
    r.review_score,
    r.review_created_date,
    r.review_answered_at,
    r.review_comment_title,
    r.review_comment_message,
    r.has_comment_message,
    (o.selected_review_id = r.review_id)        as is_selected_for_order,
    o.order_status,
    o.is_late                                   as is_order_late,
    o.is_in_analysis_window
from {{ ref('stg_order_reviews') }} as r
join {{ ref('int_orders_enriched') }} as o using (order_id)
