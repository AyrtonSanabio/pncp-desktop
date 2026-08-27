# Política de somente leitura e credenciamento

## Status da decisão

Esta é uma decisão arquitetural obrigatória do projeto.

O `pncp-desktop` e os componentes PNCP desenvolvidos para ele serão estritamente de consulta. O projeto não será uma plataforma publicadora e não representará órgãos públicos perante o PNCP.

## Regra principal

O projeto nunca deverá criar funções que publiquem, retifiquem ou excluam informações no PNCP.

Exemplos expressamente fora do escopo:

```text
publicar_contratacao(...)
retificar_contratacao(...)
excluir_contratacao(...)
publicar_contrato(...)
retificar_contrato(...)
excluir_contrato(...)
publicar_ata(...)
enviar_documento(...)
excluir_documento(...)
gerenciar_entes_autorizados(...)
```

A proibição vale mesmo que esses serviços estejam documentados na API oficial e mesmo que um colaborador possua credenciais próprias.

## O que significam credenciamento, autenticação e autorização

### Credenciamento

É o registro de um portal ou sistema de contratações públicas como plataforma apta a enviar dados ao PNCP.

Segundo as [Perguntas e Respostas do PNCP](https://www.gov.br/pncp/pt-br/pncp/perguntas-e-respostas), somente portais ou sistemas de contratações públicas, privados ou públicos, precisam desse credenciamento. Consultas públicas não exigem cadastro.

### Autenticação

Uma plataforma credenciada utiliza login e senha para obter um JSON Web Token (JWT). O token é enviado nas chamadas de manutenção para comprovar a identidade da plataforma.

O [Manual de Integração do PNCP](https://pncp.gov.br/manual/pt-br/latest/acesso_ao_pncp/index.html) informa que o token é obtido pela API de login e possui validade limitada.

### Autorização

É a definição dos órgãos que a plataforma pode representar. A autorização é vinculada aos CNPJs dos órgãos ou entidades públicas.

Conhecer o CNPJ de uma prefeitura ou de outro órgão não autoriza uma plataforma a publicar em seu nome. O gestor do órgão precisa autorizar a plataforma publicadora na área de Gestão de Órgão/Entidade. Para plataformas privadas, a inclusão de novos entes requer comprovação do vínculo com o ente público.

## Responsabilidade jurídica

Esta seção registra critérios de projeto e não substitui parecer jurídico. As obrigações concretas podem variar conforme a forma de distribuição, os contratos, as fontes integradas, os dados tratados e o uso comercial do software. Antes de uma operação comercial relevante, o responsável pelo produto deverá obter revisão jurídica própria.

### Base da decisão

A [Lei nº 14.133/2021](https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2021/lei/l14133.htm) define o PNCP como o sítio oficial para divulgação centralizada e obrigatória dos atos exigidos pela legislação de contratações públicas. A publicação no portal pode produzir efeitos relevantes para a eficácia e a transparência dos contratos públicos.

As [Perguntas e Respostas oficiais do PNCP](https://www.gov.br/pncp/pt-br/pncp/perguntas-e-respostas) informam que o envio dos dados é responsabilidade dos órgãos e entidades públicas abrangidos pela legislação.

Quando um sistema público ou privado realiza tecnicamente esse envio, o [Manual de Integração do PNCP](https://pncp.gov.br/manual/pt-br/latest/acesso_ao_pncp/index.html) declara que o sistema confiará na plataforma e que ela será juridicamente responsável por equívocos intencionais ou acidentais. O manual também atribui à plataforma o dever de garantir a precisão e a manutenção adequada dos dados enviados.

Por isso, a publicação não deve ser tratada como uma funcionalidade comum de cliente HTTP. Ela envolve a divulgação de atos oficiais em nome de terceiros.

### Matriz de responsabilidade

| Participante | Responsabilidade principal | Limite relevante para este projeto |
|---|---|---|
| Órgão ou entidade pública | Produzir, aprovar, enviar e corrigir as informações cuja divulgação é obrigatória | A utilização de uma plataforma técnica não transforma o `pncp-desktop` em responsável pelo conteúdo oficial |
| Plataforma publicadora credenciada | Transmitir fielmente os dados, operar somente para órgãos autorizados, proteger credenciais e manter os registros enviados | O `pncp-desktop` não será credenciado nem atuará nessa função |
| PNCP | Disponibilizar a infraestrutura oficial de centralização e consulta conforme sua governança | A presença de um dado no PNCP não elimina a necessidade de informar sua fonte, data e possíveis limitações |
| `pncp-desktop` | Consultar, apresentar, relacionar e exportar dados públicos sem alterar a fonte | Não publica atos, não corrige o PNCP e não substitui o órgão, a plataforma publicadora ou uma certidão oficial |
| Pessoa usuária | Avaliar o dado no contexto de sua decisão e consultar a fonte oficial quando precisar de comprovação atual | Um resultado, alerta ou resumo do aplicativo não constitui decisão administrativa, habilitação ou parecer jurídico |

Essa matriz não pretende definir exaustivamente a responsabilidade legal de cada participante. Ela estabelece a fronteira que o software deve respeitar.

### Responsabilidade específica do aplicativo de consulta

Ser somente leitura reduz substancialmente o risco de alterar atos oficiais, mas não elimina a responsabilidade sobre o modo como o produto reutiliza e apresenta dados públicos. O projeto deverá:

- identificar claramente a fonte de cada registro;
- preservar o identificador original do PNCP ou da fonte complementar;
- registrar a data e a hora da consulta;
- informar a data de atualização fornecida pela fonte quando ela existir;
- sinalizar cache vencido, falha de sincronização ou informação potencialmente desatualizada;
- permitir que a pessoa usuária abra o registro original;
- distinguir dado original, dado normalizado e inferência produzida pelo aplicativo;
- corrigir a cópia local quando a fonte oficial for retificada;
- não modificar silenciosamente o sentido de campos oficiais;
- não garantir completude quando a própria fonte puder estar incompleta ou atrasada;
- proteger os dados armazenados localmente e limitar logs ao necessário;
- documentar limitações de filtros, correspondências e relacionamentos entre bases.

O aplicativo não deve declarar automaticamente que uma empresa está habilitada, impedida, regular, segura ou apta a contratar apenas com base em cache, ausência de resultados ou combinação algorítmica. Deve apresentar os registros encontrados, suas fontes e seus períodos de validade para que a verificação competente seja realizada.

### Certidões, sanções e decisões

Uma consulta armazenada não substitui documento oficial emitido no momento exigido pelo processo de contratação.

- Ausência de resultado em uma fonte não equivale, sozinha, a certidão negativa.
- Uma certidão expirada não deve ser apresentada como regularidade atual.
- Uma sanção deve conservar órgão sancionador, fundamento, início, fim e situação informados pela fonte.
- Um processo judicial não prova automaticamente irregularidade ou responsabilidade da parte.
- Divergências entre fontes devem ser exibidas como divergências, sem escolher silenciosamente uma como verdadeira.

Relatórios e exportações deverão conter aviso de que os dados são informativos, possuem data de consulta e precisam ser confirmados na fonte oficial quando forem usados para habilitação, decisão administrativa, análise jurídica, crédito ou contratação.

### Proteção de dados pessoais

O fato de uma informação estar publicamente acessível não elimina os deveres aplicáveis ao seu tratamento. A [Lei Geral de Proteção de Dados Pessoais](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm) determina que o tratamento de dados pessoais de acesso público considere finalidade, boa-fé e interesse público, além dos princípios de necessidade, qualidade, transparência, segurança, prevenção e não discriminação.

Consequentemente, o projeto deverá:

- coletar somente dados pessoais necessários à finalidade declarada;
- evitar exposição de CPF, endereço pessoal ou outros dados sem necessidade funcional;
- não criar perfis pessoais ou pontuações discriminatórias;
- definir retenção e descarte para cache, exportações e logs;
- proteger arquivos locais e credenciais de outras fontes de consulta;
- documentar a finalidade de cada dado pessoal utilizado;
- revisar as obrigações de controlador ou operador antes de oferecer serviço hospedado ou comercial.

### Comunicação de limitações

A interface e as exportações deverão apresentar, de maneira compreensível:

```text
Dados obtidos de fontes públicas na data indicada.
O aplicativo não altera o PNCP e não substitui certidões,
decisões administrativas, consulta à fonte oficial ou orientação jurídica.
```

O aviso não serve para afastar responsabilidades próprias do projeto. Ele serve para explicar corretamente a natureza e os limites do serviço.

### Tratamento de erro relevante

Se o aplicativo detectar que apresentou dado incorreto, associação equivocada ou cache desatualizado com potencial de afetar decisões, a manutenção deverá:

1. preservar evidências técnicas e a procedência do dado;
2. interromper ou sinalizar a apresentação do resultado problemático;
3. corrigir o processamento ou atualizar a fonte;
4. registrar a correção de forma auditável;
5. avaliar se usuários afetados precisam ser informados;
6. revisar testes para impedir repetição do problema.

### Consequência arquitetural

O `pncp-desktop` é uma ferramenta de consulta para usuários finais. Ele não possui estrutura contratual, institucional ou operacional para assumir a responsabilidade de publicar atos oficiais. Manter o projeto somente leitura é uma forma deliberada de preservar essa fronteira.

## Por que as funções de manutenção não pertencem ao projeto

### 1. Credenciais com grande poder

As credenciais pertencem à plataforma e podem permitir operações em nome de órgãos autorizados. Uma falha poderia publicar, alterar ou excluir informações oficiais.

Um aplicativo desktop distribuído a usuários finais não é um local aceitável para armazenar esse tipo de segredo.

### 2. Separação entre fornecedor e plataforma publicadora

Empresas fornecedoras não usam a API de manutenção do PNCP para enviar propostas. As propostas são apresentadas no portal que realiza a disputa, como Compras.gov.br ou outro sistema adotado pelo órgão.

No PNCP, quem publica é o órgão ou a plataforma de contratação autorizada a representá-lo.

### 3. Escopo e segurança

Adicionar manutenção exigiria credenciamento, autorização por órgão, gestão de segredos, trilhas de auditoria, segregação por cliente, validações legais e operação de incidentes. Isso criaria um produto diferente do aplicativo de consulta planejado.

## Operações permitidas

O projeto pode:

- consultar APIs públicas e documentadas do PNCP;
- consultar PCA, contratações, itens, resultados, atas, contratos e documentos públicos;
- paginar resultados;
- baixar documentos públicos;
- armazenar cache local com validade identificada;
- exportar resultados;
- relacionar dados do PNCP com outras fontes públicas;
- criar alertas a partir de alterações observadas em consultas;
- abrir o registro original no portal;
- informar fonte, identificador e data da consulta.

Essas operações não alteram o PNCP.

## Operações proibidas

O projeto não pode:

- chamar endpoints de inserção, retificação ou exclusão do PNCP;
- autenticar na API de manutenção do PNCP;
- implementar ou chamar o endpoint de login de plataforma;
- obter, renovar ou armazenar JWT de plataforma publicadora;
- solicitar ou gerenciar entes autorizados;
- cadastrar órgãos ou unidades para fins de publicação;
- publicar arquivos ou documentos oficiais;
- compartilhar credenciais entre usuários;
- aceitar credenciais PNCP em campos da interface;
- incluir credenciais em código, exemplos, testes, logs ou arquivos de configuração;
- simular que um fornecedor pode enviar proposta diretamente ao PNCP.

## Fronteira técnica recomendada

```text
pncp-desktop
    -> adaptador somente de leitura
        -> pypncp
            -> API pública de consultas do PNCP

Fora da arquitetura:
    -> API de manutenção do PNCP
    -> login de plataforma
    -> JWT
    -> publicação, retificação ou exclusão
```

O código deve utilizar os endpoints públicos de consulta documentados. Um endpoint estar disponível no Swagger da integração não significa que ele deva fazer parte deste projeto.

## Controles para preservar a decisão

### Revisão de código

Toda contribuição que adicione autenticação de plataforma ou operação de manutenção deverá ser recusada por estar fora do escopo.

### Configuração

Não criar opções como:

```text
PNCP_LOGIN
PNCP_PASSWORD
PNCP_JWT
PNCP_ENTES_AUTORIZADOS
```

Essas configurações não são necessárias para consulta pública e aumentariam o risco de uso indevido.

### Testes

Os testes devem verificar que:

- os clientes PNCP utilizados pelo aplicativo são de consulta;
- nenhuma credencial é solicitada para usar o aplicativo;
- exportações e cache são locais;
- falhas de permissão nunca provocam tentativa automática de autenticação;
- endpoints de manutenção não aparecem no código nem na interface.

### Documentação e interface

A interface deve usar verbos como:

- consultar;
- pesquisar;
- filtrar;
- visualizar;
- baixar;
- exportar;
- acompanhar.

Ela não deve usar ações como publicar, retificar, excluir, homologar ou enviar ao PNCP.

## Melhorias e bibliotecas futuras

O planejamento de conectores para outras fontes foi retirado do foco ativo e preservado em [Bibliotecas e estrutura do ecossistema](melhorias-futuras/BIBLIOTECAS_E_ESTRUTURA_DO_ECOSSISTEMA.md). O limite de somente leitura continuará obrigatório se esse planejamento for retomado.

## Resumo obrigatório

```text
Consultar e organizar dados públicos: permitido.
Baixar e exportar dados públicos: permitido.
Relacionar fontes públicas: permitido.

Publicar no PNCP: proibido.
Retificar no PNCP: proibido.
Excluir no PNCP: proibido.
Armazenar credenciais de plataforma PNCP: proibido.
Representar órgãos públicos perante o PNCP: fora do escopo.
```
