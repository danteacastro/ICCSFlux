@echo off
REM ============================================================
REM  NISystem Acquisition Pipeline Diagnostic
REM
REM  Usage:
REM    test_acquisition.bat                     Auto-detect mode
REM    test_acquisition.bat --mode cdaq         Force cDAQ
REM    test_acquisition.bat --mode crio         Force cRIO
REM    test_acquisition.bat --skip-stop         Leave acquiring
REM    test_acquisition.bat --project MyProj.json
REM ============================================================
cd /d "%~dp0"
venv\Scripts\python.exe scripts\test_acquisition_flow.py %*
