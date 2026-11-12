"""Unit tests for query routing, outbound reference discovery, and adaptive planning."""

import unittest
from unittest.mock import MagicMock

from research_engine.database.models import ResearchPlan
from research_engine.research.orchestrator import ResearchOrchestrator
from research_engine.research.planner import ResearchPlanner


class TestRoutingAndOutlinks(unittest.TestCase):

    def setUp(self):
        self.mock_llm = MagicMock()
        self.mock_repo = MagicMock()
        # Create orchestrator with mocks to test internal routing and link discovery methods
        self.orchestrator = ResearchOrchestrator.__new__(ResearchOrchestrator)

    def test_provider_routing_ddgs(self):
        """DDGS should be queried for all categories and queries."""
        self.assertTrue(self.orchestrator._is_provider_relevant("ddgs", "general", "anything"))
        self.assertTrue(self.orchestrator._is_provider_relevant("duckduckgo", "academic", "quantum computing"))
        self.assertTrue(self.orchestrator._is_provider_relevant("ddgs", "community", "reddit reviews"))

    def test_provider_routing_hackernews(self):
        """Hacker News should be queried for community, opposing, tech, or startup queries."""
        self.assertTrue(self.orchestrator._is_provider_relevant("hackernews", "community", "Mistral AI"))
        self.assertTrue(self.orchestrator._is_provider_relevant("hackernews", "opposing", "Mistral complaints"))
        self.assertTrue(self.orchestrator._is_provider_relevant("hackernews", "general", "Mistral AI founders startup funding"))
        # Pure non-tech academic query with category academic should be skipped for HN
        self.assertFalse(self.orchestrator._is_provider_relevant("hackernews", "academic", "roman history pottery styles"))

    def test_provider_routing_arxiv_and_openalex(self):
        """Arxiv and OpenAlex should route academic/technical queries and skip forum/complaint queries."""
        # Academic / architecture query
        self.assertTrue(self.orchestrator._is_provider_relevant("arxiv", "academic", "Mistral 7B"))
        self.assertTrue(self.orchestrator._is_provider_relevant("arxiv", "general", "transformer model architecture benchmark"))
        self.assertTrue(self.orchestrator._is_provider_relevant("openalex", "academic", "scholarly citations"))

        # Pure community / complaints / pricing queries should be filtered out from arxiv
        self.assertFalse(self.orchestrator._is_provider_relevant("arxiv", "community", "Mistral AI Reddit complaints"))
        self.assertFalse(self.orchestrator._is_provider_relevant("arxiv", "general", "Mistral AI pricing customer reviews"))
        self.assertFalse(self.orchestrator._is_provider_relevant("openalex", "community", "Mistral AI complaints"))

    def test_canonicalize_url(self):
        """Canonicalize URL strips tracking parameters and trailing slashes."""
        raw = "https://example.com/blog/article/?utm_source=twitter&utm_medium=social#heading"
        canon = self.orchestrator.canonicalize_url(raw)
        self.assertEqual(canon, "https://example.com/blog/article")

    def test_outbound_reference_discovery(self):
        """Discovers authoritative external references (arXiv, GitHub, docs) from HTML."""
        html = """
        <html>
        <body>
            <p>Our research paper is on <a href="https://arxiv.org/abs/2310.06825">arXiv</a>.</p>
            <p>Check the code on <a href="https://github.com/mistralai/mistral-src">GitHub</a>.</p>
            <p>Self link: <a href="https://techcrunch.com/another-article">Internal</a>.</p>
            <p>Tracking ad: <a href="https://adnetwork.com/click">Ad</a>.</p>
        </body>
        </html>
        """
        refs = self.orchestrator._discover_outbound_references(html, "https://techcrunch.com/2023/10/mistral-ai")
        domains = [r["domain"] for r in refs]

        self.assertIn("arxiv.org", domains)
        self.assertIn("github.com", domains)
        self.assertNotIn("techcrunch.com", domains)  # Same domain excluded
        self.assertNotIn("adnetwork.com", domains)   # Non-authoritative excluded

    def test_startup_adaptive_planning(self):
        """Planner should generate startup-specific subquestions when topic is a startup."""
        self.mock_llm.complete.return_value = "malformed json"
        planner = ResearchPlanner(self.mock_llm, self.mock_repo, model_id="test-model")
        plan = planner.create_plan("run-test", "Mistral AI startup valuation and founders")

        self.assertIsInstance(plan, ResearchPlan)
        subq_text = " ".join(plan.subquestions).lower()
        self.assertIn("founders", subq_text)
        self.assertIn("funding", subq_text)
        self.assertIn("business model", subq_text)
        self.assertIn("competitors", subq_text)


if __name__ == "__main__":
    unittest.main()

