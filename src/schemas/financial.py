from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum

class FilingType(str, Enum):
    FORM_10K = "10-K"
    FORM_10Q = "10-Q"
    FORM_8K = "8-K"

class SectorType(str, Enum):
    TECHNOLOGY = "Technology"

class CompanyInfo(BaseModel):
    model_config = ConfigDict(extra='ignore')
    ticker: str = Field(..., description="Stock ticker symbol (e.g., AAPL)")
    cik: str = Field(..., description="SEC CIK number padded to 10 digits")
    name: str = Field(..., description="Official company name")
    sector: SectorType = SectorType.TECHNOLOGY
    sic: Optional[str] = None
    industry: Optional[str] = None

class XBRLFact(BaseModel):
    model_config = ConfigDict(extra='ignore')
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
    fiscal_period: str # e.g. FY, Q1, Q2, Q3, Q4
    form: str # 10-K, 10-Q
    filed_date: str # YYYY-MM-DD
    period_start: Optional[str] = None
    period_end: str # YYYY-MM-DD
    is_restated: bool = False

class DocumentChunk(BaseModel):
    model_config = ConfigDict(extra='ignore')
    chunk_id: str
    ticker: str
    cik: str
    filing_type: FilingType
    fiscal_year: int
    fiscal_period: str
    filed_date: str
    accession_number: str
    item_section: str # e.g., "Item 1A. Risk Factors", "Item 7. MD&A"
    page_number: int
    content: str
    is_table: bool = False
    table_data: Optional[Dict[str, Any]] = None
    source_url: str

class SearchQuery(BaseModel):
    query: str
    tickers: Optional[List[str]] = None
    filing_types: Optional[List[FilingType]] = None
    fiscal_years: Optional[List[int]] = None
    fiscal_periods: Optional[List[str]] = None
    sections: Optional[List[str]] = None
    top_k: int = Field(default=10, ge=1, le=100)

class SearchResultItem(BaseModel):
    model_config = ConfigDict(extra='ignore')
    chunk: DocumentChunk
    score: float
    retrieval_method: str # e.g., "bm25", "vector", "hybrid"
