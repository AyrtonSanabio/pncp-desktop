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
5. cataloga páginas que esgotaram as tentativas e avança ao lote seguinte sem
   descartar o índice da pendência.

O seletor **Downloads simultâneos** oferece 1, 2 ou 4. O modo 1 usa o motor sequencial
original. Acima de 1, um motor separado paraleliza somente a rede: normalização e escrita
continuam seriais. O modo acelerado começa com duas páginas, sobe gradualmente após grupos
de sucessos e nunca ultrapassa o limite escolhido.

## Falhas temporárias

Timeout, desconexão, HTTP 429, erros HTTP 5xx e validações HTTP devolvidas pelo PNCP
participam de tentativas finitas. A página não confirmada é mantida no banco pelo número,
intervalo, modalidade, quantidade de tentativas e diagnóstico. A execução tenta novamente a
mesma página até o limite configurado; se ainda falhar, marca a unidade como `FAILED` e segue
para as próximas páginas.

Na carga completa, uma página `FAILED` também não impede a passagem para os lotes seguintes.
Ela permanece ligada à execução em `work_unit` e cada ocorrência fica em `ingestion_error`.
Ao usar **Continuar** ou iniciar novamente o mesmo escopo, falhas recuperáveis são reabertas;
páginas já confirmadas não são baixadas novamente.

No modo acelerado, qualquer falha de rede reduz imediatamente a concorrência para 1. Se as
tentativas da página se esgotarem, o ciclo seguinte também começa em 1; ele não volta direto
ao teto. A concorrência só sobe depois de oito páginas confirmadas sem erro. Assim, quatro é
um teto, não uma pressão constante sobre o PNCP.

Entre tentativas recuperáveis, a carga aplica espera progressiva:

```text
1 min -> 2 min -> 4 min -> 8 min -> máximo de 15 min
```

Se alguma página avançar, a sequência volta para um minuto. A tela mostra o motivo, páginas
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
