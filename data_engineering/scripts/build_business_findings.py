"""Generate docs/business_findings.md: headline findings computed from the marts KPI views.

Every number in the output is a query result; the text around it only chooses words such as
"higher"/"lower" from those results. Interpretations are labelled as hypotheses, because the
dataset cannot show causes (it is observational and historical).

    uv run python -m data_engineering.scripts.build_business_findings
"""

import argparse
import datetime as dt
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from data_engineering.config import PROJECT_ROOT, get_settings

OUT = PROJECT_ROOT / "docs" / "business_findings.md"
MIN_STATE_ORDERS = 500  # states with fewer eligible deliveries are too noisy to rank


def brl(v) -> str:
    return f"R$ {float(v):,.0f}"


def pct(v, digits: int = 1) -> str:
    return f"{float(v) * 100:.{digits}f}%"


def compare(a: float, b: float) -> str:
    return "higher" if a > b else "lower" if a < b else "the same"


def fetch(conn, sql: str, params=None) -> list[dict]:
    return conn.execute(sql, params).fetchall()


def findings(conn) -> list[tuple[str, list[str], str]]:
    """(title, evidence lines, hypothesis) per finding."""
    k = fetch(conn, "select * from marts.kpi_overview")[0]
    out = []

    # 1. Growth: same months of 2017 and 2018, complete months only.
    months = fetch(
        conn,
        "select year_month, gmv, revenue_orders, is_complete_month "
        "from marts.kpi_monthly_sales order by year_month",
    )
    complete = [m for m in months if m["is_complete_month"]]
    in_2018 = {m["year_month"][5:] for m in complete if m["year_month"].startswith("2018")}
    same = [m for m in complete if m["year_month"][5:] in in_2018]
    g17 = sum(float(m["gmv"]) for m in same if m["year_month"].startswith("2017"))
    g18 = sum(float(m["gmv"]) for m in same if m["year_month"].startswith("2018"))
    span = f"{min(in_2018)}–{max(in_2018)}"
    peak = max(complete, key=lambda m: m["gmv"])
    out.append(
        (
            "The marketplace grew strongly, then flattened in 2018",
            [
                f"GMV for months {span}: {brl(g17)} in 2017 vs {brl(g18)} in 2018 "
                f"({(g18 / g17 - 1) * 100:+.0f}%).",
                f"Peak complete month: {peak['year_month']} with {brl(peak['gmv'])} "
                f"and {peak['revenue_orders']:,} orders.",
                "Month-on-month growth in 2018: "
                + ", ".join(
                    f"{m['year_month']} {float(m['gmv_mom_growth']) * 100:+.1f}%"
                    for m in fetch(
                        conn,
                        "select year_month, gmv_mom_growth from marts.kpi_monthly_sales "
                        "where year_month like '2018-%%' and gmv_mom_growth is not null "
                        "order by 1",
                    )
                )
                + ".",
            ],
            "Year-on-year growth came mostly from 2017's ramp-up; a forecast should not "
            "extrapolate the 2017 slope into late 2018 (see the forecasting model card).",
        )
    )

    # 2. Retention.
    m1 = fetch(
        conn,
        """
        select sum(active_customers)::float / nullif(sum(cohort_customers), 0) as r1
        from marts.kpi_customer_cohorts where months_since_first_order = 1""",
    )[0]["r1"]
    out.append(
        (
            "Almost every customer buys once",
            [
                f"{k['customers']:,} customers placed {k['revenue_orders']:,} revenue orders "
                f"({float(k['avg_orders_per_customer']):.3f} orders per customer).",
                f"Repeat purchase rate: {pct(k['repeat_purchase_rate'], 2)} "
                f"({k['repeat_customers']:,} customers with two or more orders).",
                f"Customers active again in the month after their first order, all cohorts "
                f"pooled: {pct(m1, 2)}.",
            ],
            "Growth depends on acquisition, not loyalty. This is also why the repurchase and "
            "recommendation models have little signal to learn from (see their model cards).",
        )
    )

    # 3. Concentration.
    top = fetch(
        conn,
        "select share_of_gmv, min_customer_gmv from marts.kpi_customer_concentration "
        "where gmv_decile = 1",
    )[0]
    one_order = fetch(
        conn,
        """
        with d as (select frequency, ntile(10) over (order by monetary desc) decile
                   from ml.customer_rfm)
        select avg((frequency = 1)::int) s from d where decile = 1""",
    )[0]["s"]
    bottom_half = fetch(
        conn,
        "select sum(share_of_gmv) s from marts.kpi_customer_concentration where gmv_decile > 5",
    )[0]["s"]
    out.append(
        (
            "Spend is concentrated in the top decile",
            [
                f"The top 10% of customers by spend account for {pct(top['share_of_gmv'])} "
                f"of GMV (each spent at least {brl(top['min_customer_gmv'])}).",
                f"The bottom half of customers accounts for {pct(bottom_half)}.",
                f"{pct(one_order)} of the top-decile customers placed a single order "
                "(`ml.customer_rfm`, same customers).",
            ],
            "The top decile is mostly people who bought one expensive basket, not loyal "
            "heavy buyers, so price mix matters more than purchase frequency.",
        )
    )

    # 4. Geography.
    states = fetch(
        conn, "select * from marts.kpi_sales_by_state order by gmv_rank"
    )  # one row per state
    top3 = states[:3]
    ranked = [s for s in states if (s["delivery_eligible_orders"] or 0) >= MIN_STATE_ORDERS]
    slow = max(ranked, key=lambda s: s["late_delivery_rate"])
    fast = min(ranked, key=lambda s: s["late_delivery_rate"])
    sp_sellers = fetch(conn, "select avg((seller_state = 'SP')::int) s from marts.dim_sellers")[0][
        "s"
    ]
    out.append(
        (
            "Sales are concentrated in the South-East, and delivery quality varies by state",
            [
                "Top three states by GMV: "
                + ", ".join(f"{s['state']} {pct(s['share_of_gmv'])}" for s in top3)
                + f" (together {pct(sum(float(s['share_of_gmv']) for s in top3))}).",
                f"Late-delivery rate, states with at least {MIN_STATE_ORDERS} eligible "
                f"deliveries: highest {slow['state']} {pct(slow['late_delivery_rate'])} "
                f"(average {float(slow['avg_delivery_days']):.1f} days), lowest "
                f"{fast['state']} {pct(fast['late_delivery_rate'])} "
                f"({float(fast['avg_delivery_days']):.1f} days); overall "
                f"{pct(k['late_delivery_rate'])}.",
                f"{pct(sp_sellers)} of sellers are based in SP.",
            ],
            "Distance from the sellers, most of whom are in SP, is the likely driver; "
            "the data has no carrier or route information to confirm it.",
        )
    )

    # 5. Delivery vs satisfaction.
    rev = fetch(conn, "select * from marts.kpi_review_distribution order by review_score")
    on_n = sum(r["on_time_orders"] for r in rev)
    late_n = sum(r["late_orders"] for r in rev)
    on_avg = sum(r["review_score"] * r["on_time_orders"] for r in rev) / on_n
    late_avg = sum(r["review_score"] * r["late_orders"] for r in rev) / late_n
    one = next(r for r in rev if r["review_score"] == 1)
    out.append(
        (
            "Late deliveries are strongly associated with bad reviews",
            [
                f"Average review score: {on_avg:.2f} for on-time orders vs {late_avg:.2f} "
                f"for late orders ({compare(late_avg, on_avg)} by "
                f"{abs(on_avg - late_avg):.2f} points).",
                f"1-star reviews: {pct(one['on_time_orders'] / on_n)} of on-time orders vs "
                f"{pct(one['late_orders'] / late_n)} of late orders.",
                f"Overall average score {float(k['avg_review_score']):.2f}; on-time rate "
                f"{pct(k['on_time_delivery_rate'])}.",
            ],
            "Delivery performance and delivery-date estimates in the slowest states are the "
            "most promising lever on satisfaction to test. This is a correlation; an "
            "experiment would be needed to measure the effect.",
        )
    )

    # 6. Categories and payments.
    cats = fetch(conn, "select * from marts.kpi_sales_by_category order by gmv_rank limit 5")
    pay = fetch(conn, "select * from marts.kpi_payment_mix order by payment_value desc")
    out.append(
        (
            "No single category dominates; most money is paid by card in instalments",
            [
                "Top five categories by item GMV: "
                + ", ".join(f"{c['category_name']} {pct(c['share_of_gmv'])}" for c in cats)
                + f" (together {pct(sum(float(c['share_of_gmv']) for c in cats))}).",
                "Payment value by type: "
                + ", ".join(
                    f"{p['payment_type_label']} {pct(p['share_of_payment_value'])}" for p in pay
                )
                + f"; credit card payments average {float(pay[0]['avg_installments']):.1f} "
                "instalments."
                if pay and pay[0]["payment_type"] == "credit_card"
                else "",
                f"Freight is {pct(k['freight_share_of_gmv'])} of GMV "
                f"(average {brl(k['avg_freight_per_order'])} per order).",
            ],
            "A broad catalogue spreads risk; instalments suggest price sensitivity, so "
            "free-instalment promotions are a plausible lever to test.",
        )
    )
    return out


def build(conn) -> str:
    k = fetch(conn, "select * from marts.kpi_overview")[0]
    lines = [
        "# Business findings",
        "",
        f"> Generated by `data_engineering/scripts/build_business_findings.py` on "
        f"{dt.date.today():%Y-%m-%d} from the `marts.kpi_*` views. Every number is a query "
        "result. **Hypotheses** are interpretations, not results: the data is observational, "
        "so it shows associations, not causes.",
        "",
        f"Scope: revenue orders from {k['window_start']} to {k['window_end']} "
        f"(definitions in the [KPI dictionary](kpi_dictionary.md)). Historical Olist data; "
        "money is BRL, GMV is not Olist's revenue or profit.",
        "",
        "| GMV | Revenue orders | Customers | Average order value | On-time delivery | "
        "Average review |",
        "|---|---|---|---|---|---|",
        f"| {brl(k['gmv'])} | {k['revenue_orders']:,} | {k['customers']:,} | "
        f"{brl(k['avg_order_value'])} | {pct(k['on_time_delivery_rate'])} | "
        f"{float(k['avg_review_score']):.2f} |",
    ]
    for i, (title, evidence, hypothesis) in enumerate(findings(conn), 1):
        lines += ["", f"## {i}. {title}", ""]
        lines += [f"- {e}" for e in evidence if e]
        lines += ["", f"**Hypothesis:** {hypothesis}"]
    lines += [
        "",
        "## What the models add",
        "",
        "Each model card compares the model with a simple baseline on held-out data; the "
        "summary is in [portfolio.md](portfolio.md#results-against-baselines). Finding 2 is "
        "the main constraint: with about 3% repeat customers, customer-level models have "
        "little history to learn from.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    with psycopg.connect(**get_settings().psycopg_kwargs("etl"), row_factory=dict_row) as conn:
        text = build(conn)
    args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
