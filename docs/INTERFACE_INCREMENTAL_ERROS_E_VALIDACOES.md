# Interface, atualização incremental, erros e validações

## Orientação para iniciantes

A primeira aba é **Comece aqui**. Ela explica a finalidade do PNCP, exemplos de uso para
fornecedores, assessorias, pesquisadores e desenvolvedores, a diferença entre consulta
online de contratos e sincronização de contratações, um roteiro inicial e um glossário.

A modalidade deixou de exigir que o usuário memorize um número: a interface apresenta
código e nome conforme a [tabela de domínio oficial do PNCP](https://pncp.gov.br/manual/pt-br/latest/tabelas_de_dominio/consultar_modalidade_de_Contratacao.html),
consultada em 27 de agosto de 2026.

## Estimativa compreensível

O planejamento faz uma consulta real à primeira página e apresenta:

- tempo restante da carga principal, calculado pela latência observada com margem;
- número de payloads compactados no SQLite e chamadas de página ainda necessárias;
- total de contratações informado pelo PNCP;
- estimativa de rede e tamanho do banco;
- mínimo de chamadas de itens quando os detalhes estiverem marcados.

Payload não é um arquivo solto: é a resposta original comprimida dentro do SQLite. O
tempo de itens e resultados não pode ser fechado antes da carga porque cada contratação
pode ter quantidade diferente de itens, páginas e resultados.

A estimativa usa uma tentativa de até 20 segundos e pode ser cancelada. A carga efetiva
mantém timeout e retentativas maiores. Alterar datas ou modalidade invalida o plano para
impedir que o botão Sincronizar execute filtros antigos. Uma nova estimativa remove o
plano anterior somente se ele nunca tiver iniciado.

## Carregamento do banco sem travar a interface

Consultas SQLite, contagens, detalhes e verificações de integridade são executados numa
thread própria. Trocar para a aba Banco local apenas agenda a leitura e mostra o estado
"Carregando banco local em segundo plano". A aba não consulta novamente enquanto o banco
e o texto de busca não mudarem.

A tabela continua limitada a 100 registros por carregamento. Esse limite evita criar
milhares de componentes gráficos de uma vez; a busca FTS5 deve ser usada para reduzir o
conjunto exibido.

## Local de armazenamento

O botão **Escolher local dos dados** seleciona o arquivo SQLite. O caminho fica salvo nas
configurações do usuário e é reutilizado na próxima abertura. A troca é bloqueada durante
uma sincronização. Selecionar um novo arquivo não apaga nem move o anterior.

Arquivos auxiliares `-wal` e `-shm` podem existir ao lado do SQLite enquanto o programa
estiver aberto. A pasta precisa permitir escrita e possuir espaço para o banco e sua
margem operacional.

## Atualizar desde a última execução

O botão procura a maior `data_final` de uma execução concluída para a modalidade atual.
O próximo lote começa nessa mesma data, criando um dia de sobreposição para reencontrar
retificações. O fim é hoje ou, quando a lacuna é grande, o limite seguro de 31 dias.
Novos cliques após cada lote avançam até a data atual.

A função prepara e estima o lote, mas mantém a confirmação no botão **Sincronizar**.
Execuções apenas planejadas, pausadas ou com falha não avançam a data de cobertura.

## Diagnóstico apresentado ao usuário

O botão **Ver erros e validações** executa em segundo plano:

- cobertura da última sincronização de contratações;
- cobertura de contratações com itens e itens com resultados;
- erros da carga principal e de detalhes;
- registros rejeitados pelo normalizador;
- divergências entre o JSON oficial e os modelos do `pypncp`;
- `PRAGMA quick_check` do SQLite;
- verificação de chaves estrangeiras;
- busca de identificadores PNCP duplicados.

Erros recuperáveis ficam associados à unidade e permitem continuar. Erros de contrato da
fonte ou falhas inesperadas não são ocultados. Um registro inválido não interrompe toda a
página: ele é comprimido e preservado em uma tabela de rejeição com motivo e hash.

## Validações antes e durante a carga

- data inicial não pode superar a final;
- cada lote possui no máximo 31 dias;
- modalidade deve ser positiva;
- páginas e itens precisam possuir identificadores válidos;
- o planejamento exige HTTP 200 e página inicial coerente;
- o botão Sincronizar é bloqueado se o disco não tiver a estimativa mais 25% de margem;
- a troca do arquivo SQLite é bloqueada durante a carga;
- hashes, chaves únicas e referências podem ser verificados no painel;
- operações `POST`, `PUT` e `DELETE` continuam proibidas pelo escopo somente leitura.

## Campos além do modelo de contratação do pypncp 1.2.1

O adaptador compara dinamicamente o JSON real com o modelo instalado. Os principais
campos adicionais normalizados são:

- encerramento das propostas, situação da compra e modo de disputa;
- tipo de instrumento convocatório e amparo legal completo;
- datas de inclusão e atualização (`dataAtualizacaoGlobal` já era modelada);
- poder, esfera, código da unidade, município, UF e código IBGE;
- links do sistema de origem e do processo eletrônico;
- justificativa de sessão presencial e usuário publicador;
- fontes orçamentárias e emenda parlamentar;
- órgão e unidade sub-rogados.

Em resultados, a divergência real mais importante é `localidadeFornecedor`: o
`pypncp 1.2.1` esperava texto, enquanto a API retornou um objeto com município, UF e
código IBGE. O sincronizador preserva o erro do modelo e normaliza o objeto oficial.
