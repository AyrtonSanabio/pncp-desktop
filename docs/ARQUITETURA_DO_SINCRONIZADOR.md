# Arquitetura do sincronizador do PNCP

## Objetivo da arquitetura

Construir um processo que possa coletar uma pequena janela ou anos de dados usando os mesmos componentes, sem depender de uma execução longa e perfeita. Queda de rede, reinício do computador, erro em um registro ou mudança temporária da API não podem obrigar o usuário a começar tudo de novo.

## Visão geral

```text
                        +--------------------------+
                        | CLI / painel de operação |
                        +------------+-------------+
                                     |
                                     v
+-----------+   +---------+   +------+-------+   +----------------+
| agenda de |-->| unidades|-->| orquestrador |-->| adaptador      |
| execução  |   | de carga|   | e checkpoints|   | pypncp / PNCP |
+-----------+   +---------+   +------+-------+   +--------+-------+
                                     |                    |
                                     |                    v
                                     |          API pública do PNCP
                                     v
                           +---------+----------+
                           | área bruta/staging |
                           +---------+----------+
                                     |
                                     v
                           +---------+----------+
                           | normalização e     |
                           | validação           |
                           +---------+----------+
                                     |
                  +------------------+------------------+
                  v                                     v
        +---------+----------+               +----------+---------+
        | banco relacional   |-------------->| embeddings e      |
        | e índices exatos   |               | índice vetorial   |
        +---------+----------+               +----------+---------+
                  |                                     |
                  +------------------+------------------+
                                     v
                           consultas / API / interface
```

## Componentes

### 1. CLI ou painel de operação

É a camada simples vista pelo usuário. No começo, uma CLI é suficiente:

```text
pncp-sync planejar --inicio 2025-01-01 --fim 2025-01-07
pncp-sync executar
pncp-sync status
pncp-sync retomar
pncp-sync verificar
```

Ela não deve conter regras de HTTP ou SQL. Apenas valida argumentos, chama casos de uso e apresenta progresso.

### 2. Planejador de carga

Transforma um pedido amplo em unidades pequenas de trabalho. Uma unidade inicial pode ser definida por:

```text
recurso + data inicial + data final + modalidade + página
```

Exemplo:

```text
contratacoes/publicacao | 2025-01-01 | 2025-01-01 | modalidade 1 | página 1
```

Contratações por publicação e atualização exigem modalidade no `pypncp`. Portanto, o planejador precisa percorrer todas as modalidades aceitas e registrar quais foram realmente processadas.

O tamanho da janela não deve ser fixado por intuição. Começamos com um dia, medimos páginas e duração e diminuímos ou aumentamos de acordo com o volume.

### 3. Orquestrador

Coordena o ciclo de uma unidade:

1. marca a unidade como em execução;
2. chama o adaptador da fonte;
3. persiste a resposta bruta;
4. valida e normaliza;
5. grava o lote em uma transação;
6. registra contagens e erros;
7. confirma o checkpoint somente depois do `commit`;
8. agenda detalhes dependentes quando necessário;
9. marca sucesso, falha recuperável ou rejeição de dado.

O checkpoint não pode avançar antes da transação. Caso contrário, uma queda entre “marcar página concluída” e “gravar registros” criaria uma lacuna silenciosa.

### 4. Adaptador do `pypncp`

É o único componente que conhece os métodos concretos da biblioteca. Ele traduz chamadas e modelos do `pypncp` para envelopes internos do sincronizador.

O `pypncp` já fornece:

- consultas de contratos por publicação e atualização;
- consultas de contratações por publicação e atualização;
- consultas de atas por publicação e atualização;
- acesso a um registro específico;
- paginação automática com `prefetch` concorrente;
- modelos Pydantic para as respostas.

Para a primeira versão durável, é preferível controlar a página explicitamente em vez de entregar toda a execução a `list_all*()`. A paginação automática é conveniente para consumo, mas o sincronizador precisa associar confirmação persistente a cada página. Depois poderemos propor ao `pypncp` ganchos de progresso, cancelamento seguro ou um iterador de páginas que preserve a ergonomia e exponha checkpoints.

A busca de catálogo do `pypncp` continua fora do caminho crítico. Entretanto, a revisão
do Manual de Integração v2.5 confirmou que as consultas `GET` de itens e resultados são
serviços oficiais documentados. O adaptador de detalhes usa somente essas duas operações
de leitura. Ele preserva o JSON antes da modelagem porque o `pypncp` 1.2.1 ainda possui
divergências de tipo em respostas reais, como `localidadeFornecedor`.

### 5. Área bruta ou staging

Cada resposta recebida precisa ser preservada antes ou junto da normalização. O envelope bruto deve conter:

- nome da fonte e endpoint lógico;
- parâmetros usados;
- instante da requisição e da resposta;
- status HTTP e identificador da execução;
- hash do conteúdo;
- versão do coletor e do normalizador;
- conteúdo JSON original;
- mensagem de erro, quando houver.

Opções a medir:

| Opção | Vantagem | Limite |
|---|---|---|
| JSON/JSONB no PostgreSQL | consulta e transação no mesmo banco | banco pode crescer rapidamente |
| arquivos JSON comprimidos | armazenamento bruto simples e barato | exige catálogo confiável no banco |
| combinação dos dois | flexibilidade | maior complexidade operacional |

Para a fatia inicial, JSONB no banco é a opção mais simples. Antes da carga histórica completa, mediremos se payloads comprimidos fora das tabelas relacionais são necessários.

### 6. Normalizador

Converte a representação da fonte em tabelas consultáveis sem apagar o original. Deve:

- validar tipos, datas e valores;
- aceitar campos opcionais;
- preservar identificadores oficiais;
- distinguir ausente de vazio e de zero;
- padronizar apenas o que possui regra clara;
- registrar rejeições sem abortar páginas inteiras;
- indicar a versão da regra usada;
- permitir reprocessar payloads antigos quando a regra mudar.

Normalizar não significa “melhorar” silenciosamente o dado oficial. Se o PNCP informa duas grafias diferentes para o mesmo órgão, a consolidação precisa ser explícita e auditável.

### 7. Repositórios de persistência

Encapsulam SQL e transações. Casos de uso não devem espalhar `INSERT` por todo o código. Precisaremos de operações em lote para:

- inserir novos registros;
- atualizar registros existentes;
- associar itens e resultados aos pais;
- registrar execução e checkpoints;
- armazenar rejeições;
- selecionar textos ainda sem embedding;
- atualizar a cobertura da carga.

PostgreSQL oferece `INSERT ... ON CONFLICT`, que permite inserir ou atualizar de forma atômica quando existe uma restrição única adequada. Essa é uma peça técnica do `upsert`, mas não resolve sozinha a idempotência: primeiro precisamos definir a chave correta.

Referência: [PostgreSQL — INSERT e ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html).

### 8. Gerador de embeddings

É um processo separado da coleta. Ele seleciona itens normalizados que ainda não possuem o vetor da versão atual do modelo.

Cada embedding deve registrar:

- identificador do item;
- texto exato enviado ao modelo;
- nome e versão do modelo;
- dimensão do vetor;
- instante de geração;
- hash do texto de entrada;
- estado e erro da tentativa.

Se a descrição de um item mudar ou trocarmos o modelo, o vetor antigo não pode fingir que continua atual. A combinação `(item, modelo, versão, hash do texto)` ajuda a controlar isso.

### 9. Consultas

O banco deverá oferecer três caminhos complementares:

- filtros estruturados: data, CNPJ, modalidade, UF, valor e identificador;
- busca textual: termos presentes em objeto ou descrição;
- busca vetorial: itens semanticamente semelhantes.

Uma busca híbrida pode filtrar por período e UF, recuperar candidatos textuais e vetoriais e então ordenar o conjunto. Similaridade vetorial isolada não deve decidir equivalência de produtos, fraude ou conformidade.

## Modelo de dados inicial

Os nomes finais dependerão do inventário dos endpoints, mas estas responsabilidades já são necessárias.

### Controle da ingestão

| Tabela conceitual | Finalidade |
|---|---|
| `ingestion_run` | uma execução do programa, com início, fim e versão |
| `work_unit` | partição rastreável por recurso, período, modalidade e página |
| `source_payload` | resposta original, hash, parâmetros e procedência |
| `ingestion_error` | falhas de rede, validação ou persistência classificadas |
| `data_rejection` | registro recebido, mas não normalizado, com motivo |
| `coverage` | intervalo e dimensão que foram confirmados como processados |

### Dados do domínio

| Tabela conceitual | Relação principal |
|---|---|
| `orgao` | entidade compradora |
| `unidade` | unidade pertencente ao órgão |
| `contratacao` | publicação identificada no PNCP |
| `item_contratacao` | item pertencente à contratação |
| `resultado_item` | resultado ou fornecedor ligado ao item |
| `contrato` | contrato ou empenho publicado |
| `ata` | ata de registro de preços |
| `documento` | metadado e localização de documento público |
| `item_embedding` | vetor e versão do modelo para um item |

Nem toda relação deve ser inferida por texto. Sempre que existir uma chave oficial, ela tem prioridade.

## Chaves e identidade

Uma tabela terá uma chave interna, geralmente numérica, e uma chave de negócio derivada da fonte. Exemplos candidatos incluem número de controle do PNCP ou combinações de CNPJ do órgão, ano e sequencial. O inventário precisa confirmar a estabilidade e a presença dessas chaves em cada endpoint.

Regras:

- guardar a chave original exatamente como recebida;
- criar restrição única para a identidade confirmada;
- nunca deduplicar somente por descrição, valor ou nome do órgão;
- guardar a referência ao payload que originou a versão atual;
- registrar `created_at`, `updated_at` local e data de atualização da fonte separadamente;
- não usar hash do JSON completo como única identidade, pois uma retificação altera o hash do mesmo registro lógico.

## Estados de uma unidade de trabalho

```text
PENDING -> RUNNING -> SUCCEEDED
                 \-> RETRY_WAIT -> RUNNING
                 \-> FAILED
                 \-> PARTIAL
```

- `PENDING`: planejada e ainda não iniciada.
- `RUNNING`: um worker assumiu a unidade.
- `RETRY_WAIT`: falha temporária; pode ser tentada depois.
- `PARTIAL`: alguns registros foram rejeitados ou dependências falharam.
- `FAILED`: excedeu a política de tentativas ou encontrou erro não recuperável.
- `SUCCEEDED`: dados e métricas foram confirmados na mesma fronteira transacional adequada.

Uma unidade abandonada em `RUNNING` precisa voltar a ser elegível após expirar um bloqueio, pois o processo pode ter encerrado abruptamente.

## Carga histórica e atualização incremental

### Carga histórica

Percorre períodos antigos em janelas controladas. Deve começar por um recurso e uma modalidade, medir e expandir progressivamente.

### Atualização incremental

Usa endpoints por data de atualização quando disponíveis. O cursor não deve ser simplesmente “último segundo visto”. É prudente reconsultar uma pequena janela anterior, porque atrasos de publicação e diferenças de relógio podem fazer registros chegarem depois.

Exemplo conceitual:

```text
última atualização confirmada: 2026-08-26 18:00
próxima consulta: desde 2026-08-25 18:00
```

O overlap gera registros repetidos; a idempotência deve absorvê-los.

### Reconciliação

Periodicamente, uma janela já concluída deve ser reprocessada e comparada. Isso ajuda a detectar retificações, mudanças de quantidade e lacunas. Exclusões são mais difíceis: ausência em uma listagem não prova imediatamente que o registro foi removido. Precisaremos definir uma política de confirmação.

## Concorrência, limites e backpressure

O coletor passa grande parte do tempo esperando rede, por isso concorrência assíncrona pode acelerar a carga. Porém, “mais workers” não significa crescimento linear de velocidade.

Controles obrigatórios:

- limite global de requisições simultâneas;
- limites menores para endpoints sensíveis;
- fila limitada entre download e escrita;
- timeouts de conexão e leitura;
- tentativas apenas para erros recuperáveis;
- espera exponencial com aleatoriedade;
- respeito ao `Retry-After` quando fornecido;
- redução automática de ritmo em 429 e erros persistentes;
- configuração segura como padrão.

Backpressure significa impedir que o downloader produza milhares de payloads na memória enquanto o banco grava lentamente. Uma fila limitada faz o coletor esperar quando o consumidor está cheio.

## Desempenho de escrita

O caminho de otimização será:

1. medir inserções individuais para estabelecer a linha de base;
2. agrupar registros em lotes;
3. reduzir conversões repetidas;
4. usar transações com tamanho controlado;
5. avaliar mecanismos de carga em massa;
6. criar índices necessários, mas evitar índices prematuros durante grandes backfills;
7. medir `upsert`, contenção, uso de CPU, memória, disco e WAL;
8. otimizar somente o gargalo observado.

Não devemos aumentar concorrência HTTP se o gargalo real for normalização, escrita ou índice.

## Índice vetorial

A hipótese principal é usar PostgreSQL com a extensão `pgvector`, mantendo relacionamentos e vetores no mesmo banco. A extensão suporta busca exata e índices aproximados como HNSW e IVFFlat. A escolha depende de volume, memória, tempo de construção e qualidade de recuperação.

O primeiro experimento deve:

1. selecionar uma amostra conhecida de itens;
2. definir um texto de entrada reproduzível;
3. gerar embeddings com versão registrada;
4. começar por busca exata para formar referência;
5. medir latência e relevância;
6. só então criar um índice aproximado;
7. comparar os resultados aproximados com a referência exata.

Referência: [pgvector](https://github.com/pgvector/pgvector).

## Observabilidade

Cada execução deve produzir, no mínimo:

- unidades planejadas, concluídas, parciais e falhas;
- páginas e registros recebidos;
- registros inseridos, atualizados, ignorados e rejeitados;
- requisições por endpoint e código HTTP;
- latência da API e tempo de gravação;
- tamanho da fila e quantidade de tentativas;
- bytes recebidos e crescimento estimado do banco;
- data máxima de atualização da fonte por recurso;
- quantidade de itens sem embedding ou com embedding antigo.

Logs contam acontecimentos. Métricas permitem enxergar tendência. O relatório de cobertura responde o que efetivamente está presente.

## Estrutura de código sugerida

```text
src/pncp_sync/
    cli.py
    config.py
    application/
        plan_sync.py
        run_sync.py
        resume_sync.py
        verify_coverage.py
    domain/
        work_unit.py
        ingestion_run.py
        coverage.py
        errors.py
    adapters/
        pypncp_source.py
        embeddings.py
    normalization/
        contratacoes.py
        itens.py
        contratos.py
        atas.py
    persistence/
        models.py
        repositories.py
        migrations/
    observability/
        logging.py
        metrics.py
tests/
    unit/
    integration/
    contract/
```

A estrutura é uma proposta, não uma obrigação. Ela separa regras do sincronizador, dependências externas e persistência para que possamos testar cada parte.

## Testes necessários

### Unitários

- criação de unidades por intervalo e modalidade;
- classificação de erros recuperáveis;
- normalização de campos opcionais;
- cálculo de chaves;
- decisão de inserir, atualizar ou ignorar;
- cálculo de janelas de overlap.

### Integração local

- migrações do banco;
- transação e `upsert` em lote;
- retomada após simular encerramento;
- dois workers não assumirem a mesma unidade;
- reprocessamento do payload bruto;
- invalidação de embedding quando o texto muda.

### Contrato com a fonte

- pequena consulta real por endpoint oficial;
- presença e tipo dos campos essenciais;
- paginação e metadados;
- comportamento de intervalos vazios;
- resposta a parâmetros inválidos e limite de página.

Testes de contrato devem ser poucos e controlados para não transformar a suíte em carga sobre o PNCP.

## Contribuições possíveis ao `pypncp`

O sincronizador poderá revelar melhorias úteis à biblioteca original:

- iterador de páginas que exponha metadados e número da página;
- callbacks ou eventos de progresso;
- encerramento e cancelamento seguro de tarefas de prefetch;
- instrumentação opcional de latência, tentativas e códigos HTTP;
- política configurável de concorrência e rate limit;
- testes de contrato dos endpoints oficiais usados em cargas;
- benchmarks reproduzíveis de paginação;
- redução de alocações ou validações repetidas comprovada por perfil de desempenho.

Cada contribuição deve ser pequena, medida e acompanhada de teste. O fato de o sincronizador precisar de um recurso não significa que toda a lógica do banco deva entrar na biblioteca.

## Decisões que ainda dependem de experimento

- PostgreSQL desde a primeira fatia ou SQLite apenas para a prova local;
- tamanho inicial das janelas e páginas;
- representação do payload bruto;
- número seguro de requisições concorrentes;
- mecanismos de carga em massa;
- forma oficial de obter todos os itens e resultados;
- tratamento de documentos e arquivos grandes;
- algoritmo e parâmetros do índice vetorial;
- modelo de embeddings, custo e execução local ou remota;
- distribuição local no Windows versus serviço centralizado.

As respostas virão de inventário, testes controlados e métricas, não de adivinhação.
