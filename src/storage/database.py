import sqlite3
import json
import logging
import math
from typing import List, Dict, Any, Optional, Tuple
from src.schemas.financial import CompanyInfo, XBRLFact, DocumentChunk, SearchQuery, SearchResultItem, FilingType
from src.ingestion.companies import TARGET_COMPANIES

logger = logging.getLogger(__name__)

class DatabaseStorage:
    def __init__(self, db_path: str = "financial_copilot.db"):
        self.db_path = db_path
        self._init_db()

    def get_connection(self):
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
                    is_restated INTEGER NOT NULL
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
                    source_url TEXT NOT NULL
                )
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

            conn.commit()

        # Seed companies if empty
        self.seed_companies(TARGET_COMPANIES)

    def seed_companies(self, companies: List[CompanyInfo]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for c in companies:
                cursor.execute("""
                    INSERT OR REPLACE INTO companies (ticker, cik, name, sector, sic, industry)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (c.ticker, c.cik, c.name, c.sector, c.sic, c.industry))
            conn.commit()

    def get_all_companies(self) -> List[CompanyInfo]:
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
                    industry=r["industry"]
                ) for r in rows
            ]

    def insert_xbrl_facts(self, facts: List[XBRLFact]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for f in facts:
                cursor.execute("""
                    INSERT OR REPLACE INTO xbrl_facts (
                        fact_id, ticker, cik, entity_name, concept, taxonomy, label, value, unit,
                        fiscal_year, fiscal_period, form, filed_date, period_start, period_end, is_restated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f.fact_id, f.ticker, f.cik, f.entity_name, f.concept, f.taxonomy, f.label,
                    f.value, f.unit, f.fiscal_year, f.fiscal_period, f.form, f.filed_date,
                    f.period_start, f.period_end, 1 if f.is_restated else 0
                ))
            conn.commit()

    def query_xbrl_facts(self, ticker: str, concept: Optional[str] = None, year: Optional[int] = None, period: Optional[str] = None) -> List[XBRLFact]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM xbrl_facts WHERE ticker = ?"
            params: List[Any] = [ticker.upper()]

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
                    is_restated=bool(r["is_restated"])
                ) for r in rows
            ]

    def insert_document_chunks(self, chunks: List[DocumentChunk]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for c in chunks:
                table_data_str = json.dumps(c.table_data) if c.table_data else None
                cursor.execute("""
                    INSERT OR REPLACE INTO document_chunks (
                        chunk_id, ticker, cik, filing_type, fiscal_year, fiscal_period, filed_date,
                        accession_number, item_section, page_number, content, is_table, table_data, source_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    c.chunk_id, c.ticker, c.cik, c.filing_type.value, c.fiscal_year, c.fiscal_period,
                    c.filed_date, c.accession_number, c.item_section, c.page_number, c.content,
                    1 if c.is_table else 0, table_data_str, c.source_url
                ))

                cursor.execute("""
                    INSERT OR REPLACE INTO document_chunks_fts (chunk_id, ticker, item_section, content)
                    VALUES (?, ?, ?, ?)
                """, (c.chunk_id, c.ticker, c.item_section, c.content))
            conn.commit()

    def search_bm25(self, query: SearchQuery) -> List[SearchResultItem]:
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Clean search terms for FTS5
            terms = [t for t in query.query.replace('"', ' ').replace("'", ' ').split() if len(t) > 2]
            if not terms:
                fts_query = query.query
            else:
                fts_query = " OR ".join(terms)

            sql = """
                SELECT c.*, fts.rank
                FROM document_chunks_fts fts
                JOIN document_chunks c ON c.chunk_id = fts.chunk_id
                WHERE document_chunks_fts MATCH ?
            """
            params: List[Any] = [fts_query]

            if query.tickers:
                placeholders = ",".join(["?"] * len(query.tickers))
                sql += f" AND c.ticker IN ({placeholders})"
                params.extend([t.upper() for t in query.tickers])

            if query.fiscal_years:
                placeholders = ",".join(["?"] * len(query.fiscal_years))
                sql += f" AND c.fiscal_year IN ({placeholders})"
                params.extend(query.fiscal_years)

            sql += f" ORDER BY rank LIMIT {query.top_k}"

            try:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                # Fallback to LIKE search if FTS syntax fails
                like_sql = "SELECT c.*, 1.0 as rank FROM document_chunks c WHERE 1=1"
                like_params: List[Any] = []
                if query.tickers:
                    placeholders = ",".join(["?"] * len(query.tickers))
                    like_sql += f" AND c.ticker IN ({placeholders})"
                    like_params.extend([t.upper() for t in query.tickers])
                like_sql += f" LIMIT {query.top_k}"
                cursor.execute(like_sql, like_params)
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
                    source_url=r["source_url"]
                )
                # Convert BM25 rank score (negative number in SQLite FTS) to positive score
                score = abs(float(r["rank"])) if "rank" in r.keys() else 1.0
                results.append(SearchResultItem(chunk=chunk, score=score, retrieval_method="bm25"))
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
