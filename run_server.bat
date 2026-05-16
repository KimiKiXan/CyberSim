@echo off
REM ===== CyberSim — Server Launcher =====
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)
%PY% run_server.py %*
endlocal
