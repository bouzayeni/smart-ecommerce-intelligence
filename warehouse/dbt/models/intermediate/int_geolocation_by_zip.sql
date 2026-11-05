-- One row per zip prefix (BR-09): median coordinates of points inside Brazil, most frequent
-- city/state (ties broken alphabetically by mode()).
select
    zip_code_prefix,
    percentile_cont(0.5) within group (order by latitude)  as latitude,
    percentile_cont(0.5) within group (order by longitude) as longitude,
    mode() within group (order by city)                    as city,
    mode() within group (order by state)                   as state,
    count(*)                                               as point_count,
    count(distinct state)                                  as distinct_states
from {{ ref('stg_geolocation') }}
where not is_outside_brazil
group by zip_code_prefix
