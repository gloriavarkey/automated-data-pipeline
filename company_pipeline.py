import csv
import logging
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "data/private/company_sales.csv"
OUTPUT_DIR = BASE_DIR / "data/processed/company"
DATABASE_FILE = OUTPUT_DIR / "company_sales.db"

SOURCE_COLUMNS = [
    "Sale_ID", "Order_Date", "Customer", "Customer_ID", "City",
    "Sales_Rep", "Department", "Product_or_Service", "Quantity",
    "Unit_Price_EUR", "Unit_Cost_EUR", "Discount_Percent",
    "Gross_Sales_EUR", "Net_Sales_EUR", "Payment_Status",
    "Amount_Paid_EUR", "Sales_Channel", "Project_Reference",
    "Warranty_Months", "Notes",
]

# These additional fields support reliable calculations and filtering.
EXTRA_COLUMNS = {
    "normalized_date": "TEXT",
    "normalized_payment_status": "TEXT",
    "gross_cents": "INTEGER",
    "net_cents": "INTEGER",
    "cost_cents": "INTEGER",
    "profit_cents": "INTEGER",
    "paid_cents": "INTEGER",
    "outstanding_cents": "INTEGER",
    "quality_warnings": "TEXT",
}

DEPARTMENTS = {"Firefighting", "Plumbing", "Woodwork"}
PAYMENT_STATUSES = {"Paid", "Partially Paid", "Pending", "Overdue"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def number(value):
    """Read a finite decimal without introducing binary floating-point errors."""
    result = Decimal(value.strip())
    if not result.is_finite():
        raise ValueError("Number must be finite")
    return result


def cents(value):
    """Round an amount to whole euro cents."""
    return int(
        (value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def normalize_date(value):
    """Accept the two explicit date formats used in the company export."""
    for date_format in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), date_format).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Unsupported or invalid date")


def read_sales(path):
    """Read a UTF-8 comma-, tab-, or semicolon-separated export."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        header = handle.readline()
        handle.seek(0)

        # Detect the separator from the header, not customer names or notes.
        separator = max([",", "\t", ";"], key=header.count)
        reader = csv.DictReader(handle, delimiter=separator)

        if not reader.fieldnames:
            raise ValueError("The input file has no header.")

        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        column_counts = Counter(reader.fieldnames)
        duplicates = sorted(name for name, count in column_counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"Duplicate columns: {duplicates}")

        missing = set(SOURCE_COLUMNS) - column_counts.keys()
        if missing:
            raise ValueError(f"Missing columns: {sorted(missing)}")

        rows = []
        for line_number, row in enumerate(reader, start=2):
            if None in row or any(row.get(c) is None for c in SOURCE_COLUMNS):
                raise ValueError(
                    f"Malformed CSV record near row {line_number}. "
                    "Check separators and quoted text."
                )

            # Keep original values, including spaces, for traceability.
            rows.append({column: row[column] for column in SOURCE_COLUMNS})

    return rows


def clean_company_sales(rows):
    """Return accepted records, rejected records, and duplicate count."""
    unique_rows = []
    seen = set()

    # Count CSV records before deduplication. The header is row 1.
    for source_row, row in enumerate(rows, start=2):
        signature = tuple(row[column] for column in SOURCE_COLUMNS)
        if signature not in seen:
            seen.add(signature)
            unique_rows.append((source_row, row))

    duplicate_count = len(rows) - len(unique_rows)

    # Flag different records sharing a sale ID.
    sale_id_counts = defaultdict(int)
    customer_names = defaultdict(set)

    for _, row in unique_rows:
        sale_id_counts[row["Sale_ID"].strip()] += 1
        customer_id = row["Customer_ID"].strip()
        customer = row["Customer"].strip()
        if customer_id and customer:
            customer_names[customer_id].add(customer.casefold())

    accepted = []
    rejected = []

    numeric_columns = [
        "Quantity", "Unit_Price_EUR", "Unit_Cost_EUR",
        "Discount_Percent", "Gross_Sales_EUR", "Net_Sales_EUR",
        "Amount_Paid_EUR",
    ]

    for source_row, original in unique_rows:
        row = {key: value.strip() for key, value in original.items()}
        errors = []
        warnings = []
        values = {}

        for column in ["Sale_ID", "Customer", "Department", "Product_or_Service"]:
            if not row[column]:
                errors.append(f"Missing {column}")

        if row["Department"] and row["Department"] not in DEPARTMENTS:
            errors.append("Unknown Department")

        if row["Sale_ID"] and sale_id_counts[row["Sale_ID"]] > 1:
            errors.append("Conflicting Sale_ID")

        try:
            normalized_date = normalize_date(row["Order_Date"])
        except ValueError:
            normalized_date = ""
            errors.append("Invalid Order_Date")

        for column in numeric_columns:
            try:
                values[column] = number(row[column])
            except (InvalidOperation, ValueError):
                errors.append(f"Invalid {column}")

        # Quantity may be fractional: products can be sold by metre or m².
        if "Quantity" in values and values["Quantity"] <= 0:
            errors.append("Quantity must be positive")

        for column in numeric_columns[1:]:
            if column in values and values[column] < 0:
                errors.append(f"{column} cannot be negative")

        if (
            "Discount_Percent" in values
            and values["Discount_Percent"] > 100
        ):
            errors.append("Discount_Percent exceeds 100")

        status = row["Payment_Status"].title()
        if status not in PAYMENT_STATUSES:
            errors.append("Unknown Payment_Status")

        if errors:
            rejected.append({
                **original,
                "rejection_reason": "; ".join(errors),
                "source_row": source_row,
            })
            continue

        for column in ["Customer_ID", "City", "Sales_Rep"]:
            if not row[column]:
                warnings.append(f"Missing {column}")

        if len(customer_names.get(row["Customer_ID"], set())) > 1:
            warnings.append("Customer_ID maps to multiple customer names")

        # Preserve recorded totals as the source of truth for this import.
        gross = cents(values["Gross_Sales_EUR"])
        net = cents(values["Net_Sales_EUR"])
        paid = cents(values["Amount_Paid_EUR"])

        expected_gross_amount = values["Quantity"] * values["Unit_Price_EUR"]
        expected_gross = cents(expected_gross_amount)
        expected_net = cents(
            expected_gross_amount
            * (Decimal("1") - values["Discount_Percent"] / 100)
        )

        if gross != expected_gross:
            warnings.append(
                f"Gross mismatch: recorded {gross}, expected "
                f"{expected_gross} cents"
            )

        # Retain even one-cent rounding differences for review.
        if net != expected_net:
            warnings.append(
                f"Net mismatch: recorded {net}, expected {expected_net} cents"
            )

        if paid > net:
            warnings.append("Amount paid exceeds net sales")
        if status == "Paid" and paid != net:
            warnings.append("Paid status disagrees with amount paid")
        if status == "Partially Paid" and not (0 < paid < net):
            warnings.append("Partially Paid status disagrees with amount paid")
        if status == "Pending" and paid != 0:
            warnings.append("Pending status has a payment")
        if status == "Overdue" and paid >= net:
            warnings.append("Overdue status has no positive balance")

        cost = cents(values["Quantity"] * values["Unit_Cost_EUR"])

        accepted.append({
            **original,
            "normalized_date": normalized_date,
            "normalized_payment_status": status,
            "gross_cents": gross,
            "net_cents": net,
            "cost_cents": cost,
            "profit_cents": net - cost,
            "paid_cents": paid,
            "outstanding_cents": net - paid,
            "quality_warnings": "; ".join(warnings),
        })

    return accepted, rejected, duplicate_count


def write_report(path, rows, columns):
    """Always write a header, even when the report has no records."""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def save_database(rows):
    """Replace the company snapshot atomically."""
    columns = SOURCE_COLUMNS + list(EXTRA_COLUMNS)

    definitions = [
        f'"{column}" TEXT' + (" PRIMARY KEY" if column == "Sale_ID" else "")
        for column in SOURCE_COLUMNS
    ]
    definitions += [
        f'"{column}" {sql_type}'
        for column, sql_type in EXTRA_COLUMNS.items()
    ]

    column_sql = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)

    # A failed insert rolls back the deletion and preserves the prior snapshot.
    with sqlite3.connect(DATABASE_FILE) as connection:
        connection.execute(
            f'CREATE TABLE IF NOT EXISTS company_sales ({", ".join(definitions)})'
        )
        connection.execute("DELETE FROM company_sales")
        connection.executemany(
            f"INSERT INTO company_sales ({column_sql}) "
            f"VALUES ({placeholders})",
            [tuple(row[column] for column in columns) for row in rows],
        )


def run_pipeline():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = read_sales(INPUT_FILE)
    accepted, rejected, duplicates = clean_company_sales(rows)
    review_rows = [row for row in accepted if row["quality_warnings"]]

    write_report(
        OUTPUT_DIR / "rejected_sales.csv",
        rejected,
        SOURCE_COLUMNS + ["rejection_reason", "source_row"],
    )
    write_report(
        OUTPUT_DIR / "review_sales.csv",
        review_rows,
        SOURCE_COLUMNS + list(EXTRA_COLUMNS),
    )

    logger.info("Input rows: %s", len(rows))
    logger.info("Identical duplicates removed: %s", duplicates)
    logger.info("Rejected records: %s", len(rejected))
    logger.info("Accepted records needing review: %s", len(review_rows))

    if not accepted:
        raise ValueError("No valid records. Company database was not updated.")

    save_database(accepted)

    logger.info("Accepted records saved: %s", len(accepted))
    logger.info(
        "Recorded net sales, including review records: EUR %.2f",
        sum(row["net_cents"] for row in accepted) / 100,
    )
    logger.info("Company pipeline completed successfully.")


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception:
        logger.exception("Company pipeline failed.")
        raise
