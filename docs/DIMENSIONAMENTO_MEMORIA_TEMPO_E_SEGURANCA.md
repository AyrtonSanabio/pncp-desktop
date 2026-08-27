# Dimensionamento, memória, busca vetorial e segurança

## Objetivo deste documento

Este documento consolida as decisões e estimativas discutidas para o sincronizador do PNCP:

- estimar volume, tempo, espaço e quantidade de arquivos antes da carga;
- baixar em lotes retomáveis, sem repetir registros já confirmados;
- distinguir espaço em disco de memória RAM;
- escolher uma estratégia de banco de dados;
- decidir quando e como criar um índice vetorial;
- usar concorrência sem sobrecarregar o PNCP ou o computador;
- reduzir memória e armazenamento sem destruir a capacidade de consulta;
- definir controles de segurança e procedência.

As estimativas quantitativas são referências de planejamento. Elas devem ser recalculadas por uma amostra da fonte antes de cada carga relevante.

## Escopo da medição de volume

Em uma medição experimental realizada em 26/08/2026, o endpoint público de contratos/empenhos foi consultado por período de publicação, usando páginas de até 500 registros quando aceitas pelo endpoint. O Manual da API de Consultas documenta o serviço `/v1/contratos`, paginação e os metadados de retorno. [Manual PNCP API Consultas](https://www.gov.br/pncp/pt-br/central-de-conteudo/manuais/versoes-anteriores/ManualPNCPAPIConsultasVerso1.0.pdf)

| Período | Registros retornados | Páginas de 500 |
|---|---:|---:|
| 2024 | 1.087.207 | 2.175 |
| 2025 | 2.023.344 | 4.047 |
| 01/01/2026–26/08/2026 | 1.376.047 | 2.753 |
| Total da amostra nacional | 4.486.598 | 8.975 |

Este total representa o recurso de contratos/empenhos para os períodos consultados. Não é o total de PCA, contratações, atas, itens, resultados ou documentos do PNCP. O número muda diariamente e não deve ser tratado como censo permanente.

Uma página de 500 registros retornou aproximadamente 849 KB em uma medição. Isso equivale a cerca de 1,7 KB de JSON por registro. O tamanho real varia conforme o texto e os campos presentes.

## Planejamento antes da carga

O programa deve executar uma etapa de pré-voo antes de iniciar uma carga longa:

1. Fazer uma primeira requisição válida para obter `totalRegistros` e `totalPaginas`.
2. Não assumir que todo endpoint aceita `tamanhoPagina=500`; validar o limite no Swagger e na resposta.
3. Baixar três a cinco páginas de amostra em pontos diferentes do intervalo.
4. Medir bytes recebidos, registros, latência e tempo de transformação.
5. Estimar tempo de escrita e espaço dos índices.
6. Verificar espaço livre e memória disponível.
7. Apresentar a estimativa ao usuário antes de confirmar a execução.

Fórmulas de planejamento:

```text
paginas = teto(totalRegistros / tamanhoPagina)

bytes_estimados = totalRegistros × bytes_médios_por_registro
                  + índices
                  + margem_de_segurança

tempo_estimado = paginas × latência_observada
                  + transformação
                  + gravação
                  + retries/checkpoints
```

É preferível usar a latência do percentil 95 da amostra, e não apenas a média.

### Estimativa de download

Para os 4.486.598 registros da amostra:

```text
4.486.598 / 500 = 8.975 páginas
```

| Latência média por página | Tempo de rede serial estimado |
|---:|---:|
| 1 segundo | aproximadamente 2h30 |
| 3 segundos | aproximadamente 7h30 |
| 5 segundos | aproximadamente 12h30 |
| 10 segundos | aproximadamente 25h |

Adicionar de 20% a 50% para gravação, validação, retries e checkpoints é uma margem inicial de planejamento, não uma garantia de desempenho.

### Quantidade de arquivos

Sem baixar PDFs, as respostas da API não precisam ser armazenadas como milhares de arquivos. A opção principal pode ser:

```text
pncp.db
pncp.db-wal   (durante o uso do WAL)
pncp.db-shm   (durante o uso do WAL)
```

O SQLite mantém arquivos auxiliares no modo WAL e executa checkpoints para transferir alterações ao arquivo principal. O WAL melhora a convivência entre leitura e escrita, mas existe apenas um escritor por vez. [SQLite WAL](https://www.sqlite.org/wal.html)

Se arquivos temporários forem desejados para recuperação, usar 50.000 registros por lote criaria aproximadamente 90 arquivos para a amostra de 4,48 milhões de registros. Não criar um arquivo por página: isso produziria quase 9.000 arquivos sem benefício proporcional.

## Sincronização incremental e retomável

O método recomendado é:

```text
consulta incremental
    + chave única do PNCP
    + upsert
    + checkpoint por lote
    + marca d’água de atualização
```

### Consulta incremental

Guardar a última `dataAtualizacao` confirmada e consultar somente alterações posteriores. O PNCP possui uma consulta específica de contratos e empenhos por data de atualização, criada para reduzir o volume de coleta. [Comunicado sobre consulta incremental](https://www.gov.br/pncp/pt-br/central-de-conteudo/comunicados/2025/no-03-25-implantacao-da-consulta-aos-contratos-e-empenhos-por-data-de-atualizacao-no-pncp)

Usar uma janela de sobreposição, por exemplo:

```text
última marca confirmada: 2026-08-26 18:00
próxima consulta: desde 2026-08-26 17:00
```

Os registros repetidos são absorvidos pela chave única e pelo upsert.

### Identidade e upsert

Quando confirmado pelo inventário do endpoint, `numeroControlePNCP` deve ser a chave de negócio. A operação deve ser:

```text
identificador inexistente       -> INSERT
identificador com atualização  -> UPDATE
identificador sem alteração    -> IGNORE
```

Nunca deduplicar somente por descrição, fornecedor, valor ou número local.

### Checkpoints

Registrar pelo menos:

```text
ingestion_run
work_unit
pagina
status
quantidade_de_registros
bytes_recebidos
hash_payload
finalizada_em
```

O checkpoint só pode ser confirmado depois do `commit` do lote. Se o programa for encerrado após o commit, a unidade pode ser ignorada; se for encerrado antes, ela deve ser repetida.

Não confiar somente no número da página para deduplicação. A chegada de novos registros pode deslocar o conteúdo das páginas. A chave oficial e a data de atualização são a proteção principal.

## Armazenamento dos dados

Estimativa de planejamento para contratos/empenhos, sem PDFs:

| Registros | JSON recebido | Banco normalizado com índices |
|---:|---:|---:|
| 100 mil | aproximadamente 170 MB | aproximadamente 250–400 MB |
| 1 milhão | aproximadamente 1,7 GB | aproximadamente 2,5–4 GB |
| 4,48 milhões | aproximadamente 7,6 GB | aproximadamente 11–18 GB |
| 10 milhões | aproximadamente 17 GB | aproximadamente 25–40 GB |

Os valores do banco incluem campos estruturados e índices comuns, mas não documentos binários.

Guardar também o JSON original acrescenta cerca de 7,6 GB para a amostra de 4,48 milhões de registros antes da compressão. Itens, resultados, termos e documentos de metadados aumentam o total; a quantidade precisa ser medida por recurso.

Arquivos PDF têm outra ordem de grandeza. Um documento médio de 500 KB para cada contrato equivaleria a aproximadamente 2,2 TB na amostra. Portanto, a primeira versão não deve baixar PDFs indiscriminadamente.

## Memória RAM versus espaço em disco

Um vetor ou registro persistido no banco ocupa disco. Ele não precisa ficar permanentemente na RAM do aplicativo.

Durante uma consulta, o banco pode:

1. ler páginas do arquivo;
2. manter algumas páginas no cache do banco ou do sistema operacional;
3. calcular distâncias somente nos candidatos;
4. devolver apenas os melhores resultados.

O sistema operacional pode manter páginas quentes na RAM e descartá-las quando necessário. Isso não equivale a carregar a base inteira em uma lista Python.

### Busca vetorial exata

Uma busca exata pode ler os vetores em lotes. Para 1.000 vetores de 768 dimensões `float32`:

```text
1.000 × 768 × 4 ≈ 3 MB de valores vetoriais
```

A memória pode ser limitada, mas a CPU e o disco trabalham mais porque muitos vetores precisam ser comparados.

### Índices aproximados

HNSW e IVFFlat guardam estruturas auxiliares para evitar comparar todos os vetores. O índice continua persistido, mas a construção e a consulta usam memória de trabalho.

- HNSW tende a consumir mais memória e oferece bom compromisso entre velocidade e recall.
- IVFFlat usa grupos e tende a consumir menos memória, mas precisa de treinamento e ajuste de probes.
- FAISS normalmente trabalha com índices residentes em RAM; isso é perigoso para um índice nacional grande em um desktop. [Diretrizes da FAISS](https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-an-index)
- pgvector mantém vetores no PostgreSQL, suporta busca exata e aproximada, HNSW, IVFFlat e tipos comprimidos. [Documentação do pgvector](https://github.com/pgvector/pgvector)

## Quantidade e custo dos vetores

O número de vetores deve acompanhar a unidade semântica, não a quantidade de campos:

| Estratégia | Quantidade de vetores esperada |
|---|---:|
| Piloto | 10 mil–100 mil |
| Contratações selecionadas | 100 mil–1 milhão |
| Contratos/empenhos nacionais, limite superior | até cerca de 4,5 milhões |
| Itens nacionais | 5–20 milhões ou mais, dependendo da média de itens |

Para vetores `float32` de 768 dimensões:

| Vetores | Espaço dos valores, sem índice |
|---:|---:|
| 100 mil | aproximadamente 307 MB |
| 1 milhão | aproximadamente 3,1 GB |
| 4,5 milhões | aproximadamente 13,8 GB |
| 10 milhões | aproximadamente 30,7 GB |

O índice e os metadados exigem espaço adicional.

### Redução do índice vetorial

- Usar 384 dimensões em vez de 768 reduz aproximadamente pela metade.
- `float16` usa aproximadamente metade do `float32`.
- `int8` usa aproximadamente um quarto, com possível perda de recall.
- Vetores binários usam muito menos espaço, mas são uma escolha de qualidade inferior até serem avaliados.
- Product Quantization reduz bastante o espaço, com perda controlada e necessidade de reclassificação.
- Deduplicar textos e armazenar um vetor por conteúdo único reduz armazenamento e custo de geração.
- Vetorizar primeiro itens e objetos mais relevantes, não todos os empenhos.

O índice vetorial deve ser regenerável. O banco relacional continua sendo a fonte principal.

## Tempo de consulta após a carga

Faixas iniciais de engenharia, não benchmark oficial:

| Operação | Tempo esperado com índices adequados |
|---|---:|
| Busca por identificador | poucos milissegundos a dezenas de ms |
| Filtro por CNPJ, UF e data | dezenas a centenas de ms |
| Busca textual FTS5 | dezenas a centenas de ms |
| HNSW com índice cabendo na memória | dezenas a centenas de ms |
| Busca exata sobre milhões de vetores | segundos ou mais |

O tamanho do banco não determina sozinho a latência. O que importa é o plano de execução, os índices, a quantidade de resultados e se o índice está no cache. Usar `EXPLAIN QUERY PLAN` ou o equivalente do banco durante os benchmarks.

## Banco recomendado

### Primeira fase: SQLite + FTS5

Para o aplicativo desktop, usar:

```text
SQLite
    + índices B-tree
    + FTS5 para objeto, fornecedor e órgão
    + payload bruto opcional e comprimido
```

É simples de distribuir, não exige servidor e atende à prova local. O arquivo pode conter milhões de registros, desde que a interface não tente carregar tudo de uma vez.

### Serviço multiusuário: PostgreSQL

Se o produto tornar-se um serviço centralizado, usar PostgreSQL para:

- concorrência de vários usuários;
- transações e upserts robustos;
- filtros e joins complexos;
- particionamento por ano ou recurso;
- JSONB e integração com `pgvector`.

DuckDB/Parquet pode existir como camada analítica para relatórios e exportações, mas não precisa ser o banco operacional principal.

## Threads e concorrência

Se “threads” significar threads de execução, elas já fazem parte da aplicação: [ConsultaThread](../src/pncp_desktop/ui.py) separa a consulta da interface e executa um loop assíncrono dentro de um `QThread`.

Para a ingestão futura, a arquitetura recomendada é:

```text
thread principal
    -> interface Qt

worker de ingestão
    -> HTTP assíncrono com 2–4 tarefas
    -> fila limitada de 2–4 páginas
    -> transformação
    -> um único escritor no SQLite

processos opcionais
    -> embeddings CPU-bound
```

Threads são úteis para I/O, como rede e arquivos. O GIL limita o ganho de threads para processamento pesado em Python; para embeddings CPU-bound, avaliar processos ou bibliotecas nativas. [Python threading](https://docs.python.org/3/library/threading.html)

Não permitir que dezenas de threads escrevam na mesma conexão SQLite. A concorrência deve ser limitada e o escritor deve aplicar lotes transacionais.

## Redução de memória durante a carga

O pipeline deve ser streaming:

```text
baixar página
    -> transformar
        -> gravar lote
            -> liberar objetos
```

Parâmetros iniciais:

```text
página HTTP: 100–500 registros
lote de banco: 1.000–5.000 registros
fila pendente: 2–4 páginas
embeddings: 32–128 textos
```

Evitar:

```python
todos = list(cliente.contratos.list_all(...))
```

A interface deve consultar páginas locais ou usar um modelo virtualizado. Não deve criar milhões de widgets.

## Compressão

Comprimir apenas o payload bruto é uma boa primeira opção:

```text
dados estruturados -> colunas normais e indexáveis
JSON original      -> gzip/zstd em tabela de armazenamento frio
```

Uma faixa preliminar para JSON repetitivo é reduzir 7,6 GB brutos para aproximadamente 2–4 GB, mas a decisão deve ser tomada após medir amostras reais.

Custos:

- compressão acrescenta CPU durante a carga;
- descompressão acrescenta CPU quando o JSON for consultado;
- payload comprimido não pode ser pesquisado diretamente por B-tree ou FTS5;
- manter colunas estruturadas e JSON comprimido duplica parte do conteúdo;
- gzip é simples e portátil;
- zstd normalmente oferece melhor equilíbrio, mas acrescenta dependência.

Não comprimir diretamente CNPJ, datas, valores, situações ou texto que precisa de FTS5. Se o usuário raramente abre o payload original, fazer descompressão sob demanda.

## Segurança da aplicação

### Fonte e rede

- manter a aplicação de consulta sem credenciais da API de manutenção do PNCP;
- verificar certificados TLS;
- nunca usar `verify=False`, `-k` ou equivalente em produção;
- configurar timeout, limite de tentativas e backoff;
- reagir a 429 reduzindo a concorrência;
- registrar a fonte, parâmetros, horário, status HTTP e hash do payload.

### Banco e entrada

- usar SQL parametrizado;
- nunca concatenar texto do usuário na consulta;
- validar datas, CNPJ, limites e ordenação;
- limitar intervalo máximo, páginas e espaço reservado;
- usar arquivos temporários em diretório controlado;
- realizar backup e teste de restauração;
- não compartilhar conexão SQLite de forma insegura entre threads.

Consultas parametrizadas são a principal defesa contra SQL injection. [OWASP SQL Injection](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)

### Documentos e URLs

Embora a primeira versão não baixe PDFs, o futuro módulo de documentos deve:

- permitir somente HTTPS;
- validar domínio e redirecionamentos;
- limitar tamanho e tipo de arquivo;
- impedir traversal de diretório;
- nunca executar o arquivo;
- abrir no visualizador padrão somente após gravá-lo com nome seguro;
- tratar conteúdo como não confiável.

Se o aplicativo buscar uma URL recebida de uma fonte externa, usar allowlist e validação para reduzir risco de SSRF. [OWASP SSRF](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)

### Exportação e dados pessoais

- proteger CSV contra fórmulas iniciadas por `=`, `+`, `-` ou `@`;
- não gravar tokens ou dados pessoais desnecessários nos logs;
- minimizar CPF, endereço e outros dados pessoais;
- proteger o arquivo local conforme o perfil de uso;
- informar fonte, data da consulta e possibilidade de atualização;
- distinguir dado oficial, dado normalizado e inferência do software.

CSV com conteúdo não confiável pode executar fórmulas em planilhas. [OWASP CSV Injection](https://owasp.org/www-community/attacks/CSV_Injection)

Se for usado um serviço externo para gerar embeddings, o texto das contratações será enviado a esse terceiro. A opção padrão deve ser modelo local ou consentimento explícito e documentação da finalidade.

### Responsabilidade jurídica e de produto

Esta é uma orientação de arquitetura e produto, não um parecer jurídico. O aplicativo de consulta não é uma certidão e não deve declarar automaticamente que uma empresa está habilitada, impedida, regular ou apta a contratar. A responsabilidade do projeto inclui preservar a procedência, a data e as limitações do dado apresentado, além de evitar que uma inferência seja confundida com decisão administrativa, habilitação, certidão ou parecer jurídico. A política completa, incluindo credenciamento, autenticação, LGPD e matriz de responsabilidades, está em [Política de somente leitura e credenciamento](POLITICA_SOMENTE_LEITURA_E_CREDENCIAMENTO.md).

## Critérios para a primeira implementação

Antes de criar o índice vetorial nacional, a carga deve provar:

- estimativa de volume antes da execução;
- progresso e cancelamento;
- retomada após encerramento forçado;
- segunda execução sem duplicação;
- atualização por data incremental;
- limite de memória observável;
- banco consultável durante ou após a carga;
- payload bruto recuperável;
- logs sem credenciais;
- benchmark de filtro SQL, FTS5 e busca vetorial;
- comparação da busca aproximada com busca exata;
- espaço de disco suficiente com margem.

## Ordem recomendada

```text
1. Carga em SQLite de uma janela curta
2. Estimador de espaço e tempo
3. Checkpoints e upsert
4. Consulta incremental
5. FTS5
6. Compressão do payload bruto
7. Itens e resultados
8. Amostra de embeddings
9. Índice HNSW/IVF medido
10. Expansão nacional
```

O objetivo não é manter todos os vetores na memória. O objetivo é criar uma fonte local consultável, com índices e lotes que mantenham RAM, disco, tempo e risco dentro de limites explícitos.
