select
    payment_type::text       as payment_type,
    payment_type_label::text as payment_type_label,
    is_card::boolean         as is_card
from {{ ref('payment_types') }}
