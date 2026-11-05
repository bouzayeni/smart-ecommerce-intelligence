select
    s.seller_id,
    s.seller_zip_code_prefix,
    s.seller_city,
    s.seller_state,
    g.latitude,
    g.longitude
from {{ ref('stg_sellers') }} as s
left join {{ ref('int_geolocation_by_zip') }} as g on g.zip_code_prefix = s.seller_zip_code_prefix
