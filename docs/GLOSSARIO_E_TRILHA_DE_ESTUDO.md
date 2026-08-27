# Glossário e trilha de estudo

Este documento traduz os termos que aparecerão durante o projeto. Você não precisa dominar todos antes de começar. Use a coluna “o que pesquisar” quando um termo surgir na implementação.

## Coleta e comunicação com a fonte

| Termo | Explicação direta | Por que importa aqui | O que pesquisar |
|---|---|---|---|
| API | Interface oferecida por um sistema para outro programa pedir ou enviar dados de forma definida. | É o caminho preferencial para consultar o PNCP. | `o que é API REST` |
| Endpoint | Uma operação ou endereço específico da API. | Contratos, contratações e atas possuem operações diferentes. | `endpoint API exemplo` |
| Cliente/SDK | Biblioteca que esconde detalhes de HTTP e oferece métodos Python. | O `pypncp` é o cliente usado pelo sincronizador. | `API client SDK Python` |
| HTTP | Protocolo usado nas requisições e respostas da web. | Códigos 200, 429 e 500 indicam resultados e falhas diferentes. | `HTTP status codes 200 429 500` |
| Scraping | Extração de dados de páginas ou respostas que não foram necessariamente criadas como API. | A palavra foi usada informalmente; nosso caminho principal será a API. | `web scraping versus API` |
| Crawler | Programa que descobre e percorre muitos endereços ou recursos. | O planejador percorre recursos e partições, mas não deve navegar sem limites. | `crawler architecture politeness` |
| Paginação | Divisão de muitos resultados em páginas menores. | Precisamos buscar página por página e confirmar cada uma. | `API pagination page size cursor` |
| Rate limit | Limite de requisições aceitas pela fonte em um período. | Excedê-lo pode gerar HTTP 429 ou prejudicar o serviço. | `API rate limiting 429 Retry-After` |
| Timeout | Tempo máximo de espera por conexão ou resposta. | Uma chamada travada não pode parar toda a carga. | `connect timeout read timeout` |
| Retry | Nova tentativa após uma falha recuperável. | Ajuda em instabilidade temporária, mas precisa de limite. | `HTTP retry policy idempotent requests` |
| Backoff exponencial | Esperas progressivamente maiores entre tentativas. | Evita atacar uma API que já está falhando. | `exponential backoff example` |
| Jitter | Pequena aleatoriedade acrescentada à espera. | Evita vários workers repetirem juntos no mesmo instante. | `exponential backoff jitter` |
| Concorrência | Várias tarefas avançam no mesmo intervalo, muito útil enquanto aguardam rede. | O `pypncp` é assíncrono e oferece prefetch. | `Python asyncio concurrency` |
| Paralelismo | Trabalho realmente executado ao mesmo tempo em vários núcleos ou processos. | Pode ajudar normalização ou embeddings pesados, mas não é sinônimo de `asyncio`. | `concurrency versus parallelism` |
| Prefetch | Baixar a próxima página enquanto a atual ainda é processada. | Acelera a coleta, porém exige cancelamento e controle de memória. | `async prefetch bounded queue` |
| Backpressure | Mecanismo que desacelera o produtor quando o consumidor está cheio. | Impede downloads de ocuparem toda a memória enquanto o banco grava. | `backpressure producer consumer queue` |

## Pipeline e sincronização

| Termo | Explicação direta | Por que importa aqui | O que pesquisar |
|---|---|---|---|
| Ingestão | Entrada de dados externos no nosso sistema. | É o trabalho principal do sincronizador. | `data ingestion pipeline` |
| Pipeline | Sequência de etapas que transforma dados. | Coleta, preservação, normalização, banco e vetores formam o pipeline. | `data pipeline architecture` |
| ETL | Extrair, transformar e depois carregar no destino. | Descreve a normalização antes da tabela final. | `ETL extract transform load` |
| ELT | Extrair, carregar o bruto e transformar depois. | Preservar JSON bruto aproxima o projeto de ELT. | `ETL versus ELT` |
| Batch/lote | Grupo de registros processado em conjunto. | Escrever lotes tende a ser mais rápido do que um registro por vez. | `database batch insert performance` |
| Streaming | Processar continuamente conforme dados chegam. | O projeto começa em lotes; não precisamos de streaming real agora. | `batch versus streaming data` |
| Backfill | Carga histórica de dados anteriores. | Será a parte longa de popular o banco. | `historical data backfill` |
| Sincronização incremental | Buscar apenas novidades e atualizações após a carga histórica. | Mantém o espelho útil sem baixar tudo diariamente. | `incremental data load pattern` |
| Janela | Intervalo de tempo usado numa unidade de consulta. | Janelas pequenas isolam falhas e controlam volume. | `time window data ingestion` |
| Overlap | Reconsulta intencional de um trecho já coberto. | Ajuda a capturar publicações atrasadas ou retificadas. | `incremental load overlap window` |
| Cursor | Informação que indica de onde continuar. | Pode ser página, data, token ou identificador. | `cursor pagination checkpoint` |
| Watermark | Maior ponto temporal confirmado como processado. | Ajuda a planejar a próxima atualização, com uma margem de overlap. | `high watermark incremental load` |
| Checkpoint | Registro durável do trabalho já confirmado. | Permite retomar sem reiniciar toda a carga. | `data pipeline checkpointing` |
| Unidade de trabalho | Menor partição que pode ser executada, repetida e auditada isoladamente. | Nossa unidade inclui recurso, janela, modalidade e página. | `work queue durable jobs` |
| Idempotência | Repetir uma operação produz o mesmo estado final. | É o requisito que impede duplicatas após retry ou retomada. | `idempotent data ingestion` |
| Deduplicação | Identificar e tratar registros repetidos. | É consequência das sobreposições e reexecuções. | `data deduplication business key` |
| Reconciliação | Comparar fonte e destino para detectar diferenças. | Ajuda a descobrir lacunas, retificações e contagens divergentes. | `data reconciliation source target` |
| CDC | Captura de alterações feita a partir do log ou eventos de um banco de origem. | É útil conhecer, mas não controlamos o banco do PNCP; usaremos endpoints de atualização. | `change data capture CDC` |

## Banco de dados

| Termo | Explicação direta | Por que importa aqui | O que pesquisar |
|---|---|---|---|
| Banco relacional | Organiza registros em tabelas ligadas por chaves. | Contratações, itens, resultados e órgãos têm relações claras. | `relational database fundamentals` |
| Esquema/schema | Definição de tabelas, colunas, tipos, restrições e relações. | Evita transformar tudo em JSON difícil de consultar. | `database schema design` |
| Chave primária | Identificador único interno de uma linha. | Liga tabelas com eficiência. | `primary key database` |
| Chave estrangeira | Campo que referencia uma linha de outra tabela. | Liga item à contratação e unidade ao órgão. | `foreign key referential integrity` |
| Chave natural/de negócio | Identificador que já existe no domínio ou na fonte. | Permite reconhecer o mesmo registro em outra execução. | `natural key business key` |
| Restrição única | Regra que proíbe duas linhas com a mesma identidade. | É uma defesa concreta contra duplicação. | `SQL unique constraint` |
| Transação | Grupo de mudanças confirmado inteiro ou desfeito inteiro. | O checkpoint não pode confirmar uma página gravada pela metade. | `database transaction commit rollback` |
| ACID | Propriedades que tornam transações confiáveis. | Ajuda a raciocinar sobre falha, consistência e concorrência. | `ACID database explained` |
| Upsert | Inserir quando não existe ou atualizar quando já existe. | Trata registros repetidos e retificados. | `PostgreSQL ON CONFLICT upsert` |
| Índice B-tree | Estrutura comum para acelerar igualdade, intervalos e ordenação. | Serve para CNPJ, datas, chaves e vários filtros exatos. | `PostgreSQL B-tree index` |
| Índice invertido/full-text | Estrutura que liga palavras aos documentos onde aparecem. | Atende busca lexical por termos. | `PostgreSQL full text search GIN` |
| Normalização de banco | Separação de entidades para reduzir repetição e inconsistência. | Evita repetir todos os dados do órgão em cada item. | `database normalization 1NF 2NF 3NF` |
| Desnormalização | Repetição intencional para simplificar ou acelerar leitura. | Pode ser útil depois de medir consultas, não como padrão inicial. | `database denormalization tradeoffs` |
| Migração | Mudança versionada do esquema. | O formato evoluirá sem perder o banco já carregado. | `database schema migrations Python` |
| Schema drift | Mudança inesperada nos campos ou tipos da fonte. | Uma API externa pode adicionar, remover ou alterar campos. | `schema drift API data pipeline` |
| Staging | Área intermediária antes das tabelas finais. | Isola coleta de normalização e facilita reprocessamento. | `staging tables ETL` |
| JSONB | Tipo do PostgreSQL para armazenar e consultar JSON binário. | É candidato para preservar payloads brutos. | `PostgreSQL JSONB` |
| Carga em massa | Mecanismos eficientes para inserir muitos registros. | Pode reduzir o tempo do backfill após medição. | `PostgreSQL COPY bulk loading` |
| WAL | Log de alterações do PostgreSQL usado para recuperação e replicação. | Grandes cargas também geram WAL e consomem disco. | `PostgreSQL write ahead log WAL` |
| Particionamento | Divisão lógica/física de uma tabela grande. | Pode ajudar por período, mas aumenta complexidade e só entra com evidência. | `PostgreSQL table partitioning` |

## Qualidade, operação e segurança

| Termo | Explicação direta | Por que importa aqui | O que pesquisar |
|---|---|---|---|
| Observabilidade | Capacidade de entender o estado interno por logs, métricas e rastros. | Precisamos saber se a carga está lenta, incompleta ou falhando. | `observability logs metrics traces` |
| Log | Registro de acontecimentos individuais. | Explica qual página falhou e por quê. | `structured logging Python` |
| Métrica | Medida numérica acompanhada no tempo. | Mostra registros por segundo, erros e filas. | `data pipeline metrics` |
| Trace/rastro | Encadeamento de etapas de uma operação. | Pode ligar requisição, normalização e gravação; é posterior ao MVP. | `distributed tracing concepts` |
| Procedência/lineage | Registro de onde veio o dado e como foi transformado. | Permite auditar um resultado até a resposta original. | `data lineage provenance` |
| Cobertura | Definição mensurável do que já foi processado. | “Banco completo” precisa de prova por recurso, período e modalidade. | `data completeness coverage metrics` |
| Qualidade de dados | Avaliação de completude, validade, consistência e unicidade. | A API pode devolver campos ausentes ou relações difíceis. | `data quality dimensions` |
| SLI | Medida observada do serviço, como taxa de sucesso ou atraso da sincronização. | Ajuda a medir operação sem prometer perfeição vaga. | `SLI SLO data pipeline` |
| SLO | Objetivo para uma métrica, como “99% das unidades concluídas”. | Só deve ser definido após termos linha de base. | `service level objective examples` |
| Segredo/credencial | Informação que concede acesso privilegiado. | O sincronizador público não deve pedir JWT de publicação do PNCP. | `secrets management application` |
| Dados pessoais | Informação relacionada a pessoa natural identificada ou identificável. | Mesmo dados públicos devem ser tratados com finalidade e necessidade. | `LGPD dados pessoais acesso público` |

## Busca vetorial e semântica

| Termo | Explicação direta | Por que importa aqui | O que pesquisar |
|---|---|---|---|
| Tokenização | Divisão do texto em unidades usadas pelo modelo. | Afeta limite, custo e forma de entrada do embedding. | `tokenization NLP explained` |
| Embedding | Vetor numérico que representa características semânticas do texto. | Permite buscar descrições de itens parecidas em sentido. | `text embeddings semantic search` |
| Dimensão | Quantidade de números no vetor. | Afeta armazenamento, compatibilidade e custo do índice. | `embedding vector dimensions` |
| Distância/similaridade | Função que mede proximidade entre vetores. | Define a ordem dos itens semelhantes. | `cosine similarity embeddings` |
| Similaridade do cosseno | Compara o ângulo entre vetores. | É uma medida comum para embeddings de texto. | `cosine similarity formula intuition` |
| KNN | Busca dos `k` vizinhos mais próximos. | É a operação conceitual da busca vetorial. | `k nearest neighbors vector search` |
| ANN | Busca aproximada dos vizinhos para ganhar velocidade. | Pode trocar um pouco de precisão por desempenho em grande volume. | `approximate nearest neighbor ANN` |
| Recall | Proporção dos vizinhos relevantes que a busca recuperou. | Um índice rápido pode omitir bons resultados; precisamos medir. | `vector search recall benchmark` |
| HNSW | Índice aproximado baseado em um grafo de vizinhança. | É uma opção oferecida pelo `pgvector`. | `pgvector HNSW` |
| IVFFlat | Índice aproximado que agrupa vetores em listas. | Outra opção do `pgvector`, com trade-offs diferentes. | `pgvector IVFFlat` |
| Busca híbrida | Combinação de filtros, texto e vetores. | Evita depender somente da semântica. | `hybrid search full text vector` |
| Re-ranking | Segunda ordenação mais cuidadosa sobre poucos candidatos. | Pode melhorar relevância numa fase avançada. | `semantic search reranking` |
| RAG | Técnica que recupera documentos antes de uma IA gerar uma resposta. | Pode usar o banco no futuro, mas não é necessário para criar o índice. | `retrieval augmented generation RAG` |
| Drift do modelo | Mudança de comportamento ou troca de versão do modelo. | Exige versionar e talvez regenerar embeddings. | `embedding model versioning drift` |

## Termos de engenharia de software usados no projeto

| Termo | Explicação direta | Por que importa aqui | O que pesquisar |
|---|---|---|---|
| Camada | Grupo de responsabilidades com uma fronteira clara. | CLI, aplicação, adaptadores e persistência não devem se misturar. | `layered architecture software` |
| Adaptador | Código que traduz um sistema externo para a linguagem interna. | Isola mudanças do `pypncp`, banco ou provedor de embedding. | `hexagonal architecture adapter` |
| Caso de uso | Operação que expressa uma intenção do produto. | Planejar, executar, retomar e verificar são casos de uso. | `clean architecture use case` |
| Injeção de dependência | Entregar uma dependência a um componente em vez de criá-la escondida. | Facilita trocar API real por falso em testes. | `dependency injection Python` |
| Teste unitário | Testa uma regra pequena isoladamente. | Ideal para janelas, chaves e normalização. | `Python unit testing pytest` |
| Teste de integração | Testa componentes juntos, como repositório e banco. | Prova transações, migrações e upserts. | `integration test database` |
| Teste de contrato | Verifica se uma integração ainda segue o formato esperado. | Detecta mudanças nos endpoints do PNCP. | `consumer contract testing API` |
| Benchmark | Medição reproduzível de desempenho. | Permite afirmar se uma correção no `pypncp` realmente acelerou. | `Python benchmark pyperf profiling` |
| Profiling | Medição de onde tempo e memória são consumidos. | Evita otimizar a parte errada. | `Python profiling cProfile py-spy` |
| Gargalo | Parte que limita o desempenho total. | Pode ser API, validação, banco, disco ou embeddings. | `performance bottleneck analysis` |

## Trilha de estudo ligada ao que construiremos

### Etapa 1 — compreender o caminho atual

Objetivo construível: fazer uma consulta pequena e desenhar cada etapa da resposta.

Estude:

1. API, endpoint, HTTP e paginação;
2. `async`/`await` e concorrência em Python;
3. métodos de contratos e contratações do `pypncp`;
4. códigos de erro e timeout;
5. diferença entre API oficial e endpoint interno.

Prova de aprendizado: explicar por que uma consulta pontual ainda não é um banco sincronizado.

### Etapa 2 — criar uma carga retomável

Objetivo construível: baixar uma janela pequena, interromper e continuar.

Estude:

1. unidade de trabalho;
2. checkpoint, cursor e watermark;
3. idempotência e deduplicação;
4. retry, backoff e jitter;
5. filas produtor-consumidor e backpressure.

Prova de aprendizado: desligar o processo depois de uma página e mostrar que a retomada não perde nem duplica registros.

### Etapa 3 — modelar o banco

Objetivo construível: consultar contratações, itens e resultados relacionados por SQL.

Estude:

1. tabelas, chaves primárias e estrangeiras;
2. chave de negócio e restrição única;
3. transação, commit e rollback;
4. `upsert` com `ON CONFLICT`;
5. normalização, staging, JSONB e migrações.

Prova de aprendizado: executar duas vezes a mesma carga e obter a mesma quantidade de entidades, com atualização dos registros alterados.

### Etapa 4 — medir e acelerar

Objetivo construível: aumentar vazão sem perder correção.

Estude:

1. logs estruturados e métricas;
2. profiling e benchmark;
3. inserção em lote e carga em massa;
4. limites de concorrência;
5. índices e planos de consulta.

Prova de aprendizado: apresentar comparação antes/depois com o mesmo conjunto de dados e as mesmas verificações de integridade.

### Etapa 5 — busca vetorial

Objetivo construível: encontrar itens semanticamente parecidos numa amostra.

Estude:

1. embeddings, dimensão e similaridade de cosseno;
2. busca exata KNN;
3. recall e conjunto de avaliação;
4. HNSW e IVFFlat;
5. busca híbrida e versionamento do modelo.

Prova de aprendizado: comparar resultados exatos e aproximados e explicar a troca entre latência, memória e recall.

## Perguntas que indicam boa compreensão do problema

- Qual é a chave estável deste recurso?
- Como provamos que uma partição foi completamente processada?
- O que acontece se o processo cair depois do download e antes do `commit`?
- Este erro pode ser tentado novamente ou o dado deve ser rejeitado?
- O endpoint é oficial e documentado?
- Aumentar workers acelera ou apenas pressiona API e banco?
- O resultado veio da fonte, de uma normalização ou de uma inferência?
- Qual modelo e qual texto geraram este vetor?
- Uma busca aproximada está omitindo quantos resultados relevantes?
- Qual métrica provará que a mudança foi uma melhoria?

Se soubermos responder essas perguntas com dados, estaremos tratando o projeto como engenharia de software e de dados, não apenas como um script grande.
