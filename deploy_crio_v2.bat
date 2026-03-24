@echo off
REM Deploy cRIO Node V2 — thin wrapper around Python deploy script.
REM Usage: deploy_crio_v2.bat [crio_host] [broker_host]
REM
REM All logic is in scripts/deploy_crio.py to avoid CMD escaping issues.
REM This bat file just finds Python and calls it.

REM Try venv Python first, fall back to system Python
if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" "%~dp0scripts\deploy_crio.py" %*
) else (
    python "%~dp0scripts\deploy_crio.py" %*
)
