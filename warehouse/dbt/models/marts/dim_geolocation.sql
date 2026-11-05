select
    zip_code_prefix,
    latitude,
    longitude,
    city,
    state,
    point_count::integer     as point_count,
    distinct_states::integer as distinct_states
from {{ ref('int_geolocation_by_zip') }}
