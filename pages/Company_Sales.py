"""Company Sales page for the existing Streamlit dashboard."""

import sqlite3

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import company_analytics as analytics


FIELD_LABELS = {
    "sale_id": "Sale ID", "order_date": "Order date", "department": "Department",
    "product": "Product or service", "payment_status": "Payment status",
    "city": "City", "sales_rep": "Sales representative", "sales_count": "Sales",
}


def show_table(frame, columns):
    """Display sortable numbers in euros after all cents have been added."""
    table = frame.loc[:, columns].copy()
    formats = {}
    for field, label in analytics.MONEY_LABELS.items():
        if field in table:
            table[field] = table[field] / 100
            formats[label] = st.column_config.NumberColumn(format="€%.2f")
    if "order_date" in table:
        table["order_date"] = table["order_date"].dt.strftime("%Y-%m-%d")
    table = table.rename(columns={**FIELD_LABELS, **analytics.MONEY_LABELS})
    st.dataframe(table, hide_index=True, column_config=formats)
    return table


def overview(sales, start, end):
    st.caption("Totals include all accepted sales in your selection, including sales with review warnings.")
    totals = sales[list(analytics.MONEY_LABELS)].sum()
    net, cost, profit = st.columns(3)
    net.metric("Net sales", analytics.euro(totals.net_cents), border=True,
               help="Recorded sales after discounts.")
    cost.metric("Recorded cost", analytics.euro(totals.cost_cents), border=True,
                help="Quantity multiplied by recorded unit cost, rounded per sale.")
    profit.metric("Estimated gross profit", analytics.euro(totals.profit_cents), border=True,
                  help="Net sales minus recorded cost. Overhead is excluded.")
    paid, balance, count = st.columns(3)
    paid.metric("Amount collected", analytics.euro(totals.paid_cents), border=True)
    balance.metric("Outstanding balance", analytics.euro(totals.outstanding_cents), border=True,
                   help="Recorded net sales minus payments received.")
    count.metric("Accepted sales", f"{len(sales):,}", border=True)

    trend_panel, dept_panel = st.columns(2)
    with trend_panel:
        st.subheader("Monthly net sales")
        months = analytics.monthly_net_sales(sales, start, end)
        chart = go.Figure(go.Scatter(
            x=months.index, y=months / 100, mode="lines+markers",
            line=dict(color="#167D74", width=3), marker=dict(size=6),
            hovertemplate="%{x|%B %Y}<br>Net sales €%{y:,.2f}<extra></extra>",
        ))
        chart.update_xaxes(tickformat="%b %y", nticks=6)
        if len(months) == 1:
            chart.update_xaxes(tickvals=months.index)
        chart.update_yaxes(tickprefix="€", rangemode="tozero")
        chart.update_layout(height=280, margin=dict(l=0, r=8, t=8, b=0))
        st.plotly_chart(chart, key="company_month_chart")

    with dept_panel:
        st.subheader("Net sales by department")
        departments = analytics.group_totals(sales, "department")
        chart = go.Figure(go.Bar(
            y=departments["department"], x=departments["net_cents"] / 100,
            orientation="h", marker_color="#48749B",
            hovertemplate="%{y}<br>Net sales €%{x:,.2f}<extra></extra>",
        ))
        chart.update_yaxes(autorange="reversed", automargin=True)
        chart.update_xaxes(tickprefix="€", rangemode="tozero")
        chart.update_layout(height=280, margin=dict(l=0, r=8, t=8, b=0))
        st.plotly_chart(chart, key="company_department_chart")

    st.subheader("Top products and services by net sales")
    products = analytics.group_totals(sales, "product").head(10)
    show_table(products, ["product", "sales_count", "net_cents", "cost_cents", "profit_cents"])

    with st.expander("Sales records and CSV download"):
        records = show_table(
            sales, ["sale_id", "order_date", "department", "product", "city",
                    "sales_rep", "payment_status", *analytics.MONEY_LABELS],
        )
        st.download_button(
            "Download filtered sales", records.to_csv(index=False, float_format="%.2f").encode("utf-8-sig"),
            file_name="company_sales_filtered.csv", mime="text/csv", on_click="ignore",
        )


def payments(sales):
    st.subheader("Payments by status")
    st.caption("Payment status comes from the sales export. Balances use the recorded amounts.")
    by_status = analytics.group_totals(sales, "payment_status")
    show_table(by_status, ["payment_status", "sales_count", "net_cents",
                           "paid_cents", "outstanding_cents"])

    st.subheader("Balances by department")
    by_department = analytics.group_totals(sales, "department").sort_values(
        "outstanding_cents", ascending=False,
    )
    show_table(by_department, ["department", "net_cents", "paid_cents", "outstanding_cents"])


def data_quality(sales):
    issues = analytics.warning_details(sales)
    st.subheader("Sales needing review")
    st.caption("Each count is a count of sales. A sale can have several warnings.")
    first, second, third = st.columns(3)
    first.metric("Flagged sales", issues["Sale ID"].nunique())
    shared_id = issues["Issue"].eq("Customer ID shared by multiple names")
    second.metric("Sales with shared customer IDs", issues.loc[shared_id, "Sale ID"].nunique())
    third.metric("Sales with amount mismatches",
                 issues.loc[issues["Recorded cents"].notna(), "Sale ID"].nunique())
    if issues.empty:
        st.success("The pipeline recorded no warnings for these sales.")
        return

    counts = issues.groupby("Issue")["Sale ID"].nunique().sort_values(ascending=False)
    st.dataframe(counts.rename("Affected sales").reset_index(), hide_index=True)
    choice = st.selectbox("Inspect a warning", ["All warnings", *counts.index],
                          key="company_warning_choice")
    detail = issues if choice == "All warnings" else issues.loc[issues["Issue"].eq(choice)]
    detail = detail.sort_values(["Sale ID", "Issue"]).copy()
    columns = ["Sale ID", "Issue", "Customer ID", "Customer"]
    if detail["Recorded cents"].notna().any():
        detail["Recorded (EUR)"] = detail["Recorded cents"] / 100
        detail["Expected (EUR)"] = detail["Expected cents"] / 100
        detail["Difference (EUR)"] = (detail["Recorded cents"] - detail["Expected cents"]) / 100
        columns.extend(["Recorded (EUR)", "Expected (EUR)", "Difference (EUR)"])
    st.dataframe(detail[columns + ["Original warning"]], hide_index=True,
                 column_config={c: st.column_config.NumberColumn(format="€%.2f")
                                for c in columns if c.endswith("(EUR)")})


def main():
    st.set_page_config(page_title="Company sales", page_icon="📊", layout="wide")
    st.title("Company sales")
    st.caption("Synthetic business data — portfolio demonstration.")
    st.sidebar.header("Filter company sales")
    st.sidebar.button("Reload database", help="Read the latest company import.")

    if not analytics.DATABASE_FILE.is_file():
        st.info("Run the company pipeline from your project folder, then click Reload database.")
        st.code("python company_pipeline.py", language="powershell")
        return
    try:
        sales = analytics.read_sales(analytics.DATABASE_FILE)
    except (sqlite3.Error, pd.errors.DatabaseError) as exc:
        st.error(f"Could not read the company sales table. Run the company pipeline and reload. {exc}")
        return
    if sales.empty:
        st.info("The company database contains no accepted sales.")
        return

    first = sales["order_date"].min().date()
    last = sales["order_date"].max().date()
    dates = st.sidebar.date_input("Order dates", (first, last), min_value=first, max_value=last,
                                  key="company_dates")
    departments = sorted(sales["department"].unique())
    statuses = sorted(sales["payment_status"].unique())
    depts = st.sidebar.multiselect("Departments", departments, default=departments, key="company_depts")
    selected_statuses = st.sidebar.multiselect("Payment statuses", statuses, default=statuses,
                                               key="company_statuses")
    product = st.sidebar.selectbox("Product or service", sorted(sales["product"].unique()),
                                   index=None, placeholder="All products and services", key="company_product")
    if not dates or len(dates) != 2:
        st.info("Choose a start date and an end date.")
        return
    start, end = dates
    selected = (sales["order_date"].between(pd.Timestamp(start), pd.Timestamp(end))
                & sales["department"].isin(depts) & sales["payment_status"].isin(selected_statuses))
    if product is not None:
        selected &= sales["product"].eq(product)
    filtered = sales.loc[selected]
    if filtered.empty:
        st.info("No sales match these filters. Adjust the selection in the sidebar.")
        return

    overview_tab, payments_tab, quality_tab = st.tabs(["Overview", "Payments", "Data quality"])
    with overview_tab:
        overview(filtered, start, end)
    with payments_tab:
        payments(filtered)
    with quality_tab:
        data_quality(filtered)


main()
