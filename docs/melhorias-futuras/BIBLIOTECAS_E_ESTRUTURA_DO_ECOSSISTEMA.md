# Bibliotecas e estrutura do ecossistema

## Objetivo

Planejar novas bibliotecas de consulta a dados públicos sem transformar o `pypncp` ou o aplicativo desktop em uma biblioteca monolítica que conhece todos os sistemas do governo.

Os nomes apresentados neste documento são conceituais. Antes de publicar pacotes, será necessário verificar disponibilidade no PyPI, identidade do projeto e compatibilidade com o ecossistema já existente.

## Princípio de separação

Cada fonte governamental deve possuir um conector pequeno e independente. A normalização e a combinação entre fontes pertencem a uma camada superior.

```text
Fontes oficiais
    -> bibliotecas de consulta independentes
        -> adaptadores do aplicativo
            -> modelos normalizados e casos de uso
                -> interface desktop, API ou serviço de alertas
```

Benefícios:

- uma mudança no Compras.gov.br não exige nova versão da biblioteca do PNCP;
- usuários podem instalar somente as integrações necessárias;
- falha em uma fonte não derruba as demais;
- testes e limites de acesso ficam específicos por provedor;
- cada biblioteca pode ter ciclo de lançamento próprio;
- o aplicativo continua responsável pela experiência integrada.

## Primeiras bibliotecas recomendadas

### 1. Compras.gov.br

Nome conceitual: `govbr-compras`.

Responsabilidades:

- CATMAT e CATSER;
- pesquisa de preços praticados;
- fornecedores públicos disponíveis na API;
- contratações, itens e resultados;
- atas de registro de preços;
- contratos e itens de contratos;
- paginação, filtros e downloads documentados pela fonte.

É a primeira extensão recomendada porque atende o mesmo usuário do PNCP e complementa diretamente pesquisa de preço, concorrentes e classificação de itens.

### 2. Receita Federal e CNPJ

Nome conceitual: `govbr-cnpj`.

Responsabilidades:

- baixar e validar arquivos oficiais;
- importar empresas, estabelecimentos e tabelas de domínio;
- consultar por CNPJ completo ou raiz;
- pesquisar CNAE, porte, município e situação cadastral;
- registrar competência e data da carga;
- permitir atualização incremental quando a fonte oferecer mecanismo adequado.

Essa biblioteca provavelmente será orientada a carga local e consulta em banco de dados, e não apenas a requisições HTTP pontuais.

### 3. Integridade pública

Nome conceitual: `govbr-integridade`.

Responsabilidades:

- CEIS;
- CNEP;
- CEPIM;
- acordos de leniência;
- licitantes inidôneos do TCU;
- contas julgadas irregulares;
- consulta consolidada de pessoa jurídica;
- preservação da fonte, período e autoridade responsável pela sanção.

A biblioteca deve retornar registros factuais. Não deve emitir automaticamente um veredito genérico de empresa "segura" ou "insegura".

### 4. Recursos e finanças públicas

Nome conceitual: `govbr-financas-publicas`.

Responsabilidades possíveis:

- despesas, contratos, convênios e documentos do Portal da Transparência;
- transferências e emendas do Transferegov.br;
- informações fiscais do SICONFI;
- empenhos, liquidações e pagamentos quando públicos e documentados;
- identificação da fonte e da esfera de cada registro.

Como esse domínio é amplo, pode futuramente ser dividido em `govbr-transparencia`, `govbr-transferencias` e `govbr-siconfi` se os ciclos técnicos se tornarem muito diferentes.

### 5. Obras públicas

Nome conceitual: `govbr-obras`.

Responsabilidades:

- API do ObrasGov.br;
- localização e situação de projetos de investimento;
- identificadores que permitam relacionar obra, transferência, órgão e contratação;
- normalização geográfica por município e coordenadas;
- integração opcional com o Cadastro Nacional de Obras quando houver fonte pública apropriada.

### 6. Diário Oficial

Nome conceitual: `govbr-diarios`.

Responsabilidades:

- aquisição dos XML e metadados oficiais do INLABS;
- indexação por data, seção, órgão e assunto;
- pesquisa e detecção de novas publicações;
- preservação do link para a versão oficial certificada;
- adaptadores futuros para diários estaduais ou municipais, sem fingir que todos seguem o mesmo padrão.

### 7. Saúde

Nome conceitual: `govbr-saude`.

Responsabilidades iniciais:

- Banco de Preços em Saúde;
- códigos e descrições necessárias para relacionar produtos;
- preços, quantidades, fornecedores e instituições compradoras;
- conectores regulatórios oficiais adicionados separadamente quando houver documentação e permissão adequadas.

### 8. Judiciário

Nome conceitual: `govbr-judiciario`.

Responsabilidades iniciais:

- cliente para a API Pública do DataJud;
- aliases dos tribunais;
- consultas e paginação no formato documentado;
- modelos de capa e movimentações processuais públicas;
- cumprimento dos termos de uso e proteção de dados pessoais.

Deve ser criado depois das fontes diretamente ligadas ao ciclo da contratação.

## Estrutura conceitual dos pacotes

```text
govbr-core
govbr-pncp             # papel atualmente atendido pelo pypncp
govbr-compras
govbr-cnpj
govbr-integridade
govbr-financas-publicas
govbr-obras
govbr-diarios
govbr-saude
govbr-judiciario
```

O nome `govbr-pncp` é apenas uma representação arquitetural. O projeto já utiliza `pypncp`; não há motivo para substituir ou duplicar essa biblioteca sem uma decisão explícita.

## Responsabilidade do núcleo compartilhado

O `govbr-core` deve conter somente infraestrutura reutilizável:

- cliente HTTP e configuração de timeout;
- políticas de tentativas e espera progressiva;
- paginação comum quando realmente compatível;
- limites de concorrência;
- cache e controle de validade;
- formatação e validação de CNPJ;
- tipos comuns de data, dinheiro e localidade;
- metadados de procedência;
- erros básicos de rede, autenticação da fonte e validação;
- instrumentação e logs sem dados sensíveis.

O núcleo não deve conhecer campos específicos de edital, sanção, processo judicial ou medicamento. Se uma abstração só funciona para uma fonte, ela pertence ao pacote dessa fonte.

## Estrutura interna sugerida para cada biblioteca

```text
pacote_da_fonte/
    client.py          # comunicação com a fonte
    endpoints.py       # rotas públicas documentadas
    models.py          # modelos fiéis à resposta da fonte
    pagination.py      # paginação específica, se necessária
    errors.py          # erros próprios da integração
    metadata.py        # versão, fonte e data de atualização
tests/
    unit/
    contract/
```

Regras:

- modelos da fonte devem preservar os nomes e significados originais;
- normalização entre fontes não deve apagar o dado bruto;
- mudanças incompatíveis na fonte devem ser detectadas por testes de contrato;
- cada resposta normalizada deve manter referência ao provedor e ao identificador original;
- bibliotecas de consulta não devem tomar decisões comerciais pelo usuário.

## Estrutura do aplicativo agregador

```text
Interface desktop
    -> casos de uso
        -> serviços de pesquisa e relacionamento
            -> modelos normalizados do aplicativo
                -> adaptador PNCP -> pypncp
                -> adaptador Compras -> govbr-compras
                -> adaptador CNPJ -> govbr-cnpj
                -> adaptador Integridade -> govbr-integridade
                -> demais adaptadores
```

O aplicativo não deve importar diretamente detalhes de todos os endpoints dentro da interface. Cada adaptador traduz a biblioteca externa para os modelos de apresentação do aplicativo.

## Entidades normalizadas no aplicativo

O software integrado pode relacionar:

- empresa e estabelecimento por CNPJ completo e raiz;
- órgão comprador por CNPJ;
- unidade compradora por código próprio e UASG quando aplicável;
- município por código IBGE;
- oportunidade pelo número de controle do PNCP;
- material ou serviço por CATMAT/CATSER;
- item, resultado, fornecedor e preço;
- ata, contrato, empenho e pagamento;
- transferência, emenda, projeto e obra;
- sanção e órgão sancionador;
- publicação oficial e processo judicial público.

Cada entidade combinada precisa informar:

- fonte original;
- identificador original;
- data da consulta ou competência;
- data de atualização informada pela fonte;
- nível de confiança do relacionamento quando não houver chave exata.

## Primeiros produtos sobre as bibliotecas

### Radar de oportunidades

- novas contratações;
- itens do PCA;
- filtros por objeto, região e atividade da empresa;
- contratos e atas próximos do vencimento;
- alertas controlados pelo usuário.

### Inteligência da contratação

- preços anteriores;
- vencedores e participantes;
- órgãos compradores recorrentes;
- itens semelhantes;
- histórico de contratos e atas.

### Perfil da empresa

- situação cadastral e atividades;
- histórico como fornecedor;
- sanções encontradas em cada fonte;
- checklist de documentos e validade;
- vínculos entre matriz e filiais.

### Perfil do órgão

- compras anteriores;
- contratos vigentes;
- recursos e transferências;
- indicadores fiscais;
- pagamentos e projetos relacionados.

## Ordem de implementação

### Fase 1 - núcleo do mercado público

1. Manter e estabilizar o uso do `pypncp`.
2. Criar o cliente do Compras.gov.br.
3. Criar o carregador e consulta local do CNPJ.
4. Criar a biblioteca de integridade com CGU e TCU.
5. Entregar oportunidade, preço, empresa e sanção em uma única experiência.

### Fase 2 - origem e execução do recurso

1. Portal da Transparência.
2. Transferegov.br.
3. SICONFI.
4. ObrasGov.br.

### Fase 3 - alertas e verticais

1. Diário Oficial da União.
2. Banco de Preços em Saúde.
3. DataJud.
4. Conectores regulatórios conforme demanda comprovada dos usuários.

## Limite arquitetural obrigatório

Todas as bibliotecas relacionadas ao PNCP neste ecossistema serão de consulta. O projeto não implementará publicação, retificação ou exclusão de dados no PNCP. Essa decisão está detalhada em [Política de somente leitura e credenciamento](../POLITICA_SOMENTE_LEITURA_E_CREDENCIAMENTO.md).
