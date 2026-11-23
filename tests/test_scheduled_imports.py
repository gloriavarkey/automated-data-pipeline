"""Run the scheduler entry point on disposable copies of the public examples."""

from pathlib import Path
from shutil import copyfile
import subprocess
import sys

import pytest


PROJECT_DIR = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "retail_valid,company_input",
    [(True, "valid"), (True, "missing"), (False, "valid"), (True, "invalid")],
    ids=["both-import", "retail-only", "retail-fails-company-runs", "company-fails"],
)
def test_scheduled_imports(tmp_path, retail_valid, company_input):
    # Launch from a different working directory, just as Task Scheduler can.
    project = tmp_path / "sales project"
    raw = project / "data/raw"
    raw.mkdir(parents=True)
    for name in ("scheduled_imports.py", "pipeline.py", "company_pipeline.py"):
        copyfile(PROJECT_DIR / name, project / name)

    if retail_valid:
        copyfile(PROJECT_DIR / "data/raw/sales.csv", raw / "sales.csv")
    else:
        (raw / "sales.csv").write_text("invalid_header\nrow\n", encoding="utf-8")
    if company_input != "missing":
        export = project / "data/private/company_sales.csv"
        export.parent.mkdir()
        if company_input == "valid":
            copyfile(PROJECT_DIR / "tests/fixtures/company_dashboard.tsv", export)
        else:
            export.write_text("invalid_header\nrow\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(project / "scheduled_imports.py")],
        cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", check=False, timeout=60,
    )
    expected_success = retail_valid and company_input != "invalid"
    assert (result.returncode == 0) == expected_success, result.stdout
    output = project / "data/processed"
    assert (output / "sales.db").is_file() == retail_valid
    assert (output / "company/company_sales.db").is_file() == (company_input == "valid")
    if company_input == "missing":
        assert "Company import skipped" in result.stdout
    if not expected_success:
        failed_script = "company_pipeline.py" if retail_valid else "pipeline.py"
        assert f"{failed_script} exited with code" in result.stdout
