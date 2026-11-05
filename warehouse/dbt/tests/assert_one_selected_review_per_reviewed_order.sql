-- Every reviewed order has exactly one review flagged is_selected_for_order (BR-06).
select order_id, count(*) filter (where is_selected_for_order) as selected
from {{ ref('fact_reviews') }}
group by order_id
having count(*) filter (where is_selected_for_order) <> 1
