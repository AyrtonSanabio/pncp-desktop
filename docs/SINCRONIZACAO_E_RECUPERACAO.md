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
3. baixa e confirma uma página por vez;
4. conclui o lote antes de avançar ao seguinte.

## Falhas temporárias

Timeout, desconexão, HTTP 429 e erros HTTP 5xx são recuperáveis. A página não confirmada é
mantida no banco. A carga completa repete automaticamente a mesma unidade até funcionar ou
até o usuário clicar **Pausar**.

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

A barra global usa lotes concluídos mais a fração de páginas confirmadas no lote atual. Ela
mostra lotes restantes, período, modalidade e páginas/respostas restantes no lote. Páginas
de lotes futuros só são conhecidas quando o PNCP responde; qualquer total nacional exibido
antes disso é identificado como aproximação amostral.

Cada página é armazenada comprimida dentro do SQLite. O programa não cria um arquivo separado
para cada resposta.
