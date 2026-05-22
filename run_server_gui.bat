@echo off
REM ============================================================
REM  CyberSim - Server Control Panel (GUI)
REM  Launches the PyQt5 server-control window.
REM  Unlike run_server.bat this does NOT auto-start the backend;
REM  use the "Start Server" / "Start Ollama" buttons inside the UI.
REM ============================================================
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    set "PY=.venv\Scripts\pythonw.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=pythonw"
)

start "" "%PY%" run_server_gui.py %*
endlocal
