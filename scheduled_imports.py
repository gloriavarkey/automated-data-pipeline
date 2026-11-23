"""Run the sales imports invoked by Windows Task Scheduler."""

import logging
import subprocess
import sys
from pathlib import Path

from company_pipeline import INPUT_FILE as COMPANY_INPUT_FILE


PROJECT_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


def main():
    scripts = ["pipeline.py"]
    if COMPANY_INPUT_FILE.exists():
        scripts.append("company_pipeline.py")
    else:
        logger.info("Company import skipped. No export at %s", COMPANY_INPUT_FILE)

    exit_code = 0
    for script in scripts:
        logger.info("Starting %s", script)
        # Each child uses this virtual environment and inherits the batch file's log.
        result = subprocess.run([sys.executable, str(PROJECT_DIR / script)], check=False)
        if result.returncode:
            logger.error("%s exited with code %s", script, result.returncode)
            exit_code = result.returncode
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
