-- One row per (review_id, order_id): a review_id can cover several orders placed together
-- (BR-06). Empty strings are normalised to NULL for the comment fields.
select
    review_id,
    order_id,
    review_score::integer                         as review_score,
    nullif(review_comment_title, '')              as review_comment_title,
    nullif(review_comment_message, '')            as review_comment_message,
    review_creation_date::date                    as review_created_date,
    review_answer_timestamp::timestamp            as review_answered_at,
    (nullif(review_comment_message, '') is not null) as has_comment_message
from {{ source('raw', 'order_reviews') }}
