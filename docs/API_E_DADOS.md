# API e dados armazenados

## Fontes

O caminho principal usa os endpoints públicos do PNCP por meio do `pypncp`:

- consulta de contratações por data de publicação e modalidade;
- consulta de contratações por data de atualização global (`/contratacoes/atualizacao`);
- itens de uma contratação;
- resultados de itens e fornecedores;
- contratos/empenhos;
- atas de registro de preços.

As URLs configuradas usam HTTPS. A resposta HTTP original é capturada antes da normalização
para que campos não representados pelo modelo Python não sejam perdidos.

Os endpoints de publicação e atualização global são chamados diretamente com HTTPX e
validados com os modelos do pypncp. A atualização global pertence à contratação principal;
ela não baixa automaticamente os detalhes de itens e fornecedores. O comportamento de
cursores, sobreposição e retomada está em [Sincronização e recuperação](SINCRONIZACAO_E_RECUPERACAO.md#atualização-incremental-novas-e-retificadas).

## Dados de contratação

Entre os campos normalizados estão:

- identificador PNCP, ano, sequencial, número da compra e processo;
- objeto e informação complementar;
- CNPJ, razão social, poder e esfera do órgão;
- unidade, município, UF e código IBGE;
- modalidade, modo de disputa, situação e instrumento convocatório;
- amparo legal;
- datas de inclusão, publicação, atualização, abertura e encerramento;
- valores estimado e homologado;
- sistema de origem, processo eletrônico, fontes orçamentárias e emenda parlamentar.

## Itens e fornecedores

Itens armazenam descrição, material/serviço, unidade de medida, quantidade, valores,
benefícios, critérios, situação e códigos disponíveis. Resultados ligam o item ao fornecedor,
classificação, quantidades e valores homologados, localidade e situação.

Fornecedor ausente não é preenchido por inferência. Ele depende da publicação do resultado
correspondente pelo órgão no PNCP.

## Payload bruto

Cada resposta guarda URL, parâmetros, horários, cabeçalhos permitidos, status HTTP, latência,
SHA-256, tamanho original, tamanho comprimido e conteúdo gzip. O dado bruto permite auditoria
e reprocessamento sem fingir que a estrutura normalizada contém todos os campos possíveis.

## Documentos

PDFs não são baixados na sincronização. Quando houver link oficial, o banco pode guardar URL,
título, tipo, data e metadados. O usuário decide quais documentos abrir ou baixar.
