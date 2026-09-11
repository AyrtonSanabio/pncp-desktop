# Piloto de reordenação de resultados

**Estado do teste:** a variante quantizada em lote não foi aprovada para
integração. Os motivos e medidas estão em
[resultado-reranker-2026-09-11.md](resultado-reranker-2026-09-11.md).

Este experimento reutiliza os 10 mil registros e vetores do piloto E5.
Não está integrado à interface, não altera o banco principal, não baixa
documentos e não envia textos a serviços de inferência. A rede é utilizada
para obter os arquivos públicos do modelo; as pontuações são calculadas
localmente em CPU.

## Modelo e recuperação

O modelo é [cross-encoder/mmarco-mMiniLMv2-L12-H384-v1](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1),
multilíngue, licença declarada Apache-2.0. Usa-se a exportação ONNX oficial
`onnx/model_quint8_avx2.onnx`, revisão fixa
`1427fd652930e4ba29e8149678df786c240d8825`, com tokenizador da mesma revisão.
Não se executa código Python fornecido pelo repositório do modelo.

Para cada uma das 50 consultas:

1. O E5 codifica a frase. Produto interno em vetores normalizados recupera
   os primeiros 50 resultados semânticos da amostra.
2. FTS5 recupera até 50 resultados pela expressão OR, com BM25.
3. RRF soma `1 / (60 + posição)` das duas listas e seleciona 30 candidatos.
4. O cross-encoder recebe pares `(consulta, texto da contratação)` e pontua
   esses mesmos 30 candidatos. Os dez maiores escores são apresentados.

Escores são logits, não probabilidades ou porcentagens. Em empate,
preserva-se a ordem híbrida. O modelo processa no máximo 512 tokens por
par, com truncamento `longest_first`, padding e máscara de atenção. O
texto é o mesmo do piloto inicial: objeto, complemento e metadados.
O critério `intent` serve para julgamento, mas **não entra no modelo**.

Um reranker não consegue recuperar um registro excluído pelos primeiros
estágios. Também pode continuar promovendo respostas relacionadas, mas
inadequadas à intenção. Não existe filtro de confiança calibrado neste teste.

## Execução

Requer a amostra já vetorizada e o ambiente opcional documentado em
[piloto-vetorial.md](piloto-vetorial.md). Nenhuma nova biblioteca foi
adicionada às dependências do aplicativo; ONNX Runtime, tokenizers e
Hugging Face Hub já fazem parte desse ambiente isolado.

```powershell
$env:OMP_NUM_THREADS = '2'
$env:OPENBLAS_NUM_THREADS = '2'
.\.venv-semantic\Scripts\python.exe -m pncp_sync.semantic.rerank_pilot `
  --pilot .semantic-pilot `
  --queries docs\semantic-pilot-queries.json `
  --output .semantic-pilot\rerank `
  --candidates 30 --batch-size 4 --threads 2
```

O SQLite de entrada é aberto com `mode=ro` e `query_only`. A matriz ocupa
apenas a amostra, não milhões de registros. O processo de preparação
libera o E5 antes de carregar o reranker; por isso a soma dos tempos de
consulta é uma composição de etapas, não medição da interface com ambos
os modelos residentes. Há aquecimento antes de medir o reranker.

## Retomada e arquivos

`state.sqlite3` guarda o manifesto e a resposta completa de cada consulta
em transação SQLite com `synchronous=FULL`. Uma interrupção no meio de
uma consulta repete apenas aquela consulta; as anteriores são reutilizadas.
Mudanças no hash da amostra, arquivo de consultas, modelo/revisão,
número de candidatos, lote ou threads impedem reutilização silenciosa.
Locks evitam duas execuções simultâneas sobre o mesmo experimento.

Não altere manualmente os artefatos. Para uma configuração diferente,
use outra pasta de saída. Estes arquivos são experimentais, não um
segundo banco de produção.

- `candidates.json`: candidatos congelados, textos e tempos de recuperação;
- `state.sqlite3`: checkpoints das pesquisas;
- `evaluation.json`: rankings antes/depois, candidatos e pontuações;
- `report.json`: manifesto, hashes dos arquivos do modelo, tempos e memória;
- `review.html`: comparação com seletores de relevância e links ao PNCP;
- `verification.json`: repetição de pares individualmente e em lote.

`rerank_scores` segue a ordem de `candidates`. `reranked_all` contém os
mesmos IDs reordenados. Não confundir a posição desses dois arrays.

```powershell
.\.venv-semantic\Scripts\python.exe -m pncp_sync.semantic.verify_rerank_pilot `
  --output .semantic-pilot\rerank
```

Com `--float32`, a verificação usa `onnx/model.onnx` da mesma revisão,
baixa esses pesos adicionais e salva `verification-float32.json`.
O ranking completo int8 não é sobrescrito. Esse comando compara apenas
14 pares escolhidos nos três casos de calibração; não reexecuta o piloto inteiro.

## Avaliação e limites

Q01, Q03, Q06, Q08 e Q10 são casos de calibração já inspecionados antes
deste teste. As outras 45 consultas ficam identificadas como `held_out`:
nenhum ajuste específico foi feito para seus resultados. Isso não é uma
validação independente de produção: são consultas propostas para o piloto,
não um conjunto representativo de buscas reais de clientes.

É possível avaliar o novo HTML e passar o JSON de notas a
`pncp_sync.semantic.score_pilot`, como no piloto E5, apontando para o novo
`evaluation.json`. O avaliador aceita as três colunas presentes neste
relatório. Notas faltantes continuam desconhecidas, não irrelevantes.

Sem julgamentos consistentes, a mudança de posição não demonstra melhora
geral de precisão. Casos inspecionados pelo assistente devem ser descritos
como evidências preliminares, nunca como avaliação humana independente.
A quantização dinâmica reduz o tamanho dos pesos, mas pode alterar
pontuações em função dos outros textos do lote. A verificação registra
essas diferenças, sem assumir equivalência com o modelo float32.

Latências referem-se a 30 candidatos e uma amostra de 10 mil registros,
com modelos aquecidos. Não representam desempenho sobre o acervo inteiro,
buscas concorrentes ou latência da interface. Os tempos das consultas
retomadas são os medidos na primeira execução delas.
