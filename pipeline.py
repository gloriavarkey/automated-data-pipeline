from pathlib import Path
import logging
import sqlite3

import pandas as pd


# Build paths relative to this script so it works from any working directory.
BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "data" / "raw" / "sales.csv"
OUTPUT_DIR = BASE_DIR / "data" / "processed"
DATABASE_FILE = OUTPUT_DIR / "sales.db"

# Display progress and errors in the terminal.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def clean_sales(data):
    """Validate sales and return clean rows, rejected rows, and duplicate count."""
    required_columns = [
        "sale_id", "date", "product", "category", "quantity", "unit_price"
    ]

    # Stop with a clear error if the input structure is incorrect.
    missing = set(required_columns) - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    data = data[required_columns].copy()

    # Remove surrounding spaces and treat blank text as missing.
    for column in required_columns:
        data[column] = data[column].astype("string").str.strip()
        data[column] = data[column].replace("", pd.NA)

    # Remove identical rows, while keeping the first occurrence.
    duplicate_count = int(data.duplicated().sum())
    data = data.drop_duplicates().copy()

    # Keep the original values for the rejected-record report.
    original = data.copy()

    # Invalid dates and numbers become missing values instead of crashing.
    data["date"] = pd.to_datetime(
        data["date"], format="%Y-%m-%d", errors="coerce"
    )
    for column in ["sale_id", "quantity", "unit_price"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    # Build validation rules. Sale IDs and quantities must be positive integers.
    checks = {
        "invalid sale_id": (
            data["sale_id"].gt(0) & data["sale_id"].mod(1).eq(0)
        ),
        "invalid date": data["date"].notna(),
        "missing product": data["product"].notna(),
        "missing category": data["category"].notna(),
        "invalid quantity": (
            data["quantity"].gt(0) & data["quantity"].mod(1).eq(0)
        ),
        "invalid unit_price": (
            data["unit_price"].ge(0)
            & data["unit_price"].lt(float("inf"))
        ),
        # Different records sharing an ID need review; do not choose silently.
        "conflicting sale_id": ~data["sale_id"].duplicated(keep=False),
    }

    # Record all failed rules for each row.
    reasons = pd.Series("", index=data.index, dtype="string")
    for reason, valid in checks.items():
        invalid = ~valid.fillna(False)
        reasons.loc[invalid] = reasons.loc[invalid] + reason + "; "

    valid_rows = reasons.eq("")

    rejected = original.loc[~valid_rows].copy()
    rejected["rejection_reason"] = reasons.loc[~valid_rows].str.rstrip("; ")

    clean = data.loc[valid_rows].copy()
    clean["sale_id"] = clean["sale_id"].astype("int64")
    clean["quantity"] = clean["quantity"].astype("int64")
    clean["date"] = clean["date"].dt.strftime("%Y-%m-%d")

    # Store money as whole cents to avoid floating-point totals in the database.
    clean["unit_price_cents"] = (
        clean["unit_price"].round(2).mul(100).round().astype("int64")
    )
    clean["revenue_cents"] = clean["quantity"] * clean["unit_price_cents"]
    clean = clean.drop(columns="unit_price")

    return clean, rejected, duplicate_count


def save_to_database(clean):
    """Refresh the sales snapshot inside a database transaction."""
    columns = [
        "sale_id", "date", "product", "category",
        "quantity", "unit_price_cents", "revenue_cents"
    ]

    with sqlite3.connect(DATABASE_FILE) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                sale_id INTEGER PRIMARY KEY,
                date TEXT NOT NULL,
                product TEXT NOT NULL,
                category TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
                revenue_cents INTEGER NOT NULL CHECK (revenue_cents >= 0)
            )
        """)

        # Treat the CSV as the complete current dataset.
        # Replacing the snapshot prevents duplicates on repeated runs.
        connection.execute("DELETE FROM sales")

        connection.executemany(
            """
            INSERT INTO sales (
                sale_id, date, product, category,
                quantity, unit_price_cents, revenue_cents
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            clean[columns].itertuples(index=False, name=None),
        )


def run_pipeline():
    """Read, clean, and store the sales dataset."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Reading %s", INPUT_FILE)
    data = pd.read_csv(INPUT_FILE, dtype="string")
    logger.info("Input rows: %s", len(data))

    clean, rejected, duplicate_count = clean_sales(data)

    # Avoid replacing existing data if the new input has no valid records.
    if clean.empty:
        rejected.to_csv(OUTPUT_DIR / "rejected_sales.csv", index=False)
        raise ValueError("No valid sales found. Database was not updated.")

    save_to_database(clean)

    # Export readable files for inspection.
    clean.to_csv(OUTPUT_DIR / "clean_sales.csv", index=False)
    rejected.to_csv(OUTPUT_DIR / "rejected_sales.csv", index=False)

    logger.info("Duplicates removed: %s", duplicate_count)
    logger.info("Rejected rows: %s", len(rejected))
    logger.info("Valid sales saved: %s", len(clean))
    logger.info("Total revenue: %.2f", clean["revenue_cents"].sum() / 100)
    logger.info("Pipeline completed successfully.")


# Run only when this file is executed directly.
# Tests can import its functions without starting the pipeline.
if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception:
        logger.exception("Pipeline failed.")
        raise