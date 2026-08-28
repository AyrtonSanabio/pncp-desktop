# Consulta PNCP Desktop

Aplicativo Windows de consulta e espelhamento local dos dados públicos do Portal Nacional
de Contratações Públicas (PNCP). O programa consulta a API oficial, organiza as respostas
em um único banco SQLite e permite pesquisar, analisar e exportar os dados sem repetir
consultas pela internet.

O aplicativo é estritamente de leitura. Ele não publica, retifica nem exclui informações
no PNCP.

## O que o programa faz

- consulta contratações online por período, página e CNPJ do órgão comprador;
- sincroniza uma data/modalidade específica ou toda a série desde 01/01/2021;
- divide a carga nacional em janelas de até 31 dias e nas 15 modalidades do PNCP;
- confirma cada página em uma transação SQLite e retoma do primeiro checkpoint ausente;
- repete indefinidamente falhas temporárias da carga completa, com espera progressiva;
- preserva a resposta JSON original comprimida e os dados normalizados;
- evita duplicação pelo identificador PNCP e detecta registros novos ou alterados;
- pesquisa o banco local por texto, órgão, CNPJ, município, fornecedor, modalidade,
  situação, valor e período;
- mostra detalhes, itens, resultados/fornecedores, histórico de sincronizações e análises;
- exporta resultados filtrados para CSV;
- cria backups e verifica a integridade do banco.

PDFs e outros documentos não são baixados automaticamente.

## Áreas da interface

- **Comece aqui:** explica os conceitos e apresenta um primeiro roteiro de uso.
- **Consulta online:** faz uma consulta pontual no PNCP sem gravar uma carga nacional.
- **Sincronização:** estima, baixa, pausa e retoma os dados no banco principal.
- **Banco local:** pesquisa, histórico, análises, backup, diagnóstico e manutenção.

## Executar o projeto

No Windows, execute `run.bat`. O lançador cria o ambiente virtual e instala as dependências
quando necessário. O projeto requer Python 3.12 ou mais recente para desenvolvimento.

Também é possível preparar manualmente o ambiente:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pncp_desktop
```

## Gerar o aplicativo Windows

```powershell
.\build_exe.bat
```

O pacote portátil é criado em `dist\ConsultaPNCP\`. A pasta inteira deve ser distribuída,
pois contém o executável e as bibliotecas do Qt. `build_installer.bat` gera o instalador
quando o Inno Setup está disponível.

Em uma instalação nova, o banco padrão fica em:

```text
%LOCALAPPDATA%\AyrtonSanabio\PNCPDesktop\pncp.sqlite3
```

O botão **Escolher local dos dados** pode apontar o banco para outra unidade. A escolha fica
salva para as próximas execuções.

## Qualidade

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

O build oficial também executa um teste isolado do executável sem consultar a internet.

## Limites atuais

- o tempo da carga depende da disponibilidade e dos limites de frequência do PNCP;
- a estimativa nacional usa uma amostra de até 12 lotes e apresenta aproximações;
- a carga contínua automática cobre as contratações principais; itens e resultados possuem
  execuções próprias e aumentam significativamente a quantidade de chamadas;
- os dados locais são uma cópia para consulta e não substituem o registro, edital ou documento
  oficial do PNCP.

## Documentação técnica

- [Índice da documentação](docs/README.md)
- [Arquitetura](docs/ARQUITETURA.md)
- [Banco de dados](docs/BANCO_DE_DADOS.md)
- [Sincronização e recuperação](docs/SINCRONIZACAO_E_RECUPERACAO.md)
- [API e dados armazenados](docs/API_E_DADOS.md)
- [Segurança e responsabilidade](docs/SEGURANCA_E_RESPONSABILIDADE.md)
- [Desenvolvimento e distribuição](docs/DESENVOLVIMENTO.md)

Fonte dos dados: [Portal Nacional de Contratações Públicas](https://pncp.gov.br/).
