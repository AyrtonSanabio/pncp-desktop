# Desenvolvimento e distribuição

## Requisitos

- Windows 10 ou 11;
- Python 3.12 ou mais recente;
- dependências declaradas em `pyproject.toml`.

## Ambiente

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

`run.bat` automatiza esse processo e abre a interface.

## Estrutura

```text
src/pncp_desktop/   interface e serviços desktop
src/pncp_sync/      domínio, API, sincronização e persistência
tests/              testes unitários e de integração local
scripts/            smoke test do executável
installer/          configuração do Inno Setup
```

## Verificação

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m compileall -q src
```

Os testes não executam uma carga nacional. Fontes falsas reproduzem paginação, erros,
retomada, rejeição e idempotência sem depender da disponibilidade externa.

## Build Windows

```powershell
.\build_exe.bat
```

O PyInstaller usa o modo `onedir`, necessário para carregar as DLLs do Qt de forma estável.
O script executa `scripts/smoke_exe.ps1`, que copia o pacote para uma pasta temporária, abre
o programa sem console e exige uma captura válida. O smoke test define
`PNCP_DESKTOP_DB_PATH` para um banco temporário; ele não lê nem altera o banco configurado
pelo usuário.

O instalador é gerado com:

```powershell
.\build_installer.bat
```

## GitHub Actions

`.github/workflows/release.yml` executa testes, cria o aplicativo, roda o smoke test, compila
o instalador e publica o arquivo quando uma tag `v*` é enviada. A versão do pacote e do
instalador deve permanecer igual.
