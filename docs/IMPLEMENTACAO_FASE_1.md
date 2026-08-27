# Implementação da Fase 1 e prova real

## Estado do marco

A primeira fatia vertical do sincronizador está implementada para **contratações por
data de publicação e modalidade**. Ela usa a API pública de consulta, não solicita
credenciais e não contém operações de publicação, retificação ou exclusão.

O índice vetorial ainda não foi iniciado. Primeiro precisamos completar e estabilizar
itens e resultados, conforme a ordem definida no plano de execução.

## Fluxo implementado

```text
pncp-sync plan
    -> consulta a primeira página pelo pypncp
    -> captura e comprime o JSON original
    -> mede páginas, registros, bytes e disco livre
    -> cria execução e unidades PENDING

pncp-sync run/resume
    -> assume uma unidade com lease
    -> reutiliza o probe ou consulta uma página
    -> preserva o payload bruto com SHA-256
    -> normaliza cada registro de forma independente
    -> faz insert, update ou classifica como inalterado
    -> atualiza FTS5
    -> confirma payload, registros e checkpoint na mesma transação
```

Uma falha anterior ao `commit` não avança o checkpoint. Um registro inválido vai para
`data_rejection`, comprimido e com seu motivo, sem descartar os demais registros da
página.

## Componentes criados

| Componente | Responsabilidade |
|---|---|
| `pncp_sync.adapters.pypncp_source` | Usa `PNCPClient` e captura a resposta HTTP integral por um hook público do `httpx` |
| `pncp_sync.normalization.contratacoes` | Valida e normaliza a contratação sem apagar o JSON original |
| `pncp_sync.persistence` | Migração SQLite, transações, upsert, payloads, erros, rejeições e FTS5 |
| `pncp_sync.application.plan_sync` | Probe, estimativa e criação das unidades de trabalho |
| `pncp_sync.application.run_sync` | Execução sequencial, retomada, cancelamento e checkpoint |
| `pncp_sync.cli` | Operação por comandos compreensíveis e saída JSON |

SQLite foi adotado para esta prova local. A migração para PostgreSQL continua sendo
uma decisão posterior a medições maiores, não uma premissa desta fase.

## Campos adicionais ao modelo atual do pypncp

O `pypncp` 1.2.1 transforma a resposta em um modelo Pydantic com `extra="ignore"`.
O sincronizador captura o JSON antes dessa perda e normaliza campos úteis adicionais.

| Campo normalizado | Caminho na API | Utilidade |
|---|---|---|
| `data_encerramento_proposta` | `dataEncerramentoProposta` | Alertas de prazo e oportunidades ainda abertas |
| `situacao_compra_id/nome` | `situacaoCompraId/Nome` | Distinguir contratação divulgada, suspensa ou encerrada |
| `modo_disputa_id/nome` | `modoDisputaId/Nome` | Entender a dinâmica competitiva |
| `tipo_instrumento_codigo/nome` | `tipoInstrumentoConvocatorio*` | Identificar edital, aviso e outros instrumentos |
| `amparo_legal_*` | `amparoLegal` | Exibir código, nome e descrição da base legal |
| `data_inclusao` | `dataInclusao` | Separar inclusão, publicação e atualização |
| `data_atualizacao` | `dataAtualizacao` | Detectar alteração do registro na fonte |
| `link_sistema_origem` | `linkSistemaOrigem` | Acesso ao portal em que o processo é operado |
| `link_processo_eletronico` | `linkProcessoEletronico` | Acesso ao processo eletrônico quando informado |
| `justificativa_presencial` | `justificativaPresencial` | Contexto de procedimentos presenciais |
| `fontes_orcamentarias_json` | `fontesOrcamentarias` | Analisar origem orçamentária sem perder estrutura |
| `emenda_parlamentar_json` | `emendaParlamentar` | Preservar vínculo com emenda quando existir |
| `orgao_poder_id/esfera_id` | `orgaoEntidade.*` | Classificação institucional do comprador |
| `unidade_codigo` | `unidadeOrgao.codigoUnidade` | Identidade da unidade administrativa |
| `uf_nome`, `municipio_nome`, `codigo_ibge` | `unidadeOrgao.*` | Filtros territoriais e ligação futura com IBGE |
| `usuario_nome` | `usuarioNome` | Identificar a plataforma/usuário publicador informado pela fonte |
| estruturas sub-rogadas | `orgaoSubRogado/unidadeSubRogada` | Preservar casos em que outro órgão ou unidade assume o processo |

Campos estruturados importantes ficam em colunas pesquisáveis. Estruturas variáveis
permanecem em JSON canônico, e toda a página original fica em `source_payload` usando
gzip e SHA-256.

## Tabelas da primeira migração

- `ingestion_run`: execução, janela, estimativas e estado;
- `work_unit`: uma página retomável, tentativas, lease e métricas;
- `source_payload`: JSON original comprimido, procedência, parâmetros e hash;
- `contratacao`: representação normalizada e chave `numeroControlePNCP` única;
- `contratacao_fts`: índice textual local;
- `data_rejection`: registros não normalizados e seus motivos;
- `ingestion_error`: falhas classificadas como recuperáveis ou definitivas;
- `coverage`: páginas planejadas/processadas e data máxima observada.

Valores monetários são armazenados como texto decimal canônico. Isso evita introduzir
erro binário silencioso; estratégias numéricas de consulta serão medidas antes de uma
carga ampla.

## Comandos

```text
pncp-sync doctor
pncp-sync plan --data-inicial AAAA-MM-DD --data-final AAAA-MM-DD --modalidade N
pncp-sync run --run-id UUID
pncp-sync resume --run-id UUID
pncp-sync status --run-id UUID
pncp-sync verify --run-id UUID
pncp-sync search "termos" --limit 20
```

`plan` não popula o banco de domínio: ele salva somente o probe necessário para medir e
planejar. `run` reutiliza esse payload na página 1, evitando uma requisição duplicada.

## Prova controlada com o PNCP real

Medição realizada em 27/08/2026:

```text
período:       26/08/2026 a 26/08/2026
modalidade:    12 - Credenciamento
páginas:       10
registros:     94
bytes HTTP:    211.564
primeira execução:
    inseridos:     94
    rejeitados:     0
segunda execução:
    inseridos:      0
    atualizados:    0
    inalterados:   94
banco após as provas: 552.960 bytes
```

As duas verificações retornaram:

```text
payloads com hash inválido: 0
chaves de negócio duplicadas: 0
erros de chave estrangeira: 0
```

A execução foi pausada após a primeira página e retomada a partir da página 2, provando
o checkpoint. A segunda execução da mesma janela comprovou idempotência sobre dados
reais.

## Testes automatizados

A suíte cobre:

- campos extras e estruturas aninhadas;
- rejeição por ausência da chave oficial;
- migração do banco;
- pausa e retomada;
- payload de probe sem novo download;
- insert, update e classificação de inalterado;
- segunda execução idempotente;
- erro recuperável sem avanço falso;
- rejeição parcial auditável;
- integridade de payloads e chaves estrangeiras;
- busca FTS5;
- ausência de operações de manutenção no adaptador.

Resultado atual: **15 testes aprovados** e `ruff` sem ocorrências.

## Limites conhecidos

- somente contratações por publicação foram implementadas;
- a execução é sequencial e conservadora;
- o tamanho de página usado pelo método atual do `pypncp` é controlado pela API;
- respostas podem conter caracteres de substituição já presentes na fonte; o programa
  preserva o conteúdo e não tenta corrigi-lo silenciosamente;
- ainda faltam atualização incremental, reconciliação, itens, resultados, contratos,
  atas, documentos, embeddings e índice vetorial;
- o estimador é conservador e será calibrado com janelas maiores.

## Próximo marco

O próximo marco previsto é a Fase 2: confirmar a rota oficial de itens e resultados,
implementar unidades dependentes retomáveis e ligar cada item à contratação por chave
oficial. Só depois haverá dados adequados para experimentar embeddings.
