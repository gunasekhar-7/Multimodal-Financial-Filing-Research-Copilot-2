# Technical Architecture & System Design

## Overview
The Multimodal Financial-Filing Research Copilot is designed to solve common limitations in traditional financial PDF RAG tools—such as hallucinated financial figures, lack of tabular alignment, and opaque citations—by introducing a deterministic verification layer backed by structured SEC EDGAR XBRL facts.

## System Components

### 1. Ingestion & Storage Pipeline
- **SEC EDGAR Client**: Ingests company facts and filings for 25 technology sector companies over 8 quarters (2023-Q1 through 2024-FY). Includes offline deterministic fallback for test reproducibility and high availability.
- **Page-Level Document Chunker**: Preserves SEC Item sections (Item 1A, Item 7, Item 8), page numbers, accession numbers, and table structures.
- **Storage Layer**: SQLite database using standard FTS5 full-text indexing alongside TF-IDF dense vector embeddings.

### 2. Hybrid Retrieval Engine
- **BM25 Search**: Full-text exact keyword match over SEC Item text and table chunks.
- **Dense Vector Search**: Semantic cosine similarity over n-gram TF-IDF document vectors.
- **Reciprocal Rank Fusion (RRF)**: Combines sparse BM25 and dense rank vectors:
  $$RRF(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$
- **Cross-Encoder Reranker**: Boosts tabular structures and financial metric phrases ("revenue", "net income", "operating margin").

### 3. Multi-Agent Orchestration Engine
- **Contracts**: Typed Pydantic data schemas (`AgentState`, `ResearchPlan`, `VerifiedClaim`, `FinancialMetricComparison`, `ResearchReport`).
- **Agents**:
  - `PlannerAgent`: Constructs sub-tasks and targeted search queries.
  - `RetrievalAgent`: Executes search queries and fetches XBRL ground truth facts.
  - `FinancialExtractionAgent`: Aggregates concepts into YoY and QoQ comparisons.
  - `FinancialAnalysisAgent`: Classifies risk disclosure trends.
  - `VerificationAgent`: Verifies claims against XBRL facts and flags discrepancies.
  - `ReportWriterAgent`: Formats executive summaries, citation lists, and uncertainty disclosures.

### 4. Observability & Quality Assurance
- **Operational Metrics**: Endpoint health, latency percentiles (p50/p95), database record counts.
- **Continuous Evaluation**: 150-question golden dataset executed in GitHub Actions CI/CD to prevent quality regression.
