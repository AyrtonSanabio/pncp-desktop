# Complexidade, riscos e plano de execução

## Resposta curta sobre a dificuldade

Uma demonstração que grava algumas páginas é de complexidade média. Um sincronizador confiável que mantenha uma cópia ampla do PNCP é de complexidade alta. Incluir todos os recursos, atualizações contínuas, operação simples, auditoria e índice vetorial em grande volume torna o produto de complexidade muito alta.

O código HTTP não é a parte mais difícil. A dificuldade está em saber o que já foi coberto, continuar após falhas, não duplicar, perceber mudanças da fonte, preservar procedência e operar durante muito tempo.

## O que “zero complexidade” pode significar

Não significa complexidade computacional `O(1)` nem ausência de configuração interna. Significa reduzir a complexidade acidental para quem usa:

- instalar de maneira guiada;
- escolher onde armazenar;
- iniciar e retomar com poucos comandos;
- usar limites seguros por padrão;
- enxergar progresso e espaço necessário;
- receber mensagens compreensíveis;
- não precisar conhecer paginação, retries, SQL ou embeddings.

A engenharia existe justamente para o usuário não precisar coordená-la manualmente.

## Matriz de complexidade

| Subsistema | Complexidade | Motivo principal |
|---|---|---|
| Consulta de uma página | Baixa | O `pypncp` já encapsula requisição e modelos. |
| Percorrer páginas de uma janela | Média | Envolve paginação, timeout e volume variável. |
| Planejar todos os períodos/modalidades | Média | Precisa dividir cobertura e evitar lacunas. |
| Retomada após interrupção | Alta | Checkpoint e transação precisam concordar. |
| Idempotência e retificações | Alta | Depende de chaves de negócio corretas por recurso. |
| Modelagem relacional completa | Alta | Muitos recursos e relações podem ser opcionais. |
| Itens e resultados em escala | Alta | Podem exigir chamadas adicionais por contratação. |
| Carga histórica completa | Muito alta | Tempo, falhas, armazenamento e auditoria se acumulam. |
| Atualização incremental confiável | Alta | Exige overlap, reconciliação e atraso conhecido. |
| Detectar exclusões | Muito alta | Ausência numa resposta não é prova suficiente. |
| Otimização do `pypncp` | Média a alta | Precisa de profiling e benchmark reproduzível. |
| Instalação local com PostgreSQL | Alta | Serviço, porta, dados, backup e atualização no Windows. |
| Geração de embeddings | Alta | Modelo, custo, versão, lote e reprocessamento. |
| Índice vetorial em grande volume | Alta | Memória, tempo de build, recall e filtros. |
| CLI simples | Baixa a média | Simples se os casos de uso internos estiverem corretos. |
| Interface final | Média a alta | Progresso, cancelamento e suporte aumentam o escopo. |
| Operação hospedada multiusuário | Muito alta | Segurança, isolamento, custos, disponibilidade e LGPD. |

## Principais desconhecidos

Antes de estimar prazo ou armazenamento, precisamos medir:

1. quantos registros e páginas existem por recurso, mês e modalidade;
2. quantas chamadas adicionais são necessárias para itens e resultados;
3. tamanho médio e máximo dos payloads;
4. taxa de respostas 429, 5xx e timeout em ritmo conservador;
5. quais identificadores são estáveis e únicos;
6. comportamento dos endpoints por atualização;
7. custo de reconsultar janelas de overlap;
8. velocidade de normalização e escrita em lote;
9. tamanho do banco com bruto, normalizado e índices;
10. quantidade, comprimento e idioma das descrições de itens;
11. custo e qualidade do modelo de embeddings;
12. memória e tempo para construir o índice vetorial.

O primeiro software útil será também um instrumento de medição.

## Fases de execução

### Fase 0 — inventário e linha de base

Objetivo: transformar suposições em uma tabela de capacidades verificadas.

Entregas:

- listar recursos e métodos atuais do `pypncp`;
- associar cada método ao endpoint oficial ou marcar como experimental;
- registrar parâmetros, paginação, identificadores e datas de atualização;
- executar amostras pequenas e salvar respostas anonimizadas quando necessário;
- medir latência, páginas, registros e bytes;
- definir a primeira chave de negócio candidata;
- escolher a menor fatia vertical.

Critério de saída:

- conseguimos explicar exatamente qual consulta inicia a fatia, como paginar e como identificar cada registro;
- nenhuma área experimental é dependência obrigatória da primeira carga.

### Fase 1 — fatia vertical retomável

Objetivo: provar o ciclo inteiro com contratações de um período curto e uma modalidade.

Entregas:

- comando para planejar a janela;
- tabelas de execução, unidade, payload e contratação;
- migração inicial do banco;
- coleta de páginas com timeout e retry limitados;
- armazenamento bruto e normalizado;
- checkpoint confirmado depois do `commit`;
- interrupção e retomada;
- relatório com contagens e cobertura;
- testes unitários e de integração.

Critério de saída:

- duas execuções da mesma janela produzem o mesmo conjunto lógico;
- uma interrupção simulada não gera lacuna ou duplicata;
- erros e rejeições aparecem no relatório.

### Fase 2 — itens e resultados

Objetivo: formar o conjunto que dará valor à busca semântica.

Entregas:

- confirmar o caminho oficial para obter itens e resultados;
- planejar dependências sem multiplicar requisições sem controle;
- tabelas e chaves de item e resultado;
- filas limitadas para detalhes;
- retomada independente de detalhes;
- consulta SQL da contratação até o fornecedor/resultado;
- métricas de chamadas adicionais por entidade.

Critério de saída:

- cada item possui vínculo auditável com a contratação;
- falha ao buscar um detalhe não marca falsamente a contratação inteira como completa;
- cobertura informa quantas contratações ainda não têm itens confirmados.

Decisão verificada em 27/08/2026: o Manual de Integração v2.5 documenta oficialmente
as operações `GET` para consultar itens e resultados. Portanto, a fase não depende da
busca interna de catálogo. O código deve continuar isolando essas consultas porque o
modelo `ResultadoItem` do `pypncp` 1.2.1 não aceita o objeto real retornado em
`localidadeFornecedor`.

### Fase 3 — contratos, atas e expansão histórica

Objetivo: ampliar recursos mantendo a mesma confiabilidade.

Entregas:

- adaptadores e normalizadores por recurso;
- chaves e migrações específicas;
- carga por publicação e por atualização;
- reconciliação de janelas concluídas;
- lotes e concorrência ajustados por medições;
- estimador de tempo e disco;
- política de backup e recuperação do banco.

Critério de saída:

- cada recurso possui definição de cobertura e relatório próprio;
- o programa pode pausar, reiniciar e continuar uma carga histórica prolongada;
- desempenho foi comparado com uma linha de base reproduzível.

### Fase 4 — sincronização contínua

Objetivo: manter o espelho atualizado depois do backfill.

Entregas:

- agenda incremental;
- watermarks e overlap configurados por recurso;
- reprocessamento periódico;
- alertas de atraso e falha;
- política para registros retificados;
- painel ou relatório de frescor.

Critério de saída:

- após parar por um período, o sistema recupera o atraso sem carga manual;
- a data de atualização e as lacunas são visíveis;
- reprocessar uma janela corrige mudanças sem duplicar entidades.

### Fase 5 — embeddings e busca vetorial

Objetivo: pesquisar itens semanticamente semelhantes sem perder filtros exatos.

Entregas:

- conjunto de avaliação manual com consultas e itens relevantes;
- texto de entrada padronizado e versionado;
- gerador de embeddings em lote com retomada;
- tabela de vetores ligada aos itens;
- busca exata como referência;
- experimento com HNSW e/ou IVFFlat;
- comparação de latência, armazenamento e recall;
- busca híbrida por texto, vetor e filtros.

Critério de saída:

- sabemos qual modelo gerou cada vetor;
- mudança de texto ou modelo invalida e regenera o vetor correto;
- o índice aproximado é comparado com busca exata;
- exemplos reais demonstram ganho sobre busca puramente lexical.

### Fase 6 — operação simples

Objetivo: aproximar o produto da promessa de “zero complexidade”.

Entregas possíveis:

- instalador ou ambiente conteinerizado;
- assistente de configuração;
- comandos `iniciar`, `status`, `pausar`, `retomar` e `atualizar`;
- estimativa de espaço antes do backfill;
- progresso e diagnóstico compreensíveis;
- backup e atualização guiados;
- interface gráfica preservada, adaptada ao banco local.

Critério de saída:

- uma pessoa que não conhece Python consegue instalar, iniciar uma fatia segura, acompanhar e resolver erros comuns com a documentação.

## Primeiro backlog técnico

Esta é a ordem recomendada para iniciar código depois da documentação:

1. criar o pacote `pncp_sync` sem acoplar à interface existente;
2. criar um comando `doctor` que verifique Python, dependência e conexão de banco;
3. criar migração com `ingestion_run`, `work_unit`, `source_payload` e `contratacao`;
4. implementar o planejador de um dia e uma modalidade;
5. implementar adaptador de uma página de `contratacoes.list_publicacao`;
6. persistir payload, registro normalizado e checkpoint na ordem correta;
7. produzir resumo da execução;
8. testar reexecução e falha entre etapas;
9. medir uma janela real pequena;
10. revisar os resultados antes de adicionar itens ou concorrência.

## Estratégia para melhorar desempenho

O desenvolvedor destacou que correções que deixem o `pypncp` mais rápido ajudam muito. O processo correto é:

```text
cenário reproduzível
    -> medição inicial
        -> profiling
            -> hipótese de gargalo
                -> alteração pequena
                    -> mesmos testes de correção
                        -> novo benchmark
```

Métricas mínimas do benchmark:

- intervalo, modalidade, endpoint e tamanho de página;
- versão do Python e do `pypncp`;
- prefetch/workers;
- número de requisições e registros;
- tempo total e latências;
- CPU, memória e erros;
- quantidade final e hash ou chaves do conjunto obtido.

Possíveis gargalos a investigar, sem assumir antecipadamente:

- espera de rede sequencial;
- excesso ou falta de prefetch;
- validação Pydantic repetida;
- criação e encerramento de clientes HTTP;
- conexões não reutilizadas;
- buffers de resultados fora de ordem;
- escrita registro a registro;
- índices demais durante backfill;
- chamadas de detalhes em padrão N+1;
- geração de embeddings sem lote.

Uma mudança só é melhoria quando mantém a correção, reduz uma métrica relevante e não aumenta de maneira perigosa a carga sobre o PNCP.

## Riscos e respostas

| Risco | Consequência | Resposta planejada |
|---|---|---|
| API indisponível | carga interrompida | retry limitado, checkpoint e retomada |
| Limite não documentado | 429 ou bloqueio | ritmo conservador, métricas e redução automática |
| Mudança de formato | normalização quebra | payload bruto, teste de contrato e versão do normalizador |
| Chave incorreta | duplicação ou fusão errada | inventário, restrição testada e reconciliação |
| Página confirmada cedo | lacuna silenciosa | checkpoint somente após persistência confirmada |
| Fila sem limite | falta de memória | backpressure e lotes limitados |
| Banco cresce além do disco | interrupção e corrupção operacional | estimativa, alerta, retenção e backup |
| Endpoint interno muda | itens/preços falham | isolamento experimental e caminho oficial primeiro |
| Embedding caro ou lento | índice incompleto | processo separado, lote, cache e versionamento |
| Índice aproximado perde relevância | resultados omitidos | conjunto de avaliação e comparação com busca exata |
| Dado público contém dado pessoal | risco de uso indevido | minimização, finalidade, controle de exportação e LGPD |
| Escopo cresce cedo | núcleo nunca fica confiável | melhorias futuras separadas e critérios de fase |

## Escolha inicial de banco

### SQLite

Bom para aprender, testar esquema e executar uma fatia local sem instalar serviço. Tem baixo atrito, mas uma carga longa com vários workers e busca vetorial integrada pode ultrapassar o objetivo da prova.

### PostgreSQL

É a hipótese para o produto completo porque oferece transações, concorrência, índices, JSONB, `upsert`, ferramentas de backup e extensões. A desvantagem é a operação: instalar e manter um servidor local aumenta a dificuldade para o usuário final.

### pgvector

Permite que o vetor permaneça ligado ao item no PostgreSQL e suporta busca exata e aproximada. Não elimina a necessidade de avaliar modelo, recall, memória e manutenção do índice.

Decisão recomendada:

- usar o primeiro experimento para validar as interfaces de persistência;
- se SQLite acelerar muito o aprendizado, aceitá-lo somente como backend de prova;
- não desenhar a carga completa supondo que um arquivo SQLite será a distribuição final;
- fazer uma prova com PostgreSQL cedo, antes de expandir o backfill.

Referências:

- [PostgreSQL — INSERT](https://www.postgresql.org/docs/current/sql-insert.html)
- [pgvector](https://github.com/pgvector/pgvector)

## O que pesquisar primeiro

### PNCP e `pypncp`

- `PNCP Manual API de Consultas`
- `PNCP swagger API consulta`
- `pypncp pagination prefetch`
- `PNCP contratação itens resultados endpoint`
- `PNCP data de atualização contratação`

### Ingestão confiável

- `idempotent data ingestion Python`
- `checkpoint transactional data pipeline`
- `asyncio bounded queue backpressure`
- `exponential backoff jitter Retry-After`
- `data reconciliation incremental load`

### PostgreSQL

- `PostgreSQL ON CONFLICT composite unique key`
- `PostgreSQL batch insert versus COPY`
- `PostgreSQL JSONB raw staging`
- `PostgreSQL indexing bulk load`
- `PostgreSQL EXPLAIN ANALYZE`

### Busca vetorial

- `text embeddings Portuguese procurement items`
- `pgvector exact search cosine distance`
- `pgvector HNSW versus IVFFlat`
- `vector search recall evaluation`
- `hybrid search PostgreSQL full text pgvector`

## Critério para chamar o banco de “completo”

Nunca será apenas uma frase de marketing. Uma versão deverá declarar:

```text
Fonte: PNCP
Recursos: ...
Período coberto: ...
Modalidades cobertas: ...
Última atualização confirmada: ...
Unidades concluídas: ...
Unidades parciais/falhas: ...
Registros rejeitados: ...
Itens sem detalhes: ...
Embeddings pendentes: ...
Versão do coletor e do esquema: ...
```

Enquanto houver falhas ou dependências não processadas, o software deve dizer “cobertura parcial” e mostrar onde estão as lacunas.

## Próxima decisão prática

## Feedback obrigatório de ações indisponíveis

Quando uma ação não puder ser executada, o controle deve comunicar isso visualmente e textualmente: ficar desabilitado com aparência distinta, apresentar dica explicando o motivo e atualizar o status da tela. Nenhum botão importante deve parecer clicável e simplesmente não produzir efeito. Após falhas recuperáveis, a interface deve indicar explicitamente se **Continuar** está disponível; após falhas definitivas, deve explicar que uma nova estimativa ou correção é necessária.

O melhor próximo passo é a Fase 0: criar o inventário executável e medir uma janela pequena de contratações. Ainda não devemos começar pela carga nacional nem pelo índice vetorial. Essa pequena prova revelará volume, chaves, formato, ritmo seguro e mudanças necessárias no `pypncp`.
