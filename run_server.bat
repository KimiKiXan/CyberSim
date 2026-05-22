@echo off
REM ============================================================
REM  CyberSim - Server Launcher
REM  - Auto-starts the Ollama daemon if not already running
REM  - Waits until the Ollama API is reachable
REM  - Launches the FastAPI backend
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM --- pick Python interpreter (prefer project venv) ---
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

REM --- locate the Ollama executable ---
set "OLLAMA_EXE="
for /f "delims=" %%I in ('where ollama 2^>nul') do (
    if not defined OLLAMA_EXE set "OLLAMA_EXE=%%I"
)
if not defined OLLAMA_EXE (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
)
if not defined OLLAMA_EXE (
    if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA_EXE=%ProgramFiles%\Ollama\ollama.exe"
)

REM --- start Ollama daemon if it's not already running ---
tasklist /FI "IMAGENAME eq ollama.exe" /NH 2>nul | find /I "ollama.exe" >nul
if errorlevel 1 (
    if defined OLLAMA_EXE (
        echo [run_server] Starting Ollama daemon ^("%OLLAMA_EXE%"^) ...
        start "Ollama" /B "%OLLAMA_EXE%" serve
    ) else (
        echo [run_server] WARNING: ollama.exe not found in PATH or default install dirs.
        echo [run_server]          The server will start, but /health will report Ollama DOWN.
        echo [run_server]          Install Ollama from https://ollama.com/download and retry.
    )
) else (
    echo [run_server] Ollama already running.
)

REM --- block until the Ollama API answers (max ~45s) ---
"%PY%" scripts\wait_for_ollama.py
if errorlevel 1 (
    echo [run_server] WARNING: Ollama did not become ready in time.
    echo [run_server]          Continuing anyway - the agent will auto-pull on first session.
)

REM --- launch the FastAPI backend ---
echo [run_server] Launching CyberSim server ...
"%PY%" run_server.py %*

endlocal
