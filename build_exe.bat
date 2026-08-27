@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual nao encontrado. Execute run.bat primeiro.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm pncp-desktop.spec
if errorlevel 1 (
    echo A compilacao do executavel falhou.
    pause
    exit /b 1
)

echo.
echo Executavel criado em: dist\ConsultaPNCP.exe
pause
