{#
  The contracted facts must carry their FOREIGN KEY constraints in the database.
  Rebuilding a dimension alone drops dependent FKs (dbt replaces the table with
  DROP ... CASCADE), so a partial run can silently remove them; this test catches that.
#}
-- depends_on: {{ ref('fact_order_items') }} {{ ref('fact_payments') }} {{ ref('fact_reviews') }}
{%- set expected = {
    'fact_orders': 3, 'fact_order_items': 5, 'fact_payments': 4, 'fact_reviews': 3
} %}
with expected (table_name, fk_count) as (
    values
    {%- for table, n in expected.items() %}
        ('{{ table }}', {{ n }}){{ "," if not loop.last }}
    {%- endfor %}
),

actual as (
    select c.relname as table_name, count(*) as fk_count
    from pg_constraint as k
    join pg_class as c on c.oid = k.conrelid
    join pg_namespace as n on n.oid = c.relnamespace
    where k.contype = 'f' and n.nspname = '{{ ref("fact_orders").schema }}'
    group by c.relname
)

select e.table_name, e.fk_count as expected, coalesce(a.fk_count, 0) as actual
from expected as e
left join actual as a using (table_name)
where coalesce(a.fk_count, 0) <> e.fk_count
