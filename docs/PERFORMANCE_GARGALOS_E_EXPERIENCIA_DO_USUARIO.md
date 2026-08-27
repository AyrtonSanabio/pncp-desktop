# Performance, gargalos e experiência do usuário

## Resumo executivo

Com o banco local já populado, as consultas são a parte mais barata do sistema. Em uma medição com 94 contratações e 94 vetores, a pesquisa FTS5 levou aproximadamente 2 ms, a busca por similaridade aproximadamente 9 ms e uma agregação simples aproximadamente 1 ms.

Os gargalos aparecem antes:

1. primeira população do banco: rede, limites e instabilidade do PNCP;
2. enriquecimento: chamadas de itens, resultados, documentos e histórico;
3. primeira geração de vetores: CPU, RAM, modelo e escrita do índice.

Depois disso, a atualização deve ser incremental e recalcular somente registros novos ou alterados.

## Onde o tempo é gasto

### População principal

Cada página precisa ser consultada, validada, normalizada, preservada e gravada. A velocidade depende principalmente da API e da conexão do usuário. Uma carga grande pode levar de minutos a horas.

### Itens, resultados e documentos

Uma contratação pode exigir várias chamadas adicionais. Esse é o risco de muitas requisições pequenas (N+1). A mitigação é usar fila limitada, checkpoints, cache, retomada e prioridades. Documentos devem começar por metadados e links; o conteúdo binário/PDF não deve ser baixado automaticamente.

### Vetores

O índice atual é econômico e local. Um modelo neural multilíngue seria opcional: pesos em torno de 470–500 MB, acréscimo de centenas de MB a mais de 1 GB de RAM durante a geração e tempo proporcional ao número de textos. Vetores de 384 dimensões ocupam cerca de 1.536 bytes em `float32` ou cerca de 384 bytes em `int8`, antes do overhead do banco.

## Cuidados de implementação

- A interface nunca deve esperar por rede, SQL, geração de vetores ou análise.
- Toda operação longa precisa mostrar etapa, progresso, velocidade, previsão e possibilidade de pausa.
- Checkpoints devem ser gravados por unidade; uma falha não pode duplicar nem pular dados.
- O marcador incremental só avança após cobertura completa e validada.
- Uma ausência em uma execução não prova que o órgão excluiu um registro; deve ser apresentada como indicação para conferência.
- Migrações devem ser aditivas e precedidas por backup verificável.
- Respostas HTTP, JSON, URLs e textos precisam de limites defensivos.
- O modelo e a versão dos vetores devem ser registrados para permitir reconstrução.
- O modelo semântico deve ser descarregável e o programa deve continuar funcionando sem ele.
- A precisão deve ser medida com consultas reais e marcações de relevância, não presumida pela pontuação.

## Como reduzir a complexidade percebida

O usuário não precisa escolher páginas, endpoints, dimensões ou estratégias de retry. A interface deve oferecer poucos fluxos orientados por objetivo:

### Fluxo inicial

1. “Escolha o que sua empresa procura”.
2. “Escolha região e período”.
3. “Estimar carga”.
4. “Iniciar sincronização”.
5. “Ver oportunidades encontradas”.

Configurações avançadas podem ficar atrás de “Opções técnicas”.

### Progresso em linguagem de negócio

Mostrar “Baixando contratações do período” em vez de nomes de endpoints. Exibir “423 de 1.200 páginas” e “previsão: hoje às 18:40”, mantendo detalhes técnicos em uma seção expansível.

### Separar ações perigosas ou demoradas

Sincronizar, criar índice, fazer backup e reparar banco devem ser botões diferentes. Cada um deve explicar duração, espaço e se usa internet.

### Resultados com confiança explícita

Não mostrar somente “50 resultados”. Mostrar:

- correspondência alta, média ou baixa;
- pontuação relativa;
- motivo da correspondência;
- filtros aplicados;
- botão “relevante” e “ruído”.

Isso evita que o usuário interprete similaridade como certeza jurídica ou comercial.

A busca semântica agora oferece uma pontuação mínima ajustável. O valor é relativo ao conjunto indexado e não representa porcentagem ou probabilidade. Um limiar maior reduz ruído, mas pode esconder candidatos úteis; por isso o usuário deve comparar consultas e validar os primeiros resultados antes de escolher um valor.

### Padrões seguros

- Busca textual funciona sem modelo semântico.
- Modelo semântico é baixado somente com consentimento.
- PDFs não são baixados por padrão.
- Dados são gravados na pasta escolhida pelo usuário.
- Backup e restauração são visíveis e reversíveis.
- O aplicativo informa origem, atualização e cobertura dos dados.

## Evolução recomendada

1. consolidar sincronização observável e retomável;
2. validar incremental e deltas;
3. ampliar detalhes e links sem baixar PDFs;
4. melhorar filtros, perfis e feedback de relevância;
5. medir precisão com dados reais;
6. só então comparar o índice econômico com um modelo neural multilíngue;
7. usar índice vetorial especializado apenas quando a escala justificar.

O marco automático atual também gera uma classificação local por categorias (TI, saúde, limpeza/conservação, construção, transporte ou outros), extrai palavras-chave e identifica padrões de CATMAT, CATSER, NCM e NBS. Essas sugestões são heurísticas para organizar a pesquisa; não substituem a leitura do edital.

A busca híbrida combina filtros estruturados com a lista de candidatos do banco e a pontuação de similaridade. O mesmo módulo também identifica candidatos a duplicidade por órgão e objeto. Esses recursos são auxiliares: não afirmam que duas contratações são juridicamente a mesma nem substituem a conferência do identificador PNCP.

O objetivo é manter a complexidade interna alta quando necessário, mas expor ao usuário uma sequência curta, explicável e segura.
