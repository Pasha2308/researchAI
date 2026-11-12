"""Independent second-pass claim support verifier.

Evaluates whether the candidate claim is genuinely supported by the exact quote
and surrounding source context. Fails closed if context is insufficient or contradictory.
"""

import json
import logging
import re
from typing import Optional

from research_engine.evidence.models import (
    CandidateEvidence,
    ClaimVerificationResult,
    VerificationVerdict,
)
from research_engine.providers.llm.base import BaseLLMProvider

logger = logging.getLogger("research_engine.verification.claim")

VERIFICATION_SYSTEM_PROMPT = """You are a strict, skeptical verification auditor for an evidence-first research engine.
Your sole job is to evaluate whether a candidate claim is genuinely and accurately supported by the exact supporting quote and its surrounding source context.

CRITICAL VERIFICATION RULES:
1. 'supports': The quote and context directly, unambiguously support the candidate claim without extrapolation or exaggeration.
2. 'partially_supports': The quote supports part of the claim, but the claim overstates or generalizes the evidence. (Provide a narrowed 'refined_claim').
3. 'contradicts': The quote or surrounding context directly contradicts or disproves the candidate claim.
4. 'does_not_support': The quote is irrelevant, out of context, or fails to prove the candidate claim.
5. 'insufficient_context': There is not enough information in the quote or surrounding context to verify the claim.

FAIL-CLOSED POLICY:
If you are uncertain, ambiguous, or the context is incomplete, choose 'insufficient_context' or 'does_not_support'.
Do NOT give claims the benefit of the doubt.

Output valid JSON matching:
{
  "verdict": "supports | partially_supports | contradicts | does_not_support | insufficient_context",
  "reason": "Brief, rigorous explanation of why the evidence does or does not support the claim",
  "refined_claim": "Narrowed version if partially_supports, otherwise null",
  "attribution": "Who stated this",
  "claim_type": "Refined claim type if different from original"
}
"""


class ClaimVerifier:
    """Verifies candidate claims against exact quotes and surrounding context."""

    def __init__(self, llm_provider: BaseLLMProvider, model_id: str):
        self.llm = llm_provider
        self.model_id = model_id

    def verify_claim(
        self,
        candidate_claim: str,
        exact_quote: str,
        surrounding_context: str,
        source_domain: str,
        source_url: str
    ) -> ClaimVerificationResult:
        """Run second-pass support verification."""
        user_prompt = (
            f"SOURCE DOMAIN: {source_domain}\n"
            f"SOURCE URL: {source_url}\n\n"
            f"CANDIDATE CLAIM TO VERIFY:\n"
            f"\"{candidate_claim}\"\n\n"
            f"EXACT QUOTATION:\n"
            f"\"{exact_quote}\"\n\n"
            f"SURROUNDING SOURCE CONTEXT:\n"
            f"\"{surrounding_context}\"\n\n"
            f"Evaluate whether the exact quotation and context support this claim. Fail closed if uncertain."
        )

        messages = [
            {"role": "system", "content": VERIFICATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        try:
            raw_response = self.llm.complete(
                messages=messages,
                model=self.model_id,
                temperature=0.0,
                json_mode=True
            )

            cleaned_json = raw_response.strip()
            if "```" in cleaned_json:
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned_json)
                if match:
                    cleaned_json = match.group(1).strip()

            parsed = json.loads(cleaned_json)
            verdict_str = parsed.get("verdict", "unverified").lower()

            try:
                verdict = VerificationVerdict(verdict_str)
            except ValueError:
                verdict = VerificationVerdict.INSUFFICIENT_CONTEXT

            return ClaimVerificationResult(
                verdict=verdict,
                reason=parsed.get("reason", "Verification evaluation completed."),
                refined_claim=parsed.get("refined_claim"),
                attribution=parsed.get("attribution"),
                claim_type=parsed.get("claim_type")
            )

        except Exception as e:
            logger.warning(f"Claim verification failed with error: {e}. Failing closed.")
            return ClaimVerificationResult(
                verdict=VerificationVerdict.INSUFFICIENT_CONTEXT,
                reason=f"Verification failed due to evaluation error: {e}"
            )

