# Implementação inicial da Fase 2: itens e resultados

## Estado do marco

A fatia vertical de itens e resultados está implementada e validada com uma contratação
real. Ela ainda não representa cobertura nacional: o objetivo desta etapa foi provar as
chaves, chamadas, dependências, retomada e ligação entre contratação, item e fornecedor.

## Confirmação das rotas oficiais

O Manual de Integração do PNCP v2.5 documenta as duas consultas utilizadas:

- [Consultar itens de uma contratação](https://pncp.gov.br/manual/pt-br/latest/contratacao/consultar_itens_de_uma_contratacao.html):
  `GET /v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens`;
- [Consultar resultados de um item](https://pncp.gov.br/manual/pt-br/latest/contratacao/consultar_resultados_de_item_de_uma_contratacao.html):
  `GET /v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{numeroItem}/resultados`.

O adaptador não implementa os métodos `POST`, `PUT` ou `DELETE` apresentados em outras
seções do manual. Não envia `Authorization` e não possui configuração de JWT.

## Descoberta no pypncp

O `pypncp` 1.2.1 já oferece `precos.get_items()` e `precos.get_resultados()`, mas sua
documentação local ainda classifica essas rotas como não oficiais. A documentação oficial
atual resolveu essa dúvida.

Uma resposta real revelou uma divergência adicional:

```text
campo: localidadeFornecedor
modelo pypncp 1.2.1: str | None
resposta real: objeto com ufNome, uf, nomeMunicipio e codigoIbge
resultado do modelo: ValidationError
```

O sincronizador preserva essa falha em `model_validation_errors_json`, mas normaliza o
objeto oficial sem descartar o resultado. Isso mantém compatibilidade com o `pypncp` e
evita alterar silenciosamente o payload.

## Fluxo de detalhes

```text
execução concluída de contratações
    -> plan-details seleciona contratações locais
        -> unidade ITEMS por contratação/página
            -> item_contratacao
            -> se temResultado = true:
                unidade RESULTS independente
                    -> resultado_item
```

Se uma página de itens vier cheia, a próxima página é agendada. Uma falha de resultado
não desfaz o item confirmado e não declara falsamente que o resultado está completo.
Cada unidade possui tentativas, lease, payload, hash, métricas e checkpoint próprios.

## Migração v2

Foram adicionadas:

- `detail_run` e `detail_work_unit`;
- `detail_payload`, com gzip, SHA-256 e erros do modelo do `pypncp`;
- `item_contratacao` e `item_contratacao_fts`;
- `resultado_item`;
- `detail_rejection`, `detail_error` e `detail_coverage`.

Chaves lógicas:

```text
item:      (contratacao_id, numero_item)
resultado: (item_id, sequencial_resultado)
```

Não há deduplicação por descrição, fornecedor ou valor.

## Campos úteis dos itens

Além de descrição, quantidade e valores, o banco preserva:

- material ou serviço;
- situação e existência de resultado;
- critério de julgamento;
- categoria, catálogo e NCM/NBS;
- benefícios e incentivos;
- orçamento sigiloso;
- margens de preferência;
- conteúdo nacional;
- datas de inclusão e atualização;
- patrimônio, registro imobiliário e indicador de imagem.

## Campos úteis dos resultados

- nome e identificação do fornecedor;
- porte, natureza jurídica e tipo de pessoa;
- quantidade, valores homologados e desconto;
- situação e data do resultado;
- critérios de preferência, benefício e desempate;
- ordem de classificação em SRP e reserva remanescente;
- moeda estrangeira e cotação, quando existirem;
- UF, município e IBGE do fornecedor;
- país de origem, cancelamento e subcontratação.

Valores decimais permanecem como texto canônico para evitar arredondamento binário.

## Comandos

```text
pncp-sync plan-details --source-run-id UUID [--numero-controle PNCP] [--limit N]
pncp-sync run-details --detail-run-id UUID
pncp-sync resume-details --detail-run-id UUID
pncp-sync status-details --detail-run-id UUID
pncp-sync verify-details --detail-run-id UUID
pncp-sync search-items "termos" --limit 20
```

`plan-details` não consulta a rede. Ele apenas cria unidades para contratações que já
existem no banco e pertencem à janela/modalidade da execução informada.

## Prova real

Contratação utilizada:

```text
numeroControlePNCP: 11433441000101-1-000033/2026
objeto: credenciamento de serviços de psicologia
```

Resultado da primeira execução:

```text
requisições confirmadas: 2
itens: 1
resultados: 1
bytes recebidos: 2.494
fornecedor: SANARE PSICOLOGIA LTDA
NI fornecedor: 62193758000140
quantidade homologada: 1.200
valor unitário homologado: 80.0
localidade: Presidente Getúlio/SC
código IBGE: 4214003
```

O endpoint apresentou timeouts intermitentes. A execução ficou `PAUSED`, manteve o item
já confirmado e concluiu o resultado em uma retomada posterior. Foram preservados três
erros recuperáveis durante as duas provas.

Na segunda execução:

```text
itens inseridos: 0
itens inalterados: 1
resultados inseridos: 0
resultados inalterados: 1
rejeições: 0
```

As verificações das duas execuções encontraram zero hashes inválidos, zero chaves
duplicadas e zero referências estrangeiras quebradas.

## Testes e limites

A suíte total possui **30 testes**. A parte de detalhes cobre:

- pausa entre item e resultado;
- idempotência de item e resultado;
- normalização de `localidadeFornecedor` como objeto;
- preservação do erro do modelo do `pypncp`;
- falha de resultado sem perder item;
- agendamento da próxima página cheia;
- busca FTS5 até o fornecedor;
- hashes, chaves e integridade referencial.

Limites atuais:

- apenas uma contratação real foi usada na prova de detalhes;
- não foi executado um backfill de itens para as 94 contratações;
- os endpoints mostraram latência e timeout mais altos que a listagem principal;
- reconciliação de itens removidos ou resultados cancelados ainda precisa de política;
- contratos, atas e atualização incremental continuam em fases posteriores;
- embeddings só devem começar depois de ampliar e medir a cobertura de itens.
