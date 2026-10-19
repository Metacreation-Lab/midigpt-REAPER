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
    midigpt-http --pretrained yellow_medium --port 3456
) else (
    midigpt-http --port 3456 %*
)

echo.
echo Server stopped.
REM Anything but a clean stop at startup is most often the model download:
REM the checkpoints on Hugging Face need an account that accepted the license.
if errorlevel 1 (
    echo.
    echo If the message above mentions a gated repo, 401 or 403: accept the license at
    echo https://huggingface.co/Metacreation/MIDI-GPT, then save a token with:
    echo   "%~dp0.venv\Scripts\hf.exe" auth login
)
pause
