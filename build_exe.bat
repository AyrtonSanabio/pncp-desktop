@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERRO: ambiente virtual nao encontrado. Execute run.bat primeiro.
    pause
    exit /b 1
)

echo [1/3] Verificando dependencias...
".venv\Scripts\python.exe" -c "import PyInstaller, PySide6" >nul 2>&1
if errorlevel 1 (
    echo ERRO: instale as dependencias de desenvolvimento com:
    echo .venv\Scripts\python.exe -m pip install -e .[dev]
    pause
    exit /b 1
)

echo [2/3] Criando aplicativo Windows sem console...
".venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm pncp-desktop.spec
if errorlevel 1 (
    echo ERRO: a compilacao falhou.
    pause
    exit /b 1
)

echo [3/3] Executando teste isolado...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\smoke_exe.ps1
if errorlevel 1 (
    echo ERRO: o executavel foi criado, mas falhou no teste isolado.
    pause
    exit /b 1
)

echo.
echo Aplicativo criado em: dist\ConsultaPNCP\ConsultaPNCP.exe
echo Distribua a pasta ConsultaPNCP inteira ou gere o instalador.
pause
