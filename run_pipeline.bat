@echo off
REM Switch to the folder containing this batch file.
cd /d "%~dp0" || exit /b 1

REM Create a folder for pipeline logs.
if not exist "logs" mkdir "logs"

REM Run the sales imports and append output and errors to the task log.
".venv\Scripts\python.exe" "scheduled_imports.py" >> "logs\pipeline.log" 2>&1

REM Return Python's exit code so Task Scheduler can detect failures.
exit /b %ERRORLEVEL%
