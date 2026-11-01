-- 001__initial_schema.sql
-- Initial schema for the Financial Filing Research Copilot.
-- Represents the schema as of the first migration tooling introduction.

CREATE TABLE IF NOT EXISTS companies (
    ticker TEXT PRIMARY KEY,
    cik TEXT NOT NULL,
    name TEXT NOT NULL,
    sector TEXT NOT NULL,
    sic TEXT,
    industry TEXT
);

CREATE TABLE IF NOT EXISTS xbrl_facts (
    fact_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    cik TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    concept TEXT NOT NULL,
    taxonomy TEXT NOT NULL,
    label TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_period TEXT NOT NULL,
    form TEXT NOT NULL,
    filed_date TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT NOT NULL,
    is_restated INTEGER NOT NULL,
    data_source TEXT NOT NULL DEFAULT 'legacy_unknown'
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    cik TEXT NOT NULL,
    filing_type TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_period TEXT NOT NULL,
    filed_date TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    item_section TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    is_table INTEGER NOT NULL,
    table_data TEXT,
    source_url TEXT NOT NULL,
    data_source TEXT NOT NULL DEFAULT 'legacy_unknown'
);

CREATE TABLE IF NOT EXISTS search_index_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    revision INTEGER NOT NULL
);

INSERT OR IGNORE INTO search_index_state (singleton, revision) VALUES (1, 0);

CREATE TRIGGER IF NOT EXISTS document_chunks_insert_revision
AFTER INSERT ON document_chunks
BEGIN
    UPDATE search_index_state SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS document_chunks_update_revision
AFTER UPDATE ON document_chunks
BEGIN
    UPDATE search_index_state SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS document_chunks_delete_revision
AFTER DELETE ON document_chunks
BEGIN
    UPDATE search_index_state SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
    chunk_id,
    ticker,
    item_section,
    content
);
