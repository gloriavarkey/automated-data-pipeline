"""Read the company import and prepare sales and data-quality summaries."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd


DATABASE_FILE = Path(__file__).resolve().parent / "data/processed/company/company_sales.db"
MONEY_LABELS = {
    "net_cents": "Net sales",
    "cost_cents": "Recorded cost",
    "profit_cents": "Estimated gross profit",
    "paid_cents": "Amount collected",
    "outstanding_cents": "Outstanding balance",
}


def read_sales(database):
    """Open the database read-only so a missing import cannot create an empty DB."""
    uri = database.resolve().as_uri() + "?mode=ro"
    query = """
        SELECT Sale_ID AS sale_id, normalized_date AS order_date,
               TRIM(Department) AS department, TRIM(Product_or_Service) AS product,
               normalized_payment_status AS payment_status,
               Customer_ID AS customer_id, TRIM(Customer) AS customer,
               COALESCE(NULLIF(TRIM(City), ''), 'Unknown') AS city,
               COALESCE(NULLIF(TRIM(Sales_Rep), ''), 'Unknown') AS sales_rep,
               net_cents, cost_cents, profit_cents, paid_cents, outstanding_cents,
               COALESCE(quality_warnings, '') AS quality_warnings
          FROM company_sales
         ORDER BY normalized_date, Sale_ID
    """
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return pd.read_sql_query(query, connection, parse_dates=["order_date"])


def euro(cents):
    """Format an integer total exactly for the dashboard."""
    value = int(cents)
    whole, fraction = divmod(abs(value), 100)
    return f"{'-' if value < 0 else ''}€{whole:,}.{fraction:02d}"


def group_totals(sales, by):
    """Add the amounts in integer cents and count accepted sales once each."""
    grouped = sales.groupby(by, sort=True)
    totals = grouped[list(MONEY_LABELS)].sum()
    totals.insert(0, "sales_count", grouped.size())
    return totals.sort_values("net_cents", ascending=False, kind="stable").reset_index()


def monthly_net_sales(sales, start, end):
    """Use zero for a month with no matching sales inside the selected dates."""
    month = sales["order_date"].dt.to_period("M")
    months = pd.period_range(start, end, freq="M")
    totals = sales.groupby(month)["net_cents"].sum().reindex(months, fill_value=0)
    totals.index = totals.index.to_timestamp()
    return totals


WARNING_LABELS = {
    "Customer_ID maps to multiple customer names": "Customer ID shared by multiple names",
    "Missing Customer_ID": "Missing customer ID",
    "Missing City": "Missing city",
    "Missing Sales_Rep": "Missing sales representative",
    "Gross mismatch": "Gross sales mismatch",
    "Net mismatch": "Net sales mismatch",
}
AMOUNT_WARNING = re.compile(r"(Gross|Net) mismatch: recorded (-?\d+), expected (-?\d+) cents")


def warning_details(sales):
    """Expand pipeline warnings while keeping the sale ID behind each observation."""
    rows = []
    for sale in sales.itertuples(index=False):
        for text in sale.quality_warnings.split(";"):
            warning = text.strip()
            if not warning:
                continue
            kind = warning.partition(":")[0]
            issue = WARNING_LABELS.get(kind, kind.replace("_", " "))
            recorded = expected = None
            match = AMOUNT_WARNING.fullmatch(warning)
            if match:
                recorded, expected = int(match[2]), int(match[3])
            rows.append((sale.sale_id, issue, sale.customer_id, sale.customer,
                         recorded, expected, warning))
    columns = ["Sale ID", "Issue", "Customer ID", "Customer",
               "Recorded cents", "Expected cents", "Original warning"]
    result = pd.DataFrame(rows, columns=columns)
    for field in ["Recorded cents", "Expected cents"]:
        result[field] = result[field].astype("Int64")
    return result
