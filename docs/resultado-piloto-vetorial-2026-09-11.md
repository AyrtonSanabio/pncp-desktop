# Resultado do piloto vetorial — 11/09/2026

## Execução medida

O piloto concluiu em 11/09/2026 às 04:31:53 BRT, usando 10 mil contratações
do banco local. O processamento utilizou um Ryzen 5 2600, CPU, duas threads
de inferência e lotes de 16. O modelo é `intfloat/multilingual-e5-small`,
ONNX float32, 384 dimensões, por FastEmbed 0.8.0. Modelo e dados foram
processados localmente; a origem foi aberta somente para leitura.

| Medida | Resultado observado |
| --- | ---: |
| Contratações/vetores | 10.000 |
| Geração dos vetores | 1.840,56 s — 30 min 41 s |
| Média de geração | 5,43 registros/s |
| Execução completa | 1.857,37 s — 30 min 57 s |
| Download/carregamento inicial do modelo | 11,18 s combinados |
| Pico de memória do processo informado pelo Windows, até fim da geração | 1,81 GiB |
| Modelo e cache, sem contar links duas vezes | 487.360.648 bytes — 464,78 MiB |
| Vetores brutos | 15.360.000 bytes — 14,65 MiB |
| SQLite do piloto: textos, FTS, metadados e vetores | 41.246.720 bytes — 39,34 MiB |
| Ambiente Python isolado do piloto | 183.670.472 bytes — aproximadamente 175,16 MiB |
| Consultas executadas | 50 |
| Busca semântica: média de codificação + pesquisa | 11,28 ms |
| Busca semântica: mediana | 10,97 ms |
| Busca semântica: percentil 95, nearest rank | 13,49 ms |
| FTS AND: média | 1,67 ms |
| Consultas sem resultados em FTS AND | 16 de 50 |

O download não foi medido separadamente do carregamento. O tamanho do cache
é a soma dos tamanhos dos arquivos únicos, não uma medição dos bytes de
rede nem da alocação física por clusters do NTFS. A primeira soma do cache
contava duas vezes arquivos referenciados por links simbólicos; foi
corrigida para usar a identidade dos arquivos. Ambiente Python, dependências
e HTML/JSON de resultados são espaço adicional.
Ao final, ambiente isolado e pasta completa do piloto somavam aproximadamente
720 MB decimais. Essa instalação experimental não aumentou o EXE existente.

As latências são de modelo já carregado e matriz de 10 mil vetores em RAM.
Elas excluem inicialização e interface Qt. Não significam que a mesma busca
tenha esse tempo em milhões de registros. O piloto usa cosseno exato, sem ANN.

## Casos concretos observados

As observações abaixo são uma inspeção preliminar dos textos por Codex,
não um conjunto de julgamentos humanos validado nem uma taxa de precisão.

### Caso com utilidade: controle de pragas em escolas (Q10)

FTS AND não encontrou resultados porque exige as palavras da consulta.
O primeiro resultado vetorial foi
`53970845000176-1-000019/2025`, do Fundo Municipal de Educação de Itatiaia:
controle de pragas com desinsetização, descupinização e desratização para a
rede municipal de ensino por 12 meses. O texto corresponde à intenção sem
precisar usar a expressão literal "em escolas".

[Conferir no PNCP](https://pncp.gov.br/app/editais/53970845000176/2025/19).

### Caso com utilidade: proteção contra ataques e vírus de computador (Q06)

FTS AND também retornou zero. A busca semântica colocou em primeiro
`48344014000159-1-000016/2023`, aquisição de software antivírus para proteção
dos computadores da Prefeitura de Guaíra/SP. Os próximos resultados já
incluíam equipamentos e backup, mostrando que um bom primeiro resultado
não torna o top 10 inteiro relevante.

[Conferir no PNCP](https://pncp.gov.br/app/editais/48344014000159/2023/16).

### Ruído: manutenção de computadores para escolas (Q01)

O primeiro resultado foi `07954480000179-1-016279/2026`, repasse para
manutenção de escolas no Ceará. A informação complementar trata de
telhado, telhas, ripas e caibros. Ele atende ao contexto "manutenção de
escolas", mas não ao objeto "computadores". Pela intenção estabelecida,
é um falso positivo. O segundo resultado é manutenção de impressora de
uma escola, também insuficiente para afirmar manutenção de computadores.

[Conferir o primeiro no PNCP](https://pncp.gov.br/app/editais/07954480000179/2026/16279).

### Ruído: aluguel de impressoras com manutenção (Q03)

O primeiro resultado foi `06190522000180-1-000210/2024`, manutenção de uma
empilhadeira elétrica. É inadequado para a consulta. Já o segundo,
`29803955000169-1-000032/2025`, descreve locação de impressoras multifuncionais,
insumos e manutenção para a Câmara de Itaara/RS, correspondendo à intenção.

[Empilhadeira no PNCP](https://pncp.gov.br/app/editais/06190522000180/2024/210).
[Locação de impressoras no PNCP](https://pncp.gov.br/app/editais/29803955000169/2025/32).

Esses links foram construídos dos identificadores armazenados. Os textos
foram conferidos no snapshot local do piloto; esta inspeção não consultou
novamente o conteúdo atual das páginas oficiais.

## Verificação da implementação

Seis vetores foram regenerados, incluindo a empilhadeira e a locação de
impressoras. A maior diferença absoluta entre vetor salvo e recém-gerado
foi `3,72e-9`, compatível com a persistência em float32. Comparar inferência
individual e em lote desses textos produziu diferença máxima zero.

Isso verifica o alinhamento e a estabilidade desses seis casos; não é uma
prova exaustiva de todos os resultados nem validação estatística do modelo.
A evidência reduz a hipótese de o resultado estranho ser causado por troca
de vetores entre os registros testados.

Reprodução, com o modelo já em cache:

```powershell
$env:HF_HUB_OFFLINE = "1"
.\.venv-semantic\Scripts\python.exe -m pncp_sync.semantic.verify_pilot `
  --output .semantic-pilot --ids 1985167 1999190
```

Testes automatizados do piloto e da base de embeddings: 16 aprovados.
Cobrem origem somente leitura, amostra reproduzível, retomada após falha,
persistência binária, lote inválido, prefixos E5, assinatura do modelo,
ausência de julgamentos, escape de HTML e validação/normalização numérica.
Os testes de dados e embeddings no ambiente principal também passaram
(18 testes, incluindo sobreposição com os testes de embeddings).

## Conclusão técnica e artefatos

O custo de geração e o desempenho da consulta foram medidos. Há resultados
úteis com expressões diferentes e falsos positivos claros. Ainda não há
evidência para substituir a pesquisa principal pela busca semântica pura.

Precisão@10 aguarda julgamentos. Recall@10 não é calculado porque não
conhecemos todos os relevantes do corpus. FTS AND vazio não prova ausência
de documentos relevantes. Vetor retornando dez resultados não prova que
esses dez sejam úteis.

Na pasta `.semantic-pilot`, fora do Git:

- `review.html`: quatro métodos lado a lado, seleção de relevância e exportação;
- `evaluation.json`: rankings, escores, latências e corpus congelado;
- `report.json`: medidas da execução;
- `verification.json`: comparação de vetores salvos, em lote e individuais;
- `pilot.sqlite3`: amostra e vetores;
- `model-cache/`: modelo e tokenizador baixados.

O roteiro de reprodução e cálculo de precisão está em
[piloto-vetorial.md](piloto-vetorial.md). HNSW, integração com a interface e
geração nacional não fazem parte da implementação validada neste piloto.
