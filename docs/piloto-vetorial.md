# Piloto de embeddings no PNCP

## Objetivo e escopo

Medir custo e observar resultados de recuperação semântica em uma amostra
de contratações já armazenadas. A origem só é lida, sem consulta ao PNCP,
sem baixar itens ou PDFs. A rede é usada na instalação das dependências e
no primeiro download do modelo público; textos das contratações são
processados localmente pela CPU.

O experimento usa `intfloat/multilingual-e5-small`, pesos ONNX oficiais,
mean pooling com máscara de atenção e normalização L2. Acrescenta `passage: `
ao texto das contratações e `query: ` às pesquisas, como especificado na
[ficha do modelo](https://huggingface.co/intfloat/multilingual-e5-small).
O arquivo ONNX original tem aproximadamente 470 MB; outros arquivos incluem
tokenizador e configuração. O custo real da pasta é registrado no relatório.
Não há cobrança por consulta ou geração feita localmente.

## Preparação no Windows

No diretório do projeto, usando PowerShell:

```powershell
py -3.13 -m venv .venv-semantic
.\.venv-semantic\Scripts\python.exe -m pip install -e ".[semantic]"
$env:OMP_NUM_THREADS = "2"
$env:OPENBLAS_NUM_THREADS = "2"
.\.venv-semantic\Scripts\python.exe -m pncp_sync.semantic.pilot `
  --source A:\Projetos\pncp-dados\pncp.sqlite3 `
  --output .semantic-pilot `
  --queries docs\semantic-pilot-queries.json `
  --sample-size 10000 --threads 2 --batch-size 16
```

O extra `semantic` é opcional. A execução inicial de desenvolvimento utilizou
um ambiente próprio com FastEmbed 0.8.0 e instalação editável do projeto
sem alterar as dependências do aplicativo em `.venv`. Nenhum modelo é
incluído automaticamente no EXE.

As versões exatas desse ambiente estão em `requirements-semantic-pilot.txt`.
Para reproduzi-lo em um ambiente vazio, instale esse arquivo com `pip install -r`
e em seguida instale o projeto com `pip install -e . --no-deps`.

## Amostra e limites estatísticos

O intervalo mínimo/máximo de IDs é dividido em até 10 mil faixas. Uma semente
fixa (42) escolhe um ponto em cada faixa e a primeira contratação existente
a partir dele. Se não houver registro depois do ponto, usa a primeira
contratação anterior dentro da mesma faixa. Faixas vazias e objetos vazios
são ignorados, por isso a amostra pode conter menos registros que o solicitado.

Essa seleção distribui leituras pelo acervo sem ordenar milhões de linhas
aleatoriamente. Não é uma amostra aleatória simples nem garante proporções
nacionais de região, modalidade ou período. O relatório registra essas
distribuições para tornar o viés visível. A coleta leva várias leituras e
não afirma representar um snapshot transacional instantâneo da origem.
Depois da coleta, o corpus do piloto fica congelado e ambos os métodos
pesquisam exatamente os mesmos documentos.

Entram objeto, informações complementares, modalidade, modo de disputa,
instrumento, amparo legal e órgão. A função de template também aceita itens,
mas este experimento não os inclui. Não importa a coluna `usuario_nome`,
mas não faz anonimização automática de nomes que constem do objeto público.
O template limita o texto a 8 mil caracteres; o tokenizador do modelo
trunca entradas longas conforme seu limite. Texto no fim pode não influenciar
o vetor. Não há chunking nem fine-tuning neste piloto.

## Persistência e retomada

`pilot.sqlite3` contém `document`, `document_fts` e `metadata`. Cada documento
tem ID original, identificador PNCP, texto, data, UF, modalidade, hash e vetor
float32 little-endian. São 1.536 bytes brutos por vetor de 384 dimensões.

O lote inteiro é validado antes de atualizar os vetores: dimensões, norma e
números finitos. Uma transação confirma o lote. Reexecutar o mesmo comando
gera apenas linhas com vetor ainda nulo. Se houver queda no meio de uma
inferência, repete esse lote; lotes confirmados permanecem. Um lock de arquivo
impede duas execuções simultâneas sobre a mesma pasta.

O manifesto da amostra, semente e origem não podem mudar dentro da pasta.
Os hashes SHA-256 de pesos/configurações/tokenizador e a versão do FastEmbed
também são comparados. Trocas incompatíveis pedem outra pasta, evitando
misturar espaços vetoriais. A origem é verificada como distinta do banco de
saída. Esses arquivos experimentais e o ambiente ficam ignorados pelo Git.

## Comparação das pesquisas

As 50 consultas abrangem TI, limpeza, transporte, alimentação, saúde,
construção, educação e serviços administrativos. Os critérios distinguem
serviço de aquisição: comprar impressora não equivale a alugar impressão;
compra de desinfetante não equivale a contratar equipe de limpeza.

O piloto calcula:

- FTS AND: exige todas as palavras, desconsiderando conectivos comuns;
- FTS OR: aceita qualquer palavra e ordena pelo BM25 do SQLite FTS5;
- semântica: ordena pelo produto interno/cosseno nos vetores normalizados;
- híbrida: une os primeiros 50 candidatos de cada método com
  Reciprocal Rank Fusion, soma `1/(60 + posição)` e retorna dez.

São baselines do piloto. Não reproduzem todos os sinônimos nem filtros da
busca existente no aplicativo. Cosseno não é porcentagem de relevância;
um top 10 pode conter ruído quando não há candidatos adequados na amostra.

## Arquivos e avaliação

Após concluir, abra `.semantic-pilot/review.html` no navegador. Cada consulta
tem quatro colunas com identificador PNCP, texto e seleção de relevância.
Identificadores válidos têm link direto ao edital oficial. Conteúdo vindo
da origem é escapado antes de entrar no HTML.

Os seletores sincronizam a nota de uma contratação que apareça em mais de
uma coluna. Clique em **Salvar avaliações (JSON)** antes de fechar: notas
não salvas não são persistidas. Guarde o JSON junto do relatório do mesmo
piloto. Nenhum campo vem pré-julgado como relevante.

```powershell
.\.venv-semantic\Scripts\python.exe -m pncp_sync.semantic.score_pilot `
  --evaluation .semantic-pilot\evaluation.json `
  --judgments .semantic-pilot\judgments.json `
  --output .semantic-pilot\quality.json
```

Precisão@10 é relevantes/10. Se o método retornar menos de dez, posições
vazias contam como zero. Se existir resultado retornado sem julgamento,
a precisão fica nula. O relatório informa a quantidade de consultas
avaliadas de cada método; médias com coberturas diferentes não devem ser
comparadas como equivalentes. Falsos positivos são contados apenas entre
resultados julgados. Recall@10 permanece nulo, pois requer saber todos os
relevantes do corpus, não apenas a união dos primeiros resultados.

`report.json` registra duração, geração por execução, RAM observada nos
finais dos lotes e pico do processo informado pelo Windows, tamanho do modelo,
vetores e banco. `evaluation.json` contém rankings, escores e tempos por
consulta. O tempo de geração exclui download/carregamento do modelo; os
tempos de consulta separam codificação da frase e pesquisa vetorial.

## Interpretação dos custos

Medidas de 10 mil registros não são garantias para milhões. Inferência
depende do comprimento dos textos e da carga do computador. A matriz exata
do piloto ocupa cerca de 14,65 MiB para 10 mil vetores, mas o modelo e
tensores de inferência consomem memória adicional. Consultar milhões de
vetores exige outro planejamento de armazenamento/ANN; não extrapole a
latência medida no piloto como se o aplicativo já atendesse o acervo inteiro.
