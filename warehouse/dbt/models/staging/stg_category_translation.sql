-- Source translations plus project-provided labels for untranslated categories (BR-08).
select product_category_name, product_category_name_english, false as is_project_provided
from {{ source('raw', 'category_translation') }}
union all
select product_category_name, product_category_name_english, true as is_project_provided
from {{ ref('category_translation_extra') }}
where product_category_name not in (
    select product_category_name from {{ source('raw', 'category_translation') }}
)
