@echo off
REM Build NISystem Launcher as Windows executable
REM Requires: pip install pyinstaller paho-mqtt

echo Building NISystem Launcher...

REM Activate venv if available
if exist "..\venv\Scripts\activate.bat" (
    call ..\venv\Scripts\activate.bat
)

REM Install dependencies
pip install pyinstaller paho-mqtt

REM Build executable
pyinstaller --onefile --windowed --name "NISystem Launcher" nisystem_launcher.py

echo.
echo Build complete! Executable is in: dist\NISystem Launcher.exe
echo.
pause
