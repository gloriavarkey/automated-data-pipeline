@echo off
REM Switch to the folder containing this batch file.
cd /d "%~dp0"

REM Create a folder for pipeline logs.
if not exist "logs" mkdir "logs"

REM Run with the project's Python and append output and errors to the log.
".venv\Scripts\python.exe" "pipeline.py" >> "logs\pipeline.log" 2>&1

REM Return Python's exit code so Task Scheduler can detect failures.
exit /b %ERRORLEVEL%