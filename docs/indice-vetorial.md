# Busca vetorial: fundação e piloto local

O índice vetorial é opcional, local e separado do SQLite principal. Ele não
acelera filtros por data, órgão, CNPJ, situação ou valor. Seu objetivo é trazer
textos semanticamente parecidos quando as palavras diferem.

## Estado atual

`semantic_document` usa hashing esparso em JSON e comparação sequencial. É um
protótipo determinístico, não embeddings de linguagem natural nem índice ANN.
Não deve ser reconstruído para o acervo nacional.

O módulo `pncp_sync.semantic.embeddings` é a nova base: monta somente texto
público relevante — objeto, modalidade, instrumento, amparo legal, órgão e
itens/códigos de catálogo quando existirem. Isso dá contexto administrativo a
um modelo genérico sem fingir que ele foi treinado no PNCP. O módulo fixa
versão de template e modelo, valida vetores e compara hashes para selecionar
apenas documentos novos ou alterados. Esse módulo de preparação não baixa modelos.

`pncp_sync.semantic.pilot` executa um experimento real com o modelo
`intfloat/multilingual-e5-small` (ONNX oficial, float32, 384 dimensões). O
piloto grava a amostra e vetores binários em `.semantic-pilot/pilot.sqlite3`,
com confirmação por lote. O banco de origem é aberto com `mode=ro` e
`PRAGMA query_only=ON`. O aplicativo Qt e o banco principal não recebem um
novo mecanismo de pesquisa automaticamente.

O piloto possui 50 consultas em `semantic-pilot-queries.json`, cada uma com
um critério explícito de relevância. Compara FTS5/BM25 com palavras obrigatórias
(AND), FTS5/BM25 com palavras alternativas (OR), vetores e combinação por RRF.
O relatório HTML permite marcar relevância e exportar os julgamentos.
Veja [piloto-vetorial.md](piloto-vetorial.md) para executar e reproduzir.

## Como adaptar a linguagem administrativa

1. Começar com um modelo multilíngue local e um texto estruturado por rótulos
   administrativos, como o template deste módulo.
2. Manter sinônimos e códigos de catálogo na busca FTS5; eles complementam o
   vetor e explicam termos oficiais que não devem depender de inferência.
3. Montar uma coleção de consultas reais e julgamentos humanos de relevância.
   Ela mede precisão@10, recall@10 e falsos positivos antes de trocar o modelo.
4. Só depois de reunir pares suficientes de `consulta -> contratação relevante`,
   avaliar ajuste fino. O ajuste sem revisão humana pode amplificar ruído ou
   criar uma falsa sensação de precisão.

O primeiro índice não precisa de ajuste fino: o template, a avaliação e a
combinação com FTS5 são a etapa segura e mensurável.

## Ciclo de geração

Na primeira construção, cada contratação no escopo escolhido gera um vetor e
um hash. Nas sincronizações seguintes, o hash do texto, a versão do template e
o identificador do modelo são comparados: somente contratações novas ou
alteradas voltam para a fila. Trocar o modelo ou o template exige reconstruir o
escopo, pois os vetores deixam de ser comparáveis. A execução será em lotes
com checkpoint; uma queda não reinicia o trabalho já confirmado.

## Limites do piloto

O cálculo de vizinhança é exato por produto interno de vetores normalizados,
com a matriz da amostra em RAM. Ainda não existe HNSW/ANN nem integração com
os filtros SQL da interface. Esse baseline permite avaliar o modelo antes
de introduzir o erro adicional de uma busca aproximada.

A amostra é congelada: repetir o comando retoma os vetores pendentes, mas
não incorpora retificações posteriores da origem. O planejador incremental
de embeddings é testado separadamente; não há serviço automático de
reindexação nacional. As consultas de avaliação são propostas para revisão,
não consultas coletadas de usuários reais nem um benchmark rotulado.

## Custos de referência

Com 3,9 milhões de contratações e 384 dimensões: float32 ocupa cerca de 5,6
GiB somente para vetores; float16, 2,8 GiB. O HNSW e metadados acrescentam
aproximadamente 1 a 3 GiB. O modelo deve ser opcional e nunca ser baixado ou
indexado silenciosamente.
