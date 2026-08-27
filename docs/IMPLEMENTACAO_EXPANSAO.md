# Expansão funcional

Este documento registra o que entrou nesta etapa e os limites que continuam explícitos.

## Sincronização

- A tela mostra recurso atual, página/item, bytes recebidos, velocidade, tempo restante e horário previsto.
- O histórico local registra execuções e contagens de novos, alterados e não reencontrados.
- “Atualizar desde a última execução” usa sobreposição de um dia para reduzir lacunas.
- A opção “Atualizar automaticamente ao abrir” é opt-in e prepara a atualização incremental.
- Falhas de rede são repetidas com limite; cancelamento não confirma a unidade em andamento.
- Ausência não é prova de exclusão jurídica. O sistema deve tratar o delta como indicação para conferência no portal oficial.

## Dados e pesquisa

- Respostas completas continuam preservadas comprimidas; campos desconhecidos não são descartados.
- Itens e resultados mantêm fornecedor, valores, categorias, códigos e datas disponíveis no retorno.
- A tabela de documentos guarda somente metadados e links HTTP(S); nenhum PDF é baixado.
- O banco oferece filtros por órgão, CNPJ, município, modalidade, situação, fornecedor, valor e período, além de ordenação, paginação e CSV.
- Consultas salvas, histórico de preços, frequência de compras por órgão e agrupamento de vencedores estão disponíveis na área local.
- A busca por similaridade é local, opcional e econômica. Ela usa hashing esparso e léxico de termos; não deve ser descrita como modelo neural nem como conclusão de equivalência técnica.

## Segurança e manutenção

- Backups são feitos com a API de backup online do SQLite e passam por `quick_check` antes de serem aceitos.
- Há limites para respostas HTTP, somente HTTPS nas fontes configuradas e validação defensiva de JSON.
- A interface informa origem, data de atualização, cobertura e responsabilidade do usuário de conferir edital e portal oficial.
- O aplicativo permanece somente leitura perante o PNCP: não há publicação, retificação ou exclusão de contratação.

## Distribuição

- O build oficial usa PyInstaller `onedir`, mantendo DLLs do Qt ao lado do executável.
- O smoke test abre uma cópia isolada com dados demonstrativos e valida uma captura sem Python ou terminal.
- `build_installer.bat` gera instalador Inno Setup quando ele estiver instalado; a pasta `dist/ConsultaPNCP` é o fallback portátil.
- O updater apenas avisa sobre releases do GitHub e nunca instala silenciosamente.

## Próximos limites

Ainda é necessário ampliar a coleta de documentos/histórico do PNCP em lote, medir a busca semântica em milhares de itens e validar o instalador em uma máquina Windows limpa. Esses itens não são mascarados como concluídos por esta etapa.
