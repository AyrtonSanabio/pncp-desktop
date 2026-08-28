# Segurança e responsabilidade

## Somente leitura perante o PNCP

O aplicativo consulta endpoints públicos. Não existem funções de publicação, retificação,
exclusão, homologação ou atuação em nome de órgão público. Operações dessa natureza exigiriam
credenciamento, autenticação, autorização institucional e responsabilidade operacional que
não fazem parte do software.

## Validações técnicas

- somente URLs HTTPS são aceitas para as fontes configuradas;
- respostas possuem limite padrão de 25 MB;
- status HTTP, JSON, listas, números de página e totais são validados;
- cada lote possui no máximo 31 dias;
- identificadores obrigatórios e valores são normalizados defensivamente;
- registros inválidos são isolados, comprimidos e registrados com motivo;
- hashes detectam alteração e corrupção de payload;
- chaves únicas e estrangeiras protegem relações no SQLite;
- backup e manutenção verificam a integridade antes de informar sucesso.

## Dados pessoais

O PNCP pode publicar identificadores de fornecedores ou responsáveis. O aplicativo deve ser
usado para finalidade legítima relacionada às contratações públicas. A existência de um nome,
CNPJ ou outro identificador no banco não autoriza criação de perfis indevidos nem conclusões
automáticas sobre pessoas ou empresas.

## Limites jurídicos

O banco local é uma cópia técnica sujeita a atraso, indisponibilidade, retificação e erro da
fonte. Ele não substitui:

- o registro atual no portal oficial;
- edital, contrato, ata, certidão ou documento assinado;
- análise jurídica, contábil, cadastral ou decisão administrativa.

Valores, prazos e situações relevantes devem ser confirmados no PNCP e nos documentos do
processo antes de qualquer decisão comercial ou jurídica.

O órgão publicador responde pelo conteúdo enviado ao PNCP. O projeto responde por consultar,
preservar e apresentar os dados sem alterar a fonte, deixando origem e limitações visíveis.
