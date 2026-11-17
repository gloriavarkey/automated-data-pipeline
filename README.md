# Automated Data Pipeline & Analytics Dashboard

A Python project that validates synthetic sales data, stores clean records
in SQLite, and displays sales insights in an interactive Streamlit dashboard.

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
- Includes 14 automated tests.

## Technologies

Python, pandas, SQLite, Streamlit, Plotly, pytest, and Windows Task Scheduler.

## Run locally on Windows

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe pipeline.py
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

## Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

## Sample results

The included synthetic dataset contains 14 input rows:

- 10 valid sales
- 1 identical duplicate removed
- 3 invalid rows rejected
- EUR 2,585.00 total revenue

## Scheduled execution

`run_pipeline.bat` runs the pipeline using the project's virtual environment
and appends output and errors to `logs/pipeline.log`.

Configure Windows Task Scheduler to run this file using its absolute path.
The local demonstration uses a daily 18:00 schedule while the user is
logged in. The computer must be awake.

## Scope and limitations

- The input CSV represents the complete current sales dataset.
- Each successful run replaces the database's sales snapshot.
- New data must be supplied in the CSV; external data collection is not implemented.
- Each sale ID represents one product sale.
- Returns and negative quantities are outside the current scope.
- The dashboard refresh button reloads the database; it does not run the pipeline.
- Data is synthetic and EUR is the assumed currency.