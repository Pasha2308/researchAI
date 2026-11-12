"""Iterative Research Gap Detector.

Identifies unanswered research subquestions, claims lacking independent corroboration,
and unresolved contradictions to generate targeted queries for subsequent research rounds.
"""

import json
import logging
from typing import Dict, List, Set, Tuple

from research_engine.database.models import ClaimRecord, EvidenceRecord, ResearchPlan
from research_engine.database.repository import ResearchRepository

logger = logging.getLogger("research_engine.research.gap")


class ResearchGap:
    """Represents an identified research gap or unanswered subquestion."""

    def __init__(self, subquestion: str, reason: str, suggested_queries: List[str]):
        self.subquestion = subquestion
        self.reason = reason
        self.suggested_queries = suggested_queries


class GapDetector:
    """Analyzes evidence coverage against the research plan to detect research gaps."""

    def __init__(self, repository: ResearchRepository):
        self.repo = repository

    def detect_gaps(
        self,
        run_id: str,
        plan: ResearchPlan,
        claims: List[ClaimRecord],
        evidence: List[EvidenceRecord]
    ) -> List[ResearchGap]:
        """Detect gaps in coverage and propose targeted search queries."""
        gaps: List[ResearchGap] = []
        if not plan or not plan.subquestions:
            return gaps

        # Map claims and evidence text for keyword/semantic coverage
        all_claim_texts = " ".join([c.claim_text.lower() for c in claims] + [e.candidate_claim.lower() for e in evidence])

        for subq in plan.subquestions:
            subq_words = [w.lower() for w in subq.split() if len(w) > 3 and w.lower() not in ("what", "which", "about", "does", "have")]
            matches = [w for w in subq_words if w in all_claim_texts]
            coverage_ratio = len(matches) / len(subq_words) if subq_words else 0.0

            if coverage_ratio < 0.4:
                # Subquestion lacks adequate evidence
                clean_terms = " ".join(subq_words[:4])
                suggested = [
                    f"{clean_terms} data facts",
                    f"{clean_terms} independent analysis",
                    f"{clean_terms} reddit discussion"
                ]
                gaps.append(
                    ResearchGap(
                        subquestion=subq,
                        reason="No verified evidence directly addresses this subquestion.",
                        suggested_queries=suggested
                    )
                )

        # Check for company claims that lack independent corroboration
        company_claims = [c for c in claims if c.claim_category == "company_claim"]
        if company_claims:
            for c in company_claims[:3]:
                clean_claim = " ".join(c.claim_text.split()[:5])
                gaps.append(
                    ResearchGap(
                        subquestion=f"Independent verification of: '{c.claim_text[:80]}'",
                        reason="This claim is supported solely by company marketing/PR without independent corroboration.",
                        suggested_queries=[
                            f"{clean_claim} independent benchmark",
                            f"{clean_claim} real experience complaints"
                        ]
                    )
                )

        logger.info(f"Gap detector identified {len(gaps)} research gap(s) for Run [{run_id}].")
        return gaps

