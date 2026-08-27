# Visão do sincronizador do PNCP

## De onde surgiu a ideia

O desenvolvedor do `pypncp` explicou que o uso mais valioso da biblioteca não é apenas fazer uma consulta pontual. O objetivo mais ambicioso é ajudar quem precisa popular um banco com os dados do PNCP, atualizar esse banco continuamente e criar um índice vetorial sobre a descrição dos itens.

A frase “um scraper completo, com zero complexidade” descreve a experiência desejada para o usuário, não a complexidade interna do programa. Por dentro haverá rede, paginação, persistência, retomada, deduplicação e monitoramento. Por fora, queremos chegar a algo parecido com:

```powershell
pncp-sync iniciar
pncp-sync status
pncp-sync atualizar
```

O programa deve esconder a operação difícil sem esconder erros, limites e procedência dos dados.

## Biblioteca versus produto de dados

O `pypncp` é um cliente Python assíncrono. Ele fornece objetos e métodos para consultar contratos, contratações e atas, além de paginação automática. Algumas áreas, como busca do catálogo e preços, usam endpoints internos identificados por engenharia reversa e precisam ser tratadas como experimentais.

O sincronizador será outro software, construído sobre a biblioteca:

| Responsabilidade | `pypncp` | Sincronizador |
|---|---:|---:|
| Montar requisições e converter respostas | Sim | Usa a biblioteca |
| Iterar páginas da API | Sim | Decide como particionar e retomar |
| Manter histórico da execução | Não | Sim |
| Gravar e atualizar banco | Não | Sim |
| Evitar duplicatas entre execuções | Não | Sim |
| Detectar dados removidos ou retificados | Não | Sim |
| Medir completude da carga | Não | Sim |
| Criar embeddings e índice vetorial | Não | Sim |
| Oferecer operação simples | Não é seu objetivo | Sim |

## Qual problema o software resolve

Consulta pontual responde “quais contratos foram publicados neste período?”. Um espelho local permite responder perguntas que exigem cruzar milhões de registros, repetir análises e pesquisar sem depender de várias chamadas ao PNCP:

- quais órgãos compram itens semanticamente parecidos;
- como descrições diferentes representam o mesmo tipo de produto;
- quais fornecedores venceram itens semelhantes;
- quanto um item custou ao longo do tempo;
- quais registros mudaram desde a última sincronização;
- quais modalidades, regiões ou órgãos concentram determinado objeto;
- quais dados ainda estão ausentes no espelho local.

## O que significa “popular um banco inteiro”

Não significa fazer uma única requisição gigantesca. Significa executar muitas unidades pequenas e rastreáveis até cobrir os recursos escolhidos:

```text
recurso
    -> período
        -> modalidade, quando exigida
            -> página
                -> registro principal
                    -> detalhes, itens, resultados e documentos
```

Também significa manter o espelho atualizado. Uma primeira carga completa, chamada de carga histórica ou `backfill`, é apenas o começo. Depois precisamos buscar inclusões e atualizações recentes, reprocessar janelas de segurança e corrigir registros que a fonte tenha retificado.

“Inteiro” deve sempre ser qualificado. Precisaremos publicar uma definição de cobertura, por exemplo:

- recursos incluídos;
- primeira data coberta;
- modalidades percorridas;
- campos e documentos armazenados;
- instante da última sincronização bem-sucedida;
- falhas ou lacunas ainda conhecidas.

Sem essa definição, ninguém consegue provar que o banco está completo.

## O que é o índice vetorial sobre item

Um item pode aparecer como “microcomputador portátil”, “notebook corporativo” ou “computador portátil”. Uma busca textual exata pode não perceber que as descrições são próximas.

Um modelo de embeddings transforma o texto do item em uma lista de números, chamada vetor. Textos com sentidos parecidos tendem a produzir vetores próximos. O índice vetorial acelera a procura pelos vetores mais próximos.

```text
descrição original do item
    -> limpeza controlada do texto
        -> modelo de embeddings identificado por nome e versão
            -> vetor
                -> índice de vizinhos próximos
```

O vetor não substitui os dados originais. Cada resultado semântico precisa continuar ligado ao item, à contratação e ao identificador oficial.

Também não começaremos por ele. Se os itens estiverem incompletos, duplicados ou ligados à contratação errada, o índice apenas tornará o erro mais rápido de consultar.

## Quem usaria o produto

- equipes de dados que precisam de uma cópia consultável do PNCP;
- pesquisadores e órgãos de controle;
- empresas que analisam oportunidades e histórico de compras;
- desenvolvedores de sistemas de inteligência sobre contratações;
- mantenedores do `pypncp`, para validar desempenho em cargas reais;
- pessoas sem experiência em pipelines, se entregarmos uma operação simples no futuro.

## Escopo ativo

O núcleo ativo contém:

- inventário dos endpoints oficiais utilizáveis pelo `pypncp`;
- coleta paginada por janelas pequenas;
- concorrência limitada e respeitosa;
- armazenamento bruto e normalizado;
- banco relacional com chaves e restrições;
- checkpoints, retomada e idempotência;
- sincronização histórica e incremental;
- métricas, logs e relatório de cobertura;
- itens e resultados ligados às contratações;
- embeddings e índice vetorial em uma fase posterior;
- uma CLI mínima para iniciar, acompanhar e retomar a carga.

## Fora do foco atual

- publicar, retificar ou excluir qualquer dado no PNCP;
- autenticação como plataforma publicadora;
- integrar outras bases do governo;
- criar novas bibliotecas para outras APIs;
- transformar a interface desktop em produto final;
- emitir parecer jurídico, declarar empresa habilitada ou substituir uma fonte oficial;
- baixar indiscriminadamente páginas HTML quando uma API pública atende à necessidade;
- prometer cobertura total antes de medir e auditar a carga.

As ideias laterais continuam em [Melhorias futuras](melhorias-futuras/README.md).

## Princípios do projeto

### Correção antes de velocidade

Uma carga rápida que duplica ou perde registros não é uma melhoria. Primeiro estabelecemos chaves, retomada, testes e métricas; depois aumentamos concorrência e tamanho dos lotes.

### Idempotência como requisito

Executar duas vezes a mesma unidade de trabalho deve resultar no mesmo estado final. Esse princípio permite repetir períodos após timeout, queda de energia ou mudança no código.

### Dado bruto preservado

O formato normalizado facilita consulta, mas pode perder detalhes ou interpretar campos incorretamente. Guardar a resposta original, com procedência e data, permite auditoria e reprocessamento.

### Simplicidade na entrada, transparência na saída

O usuário não deve configurar dezenas de parâmetros para começar. Ainda assim, o software precisa mostrar progresso, falhas, última atualização, lacunas e consumo de recursos.

### API oficial primeiro

Contratos, contratações e atas possuem consultas oficiais. Endpoints internos de busca e preços podem ser úteis, mas ficam isolados até termos testes de contrato e uma política para quebras.

### Busca híbrida

Filtros exatos respondem por CNPJ, data, modalidade, UF e identificadores. Busca textual encontra palavras. Busca vetorial encontra proximidade semântica. O produto sério combina as três.

## Como saberemos que a ideia começou a funcionar

A primeira prova não será uma tela bonita nem “baixamos muitos dados”. Será uma execução pequena com evidências:

- janela e modalidade conhecidas;
- total de páginas e registros observado;
- dados brutos e normalizados ligados por identificador;
- interrupção proposital seguida de retomada correta;
- segunda execução sem aumento indevido na quantidade de registros;
- contagem de inseridos, atualizados, ignorados e rejeitados;
- log das requisições e erros sem credenciais ou dados pessoais desnecessários;
- consulta SQL que reconstrói os registros da janela;
- relatório de cobertura da unidade processada.

Depois dessa prova, poderemos aumentar o período e descobrir o custo real de construir o espelho completo.

## Afirmações que ainda precisam ser verificadas

A observação de que “ninguém fez isso” deve ser entendida como percepção do desenvolvedor, não como fato comprovado. Antes de posicionar o produto, pesquisaremos projetos existentes, conjuntos de dados derivados, licenças, cobertura, atualização e limitações.

Também ainda não sabemos:

- o volume total por recurso e por ano;
- o limite de requisições sustentável do PNCP;
- quantos detalhes exigem chamadas adicionais;
- como identificar exclusões ou registros que deixam de aparecer;
- o custo de armazenamento bruto, índices e embeddings;
- qual modelo de embeddings representa melhor descrições públicas em português;
- se a instalação local no Windows será o produto principal ou apenas o ambiente de desenvolvimento.

Essas dúvidas são parte do trabalho da fase de descoberta, não falhas do planejamento.
