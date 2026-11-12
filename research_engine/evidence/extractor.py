"""LLM-based candidate evidence extraction module.

Extracts structured claims, verbatim quotes, attributions, metrics,
and source types from untrusted webpage text using prompt injection defense.
"""

import json
import logging
import re
from typing import List, Optional
from pydantic import ValidationError

from research_engine.evidence.models import CandidateEvidence, ExtractedEvidencePayload
from research_engine.providers.llm.base import BaseLLMProvider
from research_engine.security.sanitizer import build_safe_prompt_messages

logger = logging.getLogger("research_engine.evidence.extractor")

EXTRACTION_SYSTEM_PROMPT = """You are an expert evidence extraction specialist for an evidence-first research engine.
Your task is to analyze the provided untrusted webpage text and extract specific, high-fidelity candidate evidence items.

STRICT EXTRACTION RULES:
1. Every candidate evidence item MUST include an exact 'verbatim_quote' copied directly from the text.
2. The quote must directly support the 'candidate_claim'.
3. Do NOT convert marketing claims or press releases into established objective facts. Classify them as 'company_claim' with evidence_type 'corporate_pr'.
4. User comments, complaints, or forum posts must be classified as 'opinion' or 'user_experience' with evidence_type 'self_reported'. Never classify a single user review as general consensus.
5. For quantitative claims, capture the metric, units, time period, and denominator in 'metrics_data'.
6. If the page contains no substantive factual claims, benchmarks, or authentic experiences, return an empty array.
7. Do not hallucinate or guess.

Return a valid JSON object matching this schema:
{
  "candidate_evidence": [
    {
      "candidate_claim": "Clear, concise statement of what the source asserts",
      "exact_quote": "Verbatim sentence or phrase copied directly from the text",
      "claim_type": "direct_fact | quantitative | user_experience | opinion | company_claim | allegation | research_finding",
      "evidence_type": "empirical | self_reported | testimonial | corporate_pr | academic | journalistic",
      "attribution": "Author, organization, or speaker making the claim",
      "published_date": "YYYY-MM-DD or empty if unknown",
      "time_period": "Timeframe the claim applies to",
      "geographic_scope": "Geographic scope if relevant",
      "metrics_data": {"metric": "value", "unit": "unit", "sample_size": "n"},
      "surrounding_context": "Short context phrase"
    }
  ]
}
"""


class EvidenceExtractor:
    """Extracts structured candidate evidence items using an LLM provider."""

    def __init__(self, llm_provider: BaseLLMProvider, model_id: str):
        self.llm = llm_provider
        self.model_id = model_id

    def extract_candidate_evidence(
        self,
        source_id: int,
        source_url: str,
        domain: str,
        source_text: str
    ) -> List[CandidateEvidence]:
        """Extract candidate evidence items from extracted webpage text."""
        if not source_text or len(source_text.strip()) < 80:
            return []

        user_context = (
            f"Source ID: [{source_id}]\n"
            f"Domain: {domain}\n"
            f"URL: {source_url}\n\n"
            f"Analyze the following text and extract all verified candidate evidence items:"
        )

        messages = build_safe_prompt_messages(
            system_instruction=EXTRACTION_SYSTEM_PROMPT,
            user_context=user_context,
            untrusted_payload=source_text,
            metadata=f"Source #{source_id} ({domain})"
        )

        try:
            raw_response = self.llm.complete(
                messages=messages,
                model=self.model_id,
                temperature=0.05,
                json_mode=True
            )

            # Clean markdown formatting if present
            cleaned_json = raw_response.strip()
            if "```" in cleaned_json:
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned_json)
                if match:
                    cleaned_json = match.group(1).strip()

            parsed = json.loads(cleaned_json)

            # Handle both list and dict payload
            if isinstance(parsed, list):
                payload = ExtractedEvidencePayload(candidate_evidence=parsed)
            elif isinstance(parsed, dict):
                if "candidate_evidence" in parsed:
                    payload = ExtractedEvidencePayload.model_validate(parsed)
                elif "evidence" in parsed:
                    payload = ExtractedEvidencePayload(candidate_evidence=parsed["evidence"])
                elif "facts" in parsed:
                    # Map legacy format if returned
                    items = []
                    for f in parsed["facts"]:
                        items.append(CandidateEvidence(
                            candidate_claim=f.get("fact_or_review") or f.get("candidate_claim", ""),
                            exact_quote=f.get("verbatim_quote") or f.get("exact_quote", ""),
                            claim_type="direct_fact",
                            evidence_type="empirical"
                        ))
                    payload = ExtractedEvidencePayload(candidate_evidence=items)
                else:
                    payload = ExtractedEvidencePayload()
            else:
                payload = ExtractedEvidencePayload()

            return payload.candidate_evidence

        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"Failed to parse evidence extraction output for Source #{source_id}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error extracting evidence for Source #{source_id}: {e}")
            return []

