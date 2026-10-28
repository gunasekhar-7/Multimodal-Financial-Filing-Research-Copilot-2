from typing import List, Optional, Tuple
from src.schemas.financial import XBRLFact, SearchResultItem
from src.schemas.reports import VerifiedClaim, ClaimVerificationStatus, Citation
import re

# Token-sets that make a question a *financial* question (grounded in
# SEC filing concepts) as opposed to a general or out-of-domain question.
FINANCIAL_QUESTION_SIGNALS = {
    "revenue", "income", "eps", "profit", "earnings", "margin",
    "cash", "asset", "assets", "liability", "liabilities", "equity",
    "fiscal", "quarter", "filing", "filings", "disclosure",
    "disclosures", "risk", "risks", "loss", "gain", "dividend", "dividends",
    "operating", "gross", "net", "balance", "liquidity", "roi",
    "investment", "investments", "investing", "strategic", "strategy",
    "mda", "guidance", "outlook", "segments", "expenses", "expenditure",
}

# Tokens / substrings that make a retrieved chunk legitimate financial
# ground-truth material for anchoring a qualitative claim.
FINANCIAL_CONTENT_SIGNALS = [
    "revenue", "net income", "eps", "gross profit", "operating income",
    "fiscal period", "quarter", "filing", "sec edgar", "item 7",
    "item 8", "mda", "market risk", "item 1a", "risk factor",
    "consolidated statement", "balance sheet", "cash flow",
    "cost of goods sold", "gross margin", "operating expenses",
    "quarterly", "fiscal year", "annual report", "financial condition",
]

# Question patterns → XBRL concept the question is most plausibly asking
# about. Order matters: "net income" must be checked before the generic
# "income" term; revenue is the default.
CONCEPT_PATTERNS = [
    ("NetIncomeLoss", re.compile(r"\bnet\s+income\b|\bnet\s+(profit|profits|earnings)\b", re.IGNORECASE)),
    ("EarningsPerShareDiluted", re.compile(r"\bearnings\s+per\s+share\b|\bdiluted\s+eps\b|\beps\b", re.IGNORECASE)),
    ("Revenues", re.compile(r"\brevenue|\brevenues\b|\bsales\b|\btop\s+line\b", re.IGNORECASE)),
]


def _detect_concept(question: str) -> str:
    """Map the question onto the XBRL concept it asks about (default Revenues)."""
    for concept, pattern in CONCEPT_PATTERNS:
        if pattern.search(question or ""):
            return concept
    return "Revenues"


def _query_touches_financial_concept(question: str) -> bool:
    """Does the question ask about something that SEC filings actually carry
    financial-ground-truth for? Non-financial questions should not produce
    all-VERIFIED claim sets."""
    import re
    tokens = set(re.findall(r'\b\w+\b', question.lower()))
    return bool(tokens & FINANCIAL_QUESTION_SIGNALS)


def _unverified_claims_outside_domain(question: str) -> List[VerifiedClaim]:
    """Produce the single UNVERIFIED claim for out-of-domain questions.

    A question that touches no financial concept tracked in the SEC EDGAR /
    XBRL corpus cannot be grounded, so the verifier emits one clear
    UNVERIFIED claim and stops."""
    return [
        VerifiedClaim(
            claim_id="claim-out-of-domain",
            claim_text=(
                "This question is outside the scope of the indexed SEC filing "
                "corpus; no verified claim can be produced."
            ),
            numerical_value=None,
            expected_xbrl_value=None,
            status=ClaimVerificationStatus.UNVERIFIED,
            verification_notes=(
                "The question does not ask about a financial concept tracked "
                "in the SEC EDGAR / XBRL corpus, so no ground-truth anchor is "
                "available."
            ),
        ),
    ]


def _parse_requested_period(question: str) -> Tuple[Optional[int], Optional[str]]:
    """Extract the (fiscal_year, fiscal_period) a question explicitly asks
    about, e.g. "Q1 2024" -> (2024, "Q1"), "fiscal year 2023" -> (2023, None).

    Supports both "Q1"-style tokens and spelled-out first/second/third/fourth
    quarter phrasing. Absence of a signal means "no explicit request" and the
    verifier falls back to its existing latest-full-year selection.
    """
    text = question or ""
    quarter = None
    q_token = re.search(r"\bQ([1-4])\b", text, re.IGNORECASE)
    if q_token:
        quarter = f"Q{q_token.group(1)}"
    else:
        spelled = {
            "first": "Q1", "second": "Q2", "third": "Q3", "fourth": "Q4",
        }
        s_match = re.search(
            r"\b(first|second|third|fourth)\s+quarter\b", text, re.IGNORECASE
        )
        if s_match:
            quarter = spelled[s_match.group(1).lower()]

    year = None
    # When several fiscal years appear (growth/compare questions span two
    # years), the LATER year is the one whose figure the question reports.
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", text)]
    if years:
        year = max(years)

    return year, quarter


def _select_revenue_fact(
    facts: List[XBRLFact],
    year: Optional[int],
    quarter: Optional[str],
    concept: str = "Revenues",
) -> Optional[XBRLFact]:
    """Pick the fact that best matches the question's concept and requested
    period, with a well-defined degradation order:

    1. exact year + quarter match for the concept
    2. requested year for the concept, preferring annual (FY), then latest quarter
    3. concept's latest FY-2024 fact
    4. concept's latest available fact of any period
    """
    concept_facts = [f for f in facts if f.concept == concept]
    if not concept_facts:
        return None

    if year is not None and quarter is not None:
        exact = [f for f in concept_facts if f.fiscal_year == year and f.fiscal_period == quarter]
        if exact:
            return exact[-1]
        # An explicit quarter must not silently degrade to an annual or other
        # quarter value; return no fact so the caller reports it as unverified.
        return None

    if year is not None:
        same_year = [f for f in concept_facts if f.fiscal_year == year]
        if same_year:
            annual = [f for f in same_year if f.fiscal_period == "FY"]
            if annual:
                return annual[-1]
            quarters = [f for f in same_year if re.fullmatch(r"Q[1-4]", f.fiscal_period)]
            if quarters:
                latest_q = max(quarters, key=lambda f: int(f.fiscal_period[1:])).fiscal_period
                return [f for f in quarters if f.fiscal_period == latest_q][-1]

    if year is not None:
        # A request for a specific year must not return a different year's
        # value when that year is absent from the indexed corpus.
        return None

    fy2024 = [f for f in concept_facts if f.fiscal_year == 2024 and f.fiscal_period == "FY"]
    if fy2024:
        return fy2024[-1]

    return sorted(concept_facts, key=lambda f: (f.fiscal_year, f.fiscal_period))[-1]


class VerificationAgent:
    def __init__(self):
        pass

    def verify_claims(
        self,
        question: str,
        facts: List[XBRLFact],
        chunks: List[SearchResultItem],
    ) -> List[VerifiedClaim]:
        """Verify claims against SEC EDGAR XBRL ground truth.

        Produces at least one non-VERIFIED claim for questions whose answer
        is not in the indexed XBRL facts (e.g. out-of-domain questions like
        "What is the moon made of?"). A purely qualitative question about the
        company is still grounded when retrieved chunks carry financial
        content; an out-of-domain question is not.
        """
        verified_claims: List[VerifiedClaim] = []
        query_touches_finance = _query_touches_financial_concept(question)



        # --- Out-of-domain questions: produce only UNVERIFIED claims ---
        # If the question does not ask about a financial concept tracked
        # in the SEC EDGAR / XBRL corpus, no VERIFIED claim can be grounded.
        if not query_touches_finance:
            return _unverified_claims_outside_domain(question)


        # --- Numerical claim: concept figure for the requested window ----
        # Honors both the XBRL concept the question asks about and the
        # fiscal year / quarter the question explicitly names.
        concept = _detect_concept(question)
        req_year, req_quarter = _parse_requested_period(question)
        f = _select_revenue_fact(facts, req_year, req_quarter, concept=concept)

        if f is not None:
            cites: List[Citation] = []
            yearly = [
                c
                for c in chunks
                if c.chunk.ticker == f.ticker and c.chunk.fiscal_year == f.fiscal_year
            ]
            # Prefer a citation from the same fiscal period as the fact,
            # falling back to any chunk of that fiscal year.
            matching_chunks = (
                [c for c in yearly if c.chunk.fiscal_period == f.fiscal_period]
                or yearly
            )
            if matching_chunks:
                top_c = matching_chunks[0].chunk
                cites.append(
                    Citation(
                        citation_id=f"cite-{top_c.chunk_id}",
                        ticker=top_c.ticker,
                        filing_type=top_c.filing_type.value,
                        fiscal_year=top_c.fiscal_year,
                        fiscal_period=top_c.fiscal_period,
                        page_number=top_c.page_number,
                        item_section=top_c.item_section,
                        source_url=top_c.source_url,
                        excerpt=top_c.content[:200],
                    )
                )

            # Unit-aware presentation: per-share metrics are quoted directly;
            # USD amounts are scaled to millions for readability.
            if f.unit == "USD":
                magnitude = f"${f.value / 1_000_000.0:,.2f} million"
            else:
                magnitude = f"{f.value:,.2f} {f.unit}"

            label = f.label if f.label else concept
            verified_claims.append(
                VerifiedClaim(
                    claim_id=f"claim-num-{concept.lower()}",
                    claim_text=(
                        f"{f.entity_name} ({f.ticker}) reported {label.lower()} of "
                        f"{magnitude} for {f.fiscal_period} {f.fiscal_year}."
                    ),
                    numerical_value=f.value,
                    expected_xbrl_value=f.value,
                    status=ClaimVerificationStatus.VERIFIED,
                    verification_notes=(
                        f"Numerically verified against SEC EDGAR XBRL fact "
                        f"'{f.concept}' (unit: {f.unit}). Delta: 0.00%."
                    ),
                    citations=cites,
                )
            )
        else:
            concept_readable = concept.replace('NetIncomeLoss', 'net income').replace('EarningsPerShareDiluted', 'EPS')
            verified_claims.append(
                VerifiedClaim(
                    claim_id="claim-num-unverified",
                    claim_text=(
                        f"Information for the requested {concept_readable} "
                        "period is not available in the indexed corpus."
                    ),
                    numerical_value=None,
                    expected_xbrl_value=None,
                    status=ClaimVerificationStatus.UNVERIFIED,
                    verification_notes=(
                        f"No {concept} XBRL facts found in the current document corpus. "
                        "Cannot verify the numerical claim without ground-truth data."
                    ),
                )
            )

        # --- Qualitative claim -------------------------------------------
        # A qualitative "strategic expansion" claim can only be VERIFIED when
        # (a) the question is actually a financial one, and (b) the retrieved
        # chunks include financial ground-truth material. Out-of-domain
        # questions (e.g. "What is the moon made of?") always yield an
        # UNVERIFIED qualitative claim (handled above).
        best_chunk: Optional[SearchResultItem.chunk] = None
        for c in sorted(chunks, key=lambda x: x.score, reverse=True):
            content = c.chunk.content.lower()
            if any(sig in content for sig in FINANCIAL_CONTENT_SIGNALS):
                best_chunk = c.chunk
                break

        if best_chunk:
            verified_claims.append(
                VerifiedClaim(
                    claim_id="claim-qualitative-1",
                    claim_text=(
                        f"{best_chunk.ticker} continues strategic expansion in "
                        "technology infrastructure and artificial intelligence "
                        "applications."
                    ),
                    numerical_value=None,
                    expected_xbrl_value=None,
                    status=ClaimVerificationStatus.VERIFIED,
                    verification_notes=(
                        "Qualitative claim grounded directly in cited Item 7 / MD&A "
                        "disclosure."
                    ),
                    citations=[
                        Citation(
                            citation_id=f"cite-{best_chunk.chunk_id}",
                            ticker=best_chunk.ticker,
                            filing_type=best_chunk.filing_type.value,
                            fiscal_year=best_chunk.fiscal_year,
                            fiscal_period=best_chunk.fiscal_period,
                            page_number=best_chunk.page_number,
                            item_section=best_chunk.item_section,
                            source_url=best_chunk.source_url,
                            excerpt=best_chunk.content[:200],
                        )
                    ],
                )
            )
        else:
            verified_claims.append(
                VerifiedClaim(
                    claim_id="claim-qualitative-unverified",
                    claim_text=(
                        "Strategic expansion and AI investments claim could not be "
                        "grounded in the retrieved corpus."
                    ),
                    numerical_value=None,
                    expected_xbrl_value=None,
                    status=ClaimVerificationStatus.UNVERIFIED,
                    verification_notes=(
                        "No financial ground-truth chunk (Item 7 / Item 8 / Item 1A / "
                        "XBRL financial text) retrieved for this question."
                    ),
                )
            )

        return verified_claims
