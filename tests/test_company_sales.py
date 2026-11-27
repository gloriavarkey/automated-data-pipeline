"""Exercise the company importer and the Streamlit page using a temporary database."""

import csv
import subprocess
import sys
from datetime import date
from pathlib import Path
from shutil import copyfile

import pytest
from streamlit.testing.v1 import AppTest

import company_analytics as analytics
import company_pipeline as importer


FIXTURE = Path(__file__).parent / "fixtures/company_dashboard.tsv"
PAGE = Path(__file__).resolve().parents[1] / "pages/Company_Sales.py"


@pytest.fixture
def company_db(tmp_path, monkeypatch):
    source = tmp_path / "input.tsv"
    copyfile(FIXTURE, source)
    output = tmp_path / "processed"
    database = output / "company_sales.db"
    monkeypatch.setattr(importer, "INPUT_FILE", source)
    monkeypatch.setattr(importer, "OUTPUT_DIR", output)
    monkeypatch.setattr(importer, "DATABASE_FILE", database)
    monkeypatch.setattr(analytics, "DATABASE_FILE", database)
    importer.run_pipeline()
    return database


def metrics(app):
    assert not app.exception
    return {widget.label: widget.value for widget in app.metric}


def test_company_command_accepts_selected_input(tmp_path):
    script = tmp_path / "company_pipeline.py"
    copyfile(importer.__file__, script)
    default_export = tmp_path / "data/private/company_sales.csv"
    default_export.parent.mkdir(parents=True)
    default_export.write_text("unused header\n", encoding="utf-8")
    exports = tmp_path / "exports"
    exports.mkdir()
    export = exports / "November sales.tsv"
    copyfile(FIXTURE, export)

    subprocess.run(
        [sys.executable, str(script), "--input", export.name],
        cwd=exports, check=True, timeout=30,
    )
    sales = analytics.read_sales(tmp_path / "data/processed/company/company_sales.db")
    assert sales.sale_id.tolist() == ["FIX-01", "FIX-02", "FIX-03"]
    assert sales.net_cents.sum() == 16_389
    assert default_export.read_text(encoding="utf-8") == "unused header\n"


def test_repeat_import_preserves_amounts_and_excludes_invalid_rows(company_db):
    importer.run_pipeline()
    sales = analytics.read_sales(company_db)
    assert sales.sale_id.tolist() == ["FIX-01", "FIX-02", "FIX-03"]
    assert sales.net_cents.sum() == 16_389
    assert sales.cost_cents.sum() == 10_219
    assert sales.profit_cents.sum() == 6_170
    assert sales.paid_cents.sum() == 6_500
    assert sales.outstanding_cents.sum() == 9_889
    assert sales.iloc[0].order_date.date() == date(2025, 2, 25)
    assert sales.iloc[0].city == sales.iloc[0].sales_rep == "Unknown"
    assert sales.iloc[1].city == "Klaipėda"
    assert sales.iloc[2].payment_status == "Pending"
    with (company_db.parent / "rejected_sales.csv").open(encoding="utf-8-sig", newline="") as f:
        rejected = list(csv.DictReader(f))
    assert len(rejected) == 1 and rejected[0]["Sale_ID"] == "FIX-04"


def test_all_invalid_reimport_keeps_dashboard_snapshot(company_db):
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    importer.INPUT_FILE.write_text("\n".join([lines[0], lines[-1]]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="No valid records"):
        importer.run_pipeline()
    assert analytics.read_sales(company_db).net_cents.sum() == 16_389


def test_rejection_report_uses_original_record_numbers(company_db):
    rows = importer.read_sales(importer.INPUT_FILE)
    valid, invalid = rows[0], rows[-1]
    valid["Notes"] = "Valve inspection\nReturn visit"

    with importer.INPUT_FILE.open("w", encoding="utf-8", newline="") as export:
        writer = csv.DictWriter(export, fieldnames=importer.SOURCE_COLUMNS)
        writer.writeheader()
        writer.writerow(valid)
        export.write("\r\n")
        writer.writerows([valid, invalid, invalid])

    importer.run_pipeline()
    report_path = company_db.parent / "rejected_sales.csv"
    with report_path.open(encoding="utf-8-sig", newline="") as report:
        issues = list(csv.DictReader(report))
    assert issues == [
        {**invalid, "source_row": "4", "rejection_reason": "Quantity must be positive"}
    ]


def test_duplicate_sale_id_header_preserves_snapshot(company_db):
    previous_sales = analytics.read_sales(company_db)
    with FIXTURE.open(encoding="utf-8", newline="") as source:
        reader = csv.reader(source, delimiter="\t")
        header, sale = next(reader), next(reader)
    with importer.INPUT_FILE.open("w", encoding="utf-8", newline="") as export:
        writer = csv.writer(export)
        writer.writerow(header + ["Sale_ID"])
        writer.writerow(sale + ["SECOND-ID"])

    with pytest.raises(ValueError, match=r"Duplicate columns: \['Sale_ID'\]"):
        importer.run_pipeline()
    assert analytics.read_sales(company_db).equals(previous_sales)


def test_duplicate_headers_are_reported_after_trimming(tmp_path):
    export = tmp_path / "company.csv"
    export.write_text("Sale_ID,Notes, Sale_ID , Notes \n", encoding="utf-8-sig")
    with pytest.raises(ValueError, match=r"Duplicate columns: \['Notes', 'Sale_ID'\]"):
        importer.read_sales(export)


def test_reads_semicolon_delimited_company_export(tmp_path):
    with FIXTURE.open(encoding="utf-8", newline="") as source:
        sale = next(csv.DictReader(source, delimiter="\t"))
    sale["Notes"] = 'Inspect valve; use the "west" entrance, please.'

    export_path = tmp_path / "company_sales.csv"
    with export_path.open("w", encoding="utf-8-sig", newline="") as export:
        writer = csv.DictWriter(export, fieldnames=list(sale), delimiter=";")
        writer.writeheader()
        writer.writerow(sale)

    assert importer.read_sales(export_path) == [sale]


def test_monthly_totals_include_an_empty_month(company_db):
    sales = analytics.read_sales(company_db)
    totals = analytics.monthly_net_sales(sales, date(2025, 2, 25), date(2025, 5, 15))
    assert list(zip(totals.index.strftime("%Y-%m"), totals)) == [
        ("2025-02", 1674), ("2025-03", 6000), ("2025-04", 0), ("2025-05", 8715),
    ]


def test_warning_drilldown_preserves_the_recorded_amount(company_db):
    app = AppTest.from_file(str(PAGE), default_timeout=20).run()
    visible = metrics(app)
    assert visible["Flagged sales"] == "3"
    assert visible["Sales with shared customer IDs"] == "2"
    assert visible["Sales with amount mismatches"] == "1"
    for issue, recorded, expected in [
        ("Gross sales mismatch", 91.74, 91.77),
        ("Net sales mismatch", 87.15, 87.18),
    ]:
        app.selectbox(key="company_warning_choice").select(issue).run()
        assert metrics(app)["Net sales"] == "€163.89"
        detail = app.dataframe[-1].value
        assert detail["Sale ID"].tolist() == ["FIX-03"]
        assert detail["Recorded (EUR)"].iloc[0] == pytest.approx(recorded)
        assert detail["Expected (EUR)"].iloc[0] == pytest.approx(expected)


def test_page_filters_update_finance_payments_and_quality_together(company_db):
    app = AppTest.from_file(str(PAGE), default_timeout=20).run()
    assert metrics(app)["Accepted sales"] == "3"
    app.multiselect(key="company_depts").set_value(["Plumbing", "Firefighting"])
    app.date_input(key="company_dates").set_value((date(2025, 2, 25), date(2025, 3, 15)))
    app.multiselect(key="company_statuses").set_value(["Partially Paid", "Paid"]).run()
    assert metrics(app)["Net sales"] == "€76.74"
    app.selectbox(key="company_product").select("Pipe by the metre").run()
    visible = metrics(app)
    assert visible["Net sales"] == "€16.74"
    assert visible["Recorded cost"] == "€12.15"
    assert visible["Estimated gross profit"] == "€4.59"
    assert visible["Amount collected"] == "€5.00"
    assert visible["Outstanding balance"] == "€11.74"
    assert visible["Flagged sales"] == visible["Accepted sales"] == "1"
    payment_table = next(table.value for table in app.dataframe
                         if "Payment status" in table.value and "Sales" in table.value)
    assert payment_table["Payment status"].tolist() == ["Partially Paid"]
    assert payment_table["Outstanding balance"].iloc[0] == pytest.approx(11.74)
    app.multiselect(key="company_depts").set_value([]).run()
    assert not app.exception and not app.metric
    assert any("No sales match" in message.value for message in app.info)


def test_missing_database_offers_the_import_command_without_creating_a_file(tmp_path, monkeypatch):
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(analytics, "DATABASE_FILE", missing)
    app = AppTest.from_file(str(PAGE), default_timeout=20).run()
    assert not app.exception
    assert any("python company_pipeline.py" in block.value for block in app.code)
    assert not missing.exists()
