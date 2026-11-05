"""Daily series and calendar from the marts (read-only analytics role)."""

import pandas as pd
import sqlalchemy as sa

from data_engineering.config import get_settings

SERIES_SQL = """
select date_day, gmv, revenue_orders, all_orders, canceled_orders, freight, items
from marts.agg_daily_sales
order by date_day
"""
CALENDAR_SQL = """
select date_day, iso_day_of_week, month, is_weekend, is_holiday, holiday_name, is_black_friday
from marts.dim_date
order by date_day
"""


def load_daily(engine: sa.Engine | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (daily metrics indexed by date, calendar indexed by date incl. future days)."""
    engine = engine or sa.create_engine(get_settings().database_url("analytics"))
    with engine.connect() as conn:
        daily = pd.read_sql(SERIES_SQL, conn, parse_dates=["date_day"]).set_index("date_day")
        cal = pd.read_sql(CALENDAR_SQL, conn, parse_dates=["date_day"]).set_index("date_day")
    daily = daily.astype(float).asfreq("D")
    if daily.isna().any().any():
        raise ValueError("agg_daily_sales has missing days; it must cover the window densely")
    return daily, calendar_features(cal)


def calendar_features(cal: pd.DataFrame) -> pd.DataFrame:
    """Known-in-advance calendar regressors (safe to use for future dates)."""
    out = pd.DataFrame(index=cal.index)
    out["dow"] = cal["iso_day_of_week"].astype(int)
    out["month"] = cal["month"].astype(int)
    out["day_of_month"] = cal.index.day
    out["is_weekend"] = cal["is_weekend"].astype(int)
    out["is_holiday"] = cal["is_holiday"].astype(int)
    out["is_black_friday"] = cal["is_black_friday"].astype(int)
    bf_dates = cal.index[cal["is_black_friday"]]
    # Black Friday week effect: the 7 days after Black Friday (the 2017 spike decays over days).
    out["bf_week"] = 0
    for d in bf_dates:
        out.loc[d + pd.Timedelta(days=1) : d + pd.Timedelta(days=7), "bf_week"] = 1
    out["holiday_name"] = cal["holiday_name"].where(cal["is_holiday"])
    return out
