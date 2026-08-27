@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
set "PYTHONW=.venv\Scripts\pythonw.exe"

if not exist "%PYTHON%" (
    echo Preparando o aplicativo pela primeira vez...
    where py >nul 2>&1
    if errorlevel 1 goto :python_nao_encontrado

    py -3.13 -m venv .venv >nul 2>&1
    if errorlevel 1 py -3.12 -m venv .venv >nul 2>&1
    if errorlevel 1 goto :python_incompativel
)

"%PYTHON%" -c "import pncp_desktop, PySide6, pypncp" >nul 2>&1
if errorlevel 1 (
    echo Instalando as dependencias. Isso pode levar alguns minutos...
    "%PYTHON%" -m pip install -e .
    if errorlevel 1 goto :instalacao_falhou
)

if not exist "data" mkdir "data"
start "Consulta PNCP Desktop" /D "%~dp0" "%PYTHONW%" -m pncp_desktop.main
if errorlevel 1 goto :inicializacao_falhou
exit /b 0

:python_nao_encontrado
echo Python nao foi encontrado. Instale o Python 3.12 ou mais recente.
goto :mostrar_erro

:python_incompativel
echo Nao foi possivel criar o ambiente com Python 3.13 nem 3.12.
goto :mostrar_erro

:instalacao_falhou
echo Nao foi possivel instalar as dependencias do aplicativo.
goto :mostrar_erro

:inicializacao_falhou
echo Nao foi possivel abrir a interface.

:mostrar_erro
echo.
echo Copie esta mensagem ao pedir ajuda.
pause
exit /b 1
