-- One row per calendar day, dim_date_start..dim_date_end (covers every fact date key).
with days as (
    select d::date as date_day
    from generate_series(
        '{{ var("dim_date_start") }}'::date, '{{ var("dim_date_end") }}'::date, interval '1 day'
    ) as d
),

flags as (
    select
        date_day,
        -- Black Friday = day after the 4th Thursday of November.
        (make_date(extract(year from date_day)::integer, 11, 1)
            + ((4 - extract(isodow from make_date(extract(year from date_day)::integer, 11, 1))::integer + 7) % 7)
            + 21 + 1) as black_friday
    from days
)

select
    {{ date_key('d.date_day') }}                           as date_key,
    d.date_day,
    extract(year from d.date_day)::integer                 as year,
    extract(quarter from d.date_day)::integer              as quarter,
    extract(month from d.date_day)::integer                as month,
    to_char(d.date_day, 'YYYY-MM')                         as year_month,
    trim(to_char(d.date_day, 'Month'))                     as month_name,
    extract(week from d.date_day)::integer                 as iso_week,
    extract(isodow from d.date_day)::integer               as iso_day_of_week,
    trim(to_char(d.date_day, 'Day'))                       as day_name,
    extract(isodow from d.date_day) in (6, 7)              as is_weekend,
    h.holiday_date is not null                             as is_holiday,
    h.holiday_name::text                                   as holiday_name,
    h.holiday_type::text                                   as holiday_type,
    d.date_day = f.black_friday                            as is_black_friday,
    d.date_day between '{{ var("analysis_start") }}'::date
                   and '{{ var("analysis_end") }}'::date   as is_in_analysis_window,
    -- Whole calendar month inside the analysis window (Aug 2018 is partial: BR-02).
    (date_trunc('month', d.date_day)::date >= '{{ var("analysis_start") }}'::date
        and (date_trunc('month', d.date_day) + interval '1 month - 1 day')::date
            <= '{{ var("analysis_end") }}'::date)          as is_complete_month_in_window
from days as d
join flags as f using (date_day)
left join {{ ref('br_holidays') }} as h on h.holiday_date = d.date_day
