-- One row per source point (many per zip prefix, exact duplicates included). BR-09.
{%- set bb = var('brazil_bbox') %}
select
    geolocation_zip_code_prefix              as zip_code_prefix,
    geolocation_lat::double precision        as latitude,
    geolocation_lng::double precision        as longitude,
    geolocation_city                         as city,
    upper(geolocation_state)                 as state,
    not (
        geolocation_lat::double precision between {{ bb.lat_min }} and {{ bb.lat_max }}
        and geolocation_lng::double precision between {{ bb.lng_min }} and {{ bb.lng_max }}
    )                                        as is_outside_brazil
from {{ source('raw', 'geolocation') }}
