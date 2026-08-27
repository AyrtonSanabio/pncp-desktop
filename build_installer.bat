@echo off
setlocal
cd /d "%~dp0"

if not exist "dist\ConsultaPNCP\ConsultaPNCP.exe" (
    echo ERRO: execute build_exe.bat primeiro.
    pause
    exit /b 1
)

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo Inno Setup 6 nao encontrado.
    echo Instale em https://jrsoftware.org/isdl.php e execute novamente.
    echo Como alternativa, distribua a pasta dist\ConsultaPNCP inteira.
    pause
    exit /b 2
)

"%ISCC%" "installer\pncp-desktop.iss"
if errorlevel 1 (
    echo ERRO: o instalador nao foi criado.
    pause
    exit /b 1
)

echo Instalador criado em dist-installer.
pause
