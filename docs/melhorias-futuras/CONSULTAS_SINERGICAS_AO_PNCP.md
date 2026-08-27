# Consultas com sinergia ao PNCP

> Levantamento revisado em 26 de agosto de 2026. Portais, APIs, regras de acesso e formatos podem mudar; cada integração deverá registrar a fonte e a data da consulta.

## Objetivo

Mapear consultas públicas que complementam os dados do Portal Nacional de Contratações Públicas (PNCP) e que podem ajudar empresas que vendem para o governo, assessorias de licitação, órgãos públicos, pesquisadores e empresas de tecnologia.

O objetivo do produto não deve ser apenas reunir links governamentais. A oportunidade é acompanhar a jornada completa de quem vende ao governo:

```text
Planejamento do órgão
    -> descoberta da oportunidade
    -> análise do edital
    -> pesquisa de preço e concorrentes
    -> habilitação e integridade
    -> proposta e disputa
    -> contrato e entrega
    -> empenho e pagamento
    -> renovação ou nova contratação
```

## Quem costuma consumir esses dados

Não existe um único "ramo do PNCP". O ponto em comum é vender para o poder público ou prestar serviços a quem participa desse mercado.

- Distribuidores e revendedores de informática, móveis, veículos, alimentos, material de escritório, produtos de limpeza, equipamentos e peças.
- Prestadores de limpeza, segurança, manutenção, transporte, eventos, treinamento, consultoria, tecnologia, suporte e terceirização.
- Empresas de engenharia, construção, pavimentação, saneamento, projetos e fiscalização.
- Distribuidores de medicamentos, laboratórios e fornecedores de equipamentos hospitalares.
- Microempreendedores individuais, agricultores familiares, cooperativas e fornecedores locais.
- Assessorias de licitação que monitoram oportunidades e documentos para várias empresas.
- Escritórios jurídicos e contábeis especializados em contratos públicos.
- Govtechs e fornecedores de sistemas para órgãos públicos.
- Bancos, fintechs, seguradoras e empresas que analisam contratos e recebíveis públicos.
- Órgãos de controle, pesquisadores e jornalistas.

## Consultas de maior sinergia

### 1. PNCP

**Fonte:** [Portal Nacional de Contratações Públicas](https://www.gov.br/pncp/pt-br) e [Dados Abertos do PNCP](https://www.gov.br/pncp/pt-br/acesso-a-informacao/dados-abertos).

É a fonte central do projeto e permite consultar:

- Planos de Contratações Anuais (PCA);
- editais, avisos e contratações diretas;
- itens e resultados de contratações;
- atas de registro de preços;
- contratos, empenhos e documentos relacionados;
- órgãos e unidades compradoras.

**Perguntas respondidas:** o que será comprado, quando ocorrerá a disputa, qual é o objeto, quais foram os resultados e quais contratos foram publicados.

### 2. Compras.gov.br e SIASG

**Fonte:** [API de Dados Abertos do Compras.gov.br](https://dadosabertos.compras.gov.br/) e [Portal de Dados Abertos de Compras](https://www.gov.br/compras/pt-br/cidadao/portal-de-dados-abertos/portal-de-dados-abertos).

Complementa o PNCP com dados operacionais e históricos do ecossistema federal:

- catálogo de materiais (CATMAT);
- catálogo de serviços (CATSER);
- preços praticados em materiais e serviços;
- fornecedores registrados;
- contratações, itens e resultados;
- atas de registro de preços e seus saldos;
- contratos e itens de contratos;
- dados provenientes do Compras.gov.br e do SIASG.

**Perguntas respondidas:** qual código descreve o item, quanto o governo já pagou, quem participou, quem venceu, qual marca foi ofertada e quando uma ata ou contrato terminará.

**Sinergia:** altíssima. É a primeira fonte complementar recomendada para o PNCP.

### 3. Receita Federal e CNPJ

**Fonte:** [Dados abertos de cadastros da Receita Federal](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/dados-abertos/cadastros), [Repositório de Dados Abertos da Receita](https://www.gov.br/receitafederal/dados) e [consulta cadastral de pessoa jurídica](https://www.gov.br/receitafederal/pt-br/servicos/cadastro/cnpj).

Os dados do CNPJ permitem enriquecer fornecedores, vencedores, concorrentes e parceiros com:

- nome empresarial e nome fantasia;
- situação cadastral;
- matriz e filiais;
- CNAE principal e secundários;
- natureza jurídica e porte;
- endereço e município;
- opção pelo Simples Nacional ou SIMEI;
- quadro societário dentro dos limites dos dados públicos.

**Perguntas respondidas:** a empresa está ativa, quais atividades exerce, qual é seu porte, onde está localizada e quais estabelecimentos pertencem à mesma raiz de CNPJ.

**Observação técnica:** os dados abertos do CNPJ são apropriados para carga local e atualização periódica. Não se deve presumir a existência de uma API REST oficial de baixa latência para consultas massivas por CNPJ.

### 4. Portal da Transparência e cadastros da CGU

**Fonte:** [API do Portal da Transparência](https://portaldatransparencia.gov.br/api-de-dados/) e [documentação interativa](https://api.portaldatransparencia.gov.br/).

Consultas relevantes:

- Cadastro Nacional de Empresas Inidôneas e Suspensas (CEIS);
- Cadastro Nacional de Empresas Punidas (CNEP);
- Entidades Privadas sem Fins Lucrativos Impedidas (CEPIM);
- Cadastro de Expulsões da Administração Federal (CEAF);
- acordos de leniência;
- licitações e contratos do Poder Executivo Federal;
- convênios e despesas públicas;
- notas fiscais eletrônicas do Poder Executivo Federal;
- empenhos e favorecidos de despesas.

**Perguntas respondidas:** a empresa possui sanção, quem aplicou a penalidade, qual é sua vigência, quanto o órgão gastou, quais documentos de despesa existem e quem recebeu recursos.

**Sinergia:** altíssima para integridade, concorrência e acompanhamento financeiro.

### 5. Tribunal de Contas da União

**Fonte:** [Webservices de dados abertos do TCU](https://sites.tcu.gov.br/dados-abertos/webservices-tcu/).

Serviços relevantes:

- consulta consolidada de pessoa jurídica;
- licitantes inidôneos;
- responsáveis com contas julgadas irregulares;
- sanções e condenações;
- acórdãos;
- atos normativos do TCU.

**Perguntas respondidas:** a empresa está impedida por decisão do TCU, há contas irregulares relacionadas e quais decisões do Tribunal afetam determinado tema de contratação.

**Sinergia:** alta para habilitação, due diligence e inteligência jurídica.

### 6. SICAF e certidões de regularidade

**Fonte:** [Consultas detalhadas do Portal de Compras](https://www.gov.br/compras/pt-br/acesso-a-informacao/consulta-detalhada) e [informações sobre o SICAF](https://www.gov.br/compras/pt-br/acesso-a-informacao/perguntas-frequentes/sicaf-sistema/sicaf-sistema).

Consultas e documentos normalmente verificados por fornecedores e assessorias:

- situação cadastral no SICAF;
- Certificado de Registro Cadastral (CRC);
- restrições para contratar com a Administração Pública;
- regularidade da Receita Federal e PGFN;
- regularidade do FGTS;
- Certidão Negativa de Débitos Trabalhistas (CNDT);
- certidões estaduais e municipais quando exigidas;
- documentos de qualificação econômico-financeira e técnica.

**Perguntas respondidas:** a empresa possui os documentos necessários para participar e quais certidões estão vencidas ou próximas do vencimento.

**Limitação:** várias dessas consultas não possuem API pública estável. O aplicativo pode manter checklist, validade, arquivos locais e links oficiais, mas não deve contornar CAPTCHA nem afirmar que um resultado armazenado substitui uma certidão oficial atual.

### 7. Transferegov.br

**Fonte:** [API de Dados Abertos do Transferegov.br](https://api-publica.transferegov.gestao.gov.br/) e [página oficial de dados abertos](https://www.gov.br/transferegov/pt-br/ferramentas-gestao/dados-abertos).

Dados de interesse:

- emendas parlamentares e transferências especiais;
- gestão de parcerias;
- transferências fundo a fundo;
- termos de execução descentralizada;
- pagamentos, execução e localização dos recursos;
- arquivos de transferências discricionárias e legais.

**Perguntas respondidas:** de onde virá o dinheiro, qual município ou entidade recebeu recursos, quanto já foi pago e qual projeto poderá gerar futuras contratações.

**Sinergia:** alta para construção, saúde, educação, consultorias, terceiro setor e empresas que acompanham investimentos municipais.

### 8. ObrasGov.br

**Fonte:** [API de Dados Abertos do ObrasGov.br](https://www.gov.br/obrasgov/pt-br/ferramentas-de-gestao-e-transparencia/api-de-dados-abertos-obrasgov-br_novo).

Permite consultar informações estruturadas sobre projetos de investimento e obras públicas, incluindo geolocalização e acompanhamento.

**Perguntas respondidas:** onde a obra está, qual é seu estágio, qual investimento está associado e quais projetos podem gerar demanda por engenharia, materiais, equipamentos ou fiscalização.

**Sinergia:** altíssima para construção, engenharia, infraestrutura, saneamento e fornecedores de materiais.

### 9. SICONFI e Tesouro Transparente

**Fonte:** [API de Dados Abertos do SICONFI](https://www.tesourotransparente.gov.br/consultas/consultas-siconfi/siconfi-api-de-dados-abertos).

Dados relevantes:

- Matriz de Saldos Contábeis;
- receitas e despesas de estados e municípios;
- Declaração de Contas Anuais;
- Relatório Resumido da Execução Orçamentária;
- Relatório de Gestão Fiscal;
- indicadores fiscais, endividamento e capacidade de pagamento.

**Perguntas respondidas:** qual é o tamanho financeiro do ente, como ele executa despesas, qual é sua situação fiscal e se existe capacidade orçamentária compatível com o mercado analisado.

**Sinergia:** média ou alta para análise de compradores públicos e risco de execução.

### 10. Diário Oficial da União e INLABS

**Fonte:** [INLABS da Imprensa Nacional](https://inlabs.in.gov.br/acessar.php).

O INLABS disponibiliza publicações do Diário Oficial da União em XML e PDF. O XML facilita processamento automatizado, mas exige cadastro no portal e não substitui a versão certificada.

Aplicações:

- alertas de atos e extratos contratuais;
- sanções e penalidades;
- mudanças regulatórias;
- nomeações e atos administrativos relevantes;
- publicações que ainda não foram relacionadas corretamente a outras bases.

**Sinergia:** alta como fonte de eventos e alertas, embora a integração seja mais trabalhosa que uma API REST convencional.

### 11. DataJud e Conselho Nacional de Justiça

**Fonte:** [API Pública do DataJud](https://www.cnj.jus.br/sistemas/datajud/api-publica/) e [documentação dos endpoints](https://datajud-wiki.cnj.jus.br/api-publica/endpoints/).

Disponibiliza metadados de processos judiciais públicos e suas movimentações, respeitando exclusões e anonimizações previstas para processos sigilosos.

**Perguntas respondidas:** existe processo público relacionado ao contrato ou à pessoa jurídica, em qual tribunal tramita e quais movimentações públicas foram registradas.

**Cuidados:** obedecer aos termos de uso, evitar pontuações automáticas injustificadas de pessoas ou empresas e tratar corretamente dados pessoais. Resultado judicial não deve ser apresentado como prova automática de irregularidade.

**Sinergia:** média para jurídico, compliance, seguradoras e análise de risco.

### 12. Banco de Preços em Saúde

**Fonte:** [Painel de Preços da Saúde](https://www.gov.br/saude/pt-br/acesso-a-informacao/banco-de-precos/painel) e [conjunto de dados do BPS](https://opendatasus.saude.gov.br/ne/dataset/bps).

O Banco de Preços em Saúde registra compras públicas e privadas de medicamentos e dispositivos médicos.

**Perguntas respondidas:** qual preço foi praticado, em qual localidade, para qual quantidade, por qual instituição compradora e em que período.

**Sinergia:** altíssima para distribuidores de medicamentos, hospitais, laboratórios e fornecedores do SUS.

### 13. Contrata+Brasil

**Fonte:** [Contrata+Brasil](https://www.gov.br/contratamaisbrasil/pt-br/conheca-o-contrata-brasil).

Conecta órgãos públicos a MEIs, fornecedores de alimentos, agricultores familiares, cooperativas e outros pequenos negócios.

**Perguntas respondidas:** quais oportunidades locais estão abertas, quais ocupações ou linhas de fornecimento podem participar e como acompanhar uma proposta simplificada.

**Sinergia:** alta para um módulo dirigido a pequenos negócios e compras locais.

### 14. AntecipaGov

**Fonte:** [Portal AntecipaGov](https://antecipagov.comprasnet.gov.br/) e [orientações ao fornecedor](https://antecipagov.comprasnet.gov.br/AjudaFornecedor.aspx).

Permite que fornecedores utilizem contratos ou empenhos elegíveis como base para operações de crédito com instituições financeiras credenciadas.

**Perguntas respondidas:** quais contratos podem sustentar uma operação de crédito, qual margem está disponível e como acompanhar propostas de antecipação.

**Sinergia:** alta para fintechs, bancos e fornecedores que precisam financiar a execução dos contratos.

### 15. Consultas regulatórias por setor

Algumas consultas possuem grande valor apenas em determinados mercados. Devem ser adicionadas como módulos verticais, depois que o núcleo geral estiver estável.

- **Saúde:** registros, autorizações e situação de produtos ou empresas na Anvisa; preços regulados da CMED; Banco de Preços em Saúde.
- **Obras:** Cadastro Nacional de Obras, ObrasGov, registros profissionais e licenças aplicáveis.
- **Telecomunicações e eletrônicos:** homologações da Anatel e conformidade do Inmetro.
- **Energia:** autorizações, agentes e informações regulatórias da Aneel.
- **Meio ambiente:** licenças e cadastros públicos do Ibama e dos órgãos ambientais competentes.
- **Alimentos e agro:** registros e autorizações do Ministério da Agricultura, Anvisa e programas de compras de alimentos.
- **Dados territoriais:** códigos de municípios, população e indicadores do IBGE para normalização geográfica e análise de mercado.

A disponibilidade de API, licença e automação varia entre os órgãos. Antes de criar um conector, devem ser verificados documentação oficial, termos de uso, estabilidade e existência de dados abertos.

## Combinações por segmento

### Distribuidores de bens e informática

```text
PNCP + Compras.gov + CATMAT/CATSER + CNPJ + CEIS/CNEP/TCU
```

Usos principais: oportunidades, preço vencedor, marcas, concorrentes, atas vigentes e regularidade.

### Serviços, facilities e tecnologia

```text
PNCP + Compras.gov + CNPJ/SICAF + certidões + contratos e despesas
```

Usos principais: escopo, região atendida, custo de mão de obra, habilitação, renovações e histórico do comprador.

### Engenharia e construção

```text
PNCP + ObrasGov + Transferegov + SICONFI + CNPJ/CNO + TCU
```

Usos principais: descobrir projetos antes do edital, origem do recurso, estágio da obra e capacidade financeira do ente.

### Saúde

```text
PNCP + Compras.gov/CATMAT + BPS + Anvisa/CMED + integridade
```

Usos principais: preço de referência, especificação, registro do produto e histórico de secretarias de saúde.

### Assessorias de licitação

```text
Todas as fontes gerais, organizadas por vários CNPJs de clientes
```

Usos principais: alertas, correspondência entre oportunidade e atividade da empresa, documentos, concorrentes e acompanhamento do contrato.

### Crédito, seguros e garantias

```text
Contratos PNCP + empenhos/pagamentos + Portal da Transparência + SICONFI + integridade + DataJud
```

Usos principais: risco do fornecedor, risco do órgão e possibilidade de antecipação de recebíveis.

## Prioridade recomendada para o produto

1. PNCP, Compras.gov.br, CNPJ e CEIS/CNEP/TCU.
2. Portal da Transparência, Transferegov e SICONFI.
3. ObrasGov para engenharia e infraestrutura.
4. BPS e consultas regulatórias para o vertical de saúde.
5. Diário Oficial e DataJud para alertas e inteligência jurídica.
6. Demais integrações regulatórias conforme o público real do aplicativo.

O valor do produto estará menos em exibir todas as bases e mais em relacionar corretamente empresa, órgão, oportunidade, item, preço, contrato, sanção, recurso e pagamento, sempre preservando a origem do dado.
