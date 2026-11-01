import json
import logging
import os
import re
import sqlite3
from typing import Any

from src.ingestion.companies import TARGET_COMPANIES
from src.schemas.financial import (
    CompanyInfo,
    DataSource,
    DocumentChunk,
    FilingType,
    SearchQuery,
    SearchResultItem,
    XBRLFact,
)
from src.storage.migrations import run_migrations

logger = logging.getLogger(__name__)


class DatabaseStorage:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("DATABASE_PATH", "financial_copilot.db")
        self._init_db()

    def get_connection(self):
        parent = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Companies table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS companies (
                    ticker TEXT PRIMARY KEY,
                    cik TEXT NOT NULL,
                    name TEXT NOT NULL,
                    sector TEXT NOT NULL,
                    sic TEXT,
                    industry TEXT
                )
            """)

            # XBRL Facts table
            cursor.execute("""
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
                )
            """)

            # Chunks table
            cursor.execute("""
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
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_index_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    revision INTEGER NOT NULL
                )
            """)
            cursor.execute(
                "INSERT OR IGNORE INTO search_index_state (singleton, revision) VALUES (1, 0)"
            )
            for action in ("INSERT", "UPDATE", "DELETE"):
                cursor.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS document_chunks_{action.lower()}_revision
                    AFTER {action} ON document_chunks
                    BEGIN
                        UPDATE search_index_state SET revision = revision + 1 WHERE singleton = 1;
                    END
                """)

            # FTS5 full-text search index for document_chunks
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
                    chunk_id,
                    ticker,
                    item_section,
                    content
                )
            """)

            self._ensure_column(
                conn,
                "xbrl_facts",
                "data_source",
                "TEXT NOT NULL DEFAULT 'legacy_unknown'",
            )
            self._ensure_column(
                conn,
                "document_chunks",
                "data_source",
                "TEXT NOT NULL DEFAULT 'legacy_unknown'",
            )
            # Repair legacy duplicate/stale FTS entries, including databases
            # created before FTS rows were maintained idempotently.
            cursor.execute("DELETE FROM document_chunks_fts")
            cursor.execute("""
                INSERT INTO document_chunks_fts (chunk_id, ticker, item_section, content)
                SELECT chunk_id, ticker, item_section, content FROM document_chunks
            """)
            conn.commit()

        # Run schema migrations (idempotent). Migration 001 represents the
        # current schema; future schema changes are applied via new SQL files.
        run_migrations(db_path=self.db_path)

        # Seed companies if empty
        self.seed_companies(TARGET_COMPANIES)

    @staticmethod
    def _ensure_column(conn, table: str, column: str, definition: str) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def seed_companies(self, companies: list[CompanyInfo]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for c in companies:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO companies (ticker, cik, name, sector, sic, industry)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (c.ticker, c.cik, c.name, c.sector, c.sic, c.industry),
                )
            conn.commit()

    def get_all_companies(self) -> list[CompanyInfo]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM companies")
            rows = cursor.fetchall()
            return [
                CompanyInfo(
                    ticker=r["ticker"],
                    cik=r["cik"],
                    name=r["name"],
                    sector=r["sector"],
                    sic=r["sic"],
                    industry=r["industry"],
                )
                for r in rows
            ]

    def insert_xbrl_facts(self, facts: list[XBRLFact]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for f in facts:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO xbrl_facts (
                        fact_id, ticker, cik, entity_name, concept, taxonomy, label, value, unit,
                        fiscal_year, fiscal_period, form, filed_date, period_start, period_end, is_restated, data_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        f.fact_id,
                        f.ticker,
                        f.cik,
                        f.entity_name,
                        f.concept,
                        f.taxonomy,
                        f.label,
                        f.value,
                        f.unit,
                        f.fiscal_year,
                        f.fiscal_period,
                        f.form,
                        f.filed_date,
                        f.period_start,
                        f.period_end,
                        1 if f.is_restated else 0,
                        f.data_source.value,
                    ),
                )
            conn.commit()

    def query_xbrl_facts(
        self,
        ticker: str,
        concept: str | None = None,
        year: int | None = None,
        period: str | None = None,
        data_source: DataSource | None = None,
    ) -> list[XBRLFact]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM xbrl_facts WHERE ticker = ?"
            params: list[Any] = [ticker.upper()]
            if data_source is not None:
                query += " AND data_source = ?"
                params.append(data_source.value)

            if concept:
                query += " AND (concept LIKE ? OR label LIKE ?)"
                params.extend([f"%{concept}%", f"%{concept}%"])
            if year:
                query += " AND fiscal_year = ?"
                params.append(year)
            if period:
                query += " AND fiscal_period = ?"
                params.append(period)

            query += " ORDER BY fiscal_year ASC, fiscal_period ASC"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [
                XBRLFact(
                    fact_id=r["fact_id"],
                    ticker=r["ticker"],
                    cik=r["cik"],
                    entity_name=r["entity_name"],
                    concept=r["concept"],
                    taxonomy=r["taxonomy"],
                    label=r["label"],
                    value=r["value"],
                    unit=r["unit"],
                    fiscal_year=r["fiscal_year"],
                    fiscal_period=r["fiscal_period"],
                    form=r["form"],
                    filed_date=r["filed_date"],
                    period_start=r["period_start"],
                    period_end=r["period_end"],
                    is_restated=bool(r["is_restated"]),
                    data_source=DataSource(r["data_source"]),
                )
                for r in rows
            ]

    def insert_document_chunks(self, chunks: list[DocumentChunk]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for c in chunks:
                table_data_str = json.dumps(c.table_data) if c.table_data else None
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO document_chunks (
                        chunk_id, ticker, cik, filing_type, fiscal_year, fiscal_period, filed_date,
                        accession_number, item_section, page_number, content, is_table, table_data, source_url, data_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        c.chunk_id,
                        c.ticker,
                        c.cik,
                        c.filing_type.value,
                        c.fiscal_year,
                        c.fiscal_period,
                        c.filed_date,
                        c.accession_number,
                        c.item_section,
                        c.page_number,
                        c.content,
                        1 if c.is_table else 0,
                        table_data_str,
                        c.source_url,
                        c.data_source.value,
                    ),
                )

                cursor.execute(
                    "DELETE FROM document_chunks_fts WHERE chunk_id = ?", (c.chunk_id,)
                )
                cursor.execute(
                    """
                    INSERT INTO document_chunks_fts (chunk_id, ticker, item_section, content)
                    VALUES (?, ?, ?, ?)
                """,
                    (c.chunk_id, c.ticker, c.item_section, c.content),
                )
            conn.commit()

    def replace_seed_data(
        self, facts: list[XBRLFact], chunks: list[DocumentChunk]
    ) -> None:
        """Atomically replace the generated corpus and keep FTS in sync."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM xbrl_facts")
            conn.execute("DELETE FROM document_chunks")
            conn.execute("DELETE FROM document_chunks_fts")
            for fact in facts:
                conn.execute(
                    """
                    INSERT INTO xbrl_facts (
                        fact_id, ticker, cik, entity_name, concept, taxonomy, label, value, unit,
                        fiscal_year, fiscal_period, form, filed_date, period_start, period_end, is_restated, data_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        fact.fact_id,
                        fact.ticker,
                        fact.cik,
                        fact.entity_name,
                        fact.concept,
                        fact.taxonomy,
                        fact.label,
                        fact.value,
                        fact.unit,
                        fact.fiscal_year,
                        fact.fiscal_period,
                        fact.form,
                        fact.filed_date,
                        fact.period_start,
                        fact.period_end,
                        int(fact.is_restated),
                        fact.data_source.value,
                    ),
                )
            for chunk in chunks:
                conn.execute(
                    """
                    INSERT INTO document_chunks (
                        chunk_id, ticker, cik, filing_type, fiscal_year, fiscal_period, filed_date,
                        accession_number, item_section, page_number, content, is_table, table_data,
                        source_url, data_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        chunk.chunk_id,
                        chunk.ticker,
                        chunk.cik,
                        chunk.filing_type.value,
                        chunk.fiscal_year,
                        chunk.fiscal_period,
                        chunk.filed_date,
                        chunk.accession_number,
                        chunk.item_section,
                        chunk.page_number,
                        chunk.content,
                        int(chunk.is_table),
                        json.dumps(chunk.table_data) if chunk.table_data else None,
                        chunk.source_url,
                        chunk.data_source.value,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO document_chunks_fts (chunk_id, ticker, item_section, content)
                    VALUES (?, ?, ?, ?)
                """,
                    (chunk.chunk_id, chunk.ticker, chunk.item_section, chunk.content),
                )

    def search_bm25(
        self, query: SearchQuery, data_source: DataSource | None = None
    ) -> list[SearchResultItem]:
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Sanitize search terms into plain alphanumeric tokens for FTS5.
            # Punctuation such as '?' is a syntax error inside an FTS5 MATCH
            # expression, and leaving it in made every question ending in a
            # question mark silently degrade to the unranked LIKE fallback.
            # Tokens longer than 3 chars become prefix queries so "revenue"
            # also matches the indexed "Revenues:" (FTS5 does not stem), which
            # is how the financial-statement chunks carry their figures.
            tokens = [
                t.lower()
                for t in re.findall(r"[A-Za-z0-9]+", query.query)
                if len(t) > 2
            ]
            if not tokens:
                fts_query = query.query
            else:
                fts_query = " OR ".join(t + "*" if len(t) > 3 else t for t in tokens)

            sql = """
                SELECT c.*, fts.rank
                FROM document_chunks_fts fts
                JOIN document_chunks c ON c.chunk_id = fts.chunk_id
                WHERE document_chunks_fts MATCH ?
            """
            params: list[Any] = [fts_query]
            if data_source is not None:
                sql += " AND c.data_source = ?"
                params.append(data_source.value)

            if query.tickers:
                # Sanitize tickers: only accept known uppercase tickers to prevent
                # injection via unexpected values in the IN clause
                valid_tickers = [
                    t.upper() for t in query.tickers if isinstance(t, str) and t.upper()
                ]
                if valid_tickers:
                    placeholders = ",".join(["?"] * len(valid_tickers))
                    sql += f" AND c.ticker IN ({placeholders})"
                    params.extend(valid_tickers)

            if query.fiscal_years:
                # Clamp fiscal years to reasonable range to prevent injection
                valid_years = [
                    y
                    for y in query.fiscal_years
                    if isinstance(y, int) and 1900 <= y <= 2100
                ]
                if valid_years:
                    placeholders = ",".join(["?"] * len(valid_years))
                    sql += f" AND c.fiscal_year IN ({placeholders})"
                    params.extend(valid_years)

            if query.sections:
                # Section hints are trusted planner output used as exact
                # string prefixes (e.g. "Item 8."), matched as filter
                # parameters — never interpolated into SQL.
                like_clauses = []
                like_params: list[Any] = []
                for section in query.sections:
                    if isinstance(section, str) and section.strip():
                        like_clauses.append("c.item_section LIKE ?")
                        like_params.append(section.replace("%", "") + "%")
                if like_clauses:
                    sql += " AND (" + " OR ".join(like_clauses) + ")"
                    params.extend(like_params)

            sql += " ORDER BY rank LIMIT ?"
            # Clamp top_k to a safe range to prevent SQL injection via oversized LIMIT
            top_k = max(1, min(int(query.top_k), 100))  # max 100 results
            params.append(top_k)

            try:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                # Fallback to LIKE search if FTS syntax fails
                like_sql = "SELECT c.*, 1.0 as rank FROM document_chunks c WHERE 1=1"
                like_params_fallback: list[Any] = []
                if data_source is not None:
                    like_sql += " AND c.data_source = ?"
                    like_params_fallback.append(data_source.value)
                if query.tickers:
                    placeholders = ",".join(["?"] * len(query.tickers))
                    like_sql += f" AND c.ticker IN ({placeholders})"
                    like_params_fallback.extend([t.upper() for t in query.tickers])
                if query.fiscal_years:
                    valid_years = [
                        y
                        for y in query.fiscal_years
                        if isinstance(y, int) and 1900 <= y <= 2100
                    ]
                    if valid_years:
                        placeholders = ",".join(["?"] * len(valid_years))
                        like_sql += f" AND c.fiscal_year IN ({placeholders})"
                        like_params_fallback.extend(valid_years)
                if query.fiscal_periods:
                    placeholders = ",".join(["?"] * len(query.fiscal_periods))
                    like_sql += f" AND c.fiscal_period IN ({placeholders})"
                    like_params_fallback.extend(query.fiscal_periods)
                if query.sections:
                    like_clauses = []
                    for section in query.sections:
                        if isinstance(section, str) and section.strip():
                            like_clauses.append("item_section LIKE ?")
                            like_params_fallback.append(section.replace("%", "") + "%")
                    if like_clauses:
                        like_sql += " AND (" + " OR ".join(like_clauses) + ")"
                like_sql += " LIMIT ?"
                like_params_fallback.append(int(query.top_k))
                cursor.execute(like_sql, like_params_fallback)
                rows = cursor.fetchall()

            results = []
            for r in rows:
                chunk = DocumentChunk(
                    chunk_id=r["chunk_id"],
                    ticker=r["ticker"],
                    cik=r["cik"],
                    filing_type=FilingType(r["filing_type"]),
                    fiscal_year=r["fiscal_year"],
                    fiscal_period=r["fiscal_period"],
                    filed_date=r["filed_date"],
                    accession_number=r["accession_number"],
                    item_section=r["item_section"],
                    page_number=r["page_number"],
                    content=r["content"],
                    is_table=bool(r["is_table"]),
                    table_data=json.loads(r["table_data"]) if r["table_data"] else None,
                    source_url=r["source_url"],
                    data_source=DataSource(r["data_source"]),
                )
                # Convert BM25 rank score (negative number in SQLite FTS) to positive score
                score = abs(float(r["rank"])) if "rank" in r else 1.0
                results.append(
                    SearchResultItem(chunk=chunk, score=score, retrieval_method="bm25")
                )
            return results

    def get_chunk_count(self) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM document_chunks")
            return cursor.fetchone()[0]

    def get_fact_count(self) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM xbrl_facts")
            return cursor.fetchone()[0]
