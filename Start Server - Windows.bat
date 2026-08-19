@echo off
REM Double-click to start the MIDI-GPT inference server on Windows.
REM Keep this window open while using MIDI-GPT in REAPER.

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at .venv\
    echo Please run the installer first.
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo.
echo   ╔══════════════════════════════════════╗
echo   ║      MIDI-GPT Server Starting...     ║
echo   ╚══════════════════════════════════════╝
echo.
echo   The server will listen on port 3456 on all network interfaces
echo   (reachable from other machines as this PC's IP address).
echo   Keep this window open while using MIDI-GPT in REAPER.
echo   Press Ctrl+C to stop the server.
echo.

if "%~1"=="" (
    midigpt-http --pretrained yellow --port 3456
) else (
    midigpt-http --port 3456 %*
)

echo.
echo Server stopped.
pause
