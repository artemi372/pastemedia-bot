@echo off
rem Start pastemedia-bot on Windows.
rem   start.bat          - run the bot
rem   start.bat update   - update dependencies (yt-dlp etc.), then run

rem UTF-8 console, so Russian/Estonian text and emoji in logs show up.
chcp 65001 >nul
set PYTHONUTF8=1

rem === Look of this window: black background, aqua text ===
rem Colour codes: first digit = background, second = text (0-9, A-F). 0B = black + aqua.
title TIKTOK DOWNLOADER BOT
color 0B
rem Always work from the folder this file is in.
cd /d "%~dp0"

cls
type "%~dp0banner.txt"

if not exist ".env" (
    echo [!] .env not found.
    echo     Copy .env.example to .env and fill in BOT_TOKEN and STORAGE_CHAT_ID.
    pause
    exit /b 1
)

set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo Creating virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [!] Could not create .venv. Is Python installed and in PATH?
        pause
        exit /b 1
    )
    echo Installing dependencies ...
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [!] Could not install dependencies.
        pause
        exit /b 1
    )
)

if /i "%~1"=="update" (
    echo Updating dependencies ...
    "%PY%" -m pip install -U -r requirements.txt
)

echo Starting the bot. Type "stop" to shut it down, "restart" to restart.
echo.
"%PY%" bot.py

echo.
echo The bot has stopped.
pause
