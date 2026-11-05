{#
  dev target: use the configured schema as-is (staging, intermediate, marts), matching the
  schemas and grants created by infrastructure/postgres/init_roles_schemas.sql.
  Any other target: prefix with target.schema (e.g. test_ab12cd34_marts) to isolate runs.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if target.name == 'dev' -%}
        {{ custom_schema_name | trim if custom_schema_name else target.schema }}
    {%- else -%}
        {{ target.schema }}_{{ custom_schema_name | trim if custom_schema_name else 'default' }}
    {%- endif -%}
{%- endmacro %}
