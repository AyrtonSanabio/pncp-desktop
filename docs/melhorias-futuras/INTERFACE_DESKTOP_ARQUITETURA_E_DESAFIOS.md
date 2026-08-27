# Arquitetura e desafios

## Objetivo

Criar uma interface desktop que transforme as consultas oferecidas pelo `pypncp` em um fluxo acessível para pessoas que não usam Python ou terminal.

O aplicativo não publicará, editará ou excluirá dados no PNCP. Seu escopo inicial é somente consulta e exportação local.

Essa separação também limita a responsabilidade assumida pelo projeto. O órgão público continua responsável pelo envio das informações oficiais e uma eventual plataforma publicadora responde pelas operações que realiza em nome dos órgãos autorizados. O aplicativo responde pela forma como consulta e apresenta os dados: deve preservar procedência, data de consulta, limitações e acesso ao registro original, sem substituir certidões, decisões administrativas ou orientação jurídica.

As regras completas estão registradas em [Política de somente leitura e credenciamento](../POLITICA_SOMENTE_LEITURA_E_CREDENCIAMENTO.md), incluindo responsabilidade jurídica, proteção de dados pessoais e tratamento de informações desatualizadas ou divergentes.

## Arquitetura proposta

```text
Interface PySide6
    -> casos de uso
        -> adaptador do pypncp
            -> pypncp
                -> APIs do PNCP

Interface <- modelos próprios de apresentação <- resultados e erros
```

### Interface

Responsável por campos, botões, tabela, mensagens, progresso e acessibilidade. Não deve montar URLs nem conhecer detalhes dos endpoints.

### Casos de uso

Coordenam ações como consultar contratos, cancelar uma busca e exportar resultados. Essa camada impede que regras do aplicativo fiquem presas aos componentes visuais.

### Adaptador do pypncp

É o único ponto que conhece diretamente `PNCPClient`. Traduz objetos e exceções da biblioteca para resultados que a interface consegue apresentar. Se a biblioteca mudar, a maior parte do aplicativo permanece intacta.

## O que será difícil e como tratar

### 1. API lenta ou indisponível

O PNCP pode demorar mais que o timeout ou não responder. Já observamos `ReadTimeout` em uma consulta real.

Tratamento necessário:

- timeout configurável;
- número limitado de tentativas;
- mensagens compreensíveis, sem exibir somente traceback;
- botão para tentar novamente;
- botão para cancelar;
- manutenção dos filtros após uma falha;
- distinção entre falta de internet, timeout, erro de validação e erro do servidor.

### 2. Assincronismo sem congelar a janela

O `pypncp` é assíncrono, enquanto uma interface gráfica possui seu próprio loop de eventos. Executar uma consulta longa diretamente no clique do botão congelaria a janela.

Tratamento necessário:

- executar consultas fora da thread visual;
- comunicar resultados por sinais ou mensagens;
- impedir consultas duplicadas acidentais;
- cancelar e finalizar tarefas ao fechar a janela;
- atualizar a interface somente pela thread correta.

### 3. Paginação e volume de dados

Uma consulta pode retornar milhares de registros. Carregar tudo antes de mostrar qualquer coisa desperdiça memória e aumenta a espera.

Tratamento necessário:

- buscar e mostrar uma página por vez;
- oferecer próxima página e página anterior;
- limitar resultados por consulta;
- mostrar quantidade total quando a API fornecer esse valor;
- permitir exportação controlada de uma página ou de um conjunto explicitamente solicitado;
- evitar workers em excesso e respeitar limites do PNCP.

### 4. Dados incompletos ou inconsistentes

Nem todo contrato possui fornecedor, valor, município ou datas completas.

Tratamento necessário:

- aceitar campos opcionais;
- exibir `Não informado` em vez de quebrar a tela;
- formatar CNPJ, datas e valores somente quando válidos;
- preservar o identificador PNCP para auditoria e abertura do registro original.

### 5. Endpoints internos e mudanças no PNCP

Contratos, contratações e atas usam a API pública de consulta. Busca textual e parte dos preços usam endpoints internos documentados pelo projeto como resultado de engenharia reversa.

Tratamento necessário:

- começar somente por endpoints oficiais;
- isolar funcionalidades experimentais;
- avisar quando uma função depende de endpoint instável;
- criar testes de contrato que detectem mudanças no formato da resposta;
- não deixar uma falha experimental derrubar as consultas oficiais.

### 6. Problemas atuais da biblioteca

A revisão inicial encontrou pontos que devem ser resolvidos ou contornados antes da distribuição:

- clientes HTTP de `search` e `precos` não são fechados pelo contexto principal;
- tarefas de prefetch podem permanecer ativas quando o consumo é interrompido;
- o método de contrato específico precisa ser confrontado com o endpoint oficial;
- a paginação do pipeline de preços compara tamanhos de páginas diferentes;
- um teste do context manager é aprovado sem executar a coroutine.

Essas correções devem ser propostas ao projeto original em Pull Requests pequenos. Enquanto não forem publicadas, o aplicativo deverá fixar uma versão conhecida e evitar as áreas afetadas.

### 7. Exportação

CSV parece simples, mas exige decisões sobre codificação, separador, campos e formatação.

Tratamento necessário:

- cabeçalhos em português;
- UTF-8 compatível com Excel;
- valores numéricos preservados sem símbolos dentro da célula numérica;
- datas em formato consistente;
- escolha explícita do local do arquivo;
- confirmação da quantidade exportada;
- tratamento de arquivo aberto ou sem permissão de escrita.

Exportação para XLSX poderá ser adicionada depois do CSV estar validado.

### 8. Empacotamento para Windows

O usuário final não deve precisar instalar Python, `pip` ou `pypncp`.

Tratamento necessário:

- gerar pacote pelo Windows;
- incluir Python, PySide6, pypncp e demais dependências;
- testar em uma conta ou máquina limpa;
- definir ícone, versão e informações do executável;
- armazenar logs em uma pasta gravável do usuário;
- documentar falso positivo de antivírus se ocorrer;
- garantir que nenhum caminho do computador de desenvolvimento fique fixo no programa.

### 9. Logs e suporte

Erros de rede precisam ser diagnosticáveis sem exigir conhecimento técnico do usuário.

Tratamento necessário:

- mensagem simples na tela;
- detalhe técnico opcional;
- log com data, versão do aplicativo, endpoint lógico e categoria do erro;
- não registrar dados sensíveis desnecessários;
- botão para abrir ou copiar o log.

### 10. Testes

Os testes não podem depender somente de respostas simuladas, pois um mock errado também pode ser aprovado.

Tratamento necessário:

- testes unitários dos casos de uso;
- testes do adaptador com respostas simuladas;
- poucos testes de contrato contra endpoints oficiais, executados de forma controlada;
- teste de timeout e cancelamento;
- teste de exportação e caracteres acentuados;
- smoke test do executável empacotado;
- teste manual com a API indisponível.

## Fases sugeridas

### Fase 0 - fundação

- validar os endpoints oficiais necessários;
- definir modelos de apresentação e categorias de erro;
- preparar estrutura do projeto, testes e logging;
- corrigir ou contornar problemas bloqueadores do `pypncp`.

### Fase 1 - MVP de contratos

- filtros por período e CNPJ;
- consulta de uma página;
- tabela de resultados;
- estados de carregamento, vazio e erro;
- cancelamento;
- exportação CSV;
- primeiro pacote Windows.

### Fase 2 - ampliação oficial

- detalhes do contrato;
- contratações;
- atas;
- paginação completa;
- abertura do registro no portal.

### Fase 3 - recursos experimentais

- busca textual;
- preços homologados;
- filtros avançados;
- exportação XLSX;
- histórico local opcional.

## Critérios para considerar o MVP pronto

- a janela não congela durante consultas;
- uma consulta pode ser cancelada;
- timeout produz mensagem clara;
- campos ausentes não encerram o aplicativo;
- resultados podem ser exportados e reabertos corretamente;
- o executável funciona em Windows sem Python instalado;
- o log permite diagnosticar falhas;
- testes automatizados e smoke test passam;
- limitações da API e do aplicativo estão documentadas.
