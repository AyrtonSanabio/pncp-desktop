# Espelho local do PNCP e busca vetorial

Este repositório nasceu como um protótipo de interface desktop. O foco ativo mudou: construir um sincronizador que use o `pypncp` para coletar dados públicos do Portal Nacional de Contratações Públicas (PNCP), manter um banco local atualizável e, em uma etapa posterior, permitir busca semântica sobre os itens das contratações.

O nome da pasta continua `pncp-desktop` para não quebrar caminhos existentes. A interface já implementada foi preservada como uma melhoria futura; ela não é o produto principal desta etapa.

## O problema que queremos resolver

O `pypncp` simplifica consultas à API, mas não cria nem mantém um banco completo. Nosso software deverá transformar consultas paginadas em uma carga confiável e repetível:

```text
API pública do PNCP
    -> pypncp
        -> coletor por períodos, modalidades e páginas
            -> dados brutos preservados
                -> validação e normalização
                    -> banco relacional
                        -> índice textual e vetorial dos itens
                            -> CLI, API ou interface simples
```

Embora a conversa use a palavra “scraper”, o caminho principal será consumir APIs públicas. Extração de páginas HTML só deve existir se algum dado necessário não estiver disponível em uma API permitida e estável.

## Estado atual

- pacote `pncp_sync` implementado sem acoplamento à interface antiga;
- CLI para planejar, executar, retomar, verificar e pesquisar contratações e detalhes;
- SQLite com migração, FTS5, payload bruto comprimido, dados normalizados e auditoria;
- carga por publicação, checkpoints por página, retomada e idempotência implementados;
- campos úteis ainda ignorados pelo modelo do `pypncp` preservados e normalizados;
- banco local carregado em segundo plano, sem bloquear a troca de abas;
- escolha persistente do arquivo SQLite e atualização incremental pela última execução;
- painel de cobertura, erros, rejeições, validações do `pypncp` e integridade do banco;
- fatia real de 94 contratações concluída e reexecutada sem duplicação;
- prova da Fase 2 com um item e seu resultado/fornecedor concluída e reexecutada;
- protótipo anterior da interface mantido no código e em `docs/melhorias-futuras/`;
- cobertura ampla de itens/resultados, contratos, atas, atualização incremental e índice
  vetorial ainda pendentes.

O `run.bat` abre a interface integrada, com as áreas Consulta online, Sincronização e
Banco local. A interface mostra estimativa, progresso, pausa/continuação, detalhes de
contratações, itens e fornecedores, além de pesquisa textual local.

## Executável para Windows

Com Python instalado apenas na máquina de desenvolvimento, gere o pacote portátil:

```powershell
.\build_exe.bat
```

O resultado é `dist\\ConsultaPNCP.exe`. Para distribuir, copie o executável para uma
pasta com permissão de escrita; o banco será criado em `data\\pncp.sqlite3` ao lado dele.
O usuário final não precisa instalar Python nem abrir um terminal.

## Executar a primeira fatia

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\pncp-sync.exe --db data/pncp.sqlite3 doctor
.\.venv\Scripts\pncp-sync.exe --db data/pncp.sqlite3 plan `
    --data-inicial 2026-08-26 --data-final 2026-08-26 --modalidade 12
```

O comando `plan` consulta somente a primeira página, informa volume, espaço e campos
não modelados e retorna um `run_id`. A carga só começa ao executar:

```powershell
.\.venv\Scripts\pncp-sync.exe --db data/pncp.sqlite3 run --run-id SEU_RUN_ID
```

Use `Ctrl+C` para interromper com segurança e `resume` para continuar. O checkpoint só
é confirmado na mesma transação que grava o payload e os registros normalizados.

Depois de concluir uma execução de contratações, itens e resultados podem ser planejados
sem fazer requisições:

```powershell
.\.venv\Scripts\pncp-sync.exe --db data/pncp.sqlite3 plan-details `
    --source-run-id SEU_RUN_ID --limit 1
.\.venv\Scripts\pncp-sync.exe --db data/pncp.sqlite3 run-details `
    --detail-run-id SEU_DETAIL_RUN_ID
```

O limite pequeno é intencional enquanto medimos a quantidade de itens e chamadas de
resultado por contratação.

## Primeiro recorte implementável

Antes de tentar baixar “o PNCP inteiro”, faremos uma fatia vertical pequena e verificável:

1. coletar contratações de um período curto e de uma modalidade;
2. preservar a resposta original e gravar registros normalizados;
3. salvar o ponto de continuação da carga;
4. interromper e retomar sem duplicar dados;
5. repetir a mesma carga e provar idempotência;
6. medir requisições, registros, erros, tempo e espaço em disco;
7. só depois incluir itens, resultados, contratos e atas;
8. criar embeddings e índice vetorial somente após os itens estarem completos e estáveis.

## Documentação principal

- [Visão do produto e definição do problema](docs/VISAO_DO_SINCRONIZADOR_PNCP.md)
- [Arquitetura do sincronizador e do banco](docs/ARQUITETURA_DO_SINCRONIZADOR.md)
- [Complexidade, riscos e plano de execução](docs/COMPLEXIDADE_E_PLANO_DE_EXECUCAO.md)
- [Dimensionamento, memória, busca vetorial e segurança](docs/DIMENSIONAMENTO_MEMORIA_TEMPO_E_SEGURANCA.md)
- [Implementação da Fase 1 e prova real](docs/IMPLEMENTACAO_FASE_1.md)
- [Implementação inicial da Fase 2: itens e resultados](docs/IMPLEMENTACAO_FASE_2.md)
- [Interface, atualização incremental, erros e validações](docs/INTERFACE_INCREMENTAL_ERROS_E_VALIDACOES.md)
- [Glossário e trilha de pesquisa](docs/GLOSSARIO_E_TRILHA_DE_ESTUDO.md)
- [Contexto completo para outra IA](docs/CONTEXTO_PARA_OUTRA_IA.md)
- [Política de somente leitura e credenciamento](docs/POLITICA_SOMENTE_LEITURA_E_CREDENCIAMENTO.md)
- [Como Python encontra a biblioteca pypncp](docs/COMO_PYTHON_ENCONTRA_PYPNCP.md)
- [Melhorias futuras e material preservado](docs/melhorias-futuras/README.md)

## Decisões já tomadas

- O software é estritamente de leitura: não publica, retifica ou exclui dados no PNCP.
- O `pypncp` será uma dependência e continuará em seu próprio repositório.
- Uma execução que falha deve poder ser retomada do último ponto confirmado.
- Reexecutar uma janela já processada não pode duplicar registros.
- O dado bruto, a origem e a data da coleta serão preservados.
- Velocidade será obtida com concorrência limitada, lotes e medições; nunca sobrecarregando a fonte.
- A busca vetorial complementará filtros exatos e busca textual; ela não substituirá o banco relacional.
- Outras APIs governamentais, novas bibliotecas e a interface final estão fora do foco atual e foram preservadas como melhorias futuras.

## Hipótese de tecnologia

Para uma prova local pequena, SQLite ainda pode ser útil. Para a base completa, a hipótese principal é PostgreSQL, com `pgvector` para a etapa semântica. Essa escolha só será fechada depois de medirmos volume, velocidade de escrita, custo do índice e forma de distribuição no Windows.

Referências técnicas iniciais:

- [Manuais oficiais do PNCP](https://www.gov.br/pncp/pt-br/pncp/manuais)
- [Dados Abertos do PNCP](https://www.gov.br/pncp/pt-br/acesso-a-informacao/dados-abertos)
- [PostgreSQL: INSERT e ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html)
- [pgvector: busca vetorial no PostgreSQL](https://github.com/pgvector/pgvector)

## Interface preservada

O protótipo gráfico existente ainda pode ser executado para estudo:

```powershell
.\run.bat
```

No Windows, também é possível abrir a pasta no Explorador de Arquivos e dar dois
cliques em `run.bat`. Na primeira execução, o lançador cria o ambiente virtual e
instala as dependências automaticamente. É necessário ter Python 3.12 ou mais recente.

Sua arquitetura e prévia estão em [Melhorias futuras — interface desktop](docs/melhorias-futuras/INTERFACE_DESKTOP_ARQUITETURA_E_DESAFIOS.md).
