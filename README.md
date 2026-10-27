# Multimodal Financial-Filing Research Copilot

A production-style, multi-agent AI research platform that analyzes public-company SEC filings (10-K, 10-Q, 8-K), structured XBRL financial data, and market disclosures to answer complex financial research questions with verifiable, page-level citations.

---

## Key Features

- **10 Public Companies & 8 Quarters Coverage (demonstration corpus)**: Ingests and normalizes financial filings and XBRL facts for 10 technology sector public companies across 8 historical quarters (2023-Q1 through 2024-FY). The corpus is a seeded demonstration dataset — the architecture supports replacing it with a real SEC EDGAR ingestion pipeline.
- **Hybrid Retrieval Engine**: Combines SQLite FTS5 BM25 full-text search with dense vector embeddings using Reciprocal Rank Fusion (RRF) and Cross-Encoder heuristic reranking.
- **Custom Multi-Agent Orchestration**: Modular, typed Pydantic agent framework consisting of:
  - **Planner Agent**: Parses research questions into structured execution steps.
  - **Retrieval Agent**: Fetches page-level document chunks and structured XBRL facts.
  - **Extraction Agent**: Computes quarterly financial metrics, YoY, and QoQ percentage changes.
  - **Financial Analysis Agent**: Classifies material risk factor disclosures (Item 1A) and MD&A trends (Item 7).
  - **Verification Agent**: Deterministically cross-checks claims against XBRL ground truth with delta percentage calculations.
  - **Report Writer Agent**: Generates structured markdown research reports with clickable page citations and uncertainty disclosures.
- **Evaluation Benchmark Suite**: Includes a golden dataset (generated from the seeded corpus) measuring Recall@k, MRR, numerical accuracy, citation resolution rate, claim faithfulness, and p50/p95 latency. Numbers below reflect the seeded corpus, not a live SEC EDGAR ingestion.
- **Production-Style Web Interface & REST API**: Interactive Tailwind CSS financial analyst dashboard with company selectors, sample questions, metric comparison tables, and verification badges. Note: verification badges reflect the crawler's own claim-verification logic against the indexed corpus, not an independent audit of SEC filings.
- **CI/CD Quality Gates**: Automated GitHub Actions workflow testing unit coverage (96%) and evaluation benchmark thresholds.

---

## Project Architecture

```
                                  +------------------------------------+
                                  |    Analyst Research Question       |
                                  +------------------------------------+
                                                     |
                                                     v
                                  +------------------------------------+
                                  |            Planner Agent           |
                                  +------------------------------------+
                                                     |
                                                     v
                         +-------------------------------------------------------+
                         |                    Retrieval Agent                    |
                         +-------------------------------------------------------+
                                   /                                   \
                                  v                                     v
                  +-------------------------------+     +-------------------------------+
                  |  SQLite FTS5 + Dense Vector   |     |    SEC EDGAR XBRL Facts DB    |
                  |     Hybrid Search Engine      |     |     (Ground Truth Figures)    |
                  +-------------------------------+     +-------------------------------+
                                   \                                   /
                                    v                                 v
                         +-------------------------------------------------------+
                         |              Financial Extraction Agent               |
                         +-------------------------------------------------------+
                                                     |
                                                     v
                         +-------------------------------------------------------+
                         |             Deterministic Verifier Agent              |
                         +-------------------------------------------------------+
                                                     |
                                                     v
                         +-------------------------------------------------------+
                         |              Report Writer & Citation Engine          |
                         +-------------------------------------------------------+
                                                     |
                                                     v
                                  +------------------------------------+
                                  |      Interactive Analyst Report    |
                                  +------------------------------------+
```

---

## Quick Start & Setup

### Prerequisites
- Python 3.12+
- Docker & Docker Compose (optional)

### Local Installation

1. **Clone the repository and install dependencies**:
   ```bash
   git clone <repo-url>
   cd financial-filing-copilot
   pip install -r requirements.txt
   ```

2. **Seed the database**:
   ```bash
   PYTHONPATH=. python3 scripts/seed_database.py
   ```

3. **Run tests & benchmark evaluation**:
   ```bash
   PYTHONPATH=. pytest --cov=src tests/
   PYTHONPATH=. python3 scripts/run_eval.py
   ```

4. **Launch the web application & API**:
   ```bash
   uvicorn src.api.app:app --host 0.0.0.0 --port 8000
   ```
   Open your browser at `http://localhost:8000`.

---

## Evaluation Benchmark Results

Evaluated on the golden dataset derived from the seeded corpus:

| Metric | Measured Score | Target Threshold |
| :--- | :--- | :--- |
| **Retrieval Recall@5** | **64.0%** | >= 50.0% |
| **Retrieval MRR** | **43.67%** | >= 40.0% |
| **Numerical Fact Accuracy** | **52.94%** | >= 50.0% |
| **Citation Resolution Rate** | **100.0%** | >= 90.0% |
| **Claim Faithfulness Rate** | **92.0%** | >= 85.0% |
| **p50 Latency** | **0.009s** | < 1.00s |
| **p95 Latency** | **0.010s** | < 2.00s |

---

## REST API Documentation

### `GET /health`
Returns system health, database status, and row counts.

### `GET /api/companies`
Lists supported tech sector public companies.

### `GET /api/facts`
Queries XBRL facts by ticker, concept, year, and fiscal period.

### `POST /api/search`
Performs hybrid search over SEC filings.

### `POST /api/query`
Executes multi-agent research workflow and generates a structured report.

---

## Disclaimer & Limitations

- **Informational Purpose Only**: Generated analysis is provided for educational and research demonstration purposes and does not constitute investment advice.
- **Reporting vs. Forecasts**: Distinguishes reported SEC EDGAR figures from forward-looking model estimates.
"# Multimodal-Financial-Filing-Research-Copilot-2" 
