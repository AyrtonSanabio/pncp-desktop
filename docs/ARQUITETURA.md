# Arquitetura

## Visão geral

O Consulta PNCP Desktop é uma aplicação PySide6 que usa o pacote `pypncp` para acessar a
API pública do PNCP e SQLite para persistência local.

```text
Interface PySide6
    -> casos de uso de consulta e sincronização
        -> adaptadores HTTP / pypncp
        -> normalização defensiva
        -> repositórios SQLite
            -> payload bruto comprimido
            -> tabelas normalizadas
            -> índices FTS5
```

## Pacotes

### `pncp_desktop`

Contém a janela principal, diálogos, threads da interface, exportação, caminhos do aplicativo
e serviços de leitura do banco. Operações demoradas são executadas em `QThread`, evitando
bloquear a troca de abas.

### `pncp_sync`

Contém configuração, modelos de domínio, adaptadores da API, normalizadores, casos de uso
e repositórios. Não depende dos componentes visuais para executar uma sincronização.

## Fluxo de uma página

1. uma unidade `work_unit` é marcada como `RUNNING` com número máximo de tentativas;
2. o adaptador consulta a página correspondente;
3. tamanho, status HTTP, JSON e paginação são validados;
4. a resposta original é comprimida com gzip;
5. os registros válidos são normalizados e gravados por `upsert`;
6. rejeições ficam preservadas com motivo e hash;
7. payload, registros, cobertura e checkpoint são confirmados na mesma transação;
8. a unidade passa para `SUCCEEDED` ou `PARTIAL`.

Se o processo terminar antes do commit, a página não é considerada concluída e pode ser
repetida com segurança.

## Concorrência e memória

A carga principal mantém dois motores. O sequencial é usado no modo conservador. O motor
acelerado pode manter até 2 ou 4 downloads de páginas em andamento, mas processa e confirma
os resultados um por vez. Assim, SQLite continua com um único fluxo gravador e os checkpoints
mantêm a mesma transação do modo conservador.

A concorrência é adaptativa: começa abaixo do teto, aumenta somente depois de páginas
confirmadas e volta imediatamente para 1 após falha HTTP. O número de respostas mantidas em
memória fica limitado ao teto selecionado, sem relação com o volume nacional. SQLite usa
`busy_timeout`, chaves estrangeiras e modo WAL configurado pelos repositórios.

## Consulta online e banco local

A consulta online é pontual e não representa cobertura. A sincronização grava o banco e
mantém checkpoints. A pesquisa local usa filtros SQL, índices relacionais e FTS5; paginação
impede a criação de milhares de componentes visuais de uma vez.
