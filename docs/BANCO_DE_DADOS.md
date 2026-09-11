# Banco de dados

## Arquivo principal

O programa trabalha com um único banco SQLite selecionado pelo usuário. Em instalação nova,
o padrão é `%LOCALAPPDATA%\AyrtonSanabio\PNCPDesktop\pncp.sqlite3`. Em desenvolvimento, o
padrão é `data\pncp.sqlite3` no repositório.

Arquivos `-wal` e `-shm` podem aparecer ao lado do banco enquanto ele estiver aberto. Eles
fazem parte da operação normal do SQLite e não são bancos adicionais.

## Grupos de tabelas

### Carga principal

- `ingestion_run`: execução de uma data, modalidade e recurso;
- `work_unit`: uma página retomável da execução;
- `source_payload`: resposta HTTP original comprimida, hash, cabeçalhos e latência;
- `coverage`: páginas planejadas/processadas e maior atualização observada;
- `ingestion_error`: falhas de rede, fonte ou execução;
- `data_rejection`: registros inválidos preservados para auditoria;
- `sync_change`: registros novos, alterados ou não reencontrados.

### Dados de contratação

- `contratacao`: campos normalizados da contratação, órgão, localidade, modalidade, datas,
  valores, situação, links e metadados;
- `contratacao_fts`: índice textual FTS5;
- `contract_insight`: classificação e palavras-chave determinísticas.

### Itens e resultados

- `detail_run`, `detail_work_unit`, `detail_payload`, `detail_coverage`;
- `item_contratacao` e `item_contratacao_fts`;
- `resultado_item`, incluindo fornecedor e valores homologados;
- `detail_error` e `detail_rejection`.

### Contratos, empenhos e atas

- `catalog_run` e `catalog_page`;
- `pncp_contract`;
- `pncp_ata`.

### Recursos locais

- `document_link`: apenas links e metadados; não armazena PDFs;
- `saved_query`: consultas salvas;
- `app_preference`: preferências persistentes;
- `synonym` e `semantic_document`: estruturas internas de pesquisa local.

## Identidade e atualização

`numero_controle_pncp` é a chave única da contratação. O JSON normalizado gera um
`record_hash`:

- chave inexistente: registro novo;
- mesma chave e hash diferente: registro atualizado;
- mesma chave e mesmo hash: registro inalterado, apenas `last_seen_at` é atualizado.

Reexecutar uma página ou janela não duplica contratações, itens ou resultados.

## Pesquisa por identificador

O campo **Identificador PNCP completo** faz uma comparação exata com
`numero_controle_pncp`. A coluna já é uma chave única indexada, então essa consulta não
percorre a tabela inteira. Texto, órgão e outros filtros continuam combináveis com ela.

## Desempenho de filtros

A pesquisa de tela busca uma página e uma linha extra para indicar se existe próxima
página. Ela não calcula `COUNT(*)` no acervo inteiro a cada clique; a contagem completa
é reservada para a exportação de todos os resultados. Filtros de data e a ordenação por
publicação usam a coluna indexada de publicação.

Ordenar por valor exige um índice numérico adicional porque os valores da fonte são
preservados como texto. Para não bloquear a sincronização, o programa não cria esse
índice automaticamente. Com a sincronização pausada, use **Banco local → Segurança e
manutenção → Preparar índices de busca…**. A ação verifica a integridade, cria índices
para valor, modalidade, situação, CNPJ e ordenação por nome do órgão, e pode usar espaço
adicional. O nome do órgão usa FTS5, e CNPJ de fornecedor usa o índice de resultados quando
o campo contém 11 ou 14 dígitos. A busca por município continua sendo textual por conteúdo;
ela não finge usar um índice que não resolveria um termo no meio do nome. Sem o índice de
valor, o aplicativo recusa essa ordenação com uma mensagem clara em vez de parecer travado.

## Integridade e backup

A tela de segurança executa `PRAGMA quick_check`, verificação de chaves estrangeiras e
contagem de duplicidades. O backup usa a API de backup online do SQLite, adequada para um
banco aberto, e valida o arquivo produzido.

O backup manual é criado em segundo plano, mostra as páginas copiadas e pode ser cancelado.
A origem é aberta somente para leitura. A cópia é produzida primeiro em um arquivo temporário,
verificada com `quick_check` e `foreign_key_check` e só então recebe o nome escolhido. O
programa nunca sobrescreve um backup existente nem apresenta uma cópia parcial como concluída.
O backup contém contratações, checkpoints, respostas compactadas, histórico e preferências;
arquivos PDF continuam fora do banco.

Para gerar uma cópia, use **Banco local → Segurança e manutenção → Criar backup…** e escolha
o destino, preferencialmente em outro disco. O backup não é automático e não substitui a
base ativa. Uma cópia no mesmo disco não protege contra a falha física desse disco.

Antes de começar, o programa exige espaço para o banco inteiro e uma margem de 10% ou 64 MiB
(o maior valor). A cópia usa lotes de 256 páginas e também verifica o espaço durante a operação.
O limite operacional é de 30 minutos, incluindo a verificação; se for ultrapassado, o backup
falha claramente e a origem permanece preservada. Uma queda de energia pode deixar um
arquivo `.partial`, que não deve ser tratado como backup confirmado. A operação usa a API
do SQLite para incluir dados confirmados que ainda estejam no WAL, sem copiar arquivos à força.
