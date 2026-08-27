# Contexto técnico rápido para outro desenvolvedor

O PNCP Desktop é uma aplicação Windows, somente de leitura, que consulta a API pública do PNCP, preserva as respostas e mantém um espelho local pesquisável. A interface é feita em Python 3.13 com PySide6/Qt; o banco é SQLite com FTS5; o acesso ao PNCP usa `pypncp`, `httpx` e tarefas assíncronas executadas fora da thread gráfica.

## Técnicas principais

- **Processamento paginado e em lotes:** cada página da API vira uma unidade persistente de trabalho. O programa não mantém toda a carga na memória.
- **Checkpoint após commit:** uma unidade só é confirmada depois que payload, dados normalizados e métricas são gravados. Interrupções repetem apenas unidades não confirmadas.
- **Idempotência:** `numeroControlePNCP`, número do item e sequencial do resultado funcionam como chaves de negócio. Hashes distinguem registro idêntico de registro alterado.
- **Retentativas limitadas:** erros temporários de rede e HTTP 5xx podem ser repetidos; depois do limite, a unidade fica registrada como falha recuperável.
- **Preservação de procedência:** a resposta original é comprimida com gzip dentro do SQLite e ligada às linhas normalizadas.
- **Normalização relacional:** contratações, itens e resultados/fornecedores ficam em tabelas relacionadas por chaves estrangeiras.
- **Busca textual:** SQLite FTS5 oferece pesquisa local indexada, com normalização de acentos e expansão simples por sinônimos.
- **Busca semântica econômica:** textos são transformados em vetores esparsos por hashing de tokens e conceitos; similaridade de cosseno ordena resultados. É local e não é um modelo neural.
- **Busca híbrida:** filtros estruturados limitam os candidatos e a similaridade semântica os ordena.
- **Importação incremental:** bancos separados são comparados pelas chaves oficiais e hashes. Registros novos são inseridos em uma transação; duplicatas são ignoradas e divergências são relatadas sem sobrescrever o principal. Um backup precede a operação.
- **Concorrência controlada:** rede e banco rodam em workers para não bloquear a interface; o SQLite mantém escrita controlada, sem dezenas de threads gravando na mesma conexão.
- **Migrações aditivas:** `PRAGMA user_version` controla a evolução do esquema.
- **Integridade e recuperação:** `PRAGMA quick_check`, `foreign_key_check`, backup, `REINDEX` e `PRAGMA optimize` apoiam diagnóstico e manutenção.

## Tecnologias

- Python 3.13;
- PySide6/Qt para a interface desktop;
- SQLite, FTS5 e transações ACID;
- `pypncp` como cliente da API pública;
- `httpx`/`asyncio` para I/O de rede;
- gzip e SHA-256 para payloads e detecção de mudanças;
- PyInstaller para gerar `.exe` sem console;
- Inno Setup para o instalador Windows;
- pytest e Ruff para testes e qualidade;
- GitHub Actions para validar e gerar releases.

## Limites importantes

O aplicativo não publica, retifica ou exclui dados no PNCP, não usa credenciais de plataforma e não substitui edital, certidão ou parecer jurídico. PDFs não são baixados automaticamente; apenas links e metadados podem ser guardados. A ausência de um registro numa execução é uma indicação para conferência, não prova de exclusão oficial.

## Estado atual

Já existem sincronização retomável de contratações, itens e resultados, histórico, diagnóstico, busca local, índice semântico econômico, relatórios e importação incremental. A sincronização consolidada de todas as modalidades, testes abrangentes dos estados visuais e avaliação formal de precisão semântica continuam como próximos marcos.
