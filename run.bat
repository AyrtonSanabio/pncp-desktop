@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Ambiente virtual nao encontrado.
    echo Execute primeiro: python -m venv .venv
    echo Depois: .venv\Scripts\python.exe -m pip install -e ".[dev]"
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" -m pncp_desktop.main
