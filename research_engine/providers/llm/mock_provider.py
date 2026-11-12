"""Deterministic Mock LLM provider for zero-cost offline testing and fixtures."""

import json
from typing import Any, Callable, Dict, List, Optional, Tuple
from research_engine.providers.llm.base import BaseLLMProvider


class MockLLMProvider(BaseLLMProvider):
    """Deterministic mock LLM for offline tests and fixture evaluation."""

    def __init__(
        self,
        canned_responses: Optional[List[str]] = None,
        custom_handler: Optional[Callable[[List[Dict[str, str]]], str]] = None
    ):
        self.canned_responses = list(canned_responses or [])
        self.custom_handler = custom_handler
        self.call_history: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "mock"

    def validate_model(self, model: str) -> Tuple[bool, str, List[str]]:
        if model.startswith("invalid-"):
            return False, f"Model '{model}' is invalid.", ["mock-model-v1", "mock-model-v2"]
        return True, f"Mock model '{model}' is available.", ["mock-model-v1", "mock-model-v2"]

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        json_mode: bool = False,
        **kwargs: Any
    ) -> str:
        self.call_history.append({
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "json_mode": json_mode
        })

        if self.custom_handler:
            return self.custom_handler(messages)

        if self.canned_responses:
            return self.canned_responses.pop(0)

        # Default intelligent response based on prompt contents
        prompt_text = " ".join(m.get("content", "") for m in messages).lower()

        if "research plan" in prompt_text or "subquestions" in prompt_text:
            return json.dumps({
                "core_question": "What are the verified facts?",
                "scope": "Comprehensive test scope",
                "definitions": {"key": "definition"},
                "subquestions": ["What is performance?", "What are user complaints?"],
                "search_angles": ["performance benchmarks", "user reviews"],
                "primary_source_targets": ["official documentation"],
                "independent_source_targets": ["independent benchmarks"],
                "community_source_targets": ["reddit discussions"],
                "counterargument_targets": ["limitations and complaints"],
                "required_evidence_criteria": ["reproducible benchmarks"]
            })

        if "extract" in prompt_text and ("candidate_claim" in prompt_text or "fact_or_review" in prompt_text):
            return json.dumps({
                "candidate_evidence": [
                    {
                        "candidate_claim": "FastAPI is a modern web framework based on Starlette.",
                        "exact_quote": "FastAPI is a modern, fast web framework for building APIs with Python.",
                        "claim_type": "direct_fact",
                        "evidence_type": "empirical",
                        "attribution": "Documentation",
                        "published_date": "2024-01-01",
                        "surrounding_context": "Overview section of documentation."
                    }
                ]
            })

        if "verify" in prompt_text or "support_status" in prompt_text:
            return json.dumps({
                "verdict": "supports",
                "reason": "The exact quote directly supports the candidate claim.",
                "claim_type": "direct_fact",
                "attribution": "Primary documentation"
            })

        if "synthesize" in prompt_text or "report" in prompt_text:
            return json.dumps({
                "title": "Synthesized Test Report",
                "executive_summary": "Comprehensive findings indicate high performance.",
                "findings": [
                    {
                        "statement": "FastAPI provides high-performance API routing.",
                        "cited_evidence_ids": ["evid-1"]
                    }
                ]
            })

        return "{}"

