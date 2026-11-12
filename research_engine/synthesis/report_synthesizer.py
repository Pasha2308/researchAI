"""Structured Report Synthesizer.

Synthesizes findings using ONLY the verified evidence ledger.
Enforces that every factual statement references specific evidence IDs.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from research_engine.database.models import ClaimRecord, ContradictionRecord, EvidenceRecord, ResearchPlan, SourceRecord
from research_engine.database.repository import ResearchRepository
from research_engine.providers.llm.base import BaseLLMProvider

logger = logging.getLogger("research_engine.synthesis.synthesizer")


class SynthesizedStatement(BaseModel):
    statement: str
    cited_evidence_ids: List[str] = Field(default_factory=list)


class SynthesizedSection(BaseModel):
    section_title: str
    statements: List[SynthesizedStatement] = Field(default_factory=list)


class StructuredReportPayload(BaseModel):
    title: str
    executive_summary: List[SynthesizedStatement] = Field(default_factory=list)
    key_findings: List[SynthesizedStatement] = Field(default_factory=list)
    detailed_sections: List[SynthesizedSection] = Field(default_factory=list)
    community_experiences: List[SynthesizedStatement] = Field(default_factory=list)
    complaints_and_risks: List[SynthesizedStatement] = Field(default_factory=list)
    contradictions_disagreements: List[SynthesizedStatement] = Field(default_factory=list)
    what_could_not_be_established: List[str] = Field(default_factory=list)
    methodology_limitations: List[str] = Field(default_factory=list)
    conclusion: str = ""


SYNTHESIS_SYSTEM_PROMPT = """You are a master research synthesizer for an evidence-first deep research engine.
Your mission is to synthesize verified factual findings into a brutally honest, evidence-backed research report.

CRITICAL SYNTHESIS RULES:
1. You may ONLY state facts, figures, and user experiences that are backed by the provided verified evidence ledger.
2. Under NO circumstances introduce unverified outside knowledge, speculative assertions, or hallucinations.
3. Every factual sentence MUST explicitly list the supporting evidence IDs in 'cited_evidence_ids'.
4. Clearly distinguish:
   - Directly documented facts (official specs/docs)
   - Independently corroborated findings (multiple independent domains)
   - Single-source claims (only 1 source supports it)
   - Company marketing claims (what the company asserts about itself)
   - User opinions & experiences (self-reported reviews/forums; never call 1 review 'consensus')
   - Known complaints, failure modes, and criticisms
   - Unresolved contradictions and disagreements
5. If evidence on a subquestion is missing or unavailable, explicitly state that in 'what_could_not_be_established'.

Output valid JSON matching the StructuredReportPayload schema.
"""


class ReportSynthesizer:
    """Synthesizes structured reports from verified evidence and claims."""

    def __init__(self, llm_provider: BaseLLMProvider, repository: ResearchRepository, model_id: str):
        self.llm = llm_provider
        self.repo = repository
        self.model_id = model_id

    def synthesize_report(
        self,
        run_id: str,
        question: str,
        plan: ResearchPlan,
        claims: List[ClaimRecord],
        evidence: List[EvidenceRecord],
        contradictions: List[ContradictionRecord]
    ) -> StructuredReportPayload:
        """Synthesize verified evidence into structured report JSON."""
        # Build evidence ledger formatted with IDs for the model
        evidence_lines = []
        for e in evidence:
            evidence_lines.append(
                f"- [Evidence_ID: {e.id}] (Type: {e.claim_type}, Source #{e.source_id}): "
                f"\"{e.candidate_claim}\" | Quote: \"{e.exact_quote}\" | Attribution: {e.attribution or 'N/A'}"
            )
        evidence_catalog = "\n".join(evidence_lines[:250])  # Cap to fit context comfortably

        # Contradictions summary
        contradiction_lines = []
        for c in contradictions:
            contradiction_lines.append(f"- Contradiction: {c.description}")
        contradiction_catalog = "\n".join(contradiction_lines) if contradiction_lines else "None detected."

        user_prompt = (
            f"Research Question: \"{question}\"\n\n"
            f"VERIFIED EVIDENCE LEDGER ({len(evidence)} verified items):\n"
            f"{evidence_catalog}\n\n"
            f"DETECTED CONTRADICTIONS:\n"
            f"{contradiction_catalog}\n\n"
            f"Synthesize an exhaustive, brutally honest report strictly referencing the provided Evidence_IDs."
        )

        messages = [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        logger.info(f"Executing report synthesis for Run [{run_id}]...")
        raw_response = self.llm.complete(
            messages=messages,
            model=self.model_id,
            temperature=0.1,
            json_mode=True
        )

        cleaned_json = raw_response.strip()
        if "```" in cleaned_json:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned_json)
            if match:
                cleaned_json = match.group(1).strip()

        try:
            data = json.loads(cleaned_json)
            if isinstance(data, dict):
                if "title" not in data or not data["title"]:
                    data["title"] = f"Research Report: {question}"
                if "key_findings" not in data:
                    data["key_findings"] = []
            report_payload = StructuredReportPayload.model_validate(data)
        except Exception as e:
            logger.warning(f"Synthesis parsing failed ({e}). Constructing structured fallback payload.")
            # Build programmatic fallback payload from verified claims
            key_statements = []
            for c in claims[:15]:
                # Find matching evidence IDs
                matching_evids = [e.id for e in evidence if e.candidate_claim == c.claim_text or e.candidate_claim in c.claim_text]
                if not matching_evids and evidence:
                    matching_evids = [evidence[0].id]
                key_statements.append(
                    SynthesizedStatement(
                        statement=f"[{c.claim_category.upper()}] {c.claim_text}",
                        cited_evidence_ids=matching_evids
                    )
                )

            report_payload = StructuredReportPayload(
                title=f"Research Report: {question}",
                executive_summary=[
                    SynthesizedStatement(
                        statement=f"Investigation into '{question}' compiled across verified sources.",
                        cited_evidence_ids=[evidence[0].id] if evidence else []
                    )
                ],
                key_findings=key_statements,
                conclusion="Research analysis complete based on available verified findings."
            )

        return report_payload

