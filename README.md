# Automated Data Pipeline & Analytics Dashboard

[![Python Tests](https://github.com/gloriavarkey/automated-data-pipeline/actions/workflows/tests.yml/badge.svg)](https://github.com/gloriavarkey/automated-data-pipeline/actions/workflows/tests.yml)

A Python project that validates synthetic sales data, stores clean records
in SQLite, and displays sales insights in an interactive Streamlit dashboard.

The **Company Sales** page models a business with Firefighting, Plumbing, and
Woodwork departments. It shows what the business sold, how much it collected,
and which transactions need review. An **Overview** shows recorded net sales,
costs, and estimated gross profit. **Payments** shows outstanding balances by
department and payment status. **Data quality** lets you trace a warning to the
sale that caused it.

## Features

- Validates dates, required fields, quantities, and prices.
- Removes identical duplicates and rejects conflicting sale IDs.
- Exports rejected records with rejection reasons.
- Stores monetary values as integer cents.
- Refreshes the database without duplicating sales on repeated runs.
- Preserves existing database records when no valid input rows remain.
- Filters dashboard results by category and date.
- Exports filtered sales as CSV.
- Supports daily execution through Windows Task Scheduler.
- Includes 20 automated tests covering the original pipeline, company imports,
  and the Streamlit page. The tests check that reruns preserve totals and
  that changing a filter updates both financial figures and review counts.
- GitHub Actions runs automated tests and the sample pipeline on Windows and Linux.

## Technologies

Python, pandas, SQLite, Streamlit, Plotly, pytest, Git, GitHub Actions,
and Windows Task Scheduler.

## Run locally on Windows

Clone the repository and enter the project folder.

```powershell
git clone https://github.com/gloriavarkey/automated-data-pipeline.git
cd automated-data-pipeline
```

In the project folder, set up Python 3.13 and build the two sample databases.
The company importer accepts tab-separated or comma-separated exports.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe pipeline.py

# Use the small company sample when no local export has been supplied.
if (-not (Test-Path -LiteralPath .\data\private\company_sales.csv)) {
    New-Item -ItemType Directory -Force .\data\private | Out-Null
    Copy-Item .\tests\fixtures\company_dashboard.tsv .\data\private\company_sales.csv
}
.\.venv\Scripts\python.exe company_pipeline.py
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

Open http://localhost:8501 if the browser does not open automatically. Choose
**Company Sales** in the sidebar. With the included company sample, select
**Woodwork** to see one accepted sale for **€87.15**. Under **Data quality**,
select **Gross sales mismatch** to inspect its €91.74 recorded gross amount
and the €91.77 calculated from quantity and unit price.

## Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

## Sample results

| Synthetic input | Rows read | Duplicates removed | Rejected | Accepted | Sales shown |
|---|---:|---:|---:|---:|---:|
| Original retail CSV | 14 | 1 | 3 | 10 | €2,585.00 revenue |
| Company sample included in this repository | 5 | 1 | 1 | 3 | €163.89 net sales |
| Larger company export used locally | 188 | 4 | 0 | 184 | €252,031.58 net sales |

Company totals use the recorded net amounts, including accepted sales with
warnings. Estimated gross profit subtracts quantity times recorded unit cost
from net sales. Outstanding balance subtracts payments received from net sales.

## Scheduled execution

`run_pipeline.bat` runs the retail pipeline (`pipeline.py`) using the project's virtual environment
and appends output and errors to `logs/pipeline.log`.

Configure Windows Task Scheduler to run this file using its absolute path.
The local demonstration uses a daily 18:00 schedule while the user is
logged in. The computer must be awake.

After updating `data/private/company_sales.csv`, run
`.\.venv\Scripts\python.exe company_pipeline.py` from the project folder,
then click **Reload database** on the Company Sales page.

## Scope and limitations

- The input CSV represents the complete current sales dataset.
- Each successful run replaces the database's sales snapshot.
- New data must be supplied in the CSV; external data collection is not implemented.
- Each accepted sale ID represents one product or service sale.
- Returns and negative quantities are outside the current scope.
- The dashboard refresh button reloads the database; it does not run the pipeline.
- Data is synthetic and EUR is the assumed currency.
