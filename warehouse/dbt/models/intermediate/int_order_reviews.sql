-- One row per reviewed order: the most recently answered review (BR-06,
-- reviews.per_order_score = latest_answer). Ties broken by review_id, matching the Python
-- reference implementation in data_engineering/quality/analysis.py.
with ranked as (
    select
        *,
        row_number() over (
            partition by order_id order by review_answered_at desc, review_id desc
        ) as rn,
        count(*) over (partition by order_id) as review_count
    from {{ ref('stg_order_reviews') }}
)

select
    order_id,
    review_id            as selected_review_id,
    review_score,
    review_created_date,
    review_answered_at,
    has_comment_message,
    review_count
from ranked
where rn = 1
