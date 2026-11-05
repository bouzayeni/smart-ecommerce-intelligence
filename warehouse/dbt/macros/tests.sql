{#
  row_count_matches: the model has exactly as many rows as another relation.
  Used to prove that staging and facts keep every source row (rule BR-10: flag, don't drop).
#}
{% test row_count_matches(model, compare_to) %}
with a as (select count(*) as n from {{ model }}),
     b as (select count(*) as n from {{ compare_to }})
select a.n as model_rows, b.n as compare_rows
from a cross join b
where a.n <> b.n
{% endtest %}


{#
  sums_match: sum(column) over the model equals sum(compare_column) over another relation,
  within a tolerance. Used to prove that joins in the star schema never double count.
#}
{% test sums_match(model, column_name, compare_to, compare_column, tolerance=0.005) %}
with a as (select coalesce(sum({{ column_name }}), 0) as total from {{ model }}),
     b as (select coalesce(sum({{ compare_column }}), 0) as total from {{ compare_to }})
select a.total as model_total, b.total as compare_total
from a cross join b
where abs(a.total - b.total) > {{ tolerance }}
{% endtest %}
