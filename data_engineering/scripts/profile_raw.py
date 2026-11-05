"""Phase 0 profiling of the raw Olist CSVs (prints a plain-text report).

Usage (from the repo root):
    uv run python -m data_engineering.scripts.profile_raw [raw_dir]
"""

import sys
from pathlib import Path

import pandas as pd

from data_engineering.config import get_settings

raw = Path(sys.argv[1]) if len(sys.argv) > 1 else get_settings().raw_dir
files = sorted(raw.glob("*.csv"))
dfs = {}
for f in files:
    df = pd.read_csv(f, dtype=str, keep_default_na=False, na_values=[""])
    dfs[f.stem] = df
    print(
        f"\n=== {f.name}  rows={len(df):,}  cols={df.shape[1]}  full_dup_rows={df.duplicated().sum():,}"
    )
    for c in df.columns:
        n = df[c].isna().sum()
        print(f"  {c:<34} nulls={n:>7,} ({n / len(df):6.2%})  distinct={df[c].nunique():>8,}")

o = dfs["olist_orders_dataset"]
it = dfs["olist_order_items_dataset"]
p = dfs["olist_order_payments_dataset"]
r = dfs["olist_order_reviews_dataset"]
c = dfs["olist_customers_dataset"]
pr = dfs["olist_products_dataset"]
s = dfs["olist_sellers_dataset"]
g = dfs["olist_geolocation_dataset"]
t = dfs["product_category_name_translation"]

print("\n=== DATE RANGES (orders)")
ts_cols = [x for x in o.columns if "timestamp" in x or "date" in x or x.endswith("_at")]
for col in ts_cols:
    d = pd.to_datetime(o[col], errors="coerce")
    print(
        f"  {col:<34} min={d.min()}  max={d.max()}  unparseable_nonnull={(d.isna() & o[col].notna()).sum()}"
    )
for col in ["review_creation_date", "review_answer_timestamp"]:
    d = pd.to_datetime(r[col], errors="coerce")
    print(f"  reviews.{col:<26} min={d.min()}  max={d.max()}")
d = pd.to_datetime(it["shipping_limit_date"], errors="coerce")
print(f"  items.shipping_limit_date          min={d.min()}  max={d.max()}")

print("\n=== ORDERS BY STATUS")
print(o["order_status"].value_counts().to_string())

pt = pd.to_datetime(o["order_purchase_timestamp"])
print("\n=== ORDERS PER MONTH")
print(pt.dt.to_period("M").value_counts().sort_index().to_string())

print("\n=== KEY UNIQUENESS")
print("  orders.order_id unique:", o["order_id"].is_unique)
print("  customers.customer_id unique:", c["customer_id"].is_unique)
print(
    "  customers: customer_id rows",
    len(c),
    " distinct customer_unique_id",
    c["customer_unique_id"].nunique(),
)
print("  products.product_id unique:", pr["product_id"].is_unique)
print("  sellers.seller_id unique:", s["seller_id"].is_unique)
print(
    "  items (order_id, order_item_id) unique:",
    not it.duplicated(["order_id", "order_item_id"]).any(),
)
print(
    "  payments (order_id, payment_sequential) unique:",
    not p.duplicated(["order_id", "payment_sequential"]).any(),
)
print(
    "  reviews.review_id unique:",
    r["review_id"].is_unique,
    " dup review_id rows:",
    r["review_id"].duplicated().sum(),
)
print("  reviews (review_id, order_id) unique:", not r.duplicated(["review_id", "order_id"]).any())
print("  orders with >1 review:", (r.groupby("order_id").size() > 1).sum())

print("\n=== FOREIGN KEYS (orphans)")


def orphan(child, ck, parent, pk, label):
    m = ~child[ck].isin(set(parent[pk]))
    print(f"  {label:<45} orphans={m.sum():,}")


orphan(o, "customer_id", c, "customer_id", "orders.customer_id -> customers")
orphan(it, "order_id", o, "order_id", "items.order_id -> orders")
orphan(it, "product_id", pr, "product_id", "items.product_id -> products")
orphan(it, "seller_id", s, "seller_id", "items.seller_id -> sellers")
orphan(p, "order_id", o, "order_id", "payments.order_id -> orders")
orphan(r, "order_id", o, "order_id", "reviews.order_id -> orders")
cats = pr["product_category_name"].dropna()
print(
    f"  products categories missing translation      distinct={len(set(cats) - set(t['product_category_name']))} -> {sorted(set(cats) - set(t['product_category_name']))}"
)
print(
    f"  customers zip prefix not in geolocation      rows={(~c['customer_zip_code_prefix'].isin(set(g['geolocation_zip_code_prefix']))).sum():,}"
)
print(
    f"  sellers zip prefix not in geolocation        rows={(~s['seller_zip_code_prefix'].isin(set(g['geolocation_zip_code_prefix']))).sum():,}"
)
print(f"  orders without items: {(~o['order_id'].isin(set(it['order_id']))).sum():,}")
print(f"  orders without payments: {(~o['order_id'].isin(set(p['order_id']))).sum():,}")
print(f"  orders without reviews: {(~o['order_id'].isin(set(r['order_id']))).sum():,}")

print("\n=== GRAIN / FAN-OUT")
ipo = it.groupby("order_id").size()
ppo = p.groupby("order_id").size()
print(
    f"  items per order: mean={ipo.mean():.3f} max={ipo.max()}  orders with >1 item={(ipo > 1).sum():,}"
)
print(
    f"  payments per order: mean={ppo.mean():.3f} max={ppo.max()}  orders with >1 payment row={(ppo > 1).sum():,}"
)
print(f"  sellers per order >1: {(it.groupby('order_id')['seller_id'].nunique() > 1).sum():,}")

print("\n=== MONEY")
it_price = it["price"].astype(float)
it_fr = it["freight_value"].astype(float)
pv = p["payment_value"].astype(float)
print(
    f"  sum(price)={it_price.sum():,.2f}  sum(freight)={it_fr.sum():,.2f}  sum(price+freight)={(it_price + it_fr).sum():,.2f}"
)
print(f"  sum(payment_value)={pv.sum():,.2f}")
print(
    f"  price min/median/max = {it_price.min()}/{it_price.median()}/{it_price.max()}  freight zero rows={(it_fr == 0).sum():,}"
)
print(f"  payment_value zero rows={(pv == 0).sum():,}")
print("  payment_type counts:")
print(p["payment_type"].value_counts().to_string())
print("  installments distribution (top):")
print(p["payment_installments"].value_counts().head(6).to_string())
items_tot = it.assign(v=it_price + it_fr).groupby("order_id")["v"].sum()
pay_tot = p.assign(v=pv).groupby("order_id")["v"].sum()
j = pd.concat([items_tot.rename("items"), pay_tot.rename("pay")], axis=1).dropna()
diff = (j["items"] - j["pay"]).abs()
print(f"  orders where |items+freight - payments| > 1.00 BRL: {(diff > 1).sum():,} of {len(j):,}")

print("\n=== DELIVERY")
od = o.copy()
for col in [
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]:
    od[col] = pd.to_datetime(od[col])
dlv = od[od["order_status"] == "delivered"]
print(
    f"  delivered orders: {len(dlv):,}  with null delivered_customer_date: {dlv['order_delivered_customer_date'].isna().sum()}"
)
print(
    f"  non-delivered status with delivered_customer_date set: {(od['order_status'].ne('delivered') & od['order_delivered_customer_date'].notna()).sum()}"
)
days = (
    dlv["order_delivered_customer_date"] - dlv["order_purchase_timestamp"]
).dt.total_seconds() / 86400
print(
    f"  delivery days: mean={days.mean():.2f} median={days.median():.2f} p95={days.quantile(0.95):.2f} max={days.max():.2f}"
)
late = dlv["order_delivered_customer_date"].dt.normalize() > dlv["order_estimated_delivery_date"]
print(f"  late (delivered date > estimated date): {late.mean():.2%}")
print(
    f"  carrier date < purchase: {(od['order_delivered_carrier_date'] < od['order_purchase_timestamp']).sum()}"
)
print(
    f"  customer delivered < carrier: {(od['order_delivered_customer_date'] < od['order_delivered_carrier_date']).sum()}"
)
print(f"  approved < purchase: {(od['order_approved_at'] < od['order_purchase_timestamp']).sum()}")

print("\n=== CUSTOMERS / REPEAT")
oc = o.merge(c, on="customer_id")
opc = oc.groupby("customer_unique_id")["order_id"].nunique()
print(f"  distinct customer_unique_id with orders: {len(opc):,}")
print(
    f"  customers with >=2 orders: {(opc >= 2).sum():,} ({(opc >= 2).mean():.2%})  max orders={opc.max()}"
)
print("  orders per customer dist:")
print(opc.value_counts().sort_index().head(8).to_string())
print("  customer states (top 10):")
print(c["customer_state"].value_counts().head(10).to_string())

print("\n=== REVIEWS")
print(r["review_score"].value_counts().sort_index().to_string())
print(
    f"  comment_title null: {r['review_comment_title'].isna().mean():.2%}  comment_message null: {r['review_comment_message'].isna().mean():.2%}"
)

print("\n=== PRODUCTS")
print(
    f"  distinct categories: {pr['product_category_name'].nunique()}  null category: {pr['product_category_name'].isna().sum()}"
)
num = pr[["product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"]].astype(
    float
)
print(
    f"  weight_g==0: {(num['product_weight_g'] == 0).sum()}  any dim null: {num.isna().any(axis=1).sum()}"
)
ppi = it.groupby("product_id").size()
print(f"  products sold: {len(ppi):,}  sold once: {(ppi == 1).sum():,} ({(ppi == 1).mean():.2%})")
cu = oc.merge(it, on="order_id").groupby("customer_unique_id")["product_id"].nunique()
print(
    f"  customers with >=2 distinct products bought: {(cu >= 2).sum():,} ({(cu >= 2).mean():.2%})"
)

print("\n=== GEOLOCATION")
print(
    f"  rows={len(g):,}  distinct zip prefixes={g['geolocation_zip_code_prefix'].nunique():,}  exact dup rows={g.duplicated().sum():,}"
)
lat = g["geolocation_lat"].astype(float)
lng = g["geolocation_lng"].astype(float)
outside = ~(lat.between(-34, 5.5) & lng.between(-74, -34))
print(f"  points outside Brazil bounding box: {outside.sum():,}")
print(f"  distinct city spellings: {g['geolocation_city'].nunique():,}")
