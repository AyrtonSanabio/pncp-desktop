from __future__ import annotations

SCHEMA_VERSION = 2

MIGRATION_V1 = """
CREATE TABLE IF NOT EXISTS ingestion_run (
    id TEXT PRIMARY KEY,
    resource TEXT NOT NULL,
    data_inicial TEXT NOT NULL,
    data_final TEXT NOT NULL,
    modalidade INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'PLANNED', 'RUNNING', 'PAUSED', 'COMPLETED',
        'COMPLETED_WITH_REJECTIONS', 'FAILED'
    )),
    collector_version TEXT NOT NULL,
    estimated_download_bytes INTEGER NOT NULL,
    estimated_database_bytes INTEGER NOT NULL,
    free_disk_bytes_at_plan INTEGER NOT NULL,
    unmodeled_fields_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS work_unit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES ingestion_run(id) ON DELETE CASCADE,
    resource TEXT NOT NULL,
    data_inicial TEXT NOT NULL,
    data_final TEXT NOT NULL,
    modalidade INTEGER NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number >= 1),
    status TEXT NOT NULL CHECK (status IN (
        'PENDING', 'RUNNING', 'RETRY_WAIT', 'SUCCEEDED', 'PARTIAL', 'FAILED'
    )),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    lease_until TEXT,
    record_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    unchanged_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    bytes_received INTEGER NOT NULL DEFAULT 0,
    payload_hash TEXT,
    latency_ms REAL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE (run_id, resource, data_inicial, data_final, modalidade, page_number)
);

CREATE INDEX IF NOT EXISTS idx_work_unit_claim
    ON work_unit(run_id, status, page_number);

CREATE TABLE IF NOT EXISTS source_payload (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES ingestion_run(id) ON DELETE CASCADE,
    work_unit_id INTEGER NOT NULL REFERENCES work_unit(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    payload_kind TEXT NOT NULL CHECK (payload_kind IN ('PROBE', 'PAGE')),
    request_params_json TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    responded_at TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_url TEXT NOT NULL,
    response_headers_json TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    content_size INTEGER NOT NULL,
    compressed_size INTEGER NOT NULL,
    content_gzip BLOB NOT NULL,
    latency_ms REAL NOT NULL,
    normalizer_version TEXT NOT NULL,
    processed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_source_payload_unit
    ON source_payload(work_unit_id, payload_kind, id);

CREATE TABLE IF NOT EXISTS contratacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_controle_pncp TEXT NOT NULL UNIQUE,
    ano_compra INTEGER,
    sequencial_compra INTEGER,
    numero_compra TEXT,
    processo TEXT,
    objeto_compra TEXT,
    informacao_complementar TEXT,
    orgao_cnpj TEXT,
    orgao_razao_social TEXT,
    orgao_poder_id TEXT,
    orgao_esfera_id TEXT,
    unidade_codigo TEXT,
    unidade_nome TEXT,
    uf_sigla TEXT,
    uf_nome TEXT,
    municipio_nome TEXT,
    codigo_ibge TEXT,
    modalidade_id INTEGER,
    modalidade_nome TEXT,
    modo_disputa_id INTEGER,
    modo_disputa_nome TEXT,
    situacao_compra_id INTEGER,
    situacao_compra_nome TEXT,
    tipo_instrumento_codigo INTEGER,
    tipo_instrumento_nome TEXT,
    amparo_legal_codigo INTEGER,
    amparo_legal_nome TEXT,
    amparo_legal_descricao TEXT,
    srp INTEGER,
    data_inclusao TEXT,
    data_publicacao_pncp TEXT,
    data_atualizacao TEXT,
    data_atualizacao_global TEXT,
    data_abertura_proposta TEXT,
    data_encerramento_proposta TEXT,
    valor_total_estimado TEXT,
    valor_total_homologado TEXT,
    link_sistema_origem TEXT,
    link_processo_eletronico TEXT,
    justificativa_presencial TEXT,
    usuario_nome TEXT,
    fontes_orcamentarias_json TEXT,
    emenda_parlamentar_json TEXT,
    orgao_subrogado_json TEXT,
    unidade_subrogada_json TEXT,
    record_hash TEXT NOT NULL,
    normalizer_version TEXT NOT NULL,
    source_payload_id INTEGER NOT NULL REFERENCES source_payload(id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    local_updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_contratacao_publicacao
    ON contratacao(data_publicacao_pncp);
CREATE INDEX IF NOT EXISTS idx_contratacao_orgao
    ON contratacao(orgao_cnpj);
CREATE INDEX IF NOT EXISTS idx_contratacao_modalidade
    ON contratacao(modalidade_id);
CREATE INDEX IF NOT EXISTS idx_contratacao_localidade
    ON contratacao(uf_sigla, codigo_ibge);
CREATE INDEX IF NOT EXISTS idx_contratacao_situacao
    ON contratacao(situacao_compra_id);

CREATE VIRTUAL TABLE IF NOT EXISTS contratacao_fts USING fts5(
    numero_controle_pncp UNINDEXED,
    objeto_compra,
    informacao_complementar,
    orgao_razao_social,
    unidade_nome,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS data_rejection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES ingestion_run(id) ON DELETE CASCADE,
    work_unit_id INTEGER NOT NULL REFERENCES work_unit(id) ON DELETE CASCADE,
    source_payload_id INTEGER NOT NULL REFERENCES source_payload(id) ON DELETE CASCADE,
    record_index INTEGER NOT NULL,
    reason TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    record_gzip BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_error (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES ingestion_run(id) ON DELETE CASCADE,
    work_unit_id INTEGER REFERENCES work_unit(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    recoverable INTEGER NOT NULL,
    message TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coverage (
    run_id TEXT PRIMARY KEY REFERENCES ingestion_run(id) ON DELETE CASCADE,
    resource TEXT NOT NULL,
    data_inicial TEXT NOT NULL,
    data_final TEXT NOT NULL,
    modalidade INTEGER NOT NULL,
    planned_pages INTEGER NOT NULL,
    processed_pages INTEGER NOT NULL DEFAULT 0,
    partial_pages INTEGER NOT NULL DEFAULT 0,
    records_received INTEGER NOT NULL DEFAULT 0,
    max_source_update TEXT,
    updated_at TEXT NOT NULL
);
"""

MIGRATION_V2 = """
CREATE TABLE IF NOT EXISTS detail_run (
    id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL REFERENCES ingestion_run(id),
    status TEXT NOT NULL CHECK (status IN (
        'PLANNED', 'RUNNING', 'PAUSED', 'COMPLETED',
        'COMPLETED_WITH_REJECTIONS', 'FAILED'
    )),
    page_size INTEGER NOT NULL,
    planned_contracts INTEGER NOT NULL,
    filter_numero_controle TEXT,
    collector_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS detail_work_unit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detail_run_id TEXT NOT NULL REFERENCES detail_run(id) ON DELETE CASCADE,
    contratacao_id INTEGER NOT NULL REFERENCES contratacao(id) ON DELETE CASCADE,
    resource TEXT NOT NULL CHECK (resource IN ('ITEMS', 'RESULTS')),
    item_number INTEGER NOT NULL DEFAULT 0,
    page_number INTEGER NOT NULL DEFAULT 1,
    page_size INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'PENDING', 'RUNNING', 'RETRY_WAIT', 'SUCCEEDED', 'PARTIAL', 'FAILED'
    )),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    lease_until TEXT,
    record_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    unchanged_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    bytes_received INTEGER NOT NULL DEFAULT 0,
    payload_hash TEXT,
    latency_ms REAL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    CHECK (
        (resource = 'ITEMS' AND item_number = 0)
        OR (resource = 'RESULTS' AND item_number >= 1 AND page_number = 1)
    ),
    UNIQUE (detail_run_id, contratacao_id, resource, item_number, page_number)
);

CREATE INDEX IF NOT EXISTS idx_detail_work_claim
    ON detail_work_unit(detail_run_id, status, resource, contratacao_id, page_number);

CREATE TABLE IF NOT EXISTS detail_payload (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detail_run_id TEXT NOT NULL REFERENCES detail_run(id) ON DELETE CASCADE,
    work_unit_id INTEGER NOT NULL REFERENCES detail_work_unit(id) ON DELETE CASCADE,
    resource TEXT NOT NULL CHECK (resource IN ('ITEMS', 'RESULTS')),
    endpoint TEXT NOT NULL,
    request_params_json TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    responded_at TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_url TEXT NOT NULL,
    response_headers_json TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    content_size INTEGER NOT NULL,
    compressed_size INTEGER NOT NULL,
    content_gzip BLOB NOT NULL,
    latency_ms REAL NOT NULL,
    model_validation_errors_json TEXT NOT NULL,
    normalizer_version TEXT NOT NULL,
    processed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS item_contratacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contratacao_id INTEGER NOT NULL REFERENCES contratacao(id) ON DELETE CASCADE,
    numero_item INTEGER NOT NULL,
    descricao TEXT,
    quantidade TEXT,
    unidade_medida TEXT,
    valor_unitario_estimado TEXT,
    valor_total TEXT,
    situacao_id INTEGER,
    situacao_nome TEXT,
    tem_resultado INTEGER,
    material_ou_servico TEXT,
    material_ou_servico_nome TEXT,
    criterio_julgamento_id INTEGER,
    criterio_julgamento_nome TEXT,
    categoria_id INTEGER,
    categoria_nome TEXT,
    ncm_nbs_codigo TEXT,
    ncm_nbs_descricao TEXT,
    catalogo TEXT,
    catalogo_codigo_item TEXT,
    categoria_item_catalogo TEXT,
    tipo_beneficio INTEGER,
    tipo_beneficio_nome TEXT,
    incentivo_produtivo_basico INTEGER,
    orcamento_sigiloso INTEGER,
    margem_preferencia_normal INTEGER,
    margem_preferencia_adicional INTEGER,
    percentual_margem_normal TEXT,
    percentual_margem_adicional TEXT,
    tipo_margem_preferencia TEXT,
    exigencia_conteudo_nacional INTEGER,
    data_inclusao TEXT,
    data_atualizacao TEXT,
    informacao_complementar TEXT,
    patrimonio TEXT,
    codigo_registro_imobiliario TEXT,
    imagem INTEGER,
    record_hash TEXT NOT NULL,
    normalizer_version TEXT NOT NULL,
    source_payload_id INTEGER NOT NULL REFERENCES detail_payload(id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    local_updated_at TEXT NOT NULL,
    UNIQUE (contratacao_id, numero_item)
);

CREATE INDEX IF NOT EXISTS idx_item_contratacao_parent
    ON item_contratacao(contratacao_id, numero_item);
CREATE INDEX IF NOT EXISTS idx_item_catalogo
    ON item_contratacao(catalogo_codigo_item);
CREATE INDEX IF NOT EXISTS idx_item_ncm_nbs
    ON item_contratacao(ncm_nbs_codigo);

CREATE VIRTUAL TABLE IF NOT EXISTS item_contratacao_fts USING fts5(
    numero_controle_pncp UNINDEXED,
    numero_item UNINDEXED,
    descricao,
    informacao_complementar,
    catalogo_codigo_item,
    ncm_nbs_descricao,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS resultado_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES item_contratacao(id) ON DELETE CASCADE,
    sequencial_resultado INTEGER NOT NULL,
    numero_item INTEGER,
    fornecedor_nome TEXT,
    ni_fornecedor TEXT,
    porte_fornecedor_id INTEGER,
    porte_fornecedor_nome TEXT,
    natureza_juridica_id TEXT,
    natureza_juridica_nome TEXT,
    tipo_pessoa TEXT,
    codigo_pais TEXT,
    valor_unitario_homologado TEXT,
    valor_total_homologado TEXT,
    quantidade_homologada TEXT,
    data_resultado TEXT,
    situacao_id INTEGER,
    situacao_nome TEXT,
    percentual_desconto TEXT,
    aplicacao_margem_preferencia INTEGER,
    aplicacao_beneficio_me_epp INTEGER,
    aplicacao_criterio_desempate INTEGER,
    amparo_legal_margem_preferencia TEXT,
    amparo_legal_criterio_desempate TEXT,
    indicador_subcontratacao INTEGER,
    numero_controle_pncp_compra TEXT,
    ordem_classificacao_srp INTEGER,
    reserva_remanescente_codigo INTEGER,
    reserva_remanescente_nome TEXT,
    reserva_remanescente_json TEXT,
    data_inclusao TEXT,
    data_atualizacao TEXT,
    data_cancelamento TEXT,
    moeda_estrangeira TEXT,
    valor_nominal_moeda_estrangeira TEXT,
    data_cotacao_moeda_estrangeira TEXT,
    timezone_cotacao_moeda_estrangeira TEXT,
    fornecedor_uf_nome TEXT,
    fornecedor_uf_sigla TEXT,
    fornecedor_municipio_nome TEXT,
    fornecedor_codigo_ibge TEXT,
    localidade_fornecedor_json TEXT,
    localidade_exterior TEXT,
    pais_origem_produto_servico TEXT,
    motivo_cancelamento TEXT,
    record_hash TEXT NOT NULL,
    normalizer_version TEXT NOT NULL,
    source_payload_id INTEGER NOT NULL REFERENCES detail_payload(id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    local_updated_at TEXT NOT NULL,
    UNIQUE (item_id, sequencial_resultado)
);

CREATE INDEX IF NOT EXISTS idx_resultado_item_parent
    ON resultado_item(item_id, sequencial_resultado);
CREATE INDEX IF NOT EXISTS idx_resultado_fornecedor
    ON resultado_item(ni_fornecedor);
CREATE INDEX IF NOT EXISTS idx_resultado_data
    ON resultado_item(data_resultado);

CREATE TABLE IF NOT EXISTS detail_rejection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detail_run_id TEXT NOT NULL REFERENCES detail_run(id) ON DELETE CASCADE,
    work_unit_id INTEGER NOT NULL REFERENCES detail_work_unit(id) ON DELETE CASCADE,
    source_payload_id INTEGER NOT NULL REFERENCES detail_payload(id) ON DELETE CASCADE,
    resource TEXT NOT NULL,
    record_index INTEGER NOT NULL,
    reason TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    record_gzip BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS detail_error (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detail_run_id TEXT NOT NULL REFERENCES detail_run(id) ON DELETE CASCADE,
    work_unit_id INTEGER REFERENCES detail_work_unit(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    recoverable INTEGER NOT NULL,
    message TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS detail_coverage (
    detail_run_id TEXT PRIMARY KEY REFERENCES detail_run(id) ON DELETE CASCADE,
    planned_contracts INTEGER NOT NULL,
    contracts_with_items INTEGER NOT NULL DEFAULT 0,
    items_seen INTEGER NOT NULL DEFAULT 0,
    items_expecting_results INTEGER NOT NULL DEFAULT 0,
    items_with_results_confirmed INTEGER NOT NULL DEFAULT 0,
    result_records INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""
