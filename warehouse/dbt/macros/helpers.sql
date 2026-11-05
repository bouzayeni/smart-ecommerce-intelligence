{# Render a list var as a SQL literal list: ('a', 'b'). #}
{% macro sql_list(values) -%}
    ({%- for v in values -%}'{{ v }}'{{ ", " if not loop.last }}{%- endfor -%})
{%- endmacro %}


{# Integer date key YYYYMMDD from a date or timestamp expression. #}
{% macro date_key(expr) -%}
    (to_char({{ expr }}, 'YYYYMMDD')::integer)
{%- endmacro %}
