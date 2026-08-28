# Sincronização e recuperação

## Sincronização parcial

O usuário escolhe datas e uma modalidade. **Estimar** consulta a primeira página, valida a
paginação e calcula respostas, registros, espaço e tempo. **Sincronizar** executa as páginas
planejadas. Falhas recuperáveis podem ser retomadas pelo botão **Continuar**.

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
5. conclui o lote antes de avançar ao seguinte.

O seletor **Downloads simultâneos** oferece 1, 2 ou 4. O modo 1 usa o motor sequencial
original. Acima de 1, um motor separado paraleliza somente a rede: normalização e escrita
continuam seriais. O modo acelerado começa com duas páginas, sobe gradualmente após grupos
de sucessos e nunca ultrapassa o limite escolhido.

## Falhas temporárias

Timeout, desconexão, HTTP 429 e erros HTTP 5xx são recuperáveis. A página não confirmada é
mantida no banco. A carga completa repete automaticamente a mesma unidade até funcionar ou
até o usuário clicar **Pausar**.

No modo acelerado, qualquer falha de rede reduz imediatamente a concorrência para 1. Ela
só volta a subir depois de oito páginas confirmadas sem erro. Assim, quatro é um teto, não
uma pressão constante sobre o PNCP.

Depois que as tentativas curtas da página se esgotam, a carga contínua aplica espera
progressiva:

```text
1 min -> 2 min -> 4 min -> 8 min -> máximo de 15 min
```

Se alguma página avançar, a sequência volta para um minuto. A tela mostra o motivo, páginas
pendentes, duração da espera e ciclo atual. Não há loop apertado nem consultas durante a
espera.

Erros não recuperáveis — por exemplo JSON incompatível, paginação incoerente ou registro sem
chave obrigatória — interrompem o fluxo e permanecem no diagnóstico. Repetir indefinidamente
esses erros esconderia um problema de dados ou de código.

## Pausa, fechamento e reinício

**Pausar** cancela a espera ou a requisição atual. Uma unidade sem commit volta para
`PENDING`. Ao abrir o programa, unidades deixadas como `RUNNING` por queda de energia ou
fechamento forçado também voltam para `PENDING`.

Ao reiniciar a carga completa, o programa recalcula as mesmas janelas, pula as concluídas e
continua o primeiro checkpoint ausente. O banco é a fonte do progresso, não a memória da
interface.

## Progresso

A barra global usa contratações únicas já armazenadas divididas pelo total projetado pela
amostra. O texto apresenta os dois números, a quantidade aproximadamente restante e identifica
o percentual como estimado. A projeção é preservada no próprio banco e pode ser reutilizada
após reiniciar o aplicativo; se o escopo de datas mudar, uma nova estimativa é exigida.

Lotes concluídos e páginas confirmadas continuam exibidos separadamente como métricas exatas
de execução. Eles não controlam mais a porcentagem principal. Sem estimativa válida, a barra
não inventa percentual e orienta o usuário a executar **Estimar**.

Cada página é armazenada comprimida dentro do SQLite. O programa não cria um arquivo separado
para cada resposta.
