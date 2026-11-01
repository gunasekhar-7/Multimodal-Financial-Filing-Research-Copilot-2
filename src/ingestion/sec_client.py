import logging
import os
import re
from typing import Any

import httpx

from src.schemas.financial import (
    CompanyInfo,
    DataSource,
    DocumentChunk,
    FilingType,
    XBRLFact,
)

logger = logging.getLogger(__name__)

# Base 8 quarters: 2023-Q1 through 2024-Q4
QUARTERS = [
    ("2023", "Q1", "2023-03-31", "10-Q"),
    ("2023", "Q2", "2023-06-30", "10-Q"),
    ("2023", "Q3", "2023-09-30", "10-Q"),
    ("2023", "FY", "2023-12-31", "10-K"),
    ("2024", "Q1", "2024-03-31", "10-Q"),
    ("2024", "Q2", "2024-06-30", "10-Q"),
    ("2024", "Q3", "2024-09-30", "10-Q"),
    ("2024", "FY", "2024-12-31", "10-K"),
]

# Approximate diluted shares outstanding used for EPS estimation (in millions).
APPROX_SHARES_MILLIONS = 2500.0

# Baseline revenue and net income estimates for top companies to generate deterministic XBRL facts
BASE_FINANCIALS: dict[str, dict[str, Any]] = {
    "AAPL": {"base_rev": 90000.0, "base_ni": 23000.0, "growth": 0.02},
    "MSFT": {"base_rev": 52000.0, "base_ni": 18000.0, "growth": 0.04},
    "GOOGL": {"base_rev": 69000.0, "base_ni": 15000.0, "growth": 0.03},
    "AMZN": {"base_rev": 127000.0, "base_ni": 3100.0, "growth": 0.05},
    "NVDA": {"base_rev": 7192.0, "base_ni": 2043.0, "growth": 0.45},
    "META": {"base_rev": 28645.0, "base_ni": 5709.0, "growth": 0.06},
    "TSLA": {"base_rev": 23329.0, "base_ni": 2513.0, "growth": 0.03},
    "AVGO": {"base_rev": 8915.0, "base_ni": 3774.0, "growth": 0.04},
    "ORCL": {"base_rev": 12398.0, "base_ni": 2400.0, "growth": 0.03},
    "CSCO": {"base_rev": 13600.0, "base_ni": 2800.0, "growth": 0.01},
}


def projected_period_values(
    base_rev: float,
    base_ni: float,
    growth: float,
    quarters: list[tuple] = QUARTERS,
) -> list[dict[str, Any]]:
    """Project revenue, net income, and EPS across a list of fiscal periods.

    Centralizes the quarter-loop and growth math so fact and chunk generators
    share a single source of truth. Returns a list of dicts with keys:
    year, period, end_date, form, period_rev, period_ni, period_eps, filed_date, idx.
    """
    results = []
    rev = base_rev
    ni = base_ni
    growth_rate = growth
    for idx, (year, period, end_date, form) in enumerate(quarters):
        period_rev = round(rev * ((1 + growth_rate) ** idx), 2)
        period_ni = round(ni * ((1 + growth_rate) ** idx), 2)
        period_eps = round(period_ni / APPROX_SHARES_MILLIONS, 2)
        filed_date = end_date.replace("31", "28").replace("30", "28")
        results.append(
            {
                "year": year,
                "period": period,
                "end_date": end_date,
                "form": form,
                "period_rev": period_rev,
                "period_ni": period_ni,
                "period_eps": period_eps,
                "filed_date": filed_date,
                "idx": idx,
            }
        )
    return results


class DemoDataGenerator:
    """Deterministic synthetic data generator for offline/demo mode.

    Produces XBRL facts and document chunks that look like SEC filings but are
    entirely generated. Never makes network requests. Used as the default
    data source when DATA_MODE=demo.
    """

    def __init__(self):
        pass

    def _base_info(self, company: CompanyInfo) -> dict[str, Any]:
        return BASE_FINANCIALS.get(
            company.ticker, {"base_rev": 10000.0, "base_ni": 2000.0, "growth": 0.03}
        )

    def generate_facts(self, company: CompanyInfo) -> list[XBRLFact]:
        """Generate deterministic mock XBRL facts for a company across all periods."""
        facts: list[XBRLFact] = []
        base_info = self._base_info(company)
        for pv in projected_period_values(
            base_info["base_rev"], base_info["base_ni"], base_info["growth"]
        ):
            # Revenue
            facts.append(
                XBRLFact(
                    fact_id=f"{company.ticker}-{pv['year']}-{pv['period']}-Revenues",
                    ticker=company.ticker,
                    cik=company.cik,
                    entity_name=company.name,
                    concept="Revenues",
                    taxonomy="us-gaap",
                    label="Revenues",
                    value=pv["period_rev"] * 1_000_000.0,
                    unit="USD",
                    fiscal_year=int(pv["year"]),
                    fiscal_period=pv["period"],
                    form=pv["form"],
                    filed_date=pv["filed_date"],
                    period_end=pv["end_date"],
                    is_restated=False,
                    data_source=DataSource.DEMO,
                )
            )
            # Net Income
            facts.append(
                XBRLFact(
                    fact_id=f"{company.ticker}-{pv['year']}-{pv['period']}-NetIncomeLoss",
                    ticker=company.ticker,
                    cik=company.cik,
                    entity_name=company.name,
                    concept="NetIncomeLoss",
                    taxonomy="us-gaap",
                    label="Net Income (Loss)",
                    value=pv["period_ni"] * 1_000_000.0,
                    unit="USD",
                    fiscal_year=int(pv["year"]),
                    fiscal_period=pv["period"],
                    form=pv["form"],
                    filed_date=pv["filed_date"],
                    period_end=pv["end_date"],
                    is_restated=False,
                    data_source=DataSource.DEMO,
                )
            )
            # EPS
            facts.append(
                XBRLFact(
                    fact_id=f"{company.ticker}-{pv['year']}-{pv['period']}-EarningsPerShareDiluted",
                    ticker=company.ticker,
                    cik=company.cik,
                    entity_name=company.name,
                    concept="EarningsPerShareDiluted",
                    taxonomy="us-gaap",
                    label="Diluted EPS",
                    value=pv["period_eps"],
                    unit="USD/shares",
                    fiscal_year=int(pv["year"]),
                    fiscal_period=pv["period"],
                    form=pv["form"],
                    filed_date=pv["filed_date"],
                    period_end=pv["end_date"],
                    is_restated=False,
                    data_source=DataSource.DEMO,
                )
            )
        return facts

    def generate_chunks(self, company: CompanyInfo) -> list[DocumentChunk]:
        """Generate deterministic mock document chunks for a company across all periods."""
        chunks: list[DocumentChunk] = []
        base_info = self._base_info(company)
        for pv in projected_period_values(
            base_info["base_rev"], base_info["base_ni"], base_info["growth"]
        ):
            acc_num = f"{int(company.cik):010d}-{pv['year'][2:]}-{pv['idx'] + 1:06d}"
            source_url = f"demo://{company.ticker}/{pv['year']}/{pv['period']}"
            filing_type = (
                FilingType.FORM_10K if pv["form"] == "10-K" else FilingType.FORM_10Q
            )

            # Page 1: Item 7 MD&A
            chunk_1 = DocumentChunk(
                chunk_id=f"{company.ticker}-{pv['year']}-{pv['period']}-chunk-1",
                ticker=company.ticker,
                cik=company.cik,
                filing_type=filing_type,
                fiscal_year=int(pv["year"]),
                fiscal_period=pv["period"],
                filed_date=pv["end_date"],
                accession_number=acc_num,
                item_section=(
                    "Item 7. Management's Discussion and Analysis of "
                    "Financial Condition and Results of Operations"
                ),
                page_number=12,
                content=(
                    f"{company.name} ({company.ticker}) reported results for fiscal period "
                    f"{pv['period']} {pv['year']} ending on {pv['end_date']}. "
                    f"Total revenues reached ${pv['period_rev']:,.2f} million, representing "
                    f"year-over-year growth driven by strong market demand in {company.industry}. "
                    f"Net income for the quarter was ${pv['period_ni']:,.2f} million. "
                    f"Research and development investments increased as the company expanded its "
                    f"next-generation artificial intelligence and software architecture."
                ),
                is_table=False,
                source_url=source_url,
                data_source=DataSource.DEMO,
            )
            chunks.append(chunk_1)

            # Page 2: Financial Results Table (Item 8)
            chunk_table = DocumentChunk(
                chunk_id=f"{company.ticker}-{pv['year']}-{pv['period']}-chunk-table",
                ticker=company.ticker,
                cik=company.cik,
                filing_type=filing_type,
                fiscal_year=int(pv["year"]),
                fiscal_period=pv["period"],
                filed_date=pv["end_date"],
                accession_number=acc_num,
                item_section="Item 8. Financial Statements and Supplementary Data",
                page_number=28,
                content=(
                    f"CONSOLIDATED STATEMENTS OF OPERATIONS ({company.name}) - "
                    f"{pv['period']} {pv['year']}\n"
                    f"Revenues: ${pv['period_rev']:,.2f} million\n"
                    f"Cost of Goods Sold: ${(pv['period_rev'] * 0.45):,.2f} million\n"
                    f"Gross Profit: ${(pv['period_rev'] * 0.55):,.2f} million\n"
                    f"Operating Expenses: ${(pv['period_rev'] * 0.25):,.2f} million\n"
                    f"Net Income: ${pv['period_ni']:,.2f} million"
                ),
                is_table=True,
                table_data={
                    "Revenues": pv["period_rev"] * 1_000_000.0,
                    "NetIncome": pv["period_ni"] * 1_000_000.0,
                    "GrossMargin": 0.55,
                },
                source_url=source_url,
                data_source=DataSource.DEMO,
            )
            chunks.append(chunk_table)

            # Page 3: Item 1A Risk Factors
            chunk_risk = DocumentChunk(
                chunk_id=f"{company.ticker}-{pv['year']}-{pv['period']}-chunk-risk",
                ticker=company.ticker,
                cik=company.cik,
                filing_type=filing_type,
                fiscal_year=int(pv["year"]),
                fiscal_period=pv["period"],
                filed_date=pv["end_date"],
                accession_number=acc_num,
                item_section="Item 1A. Risk Factors",
                page_number=5,
                content=(
                    f"Risk Factors for {company.name}: The market for {company.industry} is rapidly evolving. "
                    f"Risks include macroeconomic instability, supply chain bottlenecks, "
                    f"semiconductor hardware availability, regulatory compliance regarding "
                    f"data privacy and AI governance, and potential cybersecurity threats."
                ),
                is_table=False,
                source_url=source_url,
                data_source=DataSource.DEMO,
            )
            chunks.append(chunk_risk)

        return chunks


# Backward-compatible module-level functions
def generate_mock_xbrl_facts(company: CompanyInfo) -> list[XBRLFact]:
    return DemoDataGenerator().generate_facts(company)


def generate_mock_document_chunks(company: CompanyInfo) -> list[DocumentChunk]:
    return DemoDataGenerator().generate_chunks(company)


class SecCompanyFactsClient:
    """Client for fetching structured XBRL facts from SEC EDGAR Company Facts.

    Makes real HTTP requests to https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json.
    Requires a descriptive User-Agent with a monitored contact email.
    Never falls back to generated data — failures raise RuntimeError.
    """

    def __init__(self, user_agent: str | None = None):
        self.user_agent = user_agent or os.getenv("SEC_USER_AGENT")
        if not self.user_agent:
            raise ValueError(
                "SEC mode requires SEC_USER_AGENT with an application name and "
                "a monitored contact email, for example 'MyResearchApp/1.0 (name@example.com)'."
            )
        self.headers = {"User-Agent": self.user_agent}
        self._http = httpx.Client(headers=self.headers, timeout=20.0)

    def fetch_company_facts(self, company: CompanyInfo) -> list[XBRLFact]:
        """Fetch structured XBRL facts from SEC EDGAR for 10-K/10-Q filings, FY 2023-2024."""
        cik_padded = company.cik.zfill(10)
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
        try:
            response = self._http.get(url)
            response.raise_for_status()
            data = response.json()
            facts: list[XBRLFact] = []
            us_gaap = data.get("facts", {}).get("us-gaap", {})
            for concept_name, concept_data in us_gaap.items():
                for unit_key, fact_list in concept_data.get("units", {}).items():
                    for item in fact_list:
                        if item.get("form") not in {"10-K", "10-Q"} or item.get(
                            "fy"
                        ) not in {2023, 2024}:
                            continue
                        filed = str(item.get("filed", ""))
                        period_end = str(item.get("end", ""))
                        fiscal_year = int(item["fy"])
                        fiscal_period = str(item.get("fp", ""))
                        accession = str(item.get("accn", ""))
                        facts.append(
                            XBRLFact(
                                fact_id=(
                                    f"{company.ticker}-{fiscal_year}-{fiscal_period}-"
                                    f"{period_end}-{accession}-{unit_key}-{concept_name}"
                                ),
                                ticker=company.ticker,
                                cik=company.cik,
                                entity_name=company.name,
                                concept=concept_name,
                                taxonomy="us-gaap",
                                label=concept_data.get("label", concept_name),
                                value=float(item["val"]),
                                unit=unit_key,
                                fiscal_year=fiscal_year,
                                fiscal_period=fiscal_period,
                                form=str(item["form"]),
                                filed_date=filed,
                                period_start=str(item["start"])
                                if item.get("start")
                                else None,
                                period_end=period_end,
                                is_restated=False,
                                data_source=DataSource.SEC_EDGAR,
                            )
                        )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.exception(
                "SEC EDGAR facts request/validation failed for %s", company.ticker
            )
            raise RuntimeError(
                f"SEC EDGAR ingestion failed for {company.ticker}: {exc}"
            ) from exc

        if not facts:
            raise RuntimeError(
                f"SEC EDGAR returned no supported 2023-2024 facts for {company.ticker}."
            )
        return facts

    async def fetch_company_facts_async(self, company: CompanyInfo) -> list[XBRLFact]:
        """Async variant of fetch_company_facts using httpx.AsyncClient."""
        cik_padded = company.cik.zfill(10)
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
        assert self.user_agent is not None
        headers: dict[str, str] = {"User-Agent": self.user_agent}
        try:
            async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.exception(
                "SEC EDGAR async facts request/validation failed for %s",
                company.ticker,
            )
            raise RuntimeError(
                f"SEC EDGAR async ingestion failed for {company.ticker}: {exc}"
            ) from exc

        facts: list[XBRLFact] = []
        us_gaap = data.get("facts", {}).get("us-gaap", {})
        for concept_name, concept_data in us_gaap.items():
            for unit_key, fact_list in concept_data.get("units", {}).items():
                for item in fact_list:
                    if item.get("form") not in {"10-K", "10-Q"} or item.get(
                        "fy"
                    ) not in {2023, 2024}:
                        continue
                    filed = str(item.get("filed", ""))
                    period_end = str(item.get("end", ""))
                    fiscal_year = int(item["fy"])
                    fiscal_period = str(item.get("fp", ""))
                    accession = str(item.get("accn", ""))
                    facts.append(
                        XBRLFact(
                            fact_id=(
                                f"{company.ticker}-{fiscal_year}-{fiscal_period}-"
                                f"{period_end}-{accession}-{unit_key}-{concept_name}"
                            ),
                            ticker=company.ticker,
                            cik=company.cik,
                            entity_name=company.name,
                            concept=concept_name,
                            taxonomy="us-gaap",
                            label=concept_data.get("label", concept_name),
                            value=float(item["val"]),
                            unit=unit_key,
                            fiscal_year=fiscal_year,
                            fiscal_period=fiscal_period,
                            form=str(item["form"]),
                            filed_date=filed,
                            period_start=str(item["start"])
                            if item.get("start")
                            else None,
                            period_end=period_end,
                            is_restated=False,
                            data_source=DataSource.SEC_EDGAR,
                        )
                    )

        if not facts:
            raise RuntimeError(
                f"SEC EDGAR returned no supported 2023-2024 facts for {company.ticker}."
            )
        return facts


class SecFilingTextClient:
    """Client for fetching filing-text chunks from SEC EDGAR.

    Uses the SEC submissions API to discover recent 10-K/10-Q filings,
    fetches the complete filing text from the EDGAR archives, and chunks
    it into DocumentChunk objects for retrieval and citation.

    Requires SEC_USER_AGENT. Never falls back to generated data — failures
    raise RuntimeError.
    """

    # Max characters per chunk to keep embedding/index size manageable.
    MAX_CHUNK_CHARS = 1200
    # Overlap between adjacent chunks to preserve context across boundaries.
    CHUNK_OVERLAP_CHARS = 150

    def __init__(self, user_agent: str | None = None):
        self.user_agent = user_agent or os.getenv("SEC_USER_AGENT")
        if not self.user_agent:
            raise ValueError(
                "SEC filing-text mode requires SEC_USER_AGENT with an application name and "
                "a monitored contact email, for example 'MyResearchApp/1.0 (name@example.com)'."
            )
        self.headers = {"User-Agent": self.user_agent}
        self._http = httpx.Client(headers=self.headers, timeout=30.0)

    def _company_submissions_url(self, cik: str) -> str:
        cik_padded = cik.zfill(10)
        return f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

    def _find_recent_filings(
        self, company: CompanyInfo, limit: int = 4
    ) -> list[dict[str, Any]]:
        """Return recent 10-K/10-Q filings with document URLs from SEC submissions."""
        url = self._company_submissions_url(company.cik)
        try:
            response = self._http.get(url)
            response.raise_for_status()
            data = response.json()
            recent = data.get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            docs = recent.get("primaryDocument", [])

            filings: list[dict[str, Any]] = []
            for i, form in enumerate(forms):
                if form not in {"10-K", "10-Q"}:
                    continue
                if len(filings) >= limit:
                    break
                accession = accessions[i] if i < len(accessions) else ""
                primary_doc = docs[i] if i < len(docs) else ""
                filings.append(
                    {
                        "form": form,
                        "filing_date": dates[i] if i < len(dates) else "",
                        "accession_number": accession,
                        "primary_document": primary_doc,
                        "cik": company.cik.zfill(10),
                    }
                )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.exception("SEC submissions request failed for %s", company.ticker)
            raise RuntimeError(
                f"SEC submissions ingestion failed for {company.ticker}: {exc}"
            ) from exc
        return filings

    def _filing_text_url(
        self, cik_padded: str, accession: str, primary_doc: str
    ) -> str:
        accession_nodash = accession.replace("-", "")
        return (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik_padded)}/"
            f"{accession_nodash}/{primary_doc}"
        )

    def _fetch_filing_text(self, url: str) -> str:
        """Fetch raw filing text from SEC EDGAR archives."""
        try:
            response = self._http.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:
            logger.exception("SEC filing text fetch failed for %s", url)
            raise RuntimeError(
                f"SEC filing text fetch failed for {url}: {exc}"
            ) from exc

    @staticmethod
    def _chunk_text(
        text: str,
        chunk_id_prefix: str,
        ticker: str,
        cik: str,
        filing_type: FilingType,
        fiscal_year: int,
        fiscal_period: str,
        filed_date: str,
        accession_number: str,
        item_section: str,
        page_number: int,
        source_url: str,
        data_source: DataSource,
    ) -> list[DocumentChunk]:
        """Split raw filing text into overlapping DocumentChunk objects."""
        # Strip HTML tags crudely for plain-text chunking
        plain = re.sub(r"<[^>]+>", " ", text)
        plain = re.sub(r"\s+", " ", plain).strip()

        chunks: list[DocumentChunk] = []
        start = 0
        idx = 0
        while start < len(plain):
            end = min(start + SecFilingTextClient.MAX_CHUNK_CHARS, len(plain))
            chunk_text = plain[start:end]
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{chunk_id_prefix}-{idx}",
                    ticker=ticker,
                    cik=cik,
                    filing_type=filing_type,
                    fiscal_year=fiscal_year,
                    fiscal_period=fiscal_period,
                    filed_date=filed_date,
                    accession_number=accession_number,
                    item_section=item_section,
                    page_number=page_number,
                    content=chunk_text,
                    is_table=False,
                    source_url=source_url,
                    data_source=data_source,
                )
            )
            idx += 1
            if end >= len(plain):
                break
            start = max(0, end - SecFilingTextClient.CHUNK_OVERLAP_CHARS)
        return chunks

    def fetch_filing_chunks(
        self,
        company: CompanyInfo,
        limit: int = 4,
    ) -> list[DocumentChunk]:
        """Fetch and chunk recent 10-K/10-Q filing text for a company."""
        filings = self._find_recent_filings(company, limit=limit)
        if not filings:
            raise RuntimeError(
                f"SEC EDGAR returned no recent 10-K/10-Q filings for {company.ticker}."
            )

        all_chunks: list[DocumentChunk] = []
        cik_padded = company.cik.zfill(10)

        for filing in filings:
            accession = filing["accession_number"]
            primary_doc = filing["primary_document"]
            if not accession or not primary_doc:
                continue

            url = self._filing_text_url(cik_padded, accession, primary_doc)
            text = self._fetch_filing_text(url)

            # Determine fiscal year/period from filing date
            filing_date = filing.get("filing_date", "")
            fiscal_year = 2024
            fiscal_period = "FY"
            if filing_date:
                try:
                    year_str, month_str, _ = filing_date.split("-")
                    fiscal_year = int(year_str)
                    month = int(month_str)
                    if month in (1, 2, 3):
                        fiscal_period = "Q1"
                    elif month in (4, 5, 6):
                        fiscal_period = "Q2"
                    elif month in (7, 8, 9):
                        fiscal_period = "Q3"
                    else:
                        fiscal_period = "Q4"
                except (ValueError, IndexError):
                    pass

            form = filing["form"]
            filing_type = FilingType.FORM_10K if form == "10-K" else FilingType.FORM_10Q

            # Try to extract item section from the text
            item_section = self._detect_item_section(text)

            chunks = self._chunk_text(
                text=text,
                chunk_id_prefix=f"{company.ticker}-{accession.replace('-', '')}",
                ticker=company.ticker,
                cik=company.cik,
                filing_type=filing_type,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                filed_date=filing_date,
                accession_number=accession,
                item_section=item_section,
                page_number=1,
                source_url=url,
                data_source=DataSource.SEC_EDGAR,
            )
            all_chunks.extend(chunks)

        if not all_chunks:
            raise RuntimeError(
                f"SEC EDGAR filing text produced no chunks for {company.ticker}."
            )
        return all_chunks

    async def fetch_filing_chunks_async(
        self,
        company: CompanyInfo,
        limit: int = 4,
    ) -> list[DocumentChunk]:
        """Async variant of fetch_filing_chunks using httpx.AsyncClient."""
        filings = self._find_recent_filings(company, limit=limit)
        if not filings:
            raise RuntimeError(
                f"SEC EDGAR returned no recent 10-K/10-Q filings for {company.ticker}."
            )

        all_chunks: list[DocumentChunk] = []
        cik_padded = company.cik.zfill(10)
        assert self.user_agent is not None
        headers: dict[str, str] = {"User-Agent": self.user_agent}

        async with httpx.AsyncClient(headers=headers, timeout=30.0) as http_client:
            for filing in filings:
                accession = filing["accession_number"]
                primary_doc = filing["primary_document"]
                if not accession or not primary_doc:
                    continue

                url = self._filing_text_url(cik_padded, accession, primary_doc)
                try:
                    response = await http_client.get(url)
                    response.raise_for_status()
                    text = response.text
                except httpx.HTTPError as exc:
                    logger.exception("SEC async filing text fetch failed for %s", url)
                    raise RuntimeError(
                        f"SEC async filing text fetch failed for {url}: {exc}"
                    ) from exc

                filing_date = filing.get("filing_date", "")
                fiscal_year = 2024
                fiscal_period = "FY"
                if filing_date:
                    try:
                        year_str, month_str, _ = filing_date.split("-")
                        fiscal_year = int(year_str)
                        month = int(month_str)
                        if month in (1, 2, 3):
                            fiscal_period = "Q1"
                        elif month in (4, 5, 6):
                            fiscal_period = "Q2"
                        elif month in (7, 8, 9):
                            fiscal_period = "Q3"
                        else:
                            fiscal_period = "Q4"
                    except (ValueError, IndexError):
                        pass

                form = filing["form"]
                filing_type = (
                    FilingType.FORM_10K if form == "10-K" else FilingType.FORM_10Q
                )

                item_section = self._detect_item_section(text)

                chunks = self._chunk_text(
                    text=text,
                    chunk_id_prefix=f"{company.ticker}-{accession.replace('-', '')}",
                    ticker=company.ticker,
                    cik=company.cik,
                    filing_type=filing_type,
                    fiscal_year=fiscal_year,
                    fiscal_period=fiscal_period,
                    filed_date=filing_date,
                    accession_number=accession,
                    item_section=item_section,
                    page_number=1,
                    source_url=url,
                    data_source=DataSource.SEC_EDGAR,
                )
                all_chunks.extend(chunks)

        if not all_chunks:
            raise RuntimeError(
                f"SEC EDGAR filing text produced no chunks for {company.ticker}."
            )
        return all_chunks

    @staticmethod
    def _detect_item_section(text: str) -> str:
        """Crudely detect the primary Item section from filing text."""
        text_upper = text.upper()
        for marker in [
            "ITEM 1A.",
            "ITEM 7.",
            "ITEM 8.",
            "ITEM 1.",
            "ITEM 6.",
        ]:
            idx = text_upper.find(marker)
            if idx != -1:
                # Capture text after marker up to next marker or 100 chars
                after = text_upper[idx : idx + 200]
                end_markers = ["ITEM 1A.", "ITEM 7.", "ITEM 8.", "ITEM 1.", "ITEM 6."]
                nearest = len(after)
                for em in end_markers:
                    eidx = after.find(em, 10)
                    if eidx != -1 and eidx < nearest:
                        nearest = eidx
                return after[:nearest].strip().replace("\n", " ")
        return "Item 1. Business"


class SECDataIngestionClient:
    """Facade that routes ingestion to the demo generator or SEC client based on DATA_MODE.

    Backward-compatible: the same interface as the original monolithic class.
    """

    def __init__(self, data_mode: str | None = None, user_agent: str | None = None):
        resolved_mode = data_mode or os.getenv("DATA_MODE", "demo") or "demo"
        self.data_mode = resolved_mode.strip().lower()
        if self.data_mode not in {"demo", "sec"}:
            raise ValueError("DATA_MODE must be either 'demo' or 'sec'.")
        self.user_agent = user_agent or os.getenv("SEC_USER_AGENT")
        if self.data_mode == "sec" and not self.user_agent:
            raise ValueError(
                "SEC mode requires SEC_USER_AGENT with an application name and "
                "a monitored contact email, for example 'MyResearchApp/1.0 (name@example.com)'."
            )
        self._demo = DemoDataGenerator()
        self._sec_facts: SecCompanyFactsClient | None = None
        self._sec_text: SecFilingTextClient | None = None
        if self.data_mode == "sec":
            self._sec_facts = SecCompanyFactsClient(user_agent=self.user_agent)
            self._sec_text = SecFilingTextClient(user_agent=self.user_agent)

    @property
    def data_mode(self) -> str:
        return self._data_mode

    @data_mode.setter
    def data_mode(self, value: str):
        self._data_mode = value

    def fetch_company_facts(self, company: CompanyInfo) -> list[XBRLFact]:
        if self.data_mode == "demo":
            return self._demo.generate_facts(company)
        assert self._sec_facts is not None
        return self._sec_facts.fetch_company_facts(company)

    def fetch_document_chunks(self, company: CompanyInfo) -> list[DocumentChunk]:
        if self.data_mode == "sec":
            assert self._sec_text is not None
            try:
                return self._sec_text.fetch_filing_chunks(company)
            except Exception as exc:  # noqa: BLE001 - graceful degradation to no chunks
                logger.warning(
                    "SEC filing-text ingestion failed for %s; returning no chunks: %s",
                    company.ticker,
                    exc,
                )
                return []
        return self._demo.generate_chunks(company)

    def fetch_filing_chunks(
        self, company: CompanyInfo, limit: int = 4
    ) -> list[DocumentChunk]:
        """Explicitly fetch filing-text chunks (SEC mode only)."""
        if self.data_mode != "sec":
            raise ValueError("fetch_filing_chunks is only available in SEC mode.")
        assert self._sec_text is not None
        return self._sec_text.fetch_filing_chunks(company, limit=limit)

    async def fetch_company_facts_async(self, company: CompanyInfo) -> list[XBRLFact]:
        """Async variant of fetch_company_facts."""
        if self.data_mode == "demo":
            return self._demo.generate_facts(company)
        assert self._sec_facts is not None
        return await self._sec_facts.fetch_company_facts_async(company)

    async def fetch_document_chunks_async(
        self, company: CompanyInfo
    ) -> list[DocumentChunk]:
        """Async variant of fetch_document_chunks."""
        if self.data_mode == "sec":
            assert self._sec_text is not None
            try:
                return await self._sec_text.fetch_filing_chunks_async(company)
            except Exception as exc:  # noqa: BLE001 - graceful degradation to no chunks
                logger.warning(
                    "SEC async filing-text ingestion failed for %s; returning no chunks: %s",
                    company.ticker,
                    exc,
                )
                return []
        return self._demo.generate_chunks(company)
