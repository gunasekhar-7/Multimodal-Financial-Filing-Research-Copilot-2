from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FilingType(str, Enum):
    FORM_10K = "10-K"
    FORM_10Q = "10-Q"
    FORM_8K = "8-K"


class SectorType(str, Enum):
    TECHNOLOGY = "Technology"


class DataSource(str, Enum):
    DEMO = "demo"
    SEC_EDGAR = "sec_edgar"
    LEGACY_UNKNOWN = "legacy_unknown"


class CompanyInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ticker: str = Field(..., description="Stock ticker symbol (e.g., AAPL)")
    cik: str = Field(..., description="SEC CIK number padded to 10 digits")
    name: str = Field(..., description="Official company name")
    sector: SectorType = SectorType.TECHNOLOGY
    sic: str | None = None
    industry: str | None = None
    fiscal_year_end: str = Field(
        default="12-31",
        description="Month and day of company's fiscal year end (MM-DD, e.g. 09-30 for Apple)",
    )


class XBRLFact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    fact_id: str
    ticker: str
    cik: str
    entity_name: str
    concept: str
    taxonomy: str = "us-gaap"
    label: str
    value: float
    unit: str = "USD"
    fiscal_year: int
    fiscal_period: str  # e.g. FY, Q1, Q2, Q3, Q4
    form: str  # 10-K, 10-Q
    filed_date: str  # YYYY-MM-DD
    period_start: str | None = None
    period_end: str  # YYYY-MM-DD
    is_restated: bool = False
    data_source: DataSource = DataSource.DEMO


class DocumentChunk(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chunk_id: str
    ticker: str
    cik: str
    filing_type: FilingType
    fiscal_year: int
    fiscal_period: str
    filed_date: str
    accession_number: str
    item_section: str
    page_number: int
    content: str
    is_table: bool = False
    table_data: dict[str, Any] | None = None
    source_url: str
    data_source: DataSource = DataSource.DEMO


class SearchQuery(BaseModel):
    query: str
    tickers: list[str] | None = None
    fiscal_years: list[int] | None = None
    fiscal_periods: list[str] | None = None
    sections: list[str] | None = None
    top_k: int = 10


class SearchResultItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chunk: DocumentChunk
    score: float
    retrieval_method: str  # "bm25", "dense_vector", "hybrid_rrf", etc.
