import logging
import re

from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
from sklearn.metrics.pairwise import cosine_similarity  # type: ignore

from src.schemas.financial import DataSource, SearchResultItem, XBRLFact
from src.schemas.reports import Citation, ClaimVerificationStatus, VerifiedClaim

logger = logging.getLogger(__name__)

# Cosine similarity threshold above which a qualitative claim is considered
# semantically entailed by its source passage.
QUALITATIVE_SIMILARITY_THRESHOLD = 0.45

# Max qualitative claims to evaluate per query.
MAX_QUALITATIVE_CLAIMS = 3


def _semantic_similarity(text_a: str, text_b: str) -> float:
    """TF-IDF cosine similarity between two texts (0.0 to 1.0)."""
    if not text_a or not text_b:
        return 0.0
    try:
        vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        tfidf = vectorizer.fit_transform([text_a, text_b])
        sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
        return float(sim)
    except (ValueError, TypeError, KeyError):
        return 0.0


# Token-sets that make a question a *financial* question (grounded in
# SEC filing concepts) as opposed to a general or out-of-domain question.
FINANCIAL_QUESTION_SIGNALS = {
    "revenue",
    "income",
    "eps",
    "profit",
    "earnings",
    "margin",
    "cash",
    "asset",
    "assets",
    "liability",
    "liabilities",
    "equity",
    "fiscal",
    "quarter",
    "filing",
    "filings",
    "disclosure",
    "disclosures",
    "risk",
    "risks",
    "loss",
    "gain",
    "dividend",
    "dividends",
    "operating",
    "gross",
    "net",
    "balance",
    "liquidity",
    "roi",
    "investment",
    "investments",
    "investing",
    "strategic",
    "strategy",
    "mda",
    "guidance",
    "outlook",
    "segments",
    "expenses",
    "expenditure",
}

# Tokens / substrings that make a retrieved chunk legitimate financial
# ground-truth material for anchoring a qualitative claim.
FINANCIAL_CONTENT_SIGNALS = [
    "revenue",
    "net income",
    "eps",
    "gross profit",
    "operating income",
    "fiscal period",
    "quarter",
    "filing",
    "sec edgar",
    "item 7",
    "item 8",
    "mda",
    "market risk",
    "item 1a",
    "risk factor",
    "consolidated statement",
    "balance sheet",
    "cash flow",
    "cost of goods sold",
    "gross margin",
    "operating expenses",
    "quarterly",
    "fiscal year",
    "annual report",
    "financial condition",
]

# Question patterns → XBRL concept the question is most plausibly asking
# about. Order matters: "net income" must be checked before the generic
# "income" term; revenue is the default.
CONCEPT_PATTERNS = [
    (
        "NetIncomeLoss",
        re.compile(
            r"\bnet\s+income\b|\bnet\s+(profit|profits|earnings)\b", re.IGNORECASE
        ),
    ),
    (
        "EarningsPerShareDiluted",
        re.compile(
            r"\bearnings\s+per\s+share\b|\bdiluted\s+eps\b|\beps\b", re.IGNORECASE
        ),
    ),
    (
        "OperatingIncomeLoss",
        re.compile(r"\boperating\s+(income|profit|earnings)\b", re.IGNORECASE),
    ),
    (
        "GrossProfit",
        re.compile(r"\bgross\s+profit\b|\bgross\s+margin\b", re.IGNORECASE),
    ),
    (
        "OperatingExpenses",
        re.compile(r"\boperating\s+expenses\b|\bopex\b", re.IGNORECASE),
    ),
    (
        "Revenues",
        re.compile(r"\brevenue|\brevenues\b|\bsales\b|\btop\s+line\b", re.IGNORECASE),
    ),
]


def _format_concept_readable(concept: str) -> str:
    """Convert an XBRL concept into plain English."""
    return (
        concept.replace("NetIncomeLoss", "net income")
        .replace("EarningsPerShareDiluted", "EPS")
        .replace("OperatingIncomeLoss", "operating income")
        .replace("GrossProfit", "gross profit")
        .replace("OperatingExpenses", "operating expenses")
    )


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
    tokens = set(re.findall(r"\b\w+\b", question.lower()))
    return bool(tokens & FINANCIAL_QUESTION_SIGNALS)


def _unverified_claims_outside_domain(question: str) -> list[VerifiedClaim]:
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


def _parse_requested_period(question: str) -> tuple[int | None, str | None]:
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
            "first": "Q1",
            "second": "Q2",
            "third": "Q3",
            "fourth": "Q4",
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


def _select_exact_fact(
    facts: list[XBRLFact],
    concept: str,
    year: int | None,
    quarter: str | None,
) -> XBRLFact | None:
    """Pick the fact that exactly matches concept + year + quarter.

    Returns the single matching fact, or None when no exact match exists.
    An explicitly requested period must never silently degrade to a
    different period — that would produce a false verification.
    """
    concept_facts = [f for f in facts if f.concept == concept]
    if not concept_facts:
        return None

    if year is not None and quarter is not None:
        exact = [
            f
            for f in concept_facts
            if f.fiscal_year == year and f.fiscal_period == quarter
        ]
        if len(exact) == 1:
            return exact[0]
        return None  # no exact match, or ambiguous (handled by caller)

    if year is not None and quarter is None:
        same_year = [f for f in concept_facts if f.fiscal_year == year]
        if not same_year:
            return None
        annual = [f for f in same_year if f.fiscal_period == "FY"]
        if annual:
            return annual[0] if len(annual) == 1 else None
        quarters = [f for f in same_year if re.fullmatch(r"Q[1-4]", f.fiscal_period)]
        if quarters:
            latest_q = max(quarters, key=lambda f: int(f.fiscal_period[1:]))
            matching_q = [
                f for f in quarters if f.fiscal_period == latest_q.fiscal_period
            ]
            return matching_q[0] if len(matching_q) == 1 else None
        return None

    # No year specified: prefer latest FY 2024, then latest available.
    fy2024 = [
        f for f in concept_facts if f.fiscal_year == 2024 and f.fiscal_period == "FY"
    ]
    if fy2024:
        return fy2024[0] if len(fy2024) == 1 else None
    return max(concept_facts, key=lambda f: (f.fiscal_year, f.fiscal_period))


def _has_ambiguous_facts(
    facts: list[XBRLFact],
    concept: str,
    year: int | None,
    quarter: str | None,
) -> bool:
    """Return True when multiple facts match the same concept/ticker/period
    with different values — the claim cannot be uniquely verified."""
    concept_facts = [f for f in facts if f.concept == concept]
    if year is not None and quarter is not None:
        exact = [
            f
            for f in concept_facts
            if f.fiscal_year == year and f.fiscal_period == quarter
        ]
        if len(exact) > 1:
            values = {f.value for f in exact}
            return len(values) > 1
    return False


def _build_citation(
    fact: XBRLFact,
    chunks: list[SearchResultItem],
) -> list[Citation]:
    """Build a citation from a retrieved chunk matching the fact's ticker,
    fiscal year, fiscal period, and data source. Returns an empty list when
    no matching source passage exists — SEC facts without filing-text
    context cannot be promoted to VERIFIED claims."""
    matching_chunks = [
        c
        for c in chunks
        if c.chunk.ticker == fact.ticker
        and c.chunk.fiscal_year == fact.fiscal_year
        and c.chunk.fiscal_period == fact.fiscal_period
        and c.chunk.data_source == fact.data_source
    ]
    if not matching_chunks:
        return []
    top_c = matching_chunks[0].chunk
    return [
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
            data_source=top_c.data_source,
        )
    ]


def _magnitude(fact: XBRLFact) -> str:
    """Unit-aware presentation: per-share metrics are quoted directly;
    USD amounts are scaled to millions for readability."""
    if fact.unit == "USD":
        return f"${fact.value / 1_000_000.0:,.2f} million"
    return f"{fact.value:,.2f} {fact.unit}"


class VerificationAgent:
    def __init__(self):
        pass

    def verify_claims(
        self,
        question: str,
        facts: list[XBRLFact],
        chunks: list[SearchResultItem],
        target_tickers: list[str] | None = None,
        tolerance_pct: float = 0.01,
    ) -> list[VerifiedClaim]:
        """Verify claims against SEC EDGAR XBRL ground truth.

        Produces at least one non-VERIFIED claim for questions whose answer
        is not in the indexed XBRL facts (e.g. out-of-domain questions like
        "What is the moon made of?"). A purely qualitative question about the
        company is still grounded when retrieved chunks carry financial
        content; an out-of-domain question is not.

        Verification rules:
        - Demo data: exact fixture match → UNVERIFIED (synthetic, not SEC-reported)
        - SEC data + matching citation → VERIFIED
        - SEC data without citation → UNVERIFIED (no filing-text context)
        - No exact fact match → UNVERIFIED (never borrow another period)
        - Multiple conflicting facts → AMBIGUOUS
        """
        verified_claims: list[VerifiedClaim] = []
        query_touches_finance = _query_touches_financial_concept(question)

        # --- Out-of-domain questions: produce only UNVERIFIED claims ---
        if not query_touches_finance:
            return _unverified_claims_outside_domain(question)

        # --- Numerical claim: exact concept + period match against XBRL ----
        selected_tickers = set(target_tickers or ()) | {
            chunk.chunk.ticker for chunk in chunks
        }
        matching_facts = [
            fact
            for fact in facts
            if not selected_tickers or fact.ticker in selected_tickers
        ]
        concept = _detect_concept(question)
        req_year, req_quarter = _parse_requested_period(question)

        if _has_ambiguous_facts(matching_facts, concept, req_year, req_quarter):
            concept_readable = _format_concept_readable(concept)
            verified_claims.append(
                VerifiedClaim(
                    claim_id=f"claim-num-{concept.lower()}",
                    claim_text=(
                        f"Multiple conflicting {concept_readable} values exist for "
                        f"{req_quarter or ''} {req_year or ''}; cannot uniquely verify."
                    ).strip(),
                    numerical_value=None,
                    expected_xbrl_value=None,
                    status=ClaimVerificationStatus.AMBIGUOUS,
                    verification_notes=(
                        f"More than one {concept} XBRL fact matches the requested "
                        "ticker and period with differing values. Claim is ambiguous."
                    ),
                )
            )
        else:
            f = _select_exact_fact(matching_facts, concept, req_year, req_quarter)
            if f is not None:
                cites = _build_citation(f, chunks)

                # Determine verification status by data source and citation presence.
                if f.data_source.value == "sec_edgar":
                    if cites:
                        claim_status = ClaimVerificationStatus.VERIFIED
                        verification_note = (
                            "Matched SEC EDGAR structured XBRL fact; cited "
                            "filing-text context is not available in SEC mode."
                        )
                    else:
                        claim_status = ClaimVerificationStatus.UNVERIFIED
                        verification_note = (
                            "The structured value was found, but no matching "
                            "source passage was retrieved. It is not promoted "
                            "as a cited finding."
                        )
                else:
                    # Demo data is never SEC-verified, even when numerically exact.
                    claim_status = ClaimVerificationStatus.UNVERIFIED
                    verification_note = "This generated demo value is synthetic and is not SEC-reported."

                magnitude = _magnitude(f)
                label = f.label if f.label else concept
                period_text = f"{f.fiscal_period} {f.fiscal_year}"
                verified_claims.append(
                    VerifiedClaim(
                        claim_id=f"claim-num-{concept.lower()}",
                        claim_text=(
                            f"{f.entity_name} ({f.ticker}) reported {label.lower()} of "
                            f"{magnitude} for {period_text}."
                        ),
                        numerical_value=f.value,
                        expected_xbrl_value=f.value,
                        status=claim_status,
                        verification_notes=verification_note,
                        citations=cites,
                    )
                )
            else:
                concept_readable = _format_concept_readable(concept)
                period_text = f"{req_quarter or ''} {req_year or ''}".strip()
                verified_claims.append(
                    VerifiedClaim(
                        claim_id="claim-num-unverified",
                        claim_text=(
                            f"Information for the requested {concept_readable} "
                            f"period is not available in the indexed corpus."
                        ).strip(),
                        numerical_value=None,
                        expected_xbrl_value=None,
                        status=ClaimVerificationStatus.UNVERIFIED,
                        verification_notes=(
                            f"No {concept} XBRL facts found for {period_text} "
                            "in the current document corpus. Cannot verify the "
                            "numerical claim without ground-truth data."
                        ),
                    )
                )

        # --- Qualitative claim -------------------------------------------
        # Use TF-IDF cosine similarity to check whether a source passage
        # semantically entails the claim. Above-threshold similarity → VERIFIED;
        # below-threshold → UNVERIFIED with source context. Demo data stays
        # UNVERIFIED regardless (synthetic, not SEC-reported).
        best_chunk = None
        best_similarity = 0.0
        for c in sorted(chunks, key=lambda x: x.score, reverse=True):
            content = c.chunk.content.lower()
            if not any(sig in content for sig in FINANCIAL_CONTENT_SIGNALS):
                continue
            sim = _semantic_similarity(question, c.chunk.content)
            if sim > best_similarity:
                best_similarity = sim
                best_chunk = c.chunk

        if best_chunk:
            excerpt_claim = next(
                (
                    sentence.strip()
                    for sentence in re.split(r"(?<=[.!?])\s+", best_chunk.content)
                    if sentence.strip()
                ),
                best_chunk.content.strip(),
            )

            # Demo data is never SEC-verified.
            if best_chunk.data_source == DataSource.DEMO:
                claim_status = ClaimVerificationStatus.UNVERIFIED
                verification_note = (
                    "Qualitative claim quoted from synthetic demo text; "
                    "not SEC-reported."
                )
            elif best_similarity >= QUALITATIVE_SIMILARITY_THRESHOLD:
                claim_status = ClaimVerificationStatus.VERIFIED
                verification_note = (
                    f"Qualitative claim semantically entailed by retrieved "
                    f"source passage (TF-IDF cosine similarity {best_similarity:.2f} "
                    f">= {QUALITATIVE_SIMILARITY_THRESHOLD})."
                )
            else:
                claim_status = ClaimVerificationStatus.UNVERIFIED
                verification_note = (
                    f"Qualitative claim not sufficiently entailed by retrieved "
                    f"source passage (TF-IDF cosine similarity {best_similarity:.2f} "
                    f"< {QUALITATIVE_SIMILARITY_THRESHOLD}). Treat as source context."
                )

            verified_claims.append(
                VerifiedClaim(
                    claim_id="claim-qualitative-1",
                    claim_text=excerpt_claim,
                    numerical_value=None,
                    expected_xbrl_value=None,
                    status=claim_status,
                    verification_notes=verification_note,
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
                            data_source=best_chunk.data_source,
                        )
                    ],
                )
            )
        else:
            verified_claims.append(
                VerifiedClaim(
                    claim_id="claim-qualitative-unverified",
                    claim_text="No source-backed qualitative finding was available in the retrieved corpus.",
                    numerical_value=None,
                    expected_xbrl_value=None,
                    status=ClaimVerificationStatus.UNVERIFIED,
                    verification_notes=(
                        "No relevant source passage was retrieved for this question."
                    ),
                )
            )

        return verified_claims
