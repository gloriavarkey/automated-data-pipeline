import sqlite3

import pandas as pd
import pytest

import pipeline


def make_sales():
    """Create a small, valid dataset for testing."""
    return pd.DataFrame({
        "sale_id": ["1001", "1002"],
        "date": ["2026-10-01", "2026-10-02"],
        "product": ["Laptop", "Mouse"],
        "category": ["Electronics", "Electronics"],
        "quantity": ["1", "3"],
        "unit_price": ["850.00", "25.00"],
    })


def test_revenue_calculation():
    """Revenue must equal quantity multiplied by price, in cents."""
    clean, rejected, duplicates = pipeline.clean_sales(make_sales())

    assert len(clean) == 2
    assert rejected.empty
    assert duplicates == 0
    assert clean["revenue_cents"].tolist() == [85000, 7500]
    assert clean["revenue_cents"].sum() == 92500


def test_identical_duplicates_are_removed():
    """Repeating an identical input row must not increase sales."""
    data = make_sales()
    data = pd.concat([data, data.iloc[[0]]], ignore_index=True)

    clean, rejected, duplicates = pipeline.clean_sales(data)

    assert len(clean) == 2
    assert rejected.empty
    assert duplicates == 1


@pytest.mark.parametrize(
    "column, invalid_value, expected_reason",
    [
        ("sale_id", "abc", "invalid sale_id"),
        ("date", "invalid-date", "invalid date"),
        ("product", "", "missing product"),
        ("category", "   ", "missing category"),
        ("quantity", "-2", "invalid quantity"),
        ("quantity", "1.5", "invalid quantity"),
        ("unit_price", "-10", "invalid unit_price"),
        ("unit_price", "inf", "invalid unit_price"),
    ],
)
def test_invalid_rows_are_rejected(column, invalid_value, expected_reason):
    """Check several invalid inputs using the same test."""
    data = make_sales()
    data.loc[0, column] = invalid_value

    clean, rejected, _ = pipeline.clean_sales(data)

    assert len(clean) == 1
    assert len(rejected) == 1
    assert expected_reason in rejected.iloc[0]["rejection_reason"]


def test_conflicting_sale_ids_are_rejected():
    """Reject different records that share the same sale ID."""
    data = make_sales()
    data.loc[1, "sale_id"] = "1001"

    clean, rejected, _ = pipeline.clean_sales(data)

    assert clean.empty
    assert len(rejected) == 2
    assert rejected["rejection_reason"].str.contains(
        "conflicting sale_id"
    ).all()


def test_missing_column_raises_error():
    """A missing required column must produce a clear error."""
    data = make_sales().drop(columns="product")

    with pytest.raises(ValueError, match="Missing required columns"):
        pipeline.clean_sales(data)


def test_running_twice_does_not_duplicate_sales(tmp_path, monkeypatch):
    """Repeated saves must leave the same database records and totals."""
    # Use a temporary database so your actual sales database stays untouched.
    database_file = tmp_path / "test_sales.db"
    monkeypatch.setattr(pipeline, "DATABASE_FILE", database_file)

    clean, _, _ = pipeline.clean_sales(make_sales())

    pipeline.save_to_database(clean)
    pipeline.save_to_database(clean)

    with sqlite3.connect(database_file) as connection:
        count, revenue = connection.execute(
            "SELECT COUNT(*), SUM(revenue_cents) FROM sales"
        ).fetchone()

    assert count == 2
    assert revenue == 92500


def test_invalid_input_preserves_existing_database(tmp_path, monkeypatch):
    """A run with no valid sales must preserve previously stored sales."""
    database_file = tmp_path / "test_sales.db"
    input_file = tmp_path / "sales.csv"

    monkeypatch.setattr(pipeline, "DATABASE_FILE", database_file)
    monkeypatch.setattr(pipeline, "INPUT_FILE", input_file)
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", tmp_path)

    # First store valid sales.
    clean, _, _ = pipeline.clean_sales(make_sales())
    pipeline.save_to_database(clean)

    # Then simulate an incoming file containing only invalid sales.
    invalid_data = make_sales()
    invalid_data["quantity"] = "-1"
    invalid_data.to_csv(input_file, index=False)

    with pytest.raises(ValueError, match="No valid sales found"):
        pipeline.run_pipeline()

    # Verify that the previous database contents are still present.
    with sqlite3.connect(database_file) as connection:
        count, revenue = connection.execute(
            "SELECT COUNT(*), SUM(revenue_cents) FROM sales"
        ).fetchone()

    assert count == 2
    assert revenue == 92500