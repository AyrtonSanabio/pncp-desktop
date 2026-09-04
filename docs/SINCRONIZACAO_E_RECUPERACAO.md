# Sincronização e recuperação

## Sincronização parcial

O usuário escolhe datas e uma modalidade. **Estimar** consulta a primeira página, valida a
paginação e calcula respostas, registros, espaço e tempo. **Sincronizar** executa as páginas
planejadas. Enquanto o processo estiver aberto, falhas recuperáveis entram em espera e são
tentadas novamente automaticamente. **Pausar** é a única ação normal que interrompe esse
ciclo; **Continuar** retoma uma pausa explícita ou uma execução de versão anterior.

**Registros por página** controla o parâmetro oficial `tamanhoPagina` somente para novos
planos. As opções são 10, 50, 100, 250 e 500; o padrão do aplicativo é 50. Cada execução e
cada unidade persistem o valor escolhido. Retomadas sempre reutilizam o tamanho original,
mesmo que a preferência da interface tenha mudado. Isso evita lacunas causadas por uma troca
de paginação no meio do recorte.

## Carga completa

A opção **Preparar carga completa** cobre o intervalo entre 01/01/2021 e a data atual. O
período é dividido em janelas consecutivas de até 31 dias, uma para cada modalidade do PNCP.

O término fica fixado na sessão persistida. Uma carga iniciada até 28/08 não passa a incluir
setembro apenas porque o aplicativo permaneceu aberto.

A estimativa é opcional. Ela consulta no máximo 12 lotes distribuídos pela série e projeta
uma faixa; **Sincronizar** pode começar sem estimativa.

Para cada lote, o programa:

1. ignora cobertura integral já confirmada;
2. reabre uma execução incompleta existente ou cria um plano;
3. baixa uma ou mais páginas conforme o modo escolhido;
4. confirma cada página separadamente e em ordem transacional no SQLite;
5. cataloga páginas que esgotaram a rodada curta e segue imediatamente para os próximos
   lotes, sem permitir que uma única resposta defeituosa monopolize a carga;
6. depois da passagem pelos lotes primários, revisita as pendências recuperáveis em rodízio,
   com espera progressiva entre as rodadas, até concluir ou o usuário apertar **Pausar**.

O seletor **Downloads simultâneos** oferece 1, 2 ou 4. O modo 1 usa o motor sequencial
original. Acima de 1, um motor separado paraleliza somente a rede: normalização e escrita
continuam seriais. O modo acelerado começa com duas páginas, sobe gradualmente após grupos
de sucessos e nunca ultrapassa o limite escolhido.

## Falhas temporárias

Timeout, desconexão, interrupção durante leitura, HTTP 429 e erros HTTP 5xx participam de
rodadas curtas. Na carga completa, uma execução saudável continua baixando e aumenta
gradualmente até o limite de concorrência escolhido. Falhas isoladas são catalogadas e as
páginas saudáveis seguintes continuam. Um grupo sem sucesso, uma redução por falhas repetidas
ou HTTP 429 adia a execução para o fim da fila. Assim, páginas com HTTP 504 não monopolizam a carga nem limitam os
lotes saudáveis a rodadas pequenas. O HTTP 429 recebe tratamento mais conservador: toda a
carga aguarda no mínimo 60 segundos (ou o Retry-After, quando maior) antes de consultar outro lote, evitando transformar a limitação do
servidor em centenas de requisições rejeitadas. Depois da
passagem primária, as execuções com falhas recuperáveis formam uma fila circular: cada uma
recebe uma nova rodada antes que qualquer execução seja tentada outra vez. Esse ciclo não
possui limite global na carga completa e continua enquanto o aplicativo estiver aberto, até as
páginas responderem ou o usuário apertar **Pausar**.

O planejamento também participa do rodízio. Na carga completa, a descoberta de um lote faz uma
sondagem de no máximo 30 segundos e sem retries internos; se a primeira página não responder,
esse recorte é adiado em memória e o próximo lote é planejado. Depois da
passagem primária, planejamentos adiados e páginas catalogadas são alternados nas rodadas de
recuperação. Ao reiniciar o aplicativo, as janelas são reconstruídas da sessão persistida e os
recortes ainda sem plano voltam à fila. Erros incompatíveis com o contrato da fonte e falhas
inesperadas de programação ou gravação permanecem fatais, pois repeti-los indefinidamente
poderia esconder corrupção ou um defeito do software.

No modo acelerado, uma falha isolada não reduz a concorrência. Dois grupos consecutivos
com falhas temporárias em pelo menos duas páginas diferentes reduzem o nível em um:
4 → 3 → 2 → 1, por exemplo. Repetir o erro da mesma página não demonstra sobrecarga geral.
Um grupo sem falhas limpa a sequência; oito páginas confirmadas em grupos sem falhas
aumentam o nível em um. HTTP 429 reduz um nível imediatamente e aplica espera global cancelável.
Erros de validação não são usados como indício de sobrecarga da rede.

A interface oferece limites 1, 2, 4 e **8 — acelerado experimental**. O modo paralelo
inicia em até duas requisições e sobe gradualmente. O nível é compartilhado entre lotes
e rodadas da mesma tarefa; não reinicia em um por reencontrar páginas pendentes.
Ao iniciar uma nova tarefa, a adaptação começa novamente. Oito é um teto, não garantia
de oito requisições ativas ou maior velocidade. Apenas downloads são concorrentes;
as transações SQLite e os checkpoints permanecem individuais e seriais.

Entre tentativas recuperáveis, a carga aplica espera progressiva:

```text
1 min -> 2 min -> 4 min -> 8 min -> máximo de 15 min
```

A espera progressiva é aplicada entre rodadas de recuperação. A exceção é o HTTP 429, cuja
pausa global imediata também vale durante a passagem primária. A tela mostra o motivo, lotes
pendentes, duração da espera e ciclo atual. Não há loop apertado nem consultas durante a
espera.

Respostas incompatíveis e paginação incoerente são catalogadas por página e não bloqueiam as
outras requisições. Registros individuais sem chave obrigatória continuam em
`data_rejection`, preservando seu conteúdo bruto. Exceções inesperadas de programação,
transação ou gravação permanecem fatais: ignorá-las poderia esconder corrupção ou perda de
dados.

## Catálogo de páginas adiadas

A tela **Erros e validações** mostra, para erros de contratações:

- identificador da execução e da unidade;
- número exato da página;
- intervalo de datas e modalidade;
- data, categoria, possibilidade de recuperação, mensagem e detalhe técnico.

O SQLite conserva todas as ocorrências. A interface carrega no máximo 200 por vez para não
travar e informa a relação entre itens exibidos e total, por exemplo `200 de 349`. O limite de
exibição não remove erros antigos.

## Pausa, fechamento e reinício

**Pausar** cancela a espera ou a requisição atual. Uma unidade sem commit volta para
`PENDING`. Ao abrir o programa, unidades deixadas como `RUNNING` por queda de energia ou
fechamento forçado também voltam para `PENDING`.

Uma tentativa interrompida antes de produzir resposta não consome definitivamente o orçamento
da página. Na recuperação, o contador é devolvido em uma unidade. Checkpoints antigos que
tenham ficado `PENDING` já no teto de tentativas também são reparados automaticamente, evitando
o estado inválido em que a página está pendente, mas nunca pode ser selecionada.

O estado `PAUSED` e a preferência `manual_pause` são reservados ao comando explícito do
usuário. HTTP 429, HTTP 5xx, timeout, páginas adiadas e rodadas de recuperação não podem
simular um clique em **Pausar** nem desativar a retomada automática.

Antes da primeira chamada de rede da carga completa, o programa grava no próprio SQLite o
intervalo, opções de conteúdo e limite de concorrência. Se o aplicativo ou o computador cair,
ao abrir novamente essa sessão é reconstruída e retomada automaticamente. Fechar o programa
também conserva essa intenção. Para impedir a retomada automática, o usuário deve clicar
**Pausar** antes de fechar; nesse caso a sessão permanece preservada e aguarda **Continuar**.

Ao retomar, o programa recalcula as mesmas janelas, pula as concluídas e continua o primeiro
checkpoint ausente. O banco é a fonte do progresso e da intenção de carga, não a memória da
interface.

## Indisponibilidade durante a carga histórica

O controlador conserva o nível adaptativo entre lotes, sem redução por falha isolada. Três
varreduras seguidas sem confirmar páginas acionam uma espera cancelável antes do próximo
lote (60 segundos inicialmente, com crescimento até 15 minutos). Uma página confirmada
zera essa sequência de indisponibilidade. O rodízio e os checkpoints são preservados;
essa espera não equivale a uma pausa manual nem resolve indisponibilidade do servidor PNCP.

## Progresso

A barra global usa contratações únicas já armazenadas divididas pelo total projetado pela
amostra ou pelos planos armazenados após o recálculo. O texto apresenta os dois números,
a quantidade aproximadamente restante e identifica
o percentual como estimado. A projeção é preservada no próprio banco e pode ser reutilizada
após reiniciar o aplicativo; se o escopo de datas mudar, uma nova estimativa é exigida.

Lotes percorridos e páginas confirmadas continuam exibidos separadamente como métricas exatas
de execução. Um lote percorrido pode ter páginas adiadas claramente indicadas; isso não as
transforma em cobertura confirmada. Essas métricas não controlam a porcentagem principal. Sem
estimativa válida, a barra não inventa percentual e orienta o usuário a executar **Estimar**.

Cada página é armazenada comprimida dentro do SQLite. O programa não cria um arquivo separado
para cada resposta.

**Recalcular projeção e pendências** lê um snapshot local consistente, sem novas chamadas
HTTP. Seleciona os mesmos planos da sessão histórica: cobertura concluída de cada recorte
tem preferência; caso contrário, usa seu checkpoint retomável mais recente. Planos
substituídos não são somados. Soma os totais das respostas de planejamento preservadas e
extrapola somente os lotes ainda sem total conhecido. O resultado substitui a projeção
antiga no banco e informa quantos lotes continuam desconhecidos.

Páginas confirmadas, pendentes, em execução e com falha são contagens do snapshot local.
O número de registros únicos ainda não recebidos **não é exato**: totais da API podem mudar
e uma página pode conter registros que já estão no banco. O recálculo não certifica a
conclusão do acervo nem atualiza os totais históricos junto ao PNCP.

**Recuperar páginas com falha** seleciona os lotes com FAILED ou RETRY_WAIT na sessão
histórica atual e retoma suas unidades não confirmadas. Inclui as páginas ainda pendentes
desses lotes; não repete SUCCEEDED e não apaga erros anteriores. Falhas antes classificadas
como definitivas recebem uma nova tentativa explícita; se continuarem definitivas, ficam
catalogadas. Falhas temporárias continuam no rodízio com espera. Pausar/Continuar conserva
checkpoints; após fechar, o botão pode ser acionado novamente. Não inicia outro coletor
enquanto houver uma sincronização ativa.

## Atualização incremental: novas e retificadas

O botão **Atualizar até hoje: novas e retificadas** inicia um ciclo sem exigir estimativa.
Ele fixa a data do clique, usa todas as modalidades e consulta duas fontes públicas:

- `/contratacoes/publicacao`: publicações recentes;
- `/contratacoes/atualizacao`: registros cuja data de atualização global está no período,
  mesmo quando a publicação original é de anos anteriores.

O contrato HTTP foi conferido no [OpenAPI oficial do PNCP](https://pncp.gov.br/api/consulta/v3/api-docs).
As datas são enviadas em `yyyyMMdd`, com modalidade e página. O ciclo incremental limita a
paginação entre 10 e 50 registros, conforme esse contrato, e divide o período em até sete dias
por lote. Não inclui itens, resultados, contratos, atas ou documentos: esses recursos não
passam a estar atualizados simplesmente porque a contratação principal foi atualizada.

### Datas e cobertura

O botão pode atualizar o período posterior ao escopo histórico já planejado mesmo quando
esse histórico tem lacunas. Essas lacunas são preservadas, não são marcadas como concluídas
e continuam precisando de recuperação separada. É necessário haver um planejamento histórico
para cada modalidade; um banco vazio não ganha uma cobertura inicial fictícia. A função
programática `prepare_incremental` mantém a exigência de cobertura integral por padrão;
o botão habilita explicitamente a atualização independente do histórico incompleto.

No botão, o fluxo de publicações começa no fim do escopo histórico planejado, com sobreposição.
No modo programático estrito, começa na data coberta. O fluxo de alterações
começa na data de início dessa carga, para incluir retificações feitas enquanto o histórico
estava sendo baixado. Nos ciclos seguintes, a marca é derivada somente de intervalos
incrementais contíguos e integralmente confirmados. `MAX(dataAtualizacaoGlobal)` não é cursor.

Ambos repetem o dia da marca e o anterior. Assim, podem ser recebidos alguns registros já
conhecidos, mas eles não são duplicados. Essa sobreposição também permite reler o dia atual,
que ainda recebe publicações. Não é possível prometer zero registros repetidos na rede:
o PNCP devolve páginas, não compara o conteúdo com o banco do usuário.

A sobreposição reduz riscos de mudanças na paginação, mas a API não oferece aqui um snapshot
imutável. Se os totais de páginas/registros mudarem durante um lote, ele não é considerado
integral: a falha fica catalogada e uma nova atualização explícita relê o intervalo. Publicações
retroativas ou correções não refletidas nas datas da fonte podem exigir reconciliação histórica.

### Persistência e retomada

`sync.incremental.v1`, em `app_preference`, guarda os pontos iniciais e a sessão com janelas,
data de criação, tamanho das páginas e pausa manual. Os checkpoints usam as tabelas existentes:

| Recurso | Finalidade |
| --- | --- |
| `contratacoes_publicacao` | Carga histórica já existente |
| `contratacoes_publicacao_incremental` | Novas publicações do ciclo incremental |
| `contratacoes_atualizacao` | Retificações por atualização global |

Esses recursos não compartilham planos. Uma nova sessão relê a sobreposição; uma retomada
mantém o período e o tamanho de página originais e reutiliza as páginas já confirmadas.
Um novo clique em Atualizar até hoje amplia uma sessão ativa com janelas posteriores até
a nova data, sem apagar suas janelas anteriores. Continuar não amplia silenciosamente o período.
Falhas temporárias seguem o rodízio e as esperas do motor da carga principal. Pausar preserva
a sessão; Continuar retoma o ciclo incremental. Ao abrir novamente, uma sessão interrompida
é retomada, exceto se houve pausa manual. A retomada da carga histórica tem prioridade caso
ela também esteja pendente e não tenha sido pausada manualmente. Um histórico pausado não
bloqueia a retomada de uma atualização incremental ativa.

Falhas definitivas e rejeições não avançam a cobertura do intervalo. Depois de revisar o
diagnóstico, uma nova atualização volta ao intervalo que continua sem cobertura integral.

### Identificação de alterações

O identificador PNCP é a chave de negócio. Registros desconhecidos são inseridos; hashes
SHA-256 diferentes geram atualização e evento `UPDATED`; hashes iguais não duplicam a
contratação nem reescrevem seus campos de negócio. O payload original continua preservado.
Uma resposta com versão anterior não substitui dados mais recentes. Uma alteração sem data
válida não substitui uma versão local datada: é preservada como rejeição.

Ausência em uma lista incremental **não significa exclusão** e nunca gera `MISSING`.
As operações são somente GET na origem. Essa funcionalidade reutiliza o esquema SQLite
existente e não exige migração de banco.

## Itens de licitações recentes ainda abertas

A sincronização possui uma barra independente para itens e resultados. Ela apresenta
unidades confirmadas sem rejeições, pendentes, com falha e parciais, além das quantidades
de itens e resultados recebidos no lote atual. O denominador é o total de unidades já
conhecidas: pode aumentar quando novas páginas ou resultados forem descobertos. Uma
falha não é contada como conclusão, e a barra das contratações não é substituída.

**Baixar itens e fornecedores** mantém a seleção original. A opção complementar
**Somente vigentes dos últimos 12 meses** restringe essa coleta às contratações publicadas
nos últimos 365 dias, com situação 1 (Divulgada no PNCP) e prazo de propostas igual ou
posterior ao instante do planejamento. Datas sem fuso são interpretadas em Brasília.
Prazo ausente ou inválido, suspensão e encerramento excluem o registro desta seleção.
É um critério operacional de oportunidades abertas, não de vigência de contratos.

O filtro é aplicado no planejamento dos detalhes, não no download da carga principal.
Planos de itens já existentes conservam a seleção original ao retomar. Itens antigos já
armazenados não são apagados. Fornecedores são obtidos dos resultados publicados dos itens;
licitações abertas podem não ter resultados ou vencedores disponíveis ainda.

Para coletar sobre o acervo que já foi carregado sem itens, o CLI oferece:

```powershell
python -m pncp_sync.cli --db "A:/Projetos/pncp-dados/pncp.sqlite3" plan-recent-details
python -m pncp_sync.cli --db "A:/Projetos/pncp-dados/pncp.sqlite3" --timeout 90 --retries 8 run-recent-details
```

O primeiro comando seleciona o acervo local inteiro, sem chamadas HTTP. O segundo coleta
itens e resultados; recusa iniciar enquanto uma sessão histórica ou incremental estiver
ativa. Deve haver somente um coletor de itens executando. Nenhum PDF é baixado.

`sync.recent_details.v1` guarda a referência temporal e os IDs dos planos. A seleção e o
checkpoint são gravados na mesma transação. Cada contratação pertence a um único plano
da seleção, associado ao payload que a originou. A seleção fica no SQLite, não numa lista
de todas as contratações em memória Python. Repetir o comando reutiliza essa seleção,
inclusive se concluída; não cria silenciosamente um novo ciclo de itens.

A coleta percorre uma unidade de cada plano por rodada. Falhas temporárias são catalogadas
e adiadas com espera progressiva persistida no SQLite, sem teto de três rodadas. As demais
unidades continuam. Falhas definitivas e rejeições permanecem visíveis e não são anunciadas
como conclusão integral. Fechar ou interromper preserva commits; executar o mesmo comando
retoma as unidades pendentes. Não há um serviço do sistema que abra o aplicativo sozinho.
