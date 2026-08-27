# Contexto completo para continuar este projeto com outra IA

> Este arquivo foi escrito para ser copiado integralmente em outra conversa. Ele reúne o histórico, as decisões, o estado real do código e o próximo problema a resolver. Não trate ideias futuras como funcionalidades já implementadas.

## Instrução inicial para a outra IA

Você está ajudando a continuar um projeto brasileiro, em português, no Windows/PowerShell. Leia este documento antes de propor código. Preserve o trabalho existente, não apague o protótipo nem reintroduza no foco ativo as ideias arquivadas. Diferencie sempre:

- o que já foi verificado no código;
- o que é uma hipótese de arquitetura;
- o que ainda precisa ser medido na API do PNCP;
- o que é uma melhoria futura;
- o que ainda não foi implementado.

O sincronizador confiável já possui fatias funcionais para contratações por publicação e para itens/resultados. O próximo objetivo é ampliar a Fase 2 de uma contratação para uma amostra pequena, medir chamadas e latência e então fechar a cobertura da janela. Não comece pela interface final, por outras APIs governamentais ou pelo índice vetorial em grande escala.

## 1. Perfil e forma de colaboração

- O usuário é brasileiro e trabalha principalmente em português, Windows e PowerShell.
- Ele está aprendendo Python, Git, arquitetura, bancos de dados e engenharia de software.
- Prefere explicações claras, progressivas e ligadas a algo que possa construir.
- Quando pedir implementação, deve-se concluir e validar uma funcionalidade por vez.
- Alterações destrutivas não devem ser feitas sem confirmação.
- Não criar commit automaticamente; mostrar o estado e deixar a decisão para o usuário, salvo pedido explícito.
- Explicar comandos e erros em linguagem simples, sem esconder os termos técnicos.
- Ao sugerir melhorias de desempenho, medir primeiro e comparar depois.

## 2. Como chegamos até aqui

### 2.1 Descoberta do `pypncp`

O usuário clonou do GitHub o repositório da biblioteca `pypncp` para o computador. O caminho real encontrado no Windows é:

```text
C:\Users\admin\Desktop\software_prefeitura\pypncp
```

O nome correto da pasta é `software_prefeitura` (com sublinhado), não um caminho escrito como `software\_prefeitura` ou `_prefeitura` separado. Ao diagnosticar caminhos, confirmar sempre com `Get-ChildItem` ou `Resolve-Path`.

O repositório clonado contém, entre outros:

```text
src/pypncp/client.py
src/pypncp/models.py
src/pypncp/resources/contratos.py
src/pypncp/resources/contratacoes.py
src/pypncp/resources/atas.py
src/pypncp/resources/search.py
src/pypncp/resources/precos.py
docs/quickstart.md
docs/pagination.md
docs/resources/*.md
exemplo.py
pyproject.toml
tests/
```

### 2.2 Erros que já foram explicados

O usuário executou a instalação no diretório pai e recebeu:

```text
ERROR: file:///C:/Users/admin/Desktop/software_prefeitura does not appear to be a Python project: neither 'setup.py' nor 'pyproject.toml' found.
```

O motivo é que `pip install -e .` significa “instale o projeto representado pela pasta atual”. A pasta pai não era um projeto Python; o `pyproject.toml` estava dentro do repositório correto, `...\software_prefeitura\pypncp`.

Também houve tentativa de executar:

```powershell
..\.venv\Scripts\python.exe .\exemplo.py
```

e o Python informou que não encontrou o arquivo. O diagnóstico correto é verificar a combinação de diretório atual, caminho do interpretador e existência de `exemplo.py`; não assumir que o arquivo está no diretório corrente. No clone confirmado, `exemplo.py` existe em `C:\Users\admin\Desktop\software_prefeitura\pypncp\exemplo.py`.

O usuário também perguntou se o código foi feito por IA. A conclusão foi que não é possível provar autoria só pela leitura; no máximo podem ser observados sinais de estilo, inconsistências e histórico Git. Isso não é uma funcionalidade nem uma premissa do projeto atual.

### 2.3 Entendimento inicial da biblioteca

O `pypncp` foi entendido como uma biblioteca/cliente Python assíncrono para a API pública de consultas do Portal Nacional de Contratações Públicas. Ele pode ser instalado como dependência de outro software, em vez de ser copiado para dentro dele.

O computador encontra a biblioteca porque a instalação coloca o pacote no ambiente Python (`site-packages`) ou cria uma instalação editável que aponta para a pasta do código. O GitHub é a hospedagem do código-fonte; o PyPI, quando há publicação, é o canal usual de instalação de uma versão empacotada. Esse assunto está explicado em [Como Python encontra a biblioteca pypncp](COMO_PYTHON_ENCONTRA_PYPNCP.md).

### 2.4 Criação do projeto derivado

Foi criado um repositório separado em:

```text
A:\Projetos\pncp-desktop
```

Ele não copia o `pypncp`. A ideia é consumir a biblioteca como dependência e manter o software derivado separado, para que dependências de interface ou banco não sejam misturadas à biblioteca original.

O projeto inicialmente foi pensado como uma interface desktop em PySide6 para pessoas que não usam Python ou terminal. Foi implementado um protótipo com filtros, consulta real de uma página de contratos, thread separada, cancelamento, tratamento amigável de timeout, modo de demonstração, tabela e exportação CSV.

### 2.5 Mudança de foco após a conversa com o desenvolvedor

O desenvolvedor do `pypncp` sugeriu, em essência:

```text
o foco da biblioteca é quem precisa popular um banco inteiro com os dados do PNCP;
se for possível fazer um scraper completo, com zero complexidade, que popule um banco inteiro;
criar índice vetorial sobre item seria algo que ainda não foi feito e é muito trabalhoso.
```

O termo “PipeMCP” usado pelo usuário foi interpretado como referência ao `pypncp`, pois é o projeto que está sendo estudado. Se a outra IA descobrir que é outro produto, deve pedir confirmação antes de mudar o escopo.

A partir dessa sugestão, o foco ativo deixou de ser a interface. O produto passou a ser um sincronizador/espelho local do PNCP, com banco relacional, atualização incremental, preservação do dado bruto e futura busca vetorial dos itens.

## 3. Estado real dos repositórios

### 3.1 Projeto ativo

Pasta:

```text
A:\Projetos\pncp-desktop
```

Arquivos principais atuais:

```text
README.md
pyproject.toml
run.bat
src/pncp_desktop/       # protótipo PySide6, ainda preservado
src/pncp_sync/          # sincronizador retomável implementado
tests/                   # testes do protótipo e do sincronizador
docs/
```

O nome da pasta não foi alterado para evitar quebrar caminhos existentes. Isso não significa que a interface seja o foco atual.

O sincronizador e o esquema SQLite foram implementados para contratações por publicação, itens e resultados. Existem CLI, payload bruto comprimido, normalização, FTS5, checkpoint por unidade, retomada, erros/rejeições e verificação. Uma prova real armazenou 94 contratações; outra ligou contratação, item, resultado e fornecedor e foi reexecutada sem duplicação. O índice vetorial ainda não foi implementado. A última validação executou 18 testes com sucesso e está detalhada em [Implementação da Fase 1](IMPLEMENTACAO_FASE_1.md) e [Implementação da Fase 2](IMPLEMENTACAO_FASE_2.md).

### 3.2 Biblioteca original

Pasta:

```text
C:\Users\admin\Desktop\software_prefeitura\pypncp
```

Ela deve ser tratada como projeto externo. Alterações nela só devem ser propostas como contribuição separada, com benchmark e testes próprios.

### 3.3 DevManager

O registro em `A:\DevManager\projects.json` tem id `pncp-desktop` e foi atualizado para:

- nome: `Sincronizador PNCP e Busca Vetorial`;
- status: `Em andamento`;
- progresso: `10`;
- tecnologia: Python/pypncp, com PostgreSQL e pgvector ainda em validação;
- contexto: protótipo de interface preservado, sincronizador ainda não implementado.

O progresso foi reduzido de 30 para 10 porque o escopo mudou para um problema maior e ainda está na fundação documental.

### 3.4 Git

O repositório existe, mas ainda não tem commit inicial. O estado verificado mostra os arquivos como não rastreados. Não interpretar isso como perda de arquivos. Para diagnósticos Git no Windows, o repositório pode exigir o parâmetro pontual:

```powershell
git -c safe.directory=A:/Projetos/pncp-desktop -C A:/Projetos/pncp-desktop status
```

Não alterar a configuração global de segurança sem pedido do usuário.

## 4. O que o `pypncp` oferece hoje

O inventário local mostrou um `PNCPClient` assíncrono com recursos para:

- `contratos`: listar por publicação ou atualização, consultar um contrato específico e iterar páginas;
- `contratacoes`: listar publicações, atualizações e contratações com proposta aberta;
- `atas`: listar atas e atualizações;
- `search`: busca no catálogo;
- `precos`: itens e resultados de preços homologados.

Os métodos `list_all*()` oferecem paginação automática e `prefetch` concorrente. Isso é conveniente para uma aplicação consumidora, mas a carga durável precisa saber exatamente qual unidade foi confirmada. Por isso a hipótese atual é controlar páginas/partições explicitamente na primeira versão.

Detalhes importantes encontrados na documentação local:

- `contratacoes.list_publicacao` e `list_atualizacao` exigem `codigo_modalidade`;
- datas e tamanho de página fazem parte dos parâmetros da coleta;
- `search` e `precos` usam endpoints internos não documentados oficialmente pelo PNCP, identificados por engenharia reversa;
- endpoints internos não devem ser dependência do caminho crítico inicial;
- antes de usar chamadas de itens e resultados em escala, confirmar a rota, a paginação e as chaves no manual oficial.

## 5. Produto que estamos tentando construir

### 5.1 Definição

Um software que usa o `pypncp` para coletar dados públicos do PNCP em unidades pequenas, preservar as respostas originais, normalizar os dados, gravá-los em banco local, permitir retomada após falhas e manter a cópia atualizada.

Em uma fase posterior, o software gerará embeddings das descrições dos itens e manterá um índice vetorial para encontrar itens semanticamente semelhantes.

### 5.2 Fluxo conceitual

```text
API pública do PNCP
    -> pypncp
        -> planejador de períodos, modalidades e páginas
            -> coletor com limite de concorrência
                -> payload bruto/staging
                    -> validação e normalização
                        -> banco relacional
                            -> embeddings dos itens
                                -> índice vetorial
                                    -> CLI, API e futura interface
```

### 5.3 “Scraper” não é necessariamente HTML

Na conversa, “scraper” foi usado como sinônimo de coletor. A decisão atual é priorizar as APIs públicas e documentadas do PNCP. Raspar HTML só seria cogitado se um dado necessário não estivesse disponível por uma API permitida, e ficaria isolado por ser mais frágil.

### 5.4 “Popular um banco inteiro”

Não é uma requisição gigante. É percorrer muitos recursos, períodos, modalidades e páginas, possivelmente buscando detalhes, itens e resultados. “Inteiro” só pode ser usado junto de uma definição de cobertura:

- quais recursos;
- qual período;
- quais modalidades;
- quais campos e documentos;
- qual instante da última atualização;
- quais falhas ou lacunas.

Uma carga histórica (`backfill`) é apenas o primeiro passo. Depois será necessária uma sincronização incremental e reprocessamento de janelas para capturar atrasos e retificações.

### 5.5 “Índice vetorial sobre item”

Um embedding transforma a descrição de um item em uma lista de números. Descrições semanticamente parecidas tendem a ficar próximas nesse espaço. O índice vetorial acelera a recuperação dos vizinhos próximos.

Exemplo:

```text
“microcomputador portátil”
“notebook corporativo”
“computador portátil”
```

Podem ser semanticamente próximos mesmo sem compartilhar exatamente as mesmas palavras.

O vetor nunca substitui descrição, identificador, contratação, fornecedor ou fonte original. Primeiro os itens precisam estar completos e corretos; só depois vale gerar embeddings.

### 5.6 “Zero complexidade”

Não significa algoritmo `O(1)` nem que o problema interno seja simples. Significa esconder a operação difícil do usuário:

- poucos comandos;
- limites seguros por padrão;
- retomada automática;
- progresso compreensível;
- estimativa de espaço;
- mensagens de erro úteis;
- nenhuma necessidade de configurar manualmente paginação, retries ou SQL.

## 6. Arquitetura decidida como hipótese

As camadas sugeridas são:

1. CLI/painel de operação;
2. planejador de unidades de trabalho;
3. orquestrador de execução e checkpoints;
4. adaptador do `pypncp`;
5. área bruta/staging;
6. normalizadores;
7. repositórios e transações do banco;
8. gerador de embeddings;
9. consultas estruturadas, textuais e vetoriais;
10. observabilidade.

### 6.1 Unidade de trabalho

Uma unidade mínima pode ser:

```text
recurso + data inicial + data final + modalidade + página
```

Ela deve poder ser planejada, executada, repetida, marcada como sucesso/falha e auditada de modo independente.

### 6.2 Ordem de confirmação

O ciclo seguro é:

```text
assumir unidade
    -> requisitar página
        -> salvar resposta bruta
            -> normalizar
                -> gravar lote em transação
                    -> commit
                        -> confirmar checkpoint
```

O checkpoint não pode avançar antes do `commit`. Caso contrário, uma queda pode deixar uma página marcada como concluída sem seus registros no banco.

### 6.3 Dados de controle

Tabelas conceituais:

- `ingestion_run`: execução do programa, versão e horários;
- `work_unit`: recurso, janela, modalidade, página e estado;
- `source_payload`: JSON bruto, parâmetros, status, hash e procedência;
- `ingestion_error`: falha classificada e tentativas;
- `data_rejection`: registro recebido, mas não normalizado;
- `coverage`: resumo do que foi confirmado.

### 6.4 Dados do domínio

Tabelas conceituais:

- `orgao` e `unidade`;
- `contratacao`;
- `item_contratacao`;
- `resultado_item`;
- `contrato`;
- `ata`;
- `documento`;
- `item_embedding`.

Os nomes e as chaves só devem ser fechados depois do inventário real dos endpoints.

### 6.5 Chaves e idempotência

O sistema precisa guardar identificadores oficiais e criar restrições únicas adequadas. Não deduplicar apenas por descrição, valor ou nome.

Idempotência significa que repetir a mesma unidade produz o mesmo estado lógico, usando inserção/atualização (`upsert`) e não criando duplicatas. PostgreSQL oferece `INSERT ... ON CONFLICT`, mas a instrução só é correta se a chave de negócio estiver correta.

### 6.6 Carga histórica e incremental

- `backfill`: percorre períodos antigos;
- incremental: consulta novidades e atualizações;
- overlap: reconsulta uma janela anterior para compensar atraso da fonte;
- watermark: maior ponto temporal confirmado;
- reconciliação: compara novamente fonte e destino.

A ausência de um registro numa listagem não prova automaticamente que ele foi excluído. A política de exclusões ainda precisa ser pesquisada.

### 6.7 Concorrência e backpressure

O `pypncp` é assíncrono, então várias requisições podem avançar enquanto aguardam rede. Isso não autoriza criar workers ilimitados.

Controles necessários:

- concorrência global limitada;
- limites por endpoint;
- fila limitada entre download e gravação;
- timeout de conexão e leitura;
- retry só para erros recuperáveis;
- backoff exponencial com jitter;
- respeito a `Retry-After`;
- redução de ritmo quando houver 429 ou erros persistentes.

Backpressure impede que o download acumule mais payloads na memória do que o banco consegue gravar.

### 6.8 Banco e vetores

SQLite pode acelerar a primeira prova local. PostgreSQL é a hipótese para a base completa por transações, concorrência, índices, JSONB, backup e `upsert`. `pgvector` é a hipótese para guardar vetores no mesmo banco.

Nenhuma dessas escolhas está definitivamente fechada. Primeiro é preciso medir volume, escrita, armazenamento, instalação no Windows, construção do índice e qualidade de recuperação.

## 7. Decisões e limites obrigatórios

- O software é somente leitura.
- Não publicar, retificar ou excluir dados no PNCP.
- Não solicitar nem armazenar credenciais de plataforma publicadora.
- Não representar órgão público perante o PNCP.
- Preservar fonte, identificador e data de consulta.
- Distinguir dado original, dado normalizado e inferência.
- Não declarar automaticamente uma empresa “segura”, “habilitada” ou “regular”.
- Não tratar ausência de resultado como certidão negativa.
- Não afirmar que o banco está completo sem relatório de cobertura.
- Não usar endpoints internos como base crítica sem decisão explícita.
- Não começar outras APIs ou novas bibliotecas antes de provar o núcleo.
- Não trocar correção por velocidade.

As justificativas estão em [Política de somente leitura e credenciamento](POLITICA_SOMENTE_LEITURA_E_CREDENCIAMENTO.md).

## 8. O que foi arquivado como melhoria futura

Foi criada a pasta:

```text
A:\Projetos\pncp-desktop\docs\melhorias-futuras
```

Ela contém:

- `INTERFACE_DESKTOP_ARQUITETURA_E_DESAFIOS.md`: arquitetura e dificuldades do protótipo PySide6;
- `preview-interface.png`: prévia visual;
- `CONSULTAS_SINERGICAS_AO_PNCP.md`: outras fontes públicas, como Compras.gov.br, CNPJ, CGU/TCU, Transferegov, ObrasGov, SICONFI, DOU, DataJud e saúde;
- `BIBLIOTECAS_E_ESTRUTURA_DO_ECOSSISTEMA.md`: proposta de bibliotecas separadas para fontes governamentais adicionais;
- `README.md`: regra para retomar esse material.

Arquivar não significa apagar. Significa evitar que interfaces e integrações laterais concorram com a prova do sincronizador.

## 9. Complexidade avaliada

Classificação qualitativa:

- consulta de uma página: baixa;
- percorrer uma janela: média;
- checkpoint e retomada: alta;
- idempotência e retificações: alta;
- modelagem completa: alta;
- backfill nacional: muito alta;
- atualização incremental: alta;
- detectar exclusões: muito alta;
- embeddings: alta;
- índice vetorial em grande volume: alta;
- instalação simples com PostgreSQL: alta;
- operação hospedada multiusuário: muito alta.

A parte difícil não é somente HTTP. É combinar rede instável, paginação, chaves, transações, cobertura, mudanças de esquema, armazenamento, limites da fonte e operação prolongada.

## 10. Plano de execução

### Fase 0 — inventário e linha de base

1. listar recursos e métodos atuais;
2. marcar cada endpoint como oficial ou experimental;
3. registrar parâmetros, paginação, datas e identificadores;
4. executar amostras pequenas;
5. medir latência, páginas, registros e bytes;
6. escolher uma fatia vertical.

Saída: sabemos exatamente qual consulta será feita e como identificar seus registros.

### Fase 1 — fatia vertical retomável

1. janela de um dia e uma modalidade;
2. `ingestion_run`, `work_unit`, `source_payload` e tabela de contratação;
3. migração inicial;
4. timeout e retry limitado;
5. bruto + normalizado;
6. checkpoint após commit;
7. interrupção e retomada;
8. relatório de contagens;
9. prova de reexecução sem duplicatas.

### Fase 2 — itens e resultados

As rotas `GET` oficiais foram confirmadas no Manual de Integração v2.5. A migração v2,
unidades independentes, normalizadores, cobertura e consulta até o fornecedor estão
implementadas. A prova real cobriu uma contratação, um item e um resultado. Falta ampliar
a amostra e medir a cobertura das demais contratações da janela antes de declarar a fase
concluída em escala.

### Fase 3 — contratos, atas e expansão histórica

Adicionar recursos com adaptadores, normalizadores, chaves, migrações, reconciliação, estimativa de disco e backup.

### Fase 4 — atualização contínua

Adicionar agenda, watermarks, overlap, reprocessamento e alertas de atraso.

### Fase 5 — embeddings e busca vetorial

Criar amostra de avaliação, versionar modelo/texto, gerar embeddings em lote, comparar busca exata com HNSW/IVFFlat e implementar busca híbrida.

### Fase 6 — operação simples

Só depois entregar instalação guiada, comandos simples, estimativa de espaço, diagnósticos e possível interface gráfica.

## 11. Como melhorar o `pypncp` com segurança

O sincronizador pode revelar contribuições úteis à biblioteca original:

- iterador de páginas com metadados;
- callbacks de progresso;
- cancelamento seguro de prefetch;
- métricas opcionais de latência e tentativas;
- limites de concorrência configuráveis;
- testes de contrato dos endpoints oficiais;
- benchmarks reproduzíveis;
- otimizações comprovadas por profiling.

Regra: cenário reproduzível → medição inicial → hipótese de gargalo → alteração pequena → mesmos testes → novo benchmark. Uma alteração só é melhoria se mantiver correção e reduzir uma métrica relevante sem sobrecarregar a fonte.

## 12. Perguntas ainda abertas

- Qual volume existe por recurso, ano, mês e modalidade?
- Quantas chamadas de detalhe são necessárias para itens e resultados?
- Quais identificadores são estáveis e únicos?
- Como a fonte sinaliza retificação?
- Como detectar exclusões, se for possível?
- Qual ritmo de requisições é seguro?
- JSONB é suficiente ou payloads precisam ser comprimidos fora do banco?
- SQLite servirá apenas para prova ou também para distribuição local?
- PostgreSQL será instalado localmente, via Docker ou oferecido como serviço?
- Qual modelo de embeddings funciona bem para português e descrições públicas?
- Quantos itens cabem na memória e no índice?
- Qual recall é aceitável para busca aproximada?
- O produto final será CLI, serviço, desktop ou combinação?

Nenhuma dessas perguntas deve ser respondida inventando números. Devem ser respondidas com documentação, experimento e métricas.

## 13. Próxima tarefa recomendada para a outra IA

Continue a Fase 2, sem repetir inventário, migrações ou a prova de uma contratação:

1. ler `README.md`, `IMPLEMENTACAO_FASE_1.md` e `IMPLEMENTACAO_FASE_2.md`;
2. planejar uma amostra explícita de 5 a 10 contratações da execução real;
3. medir itens, resultados, bytes, latência, timeouts e chamadas por contratação;
4. verificar se a paginação real de itens coincide com o comportamento testado;
5. calibrar timeout/backoff sem elevar a concorrência além de um;
6. só então ampliar para as 94 contratações e revisar a cobertura.

Não adicionar PostgreSQL, pgvector, interface final ou novas APIs antes de itens e resultados estarem completos, estáveis e auditáveis.

## 14. Critério de sucesso da continuidade

Uma IA que continuar este trabalho deverá conseguir responder, com evidência:

- o que foi alterado;
- em qual arquivo;
- quais testes foram executados;
- qual hipótese foi medida;
- qual limitação continua aberta;
- se o banco contém dados reais ou apenas dados demonstrativos;
- se o endpoint usado é oficial ou experimental;
- como repetir ou desfazer a etapa de forma segura.

O objetivo não é apenas “fazer rodar”. É construir um coletor que possa ser interrompido, retomado, auditado, medido e ampliado sem perder a confiança nos dados.
