from pathlib import Path
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st


# Locate the database created by our pipeline.
BASE_DIR = Path(__file__).resolve().parent
DATABASE_FILE = BASE_DIR / "data" / "processed" / "sales.db"

# Configure the browser tab and dashboard layout.
st.set_page_config(
    page_title="Sales Analytics Dashboard",
    page_icon="📊",
    layout="wide",
)

st.title("Sales Analytics Dashboard")
st.caption("Automated Data Pipeline & Analytics Dashboard")
st.info("Portfolio demonstration using synthetic sales data. All amounts are in EUR.")

# Stop with helpful instructions if the pipeline has not been run.
if not DATABASE_FILE.exists():
    st.warning("Database not found. Run `python pipeline.py` first.")
    st.stop()

# Read the stored sales. The connection closes after reading.
with sqlite3.connect(DATABASE_FILE) as connection:
    sales = pd.read_sql_query("SELECT * FROM sales", connection)

if sales.empty:
    st.warning("The database contains no sales.")
    st.stop()

# Convert dates for filtering and cents for display.
sales["date"] = pd.to_datetime(sales["date"])
sales["revenue"] = sales["revenue_cents"] / 100
sales["unit_price"] = sales["unit_price_cents"] / 100

# Add interactive controls in the sidebar.
st.sidebar.header("Filter sales")

selected_categories = st.sidebar.multiselect(
    "Categories",
    options=sorted(sales["category"].unique()),
    default=sorted(sales["category"].unique()),
)

date_range = st.sidebar.date_input(
    "Date range",
    value=(sales["date"].min().date(), sales["date"].max().date()),
    min_value=sales["date"].min().date(),
    max_value=sales["date"].max().date(),
)

# Clicking this button reruns the script and reads the database again.
st.sidebar.button("Refresh data")

if len(date_range) != 2:
    st.info("Select both a start date and an end date.")
    st.stop()

start_date, end_date = date_range

# Keep only rows matching the selected categories and dates.
filtered = sales.loc[
    sales["category"].isin(selected_categories)
    & sales["date"].dt.date.between(start_date, end_date)
].copy()

if filtered.empty:
    st.warning("No sales match these filters. Adjust your selection.")
    st.stop()

# Calculate totals from integer cents.
total_revenue = int(filtered["revenue_cents"].sum()) / 100
total_sales = len(filtered)
units_sold = int(filtered["quantity"].sum())
average_sale = total_revenue / total_sales

# Display the main performance indicators.
col1, col2, col3, col4 = st.columns(4)

col1.metric("Total revenue", f"€{total_revenue:,.2f}")
col2.metric("Sales records", total_sales)
col3.metric("Units sold", units_sold)
col4.metric("Average sale", f"€{average_sale:,.2f}")

# Group revenue by date for the trend chart.
daily_sales = (
    filtered.groupby("date", as_index=False)["revenue_cents"]
    .sum()
    .sort_values("date")
)
daily_sales["revenue"] = daily_sales["revenue_cents"] / 100

trend_chart = px.line(
    daily_sales,
    x="date",
    y="revenue",
    markers=True,
    title="Daily Sales Revenue",
    labels={"date": "Date", "revenue": "Revenue (EUR)"},
)

st.plotly_chart(trend_chart)

# Compare products by their total revenue.
product_sales = (
    filtered.groupby("product", as_index=False)["revenue_cents"]
    .sum()
    .sort_values("revenue_cents", ascending=False)
)
product_sales["revenue"] = product_sales["revenue_cents"] / 100

product_chart = px.bar(
    product_sales,
    x="product",
    y="revenue",
    title="Revenue by Product",
    labels={"product": "Product", "revenue": "Revenue (EUR)"},
)

st.plotly_chart(product_chart)

# Show the underlying records so users can inspect the chart data.
st.subheader("Sales records")

display_data = filtered[
    ["sale_id", "date", "product", "category", "quantity", "unit_price", "revenue"]
].sort_values(["date", "sale_id"]).copy()

display_data["date"] = display_data["date"].dt.strftime("%Y-%m-%d")

st.dataframe(display_data, hide_index=True)

# Allow users to download exactly the records shown by their filters.
st.download_button(
    label="Download filtered sales",
    data=display_data.to_csv(index=False).encode("utf-8"),
    file_name="filtered_sales.csv",
    mime="text/csv",
)