# Interface, atualização incremental, erros e validações

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
