import logging
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.ingestion.companies import TARGET_COMPANIES
from src.ingestion.sec_client import SECDataIngestionClient
from src.storage.database import DatabaseStorage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def seed():
    logger.info("Initializing database...")
    db = DatabaseStorage(db_path=os.getenv("DATABASE_PATH", "financial_copilot.db"))
    client = SECDataIngestionClient()

    logger.info(
        "Seeding %s data for %d technology companies across the supported periods...",
        client.data_mode,
        len(TARGET_COMPANIES),
    )
    all_facts = []
    all_chunks = []
    for company in TARGET_COMPANIES:
        logger.info("Processing company: %s (%s)...", company.name, company.ticker)
        all_facts.extend(client.fetch_company_facts(company))
        all_chunks.extend(client.fetch_document_chunks(company))

    # Replace the corpus in one transaction. A failure during SEC retrieval
    # occurs before the existing dataset is touched.
    db.replace_seed_data(all_facts, all_chunks)
    logger.info("Seeding complete! data_mode=%s", client.data_mode)
    logger.info("Total XBRL Facts in DB: %d", db.get_fact_count())
    logger.info("Total Document Chunks in DB: %d", db.get_chunk_count())


if __name__ == "__main__":
    seed()
