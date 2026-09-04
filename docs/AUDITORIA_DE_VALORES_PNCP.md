# Auditoria de valores: evidências, reprodução e investigação por amostragem

Registro técnico da investigação realizada em **04/09/2026**. Os valores e respostas abaixo
são observações dessa data, não garantias de que as publicações continuarão iguais.

## 1. Objetivo e estado do trabalho

Investigar divergências entre valores da contratação, itens, documentos e sistemas de
origem, preservando a informação publicada. Um valor elevado é um sinal de triagem, não
prova de erro, fraude, superfaturamento ou pagamento realizado.

**Decisão do projeto:** após concluir a população da carga principal, retomar a investigação
dessas divergências por triagem local e consultas dirigidas. A conclusão deve ser verificada
pela cobertura e pelas pendências, não por atingir a quantidade estimada de registros.
Se ainda houver lacunas, registrar quais são e não apresentar a auditoria como nacional completa.

Esse trabalho posterior procurará reproduzir o mecanismo dos erros e produzir evidências
para os responsáveis. Não pressupõe que seja possível descobrir o código interno da fonte.

| Componente | Estado |
|---|---|
| Investigação dos dez maiores valores locais | Realizada, com limites descritos neste documento |
| Conferência documental da USP e de Xique-Xique | Realizada |
| Reprodução offline dos quinze totais divergentes de Xique-Xique | Realizada e incluída em `docs/exemplos` |
| Coleta de itens recentes e vigentes | Existe no código; escopo preservado abaixo |
| Auditoria automatizada de todo o acervo, seleção amostral e relatório de suspeitas | Plano de trabalho, ainda não implementado como funcionalidade do aplicativo |
| Correção automática dos valores oficiais | Não implementada e não autorizada por esta investigação |

Não foi criado agendamento ou processo que iniciará essa auditoria sozinho ao terminar a carga.
Este documento registra a próxima etapa acordada, não um recurso automático já entregue.

## 2. Preservar o escopo de itens recentes e vigentes

A carga normal de itens deve continuar restrita, quando essa opção for selecionada, a:

- publicação nos últimos **365 dias** em relação à data de referência;
- situação `situacao_compra_id = 1` (Divulgada no PNCP);
- encerramento de propostas igual ou posterior ao instante de referência;
- datas interpretadas com fuso; no filtro atual, a data local usa UTC−03:00.

Essa é a definição operacional do filtro existente em
`src/pncp_sync/persistence/detail_repositories.py`, função `_recent_active_selection`.
Não é uma declaração jurídica de vigência contratual: aqui, "vigente" significa oportunidade
com prazo para propostas ainda aberto segundo os campos disponíveis. Data de encerramento
ausente ou inválida não permite incluir a contratação nesse filtro.

A opção original de itens sem esse recorte continua existindo; documentar o plano de auditoria
não a ativa nem altera configurações. A atualização dos metadados deve preceder a seleção,
pois situação e prazo locais desatualizados podem produzir uma seleção incorreta.

**A investigação não exige baixar itens de todas as contratações.** Ela terá uma amostra
explícita de identificadores. Casos antigos, como os deste relatório, podem ser consultados
individualmente como exceções de pesquisa, sem ampliar a carga operacional de itens.
Se não quisermos nenhuma consulta fora do recorte recente, podemos auditar somente o
subconjunto disponível, mas não teremos evidências para explicar os casos históricos.

## 3. O que o banco local permite verificar

- `contratacao.numero_controle_pncp`: chave para localizar o registro e o portal oficial.
- `valor_total_estimado` e `valor_total_homologado`: grandezas diferentes; homologação
  ausente não é zero, e nenhum dos dois campos comprova pagamento.
- `source_payload_id`: resposta que deu origem à versão normalizada.
- `source_payload.content_gzip`: corpo original comprimido; deve ser descomprimido e
  interpretado com precisão decimal para a comparação.
- `source_payload.responded_at`, parâmetros, URL, hash e cabeçalhos: contexto da coleta.
- `usuarioNome` no JSON: identificação da plataforma/usuário de publicação, útil para
  agrupamento e encaminhamento. Não prova qual sistema causou o problema.

Na seleção realizada, foram percorridas aproximadamente 1,49 milhão de contratações em
lotes de 10 mil, mantendo apenas dez candidatos em memória e comparando números com
`Decimal`. A varredura levou aproximadamente **65 segundos** nesse computador e momento.
É uma medição de seleção dos maiores valores, não um benchmark de auditoria completa,
descompressão, OCR ou consultas HTTP. Uma consulta SQL monolítica anterior foi interrompida
ao atingir o limite de tempo de segurança.

Nos dez casos selecionados, o valor estimado normalizado coincidiu numericamente com o
campo `valorTotalEstimado` do JSON original associado. Portanto, não se encontrou inflação
do valor causada pelo armazenamento local **nesses dez casos**. Isso não certifica todos
os campos nem todos os registros do acervo.

## 4. Dez maiores valores observados

Este ranking pertence ao banco local na leitura de 04/09/2026, não a todo o PNCP.
Identificadores numéricos de payload abaixo são locais e não existirão iguais em outra instalação.

| Órgão e objeto resumido | Identificador PNCP | Valor estimado armazenado | Payload local | `usuarioNome` |
|---|---|---:|---:|---|
| Laranjeiras: construção | `13120613000104-1-000033/2026` | R$ 43.880.000.000.000,00 | 35089 | AGAPE SISTEMAS E CONSULTORIA |
| Xique-Xique: serviços hospitalares | `13880257000127-1-000020/2025` | R$ 29.833.705.404.040,13 | 29895 | Open Tecnologia da Informação EIRELI |
| Câmara de Muniz Ferreira: buffet | `13458864000101-1-000008/2024` | R$ 17.908.000.017.617,68 | 37872 | Open Tecnologia da Informação EIRELI |
| Saúde de Surubim: alimentos | `08937139000178-1-000001/2025` | R$ 14.880.440.047.484,94 | 37314 | Open Tecnologia da Informação EIRELI |
| Saúde de Surubim: limpeza | `08937139000178-1-000002/2025` | R$ 10.116.600.049.058,62 | 37314 | Open Tecnologia da Informação EIRELI |
| Metrô/SP: projeto Linha 17 | `62070362000106-1-000197/2026` | R$ 9.999.999.999.999,99 | 34567 | Compras.gov.br |
| Metrô/SP: projeto Linha 22, lote 1 | `62070362000106-1-000196/2026` | R$ 9.999.999.999.999,99 | 34560 | Compras.gov.br |
| Metrô/SP: projeto Linha 22, lote 2 | `62070362000106-1-000195/2026` | R$ 9.999.999.999.999,99 | 34560 | Compras.gov.br |
| Fiocruz: iluminação temática | `33781055000135-1-000077/2024` | R$ 8.987.040.000.000,00 | 11159 | Compras.gov.br |
| USP: curso de planejamento e IA | `63025530000104-1-005060/2025` | R$ 8.299.210.000.000,00 | 36160 | Compras.gov.br |

Para abrir o portal, decompor `CNPJ-1-SEQUENCIAL/ANO` em:

```text
https://pncp.gov.br/app/editais/CNPJ/ANO/SEQUENCIAL_SEM_ZEROS_A_ESQUERDA
```

Exemplo: `13880257000127-1-000020/2025` corresponde a
[Xique-Xique, 2025/20](https://pncp.gov.br/app/editais/13880257000127/2025/20).
O CNPJ deve permanecer texto, preservando zeros à esquerda.

## 5. Caso USP: quantidade diferente do documento

Identificador: **`63025530000104-1-005060/2025`**.

- [Portal oficial](https://pncp.gov.br/app/editais/63025530000104/2025/5060).
- [Itens estruturados](https://pncp.gov.br/api/pncp/v1/orgaos/63025530000104/compras/2025/5060/itens?pagina=1&tamanhoPagina=50).
- [Lista de documentos](https://pncp.gov.br/api/pncp/v1/orgaos/63025530000104/compras/2025/5060/arquivos).
- [Autorização da fase preparatória](https://pncp.gov.br/pncp-api/v1/orgaos/63025530000104/compras/2025/5060/arquivos/1).
- [Despacho de homologação](https://pncp.gov.br/pncp-api/v1/orgaos/63025530000104/compras/2025/5060/arquivos/2).

A página 1 da autorização, conferida visualmente, identifica a compra
`202500134871 / 1 - RUSP`, processo `154.00012073/2025-75`, e informa:

| Campo | Autorização original | API de itens |
|---|---:|---:|
| Quantidade | 1 UNIDADE | 91.100.000 |
| Valor unitário | R$ 91.100,00 | R$ 91.100,00 |
| Total | R$ 91.100,00 | R$ 8.299.210.000.000,00 |

O valor homologado da contratação preservado no banco também era R$ 91.100,00.
O despacho consultado referencia o mesmo processo e curso; não contém uma nova tabela
de valores que substitua a autorização analisada.

Reprodução aritmética: `91.100.000 × 91.100 = 8.299.210.000.000`.
Logo, o cálculo é coerente com a quantidade publicada, mas essa quantidade não corresponde
ao documento original. Possível troca de campo ou escala permanece hipótese; não foi obtido
o JSON originalmente enviado pela plataforma. Não afirmar que identificamos a linha de código.

## 6. Caso Xique-Xique: transformação reproduz os quinze totais divergentes

Identificador: **`13880257000127-1-000020/2025`**.

- [Portal oficial](https://pncp.gov.br/app/editais/13880257000127/2025/20).
- [Itens, página 1](https://pncp.gov.br/api/pncp/v1/orgaos/13880257000127/compras/2025/20/itens?pagina=1&tamanhoPagina=50).
- [Itens, página 2](https://pncp.gov.br/api/pncp/v1/orgaos/13880257000127/compras/2025/20/itens?pagina=2&tamanhoPagina=50).
- [Lista de documentos](https://pncp.gov.br/api/pncp/v1/orgaos/13880257000127/compras/2025/20/arquivos).
- [Edital 001/2025, processo administrativo 014/2025](https://pncp.gov.br/pncp-api/v1/orgaos/13880257000127/compras/2025/20/arquivos/1).

O edital possui 48 páginas digitalizadas. As tabelas das páginas 13–15 foram renderizadas e
conferidas visualmente; extração textual simples não retornou seu conteúdo. A página 15
informa o total geral **R$ 10.198.897,55**, também por extenso.

As duas páginas da API retornaram 50 e 9 itens. A soma de `quantidade × valorUnitarioEstimado`
dos 59 itens foi **10.198.897,55000000**, coincidente com o total geral do edital.
A soma dos `valorTotal` publicados foi **29.833.705.404.040,1309**; o total principal
preservado era **29.833.705.404.040,13**, compatível com a soma expressa em centavos.

| Item | Quantidade × unitário | Total decimal correto e presente no edital | Total exato da API |
|---|---|---:|---:|
| 2, Amigdalectomia | 12 × 1226.70 | 14720.40 | 1472040000000.0001 |
| 3, Amigdalectomia com adenoidectomia | 36 × 1348.88 | 48559.68 | 485596800000.0001 |
| 5, Amputação/desarticulação | 12 × 1785.48 | 21425.76 | 2142576000000.0002 |

Os itens divergentes são **2, 3, 5, 7, 15, 21, 23, 27, 36, 37, 38, 39, 42, 45 e 46**.

### Transformação candidata

```text
12 × 1226.70 com aritmética decimal: 14720.40
Representação do produto em float:  14720.400000000001
Removendo o ponto:                  14720400000000001
Aplicando quatro casas implícitas:  1472040000000.0001
Total exato observado na API:       1472040000000.0001
```

Essa mesma sequência reproduziu **15/15 totais divergentes**, exatamente, inclusive as
quatro casas finais. Os fatores aparentes de 10 milhões, 100 milhões etc. variam porque
muda o comprimento da representação textual do produto binário. Ponto flutuante sozinho
não transforma milhares em trilhões; a reinterpretação dos dígitos é essencial à hipótese.

### Controle negativo e limite da descoberta

O item 1 tem quantidade 24, unitário 674.44 e total correto 16186.56. Seu produto em float
também contém resíduo, mas o valor publicado não sofreu a transformação candidata.
Portanto, a hipótese não explica por que somente parte dos itens foi afetada.

Reproduzir os quinze erros não prova que o código da fonte executou essa sequência, não
identifica a plataforma culpada e não autoriza uma correção generalizada. A coincidência
do total geral não representa uma revisão completa de todas as linhas do próprio edital.

### Reprodução offline

O experimento está em [exemplos/reproduzir_divergencias_pncp.py](exemplos/reproduzir_divergencias_pncp.py).
Contém os quinze valores observados e um controle negativo. Não consulta internet ou banco,
não grava dados e usa apenas a biblioteca padrão. Foi validado em Python 3.13; registrar
a versão ao repetir, pois representações de float podem variar entre linguagens/runtime.

Na raiz do projeto, em PowerShell:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe .\docs\exemplos\reproduzir_divergencias_pncp.py
```

Não executar com `-O`, que desabilita as asserções. Resultado esperado: quinze igualdades
exatas, controle negativo preservado e reprodução da multiplicação divergente da USP.
As fixtures são evidências históricas; não são uma consulta do estado atual do portal.

## 7. Outros padrões e verificações incompletas

- **Surubim/limpeza, `08937139000178-1-000002/2025`:** a resposta trouxe 22 itens;
  21 tinham divergência entre produto e total. Item 3: 150 × 0.3114 = 46.71, mas total
  4671.00 (fator 100). Item 4: 18 × 0.2385 = 4.293, mas total 429.30 (fator 100).
  Item 2 tinha unitário zero, total 5180.00 e `orcamentoSigiloso=false`. Não é possível
  decidir qual campo está correto sem comparar a documentação. A hipótese de Xique-Xique
  ainda não foi validada nesse conjunto.
- **Laranjeiras, `13120613000104-1-000033/2026`:** os 14 itens retornados tinham produtos
  coerentes com os totais. No primeiro, 3.000.000 × 1.550.000 = 4.650.000.000.000.
  A descrição trata de maior desconto sobre SINAPI/ORSE. É necessário revisar a representação
  dos quantitativos e valores no edital; teste aritmético sozinho não detecta a origem.
- **Metrô/SP, `62070362000106-1-000195/2026`, `...000196/2026` e `...000197/2026`:** cada
  resposta trouxe um item com quantidade 1 e unitário/total `9999999999999.9900`.
  `orcamentoSigiloso=false` nos três. Valor artificial de preenchimento é hipótese,
  não convenção oficial comprovada. Não classificá-lo automaticamente como orçamento sigiloso.
- **Fiocruz, `33781055000135-1-000077/2024`:** homologado local R$ 94.800,00 contra estimado
  de R$ 8,987 trilhões; consultas dos itens atingiram timeout. Causa não identificada.
- **Muniz Ferreira, `13458864000101-1-000008/2024`, e Surubim/alimentos,
  `08937139000178-1-000001/2025`:** consultas de itens atingiram timeout. Não classificar
  ausência de resposta como ausência de itens ou erro financeiro comprovado.

Critério usado na triagem matemática: diferença superior ao maior entre 0,01 e uma
milionésima do produto. É uma tolerância exploratória, não regra legal nem garantia de
arredondamento adequada a qualquer contratação. Para casos selecionados, conservar todos
os dígitos e comparar com `Decimal`; não converter números monetários primeiro para float.

## 8. Protocolo pós-população sem carga integral de itens

### Etapa A — triagem local

1. Registrar data, escopo histórico, cobertura, número de registros e pendências da carga.
2. Ler apenas os campos necessários em lotes, preferindo paginação por chave (`id > último_id`)
   em vez de grandes `OFFSET`. Usar conexão somente leitura, timeout e limite de trabalho;
   não criar índices ou migrar o banco durante a análise sem decisão separada.
3. Selecionar sinais: extremos de valor, valores repetidos com aparência de preenchimento,
   valores negativos/não finitos e relações muito discrepantes entre estimado e homologado.
   Homologado ausente não deve ser usado como zero. Comparar grupos semelhantes por ano,
   modalidade e tipo de objeto; um corte monetário universal produz falsos positivos.
4. Para os selecionados, comparar com o payload associado. Descomprimir cada payload uma
   vez por lote, pois a mesma resposta contém várias contratações. Limitar cache e tamanho
   descomprimido; não carregar os payloads nacionais de uma vez.
5. Separar possível erro de importação local de dado já divergente na fonte.

Essa etapa não precisa de itens nem de chamadas HTTP. A consulta pelo identificador pode
ser feita diretamente na Pesquisa do Banco local ou, em ferramenta SQLite somente leitura:

```sql
SELECT numero_controle_pncp, orgao_razao_social, valor_total_estimado,
       valor_total_homologado, source_payload_id, data_atualizacao
FROM contratacao
WHERE numero_controle_pncp = '13880257000127-1-000020/2025';
```

Os valores normalizados são armazenados como texto: não ordenar lexicograficamente
(`'9' > '100'`). Para a auditoria de precisão, interpretar como Decimal. Um CAST REAL serve
apenas como aproximação de triagem, não para provar diferenças nos últimos dígitos.

### Etapa B — piloto amostral, antes de ampliar

Proposta inicial de **100 contratações distintas**, com limites ajustáveis antes de executar:

| Grupo | Quantidade proposta | Finalidade |
|---|---:|---|
| Suspeitos selecionados por critérios previamente registrados | 40 | Testar padrões e reproduzir erros |
| Controles sem o sinal, pareados por plataforma/época/modalidade | 40 | Medir se a hipótese também condenaria dados corretos |
| Amostra aleatória estratificada do restante do acervo | 20 | Detectar padrões não cobertos pela seleção de extremos |

Deduplicar por identificador; não repetir os casos já conhecidos no conjunto de validação
independente. Selecionar antes de conferir os itens. Fixar uma semente e persistir a lista
de identificadores, o algoritmo e sua versão: a semente sozinha não basta se o banco mudar.
Reutilizar itens recentes já disponíveis, registrando a idade da captura. Itens antigos
necessários à pesquisa ficam restritos aos identificadores aprovados na amostra.

Os casos Xique-Xique e USP são exemplos de descoberta, não validação independente.
Congelar a hipótese antes do novo teste. Se ela for alterada depois de observar os
resultados, será necessário outro conjunto ainda não examinado.

### Etapa C — consultas dirigidas e orçamento de rede

- Até duas chamadas concorrentes durante a pesquisa, independentemente do teto experimental
  da carga operacional. Não executar dois escritores no banco principal.
- Proposta de teto: até cinco páginas de 50 itens por contratação, **500 chamadas de itens**
  no piloto de 100 casos. O limite total deve incluir retries, para uma API indisponível
  não transformar pesquisa pontual em carga ilimitada.
- Paginação incompleta deve ser marcada como parcial. É possível comprovar uma divergência
  em um item sem terminar a contratação; não é possível validar o total global usando só
  uma página. Se necessário, ampliar o limite de um caso explicitamente, não de todo o acervo.
- Distinguir HTTP 204/lista vazia de timeout, 429, erro de JSON e demais falhas. Preservar
  status e contexto. Respeitar Retry-After e permitir interrupção da coleta de evidências.
- Não buscar resultados/fornecedores se quantidade, unitário e total bastarem ao teste.
- Consultar a lista de documentos e baixar manualmente apenas os documentos pertinentes
  aos casos escolhidos; PDF nacional e OCR em massa ficam fora do plano.

O orçamento não obriga a atingir 500 chamadas: se o piloto já reproduzir o mecanismo em
casos independentes, encerrar e consolidar a evidência. As consultas preparatórias de
metadados/documentos têm orçamento separado e devem aparecer no relatório de consumo.

### Comparação ilustrativa de custo

Com 1,49 milhão de contratações e ao menos uma chamada de itens por contratação, uma
varredura completa exigiria pelo menos **1,49 milhão de chamadas**, sem contar páginas
adicionais, resultados e retries. Um piloto com teto de 500 chamadas é cerca de **2.980 vezes
menor** nesse exemplo. Não é previsão do número de chamadas da carga normal de itens vigentes.

Modelo simplificado: `tempo ≈ chamadas × latência média / concorrência efetiva`, acrescido
de esperas, processamento e retries. Exemplo hipotético, não benchmark: 500 chamadas a
2 segundos, com duas simultâneas, dariam cerca de 8 min 20 s; a 30 segundos, cerca de
2 h 5 min. Timeouts e backoff podem aumentar muito esses tempos.

Armazenamento: medir bytes reais de uma pequena amostra; multiplicar pelo número de
respostas planejadas e acrescentar metadados. JSON bruto, JSON comprimido e PDFs têm
custos diferentes. A auditoria local em lotes limita RAM, mas ainda disputa disco e CPU
com a sincronização; deve ocorrer após a carga, ou com atividade limitada se autorizada.

### Etapa D — classificação e validação humana

| Classificação | Significado |
|---|---|
| Suspeita por magnitude/padrão | Sinal local; ainda sem comprovação documental |
| Divergência aritmética | Produto e total não coincidem segundo tolerância registrada |
| Divergência documental | Campo estruturado difere do documento identificado |
| Reprodução da transformação candidata | Hipótese gera o mesmo número; autoria e caminho interno ainda não provados |
| Inconclusivo | Falta de dados, contexto ou falha da API |

Registrar número de casos selecionados, respondidos, parciais, inconclusivos e confirmados;
quantos erros a hipótese reproduziu e quantos controles corretos ela sinalizou. Não tratar
um timeout como resultado negativo. Não calcular uma "taxa nacional de erro" usando só
os extremos: a amostra dirigida não é representativa. Inferência populacional exige desenho
amostral apropriado, pesos e incerteza; os 20 casos aleatórios propostos são exploratórios.

## 9. Evidência reproduzível e armazenamento

Para cada caso, o futuro coletor/relatório deverá registrar:

- identificador PNCP, item, órgão e campos relevantes, sem dados pessoais desnecessários;
- instante UTC da consulta, recurso/URL, parâmetros, HTTP e versão da hipótese/script;
- corpo bruto e SHA-256, além da representação decimal usada na análise;
- campos localizados no documento, título, URL, página e hash do arquivo;
- origem da seleção, semente/lista congelada, cobertura da paginação e motivo do resultado;
- erro observado, tentativas e ponto de retomada, sem sobrescrever evidência anterior.

Arquivos de evidência podem ficar numa pasta explícita escolhida para auditoria, fora do
repositório e do banco operacional, com manifesto e JSONs compactados. Isso não exige um
segundo banco SQLite nem uma cópia integral do banco principal. Essa organização é proposta
para o coletor posterior, não funcionalidade já presente na interface.

Comparar capturas da mesma versão, sempre que possível. Se fonte ou documento forem
retificados, manter capturas anteriores e distinguir correção posterior de erro de importação.
Um resultado atual diferente não invalida automaticamente a evidência histórica.

Limitar tamanho de respostas e descompressão; tratar JSON/PDF como conteúdo não confiável;
não executar anexos. Em eventual CSV, proteger contra fórmulas e preservar CNPJ/identificador
como texto. Não publicar dados pessoais ou acervos de documentos indiscriminadamente.
Preservar os valores oficiais: eventual valor derivado deve ficar separado, com fórmula,
evidência e rótulo explícito; nunca substituir silenciosamente `valor_total_estimado`.

## 10. Próximos experimentos definidos

1. Validar a transformação de Xique-Xique em casos independentes de Surubim e Muniz Ferreira,
   sem ajustá-la depois de olhar os resultados.
2. Comparar com controles corretos da mesma plataforma e explicar a exceção do item 1.
3. Repetir as operações em Python e JavaScript e testar conversão brasileira e máscaras
   de quatro casas. Isso testa plausibilidade técnica; não identifica a linguagem real da fonte.
4. Procurar, por amostragem, outras quantidades iguais ao preço unitário multiplicado por
   1.000, padrão suspeito observado na USP, sem classificá-lo sozinho como erro.
5. Comparar documento → portal de origem → API PNCP e, quando houver histórico público,
   identificar se a divergência surgiu numa atualização. Não há acesso presumido a logs privados.

Solicitação técnica aos responsáveis: comparar campos no sistema de origem, JSON original
de envio, valor recebido/persistido no PNCP e resposta de consulta. Para Xique-Xique,
encaminhar os 15 exemplos e o controle negativo; para USP, rastrear quantidade 1 versus
91.100.000. Informar fatos sem acusar plataformas ou pessoas e solicitar protocolo.

## 11. Referências e integridade das fontes consultadas

- [Manual oficial: campos de itens](https://pncp.gov.br/manual/pt-br/latest/contratacao/inserir_contratacao.html).
  A referência descreve campos; esta pesquisa não utiliza operações de inserção.
- [Atendimento e suporte PNCP](https://www.gov.br/pncp/pt-br/pncp).
- Autorização USP (URL na seção 5), SHA-256 consultado:
  `C2C5E729DDD13F9D4390085F5C76690075EAC2245D79F92899E5E6EB9035BA8F`.
- Edital Xique-Xique (URL na seção 6), SHA-256 consultado:
  `BEE8D2BEF282E800E9D9FB3A480CFCA1AE30B57D94D7B89F7FC701F61B3FA1DB`.

Os hashes identificam os arquivos analisados; não certificam assinaturas digitais nem
atestam que todo o conteúdo esteja correto. PDFs, banco e capturas não foram adicionados
ao código do projeto. Para conferir posteriormente, obter o documento pelo link/lista,
anotar data e hash e comparar as páginas indicadas; uma nova versão pode ter outro hash.
