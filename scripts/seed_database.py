import sys
import os
import logging

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.ingestion.companies import TARGET_COMPANIES
from src.ingestion.sec_client import SECDataIngestionClient
from src.storage.database import DatabaseStorage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def seed():
    logger.info("Initializing database...")
    db = DatabaseStorage(db_path="financial_copilot.db")
    client = SECDataIngestionClient()

    logger.info(f"Seeding data for {len(TARGET_COMPANIES)} tech companies across 8 quarters...")
    total_facts = 0
    total_chunks = 0

    for company in TARGET_COMPANIES:
        logger.info(f"Processing company: {company.name} ({company.ticker})...")

        facts = client.fetch_company_facts(company)
        db.insert_xbrl_facts(facts)
        total_facts += len(facts)

        chunks = client.fetch_document_chunks(company)
        db.insert_document_chunks(chunks)
        total_chunks += len(chunks)

    logger.info("Seeding complete!")
    logger.info(f"Total XBRL Facts in DB: {db.get_fact_count()} (Inserted: {total_facts})")
    logger.info(f"Total Document Chunks in DB: {db.get_chunk_count()} (Inserted: {total_chunks})")

if __name__ == "__main__":
    seed()
