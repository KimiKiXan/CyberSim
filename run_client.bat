@echo off
REM ===== CyberSim — Client Launcher =====
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)
%PY% run_client.py %*
endlocal
