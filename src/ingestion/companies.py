from typing import List
from src.schemas.financial import CompanyInfo, SectorType

TARGET_COMPANIES: List[CompanyInfo] = [
    CompanyInfo(ticker="AAPL", cik="0000320193", name="Apple Inc.", sector=SectorType.TECHNOLOGY, sic="3571", industry="Consumer Electronics"),
    CompanyInfo(ticker="MSFT", cik="0000789019", name="Microsoft Corporation", sector=SectorType.TECHNOLOGY, sic="7372", industry="Software - Infrastructure"),
    CompanyInfo(ticker="GOOGL", cik="0001652044", name="Alphabet Inc.", sector=SectorType.TECHNOLOGY, sic="7370", industry="Internet Content & Information"),
    CompanyInfo(ticker="AMZN", cik="0001018724", name="Amazon.com Inc.", sector=SectorType.TECHNOLOGY, sic="5961", industry="Internet Retail / Cloud"),
    CompanyInfo(ticker="NVDA", cik="0001045810", name="NVIDIA Corporation", sector=SectorType.TECHNOLOGY, sic="3674", industry="Semiconductors"),
    CompanyInfo(ticker="META", cik="0001326801", name="Meta Platforms Inc.", sector=SectorType.TECHNOLOGY, sic="7370", industry="Internet Content & Information"),
    CompanyInfo(ticker="TSLA", cik="0001318605", name="Tesla Inc.", sector=SectorType.TECHNOLOGY, sic="3711", industry="Automotive / Clean Energy"),
    CompanyInfo(ticker="AVGO", cik="0001730168", name="Broadcom Inc.", sector=SectorType.TECHNOLOGY, sic="3674", industry="Semiconductors"),
    CompanyInfo(ticker="ORCL", cik="000013414", name="Oracle Corporation", sector=SectorType.TECHNOLOGY, sic="7372", industry="Software - Infrastructure"),
    CompanyInfo(ticker="CSCO", cik="0000858877", name="Cisco Systems Inc.", sector=SectorType.TECHNOLOGY, sic="3576", industry="Communication Equipment"),
    CompanyInfo(ticker="ADBE", cik="0000796343", name="Adobe Inc.", sector=SectorType.TECHNOLOGY, sic="7372", industry="Software - Infrastructure"),
    CompanyInfo(ticker="CRM", cik="0001108524", name="Salesforce Inc.", sector=SectorType.TECHNOLOGY, sic="7372", industry="Software - Application"),
    CompanyInfo(ticker="AMD", cik="0000002488", name="Advanced Micro Devices Inc.", sector=SectorType.TECHNOLOGY, sic="3674", industry="Semiconductors"),
    CompanyInfo(ticker="QCOM", cik="0000804328", name="QUALCOMM Inc.", sector=SectorType.TECHNOLOGY, sic="3663", industry="Semiconductors"),
    CompanyInfo(ticker="TXN", cik="0000097476", name="Texas Instruments Inc.", sector=SectorType.TECHNOLOGY, sic="3674", industry="Semiconductors"),
    CompanyInfo(ticker="INTC", cik="0000050863", name="Intel Corporation", sector=SectorType.TECHNOLOGY, sic="3674", industry="Semiconductors"),
    CompanyInfo(ticker="IBM", cik="0000051143", name="International Business Machines Corp.", sector=SectorType.TECHNOLOGY, sic="7370", industry="Information Technology Services"),
    CompanyInfo(ticker="AMAT", cik="0000006951", name="Applied Materials Inc.", sector=SectorType.TECHNOLOGY, sic="3559", industry="Semiconductor Equipment"),
    CompanyInfo(ticker="NOW", cik="0001373787", name="ServiceNow Inc.", sector=SectorType.TECHNOLOGY, sic="7372", industry="Software - Application"),
    CompanyInfo(ticker="INTU", cik="0000896878", name="Intuit Inc.", sector=SectorType.TECHNOLOGY, sic="7372", industry="Software - Application"),
    CompanyInfo(ticker="MU", cik="0000723125", name="Micron Technology Inc.", sector=SectorType.TECHNOLOGY, sic="3674", industry="Semiconductors"),
    CompanyInfo(ticker="PANW", cik="0001327567", name="Palo Alto Networks Inc.", sector=SectorType.TECHNOLOGY, sic="7372", industry="Software - Cybersecurity"),
    CompanyInfo(ticker="LRCX", cik="0000707549", name="Lam Research Corporation", sector=SectorType.TECHNOLOGY, sic="3559", industry="Semiconductor Equipment"),
    CompanyInfo(ticker="ADI", cik="0000006281", name="Analog Devices Inc.", sector=SectorType.TECHNOLOGY, sic="3674", industry="Semiconductors"),
    CompanyInfo(ticker="CRWD", cik="0001535527", name="CrowdStrike Holdings Inc.", sector=SectorType.TECHNOLOGY, sic="7372", industry="Software - Cybersecurity"),
]

def get_company_by_ticker(ticker: str) -> CompanyInfo:
    ticker_upper = ticker.upper()
    for comp in TARGET_COMPANIES:
        if comp.ticker == ticker_upper:
            return comp
    return CompanyInfo(
        ticker=ticker_upper,
        cik="0000000000",
        name=f"{ticker_upper} Corporation",
        sector=SectorType.TECHNOLOGY,
        sic="7372",
        industry="Technology"
    )
