-- One row per (order_id, payment_sequential). payment_type mapped per BR-04.
{%- set type_map = var('payment_type_map') %}
select
    order_id,
    payment_sequential::integer      as payment_sequential,
    case payment_type
        {%- for source_value, mapped in type_map.items() %}
        when '{{ source_value }}' then '{{ mapped }}'
        {%- endfor %}
        else payment_type
    end                              as payment_type,
    payment_type                     as payment_type_source,
    payment_installments::integer    as payment_installments,
    payment_value::numeric(12, 2)    as payment_value,
    (payment_value::numeric(12, 2) <= 0)   as is_non_positive_value,
    (payment_installments::integer < 1)    as is_zero_installments
from {{ source('raw', 'order_payments') }}
