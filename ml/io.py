"""Fast table writes to the warehouse `ml` schema (ETL role)."""

import io

import pandas as pd
import sqlalchemy as sa

from data_engineering.config import get_settings


def replace_table(df: pd.DataFrame, table: str, schema: str = "ml",
                  engine: sa.Engine | None = None) -> int:  # fmt: skip
    """Replace schema.table with df in one transaction: DDL from pandas, rows via COPY.

    COPY is ~50x faster than multi-row INSERT for the ~1M-row recommendation table.
    """
    engine = engine or sa.create_engine(get_settings().database_url("etl"))
    with engine.begin() as conn:
        df.head(0).to_sql(table, conn, schema=schema, if_exists="replace", index=False)
        buf = io.StringIO()
        df.to_csv(buf, index=False, header=False)
        buf.seek(0)
        cols = ", ".join(f'"{c}"' for c in df.columns)
        raw = conn.connection.driver_connection  # psycopg connection inside the transaction
        with (
            raw.cursor() as cur,
            cur.copy(f'COPY "{schema}"."{table}" ({cols}) FROM STDIN WITH (FORMAT csv)') as copy,
        ):
            copy.write(buf.getvalue())
    return len(df)
