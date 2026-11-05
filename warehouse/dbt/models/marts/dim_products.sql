-- One row per product. category_name is English, 'unknown' when missing (BR-08).
select
    p.product_id,
    p.product_category_name                              as category_name_pt,
    coalesce(t.product_category_name_english, '{{ var("unknown_category") }}') as category_name,
    coalesce(t.is_project_provided, false)               as is_category_label_project_provided,
    p.is_category_missing,
    p.product_name_length,
    p.product_description_length,
    p.product_photos_qty,
    p.product_weight_g,
    p.product_length_cm,
    p.product_height_cm,
    p.product_width_cm,
    (p.product_length_cm * p.product_height_cm * p.product_width_cm)::bigint as product_volume_cm3
from {{ ref('stg_products') }} as p
left join {{ ref('stg_category_translation') }} as t using (product_category_name)
