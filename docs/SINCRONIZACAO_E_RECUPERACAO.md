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
gradualmente até o limite de concorrência escolhido. Quando um grupo apresenta falha, seus
resultados são catalogados, as páginas restantes continuam pendentes e a execução vai para o
fim da fila. Assim, dezenas de páginas com HTTP 504 não monopolizam a carga nem limitam os
lotes saudáveis a rodadas pequenas. O HTTP 429 recebe tratamento mais conservador: toda a
carga aguarda 60 segundos antes de consultar outro lote, evitando transformar a limitação do
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

No modo acelerado, qualquer falha de rede reduz imediatamente a concorrência para 1. Se as
tentativas da página se esgotarem, o ciclo seguinte também começa em 1; ele não volta direto
ao teto. A concorrência só sobe depois de oito páginas confirmadas sem erro. Assim, quatro é
um teto, não uma pressão constante sobre o PNCP.

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

## Progresso

A barra global usa contratações únicas já armazenadas divididas pelo total projetado pela
amostra. O texto apresenta os dois números, a quantidade aproximadamente restante e identifica
o percentual como estimado. A projeção é preservada no próprio banco e pode ser reutilizada
após reiniciar o aplicativo; se o escopo de datas mudar, uma nova estimativa é exigida.

Lotes percorridos e páginas confirmadas continuam exibidos separadamente como métricas exatas
de execução. Um lote percorrido pode ter páginas adiadas claramente indicadas; isso não as
transforma em cobertura confirmada. Essas métricas não controlam a porcentagem principal. Sem
estimativa válida, a barra não inventa percentual e orienta o usuário a executar **Estimar**.

Cada página é armazenada comprimida dentro do SQLite. O programa não cria um arquivo separado
para cada resposta.
