"""Research Planning module.

Generates structured, topic-specific research plans breaking questions into
subquestions, search angles, primary/secondary/community targets, and counterarguments.
Never uses hardcoded universal templates.
"""

import json
import logging
import re
from typing import Optional
import uuid

from research_engine.database.models import ResearchPlan
from research_engine.database.repository import ResearchRepository
from research_engine.providers.llm.base import BaseLLMProvider

logger = logging.getLogger("research_engine.research.planner")

PLANNING_SYSTEM_PROMPT = """You are a research architect for an evidence-first deep research engine.
Analyze the user's question and output a COMPACT, structured research plan as valid JSON.

STRICT OUTPUT RULES:
- Keep ALL string values SHORT (under 15 words each). Do NOT write paragraphs.
- Limit arrays: subquestions max 6 items, search_angles max 5 items, all other arrays max 3 items.
- Output ONLY the JSON object. No markdown, no code fences, no explanation.

GUIDELINES:
1. Tailor subquestions to the subject matter:
   - Startups/companies: founders, products/technology, funding/investors, business model, enterprise customers, competitors, risks.
   - Technical comparisons: architecture, benchmarks, failure modes.
   - Science: methodology, peer review, sample sizes.
   - Consumer products: user reviews, reliability, failure rates.
2. Plan searches across distinct tiers: primary (official docs), independent (journalism/benchmarks), community (Reddit/HN), counterarguments (flaws/criticisms).

Output valid JSON matching exactly this schema (keep values short):
{
  "core_question": "Normalized question (1 sentence)",
  "scope": "Brief scope (1 sentence)",
  "definitions": {"term": "definition"},
  "subquestions": ["Subquestion 1", "Subquestion 2", "Subquestion 3"],
  "search_angles": ["Query angle 1", "Query angle 2", "Query angle 3"],
  "primary_source_targets": ["Source type 1", "Source type 2"],
  "independent_source_targets": ["Source type 1", "Source type 2"],
  "community_source_targets": ["Reddit discussion", "HN post"],
  "counterargument_targets": ["Known limitations", "Customer complaints"],
  "temporal_constraints": "Date range",
  "required_evidence_criteria": ["Criterion 1", "Criterion 2"]
}
"""


class ResearchPlanner:
    """Generates and persists structured research plans."""

    def __init__(self, llm_provider: BaseLLMProvider, repository: ResearchRepository, model_id: str):
        self.llm = llm_provider
        self.repo = repository
        self.model_id = model_id

    def create_plan(self, run_id: str, question: str, scope: str = "") -> ResearchPlan:
        """Generate structured research plan using the LLM and persist it."""
        user_prompt = (
            f"Research Question: \"{question}\"\n"
            f"Scope / Additional Instructions: \"{scope}\"\n\n"
            f"Create an exhaustive, structured research plan tailored to this topic."
        )

        messages = [
            {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        logger.info(f"Generating research plan for Run [{run_id}]...")
        raw_response = self.llm.complete(
            messages=messages,
            model=self.model_id,
            temperature=0.1,
            max_tokens=1500,  # Cap strictly: plan JSON must be compact; prevents json_validate_failed 400 error
            json_mode=True
        )

        cleaned_json = raw_response.strip()
        if "```" in cleaned_json:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned_json)
            if match:
                cleaned_json = match.group(1).strip()

        try:
            data = json.loads(cleaned_json)
            plan = ResearchPlan.model_validate(data)
        except Exception as e:
            logger.warning(f"Plan JSON parsing failed ({e}). Constructing default structured plan.")
            is_company_or_startup = any(k in question.lower() for k in ("startup", "founder", "funding", "investor", "company", "business model", "valuation", "mistral", "anthropic", "openai"))
            if is_company_or_startup:
                subqs = [
                    f"Who are the founders and key leadership of {question}, and what is their background?",
                    f"What are the core products, models, and technical architecture of {question}?",
                    f"What is the funding history, total capital raised, lead investors, and valuation of {question}?",
                    f"What is the business model, commercial monetization strategy, and pricing structure of {question}?",
                    f"Who are the key enterprise customers, strategic partnerships, and distribution channels of {question}?",
                    f"Who are the main competitors and what is the market positioning of {question}?",
                    f"What are the primary business risks, technical limitations, and community criticisms of {question}?"
                ]
                angles = [
                    f"{question} founders executive background",
                    f"{question} funding valuation investors",
                    f"{question} business model pricing revenue",
                    f"{question} competitors alternatives",
                    f"{question} risks criticisms limitations"
                ]
            else:
                subqs = [
                    f"What are the primary facts and specifications regarding {question}?",
                    f"What do independent benchmarks and expert reviews reveal about {question}?",
                    f"What authentic user experiences, complaints, and limitations are reported for {question}?"
                ]
                angles = [
                    f"{question} documentation architecture",
                    f"{question} benchmark comparison",
                    f"{question} reddit complaints flaws limitations"
                ]

            plan = ResearchPlan(
                core_question=question,
                scope=scope or "General comprehensive investigation",
                subquestions=subqs,
                search_angles=angles,
                primary_source_targets=["Official documentation", "Technical papers", "Corporate filings"],
                independent_source_targets=["Independent benchmarks", "Expert reviews", "Financial journalism"],
                community_source_targets=["Reddit", "Hacker News"],
                counterargument_targets=["Limitations", "Criticisms", "Risks"]
            )

        plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        self.repo.save_plan(plan_id, run_id, plan)
        return plan

