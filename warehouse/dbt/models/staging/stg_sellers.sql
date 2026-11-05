select
    seller_id,
    seller_zip_code_prefix,
    seller_city,
    upper(seller_state) as seller_state
from {{ source('raw', 'sellers') }}
