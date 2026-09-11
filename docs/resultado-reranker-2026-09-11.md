# Resultado do piloto de reranker — 11/09/2026

## Conclusão

O reranker melhorou exemplos importantes de ordenação, mas não eliminou
ruído e apresentou regressões. **A configuração quantizada em lote não
foi aprovada para integração à pesquisa do aplicativo.** A verificação
detectou dependência das pontuações em relação à composição do lote.
Uma comparação pequena com os pesos float32 não apresentou essa variação.

O banco principal não foi aberto por este experimento. Os 10 mil vetores
já existentes foram reutilizados, sem recalculá-los. A interface e o
executável não receberam alteração de busca semântica nesta etapa.

## Execução medida

Ambiente: Ryzen 5 2600, 16 GB de RAM, CPU, duas threads de inferência,
ONNX Runtime 1.30.0, lotes de quatro pares e limite de 512 tokens.
O ambiente Python é o mesmo registrado em `requirements-semantic-pilot.txt`.
Modelo, revisão e comandos: [piloto-reranker.md](piloto-reranker.md).

| Medida | Resultado |
|---|---:|
| Registros na amostra congelada | 10.000 |
| Consultas | 50 |
| Candidatos por consulta | 30 |
| Pares pontuados | 1.500 |
| Reordenação, média por consulta | 4.048,42 ms |
| Reordenação, mediana | 3.928,32 ms |
| Reordenação, p95, posição 48 de 50 | 5.894,65 ms |
| Reordenação, pior consulta | 6.415,81 ms |
| Recuperação + reordenação, média | 4.063,54 ms |
| Soma do tempo das 50 reordenações | 202,42 s |
| Download/carregamento inicial do reranker | 6,88 s |
| Cache inicial dos pesos quantizados e tokenizador | 135.710.104 bytes |
| Pico do processo informado pelo Windows | 943.841.280 bytes, aproximadamente 900 MiB |

Os tempos acima são da variante quantizada, **não** da float32. O pico
inclui a execução de preparação/recuperação, não apenas os pesos do
reranker. O E5 foi liberado antes de carregar o segundo modelo. A soma
de tempos de etapas não é uma medição da interface nem de ambos os
modelos carregados simultaneamente. Resultados de latência não foram
extrapolados para milhões de registros.

## Casos concretos: avanços e regressões

Posições na tabela são de listas distintas: semântica original, híbrida
RRF e híbrida seguida do reranker quantizado. “Fora do top 10” não
significa ausente do conjunto de 30 candidatos.

| Pesquisa / contratação | Semântica | Híbrida | Após reranker |
|---|---:|---:|---:|
| Computadores escolares: serviço correto de Piçarra | Fora do top 10 | 4 | 1 |
| Computadores escolares: reparo de telhado | 1 | 1 | 4 |
| Aluguel de impressoras: locação com manutenção em Jacutinga | 6 | 21 | 1 |
| Aluguel de impressoras: manutenção de empilhadeira | 1 | 17 | 19 |
| Limpeza de prédios: mão de obra em Prudentópolis | 1 | 1 | 1 |
| Limpeza de prédios: compra de materiais em Chapecó | Fora do top 10 | 4 | 2 |
| Limpeza de prédios: limpeza da Câmara de Pindobaçu | 2 | 9 | 12 |
| Controle de pragas em escolas: rede de ensino de Itatiaia | 1 | 3 | 1 |

Identificadores para replicar a conferência:

- Q01 — Piçarra: `01612163000198-1-000016/2024`, ID local `1450147`.
  Objeto explicita reparação e manutenção de computadores e periféricos
  destinados aos alunos da rede municipal. O reranker trouxe ao primeiro lugar.
- Q01 — telhado: `07954480000179-1-016279/2026`, ID `3530174`.
  O complemento descreve telhas, ripas e caibros. Caiu para quarto,
  **mas continuou no top 10**, apesar de não atender à pesquisa por computadores.
- Q03 — Jacutinga: `87613394000131-1-000009/2025`, ID `1703519`.
  Locação de equipamentos de impressão/fotocópias com manutenção.
  Estava no candidato 21; restringir previamente a dez candidatos o excluiria.
- Q03 — empilhadeira: `06190522000180-1-000210/2024`, ID `1985167`.
  Manutenção de empilhadeira elétrica. O híbrido já a havia rebaixado;
  o reranker a rebaixou mais. Não atribuir ao reranker todo o ganho.
- Q08 — Prudentópolis: `77003424000134-1-000352/2024`, ID `2147441`.
  Limpeza/conservação/copeiragem com dedicação exclusiva de mão de obra.
- Q08 — Chapecó: `83021808000182-1-000049/2024`, ID `603573`.
  Compra de material de higiene e limpeza: não atende ao critério de
  serviço/equipe. **Subiu**, demonstrando que o reranker também pode piorar.
- Q08 — Pindobaçu: `13222500000110-1-000002/2025`, ID `2799861`.
  Limpeza/manutenção do prédio da Câmara. Caiu de segundo na semântica
  para fora dos dez primeiros após a sequência híbrida + reranker.
- Q10 — Itatiaia: `53970845000176-1-000019/2025`, ID `2582230`.
  Controle de pragas para a rede de ensino; voltou ao primeiro lugar.

Essas classificações são inspeção preliminar do assistente, baseada nos
textos da amostra. Não são julgamentos humanos independentes, verificação
jurídica dos editais ou uma taxa global de precisão. As 50 consultas têm
rankings, mas não têm todas as respostas julgadas.

## Verificação que impediu a aprovação da variante compacta

Repetiram-se 14 pares de três consultas (Q01, Q03, Q08), primeiro em
lotes de até quatro e depois individualmente. Foram preservados query,
texto, modelo, tokenizador, limite de tokens e threads.

| Consulta | Maior diferença absoluta do logit, int8 | Ordem int8 igual? | Diferença float32 |
|---|---:|---|---:|
| Q01 | 0,841436 | Não | 0 |
| Q03 | 0,919025 | Não | 0 |
| Q08 | 0,335613 | Não | 0 |

No int8, houve troca do primeiro resultado em Q01 e Q08 entre as duas
formas de agrupar os pares. No float32, os escores e a ordem foram iguais
nessas três verificações. Isso aponta para a variante quantizada, não
para troca dos IDs ou instabilidade dos vetores E5, como explicação para
a variação observada. Não prova estabilidade em todos os textos possíveis.

O float32 foi testado **apenas nesses 14 pares**, não nas 50 pesquisas
com 30 candidatos cada. Não há benchmark completo de custo/qualidade dele.
Ele também manteve materiais de limpeza em posição alta no pequeno
conjunto Q08: estabilidade numérica não resolve sozinha a relevância.

A checagem float32 baixou mais 470.883.696 bytes de pesos. O cache do
reranker passou a conter cerca de **606,6 MB**, pois preserva as duas
variantes e compartilha o tokenizador. Isso é adicional ao piloto E5 já
existente; não é aumento do tamanho do executável distribuído.

## Reprodutibilidade e testes

Os comandos estão em [piloto-reranker.md](piloto-reranker.md).
Para repetir a checagem sem sobrescrever o resultado int8:

```powershell
.\.venv-semantic\Scripts\python.exe -m pncp_sync.semantic.verify_rerank_pilot `
  --output .semantic-pilot\rerank --float32
```

Artefatos locais em `.semantic-pilot/rerank/`:

- `evaluation.json`, SHA-256
  `16bdb836daee05907145d62dda83253da581ecf0f980813d9bf984740a4dfea2`;
- `report.json`: métricas das 50 consultas quantizadas;
- `verification.json`: escores e ordens int8, por par;
- `verification-float32.json`: comparação float32;
- `review.html`: semântica, híbrida e reranker, com links oficiais e notas exportáveis;
- `state.sqlite3`: 50 consultas confirmadas, retomáveis.

Hash do banco experimental congelado:
`0e6e5689c88e4e275fda9a62f80b35f1e161bda9533129c10926f6f3dccb3efa`.
Hash dos pesos int8:
`6c2513767fb63d008a4377bef7a7a3555433d9436342bb53e35a3a72ffc52d4b`.
Hash dos pesos float32:
`3e9a03ed1e966f7c5288dd4230e3d6a9bf5e3a170a06f1f4241c5bca12c6487c`.

Validação do código: **36 testes aprovados** em `test_embeddings.py`,
`test_semantic_pilot.py`, `test_rerank_pilot.py` e `test_data_services.py`.
Incluem retomada sem repetir consultas confirmadas, rejeição de resultados
incompletos/não finitos, associação entre IDs e escores, preservação da
ordem em empate, bloqueio de configuração diferente e HTML escapado.
Ruff aprovado. Esses testes verificam implementação, não precisão semântica.

## Próxima decisão técnica

Antes de integrar qualquer reranker, a comparação precisa incluir custo
do float32 e relevância julgada nos mesmos candidatos. Reduzir candidatos
ou comprimento dos textos pode diminuir a latência, mas deve ser medido
contra perda de resultados, como o caso de Jacutinga. Distinguir aquisição
de materiais de contratação de serviços permanece um problema a validar.
Não foi iniciado treinamento nem vetorização do acervo completo.
