"""Validation for the assistant's guarded SQL tool. Defence in depth, layered on top of the
database role (analytics_ro: SELECT on marts/ml only, read-only transactions):

1. exactly one statement, parsed by sqlglot (PostgreSQL dialect); parse failures are rejected
2. only SELECT queries (UNION / INTERSECT / EXCEPT of SELECTs, CTEs of SELECTs) - no DML, DDL,
   COPY, SET, SELECT ... INTO, locking clauses
3. every table must be schema-qualified and in the allowlist (marts.*, ml.*)
4. free-text columns are blocked: review comments are customer-written text, a prompt-
   injection channel into the model, and are not needed for analytics
5. no system or side-effect functions (pg_*, dblink, lo_*, set_config, ...)
6. the query is wrapped so at most MAX_ROWS rows can ever come back
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

MAX_ROWS = 200
ALLOWED_SCHEMAS = {"marts", "ml"}
BLOCKED_COLUMNS = {"review_comment_title", "review_comment_message"}
BLOCKED_FUNCTION_PREFIXES = (
    "pg_",
    "lo_",
    "dblink",
    "current_setting",
    "set_config",
    "txid_",
    "query_to_xml",
    "table_to_xml",
    "cursor_to_xml",
    "xpath",
)


class UnsafeQueryError(ValueError):
    pass


@dataclass(frozen=True)
class CheckedQuery:
    sql: str  # the wrapped, row-limited query to execute
    tables: list[str]


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def check_query(sql: str) -> CheckedQuery:
    if not sql or len(sql) > 5000:
        raise UnsafeQueryError("Query is empty or longer than 5000 characters")
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise UnsafeQueryError(f"Could not parse the query: {exc}") from None
    if len(statements) != 1:
        raise UnsafeQueryError("Exactly one statement is allowed")
    tree = statements[0]
    if not isinstance(tree, exp.Query):  # Select, Union, Intersect, Except (and CTE wrappers)
        raise UnsafeQueryError(f"Only SELECT queries are allowed, got {tree.key.upper()}")
    for node in tree.walk():
        if isinstance(node, exp.DML | exp.DDL | exp.Command | exp.Set | exp.Into | exp.Lock):
            raise UnsafeQueryError(f"{node.key.upper()} is not allowed")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables = []
    for table in tree.find_all(exp.Table):
        name, schema = table.name.lower(), (table.db or "").lower()
        if not name:
            raise UnsafeQueryError(
                "Table functions (e.g. dblink, generate_series in FROM) are not allowed"
            )
        if not schema and name in cte_names:
            continue  # reference to a CTE defined in this query
        if schema not in ALLOWED_SCHEMAS:
            raise UnsafeQueryError(
                f"Table {schema + '.' if schema else ''}{name} is not allowed; "
                f"use schema-qualified tables in {sorted(ALLOWED_SCHEMAS)}"
            )
        if table.catalog:
            raise UnsafeQueryError("Cross-database references are not allowed")
        tables.append(f"{schema}.{name}")

    for column in tree.find_all(exp.Column):
        if column.name.lower() in BLOCKED_COLUMNS:
            raise UnsafeQueryError(f"Column {column.name} (free text) is not available")
    if any(t == "marts.fact_reviews" for t in tables) and any(
        isinstance(s, exp.Star) for s in tree.find_all(exp.Star)
    ):
        raise UnsafeQueryError("SELECT * on marts.fact_reviews is not allowed (free-text columns)")

    for func in tree.find_all(exp.Func):
        fname = _function_name(func)
        if fname.startswith(BLOCKED_FUNCTION_PREFIXES):
            raise UnsafeQueryError(f"Function {fname} is not allowed")

    inner = tree.sql(dialect="postgres")
    wrapped = f"select * from ({inner}) as assistant_query limit {MAX_ROWS}"
    return CheckedQuery(sql=wrapped, tables=sorted(set(tables)))
