# Painel de sincronização

O painel tem duas colunas e não apresenta estimativas de tempo, armazenamento
ou total nacional. Os contadores são lidos do SQLite em uma transação somente
de leitura, em uma thread separada. O horário da leitura aparece no painel.
Uma falha na leitura preserva o último resultado e apresenta uma mensagem;
não transforma dados indisponíveis em zero.

## Contratações

- Registros no banco: quantidade de contratações armazenadas.
- Páginas baixadas / faltam: unidades persistidas com sucesso / demais unidades.
  São tarefas dos planos existentes, não a quantidade de registros restantes.
  Planos diferentes podem consultar a mesma publicação. Novas páginas ainda
  não descobertas não estão no denominador.
- Falhas e retry: subconjunto das páginas que faltam; inclui rejeições parciais.
- Lote em download: período e modalidade das páginas realmente em execução,
  inclusive na recuperação, e não o último lote da primeira passagem.

## Itens

O universo é o mesmo do filtro de coleta recente: licitações já armazenadas,
publicadas nos últimos 365 dias, situação divulgada e propostas ainda abertas.
O filtro usa horário de Brasília e é reavaliado na leitura. Portanto pode diminuir
quando licitações encerram. Não representa todos os itens existentes no PNCP.

Cada contratação conta uma vez. Considera-se a execução de itens mais recente
daquela contratação. Concluída significa todas as páginas de ITEMS confirmadas.
Visitadas inclui tentativas com falha. Falhas permanecem em faltam. Resultados
de fornecedores são tarefas distintas e não viram contratações adicionais.
O identificador em execução é exibido para localizar a contratação.

A primeira data de publicação com itens pendentes é calculada, não fixada em
28/08. O fim do histórico planejado é mostrado separadamente: planejar até
28/08 não prova cobertura completa; a próxima faixa começa em 29/08.
Publicações ainda não armazenadas não podem entrar na contagem de itens.

## Operação

Sincronizar pode planejar e iniciar a coleta diretamente, sem estimativa prévia.
O painel atualiza em segundo plano a cada dois minutos ou pelo botão Atualizar
contadores. Leituras têm limite e cancelamento ao fechar. Não alteram dados,
índices ou estados de sincronização do banco principal.
