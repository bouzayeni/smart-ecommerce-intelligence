-- One row per customer_id (one per order). customer_unique_id identifies the person (BR-01).
select
    customer_id,
    customer_unique_id,
    customer_zip_code_prefix,
    customer_city,
    upper(customer_state) as customer_state
from {{ source('raw', 'customers') }}
