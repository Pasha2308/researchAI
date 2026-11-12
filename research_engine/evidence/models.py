"""Data models for structured evidence extraction and validation."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ClaimType(str, Enum):
    DIRECT_FACT = "direct_fact"
    QUANTITATIVE = "quantitative"
    USER_EXPERIENCE = "user_experience"
    OPINION = "opinion"
    COMPANY_CLAIM = "company_claim"
    ALLEGATION = "allegation"
    RESEARCH_FINDING = "research_finding"
    HISTORICAL_STATEMENT = "historical_statement"
    INFERENCE = "inference"


class EvidenceType(str, Enum):
    EMPIRICAL = "empirical"
    SELF_REPORTED = "self_reported"
    TESTIMONIAL = "testimonial"
    CORPORATE_PR = "corporate_pr"
    ACADEMIC = "academic"
    JOURNALISTIC = "journalistic"
    UNKNOWN = "unknown"


class VerificationVerdict(str, Enum):
    SUPPORTS = "supports"
    PARTIALLY_SUPPORTS = "partially_supports"
    CONTRADICTS = "contradicts"
    DOES_NOT_SUPPORT = "does_not_support"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    UNVERIFIED = "unverified"


class CandidateEvidence(BaseModel):
    """Raw candidate evidence item extracted from source text by the LLM."""
    candidate_claim: str
    exact_quote: str
    claim_type: str = "direct_fact"
    evidence_type: str = "empirical"
    attribution: str = ""
    published_date: str = ""
    time_period: str = ""
    geographic_scope: str = ""
    metrics_data: Dict[str, Any] = Field(default_factory=dict)
    surrounding_context: str = ""


class ExtractedEvidencePayload(BaseModel):
    """Container for batch candidate evidence extraction."""
    candidate_evidence: List[CandidateEvidence] = Field(default_factory=list)


class ClaimVerificationResult(BaseModel):
    """Result of independent second-pass claim support verification."""
    verdict: VerificationVerdict
    reason: str
    refined_claim: Optional[str] = None
    attribution: Optional[str] = None
    claim_type: Optional[str] = None

