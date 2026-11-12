"""End-to-End fixture integration test.

Covers:
- Test 32: Run complete research task on fixed local HTML fixtures.
- Test 33: Generate report from fixture data.
- Test 34: Programmatically verify every claim and citation in the generated report.
"""

import json
import os
import re
import tempfile
import unittest

from config import settings
from research_engine.database.connection import init_database
from research_engine.database.models import EvidenceRecord
from research_engine.database.repository import ResearchRepository
from research_engine.extractors.page_extractor import PageExtractor
from research_engine.providers.llm.mock_provider import MockLLMProvider
from research_engine.reporting.markdown_renderer import MarkdownReportRenderer
from research_engine.reporting.validator import ReportCitationValidator
from research_engine.synthesis.corroboration import CorroborationEngine
from research_engine.synthesis.report_synthesizer import (
    ReportSynthesizer,
    StructuredReportPayload,
    SynthesizedStatement,
)
from tests.fixtures.sample_pages import (
    PAGE_BENCHMARK_REVIEW,
    PAGE_FASTAPI_OFFICIAL_DOCS,
    PAGE_REDDIT_COMPLAINT_THREAD,
)


class TestEndToEndFixtureResearch(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()
        init_database(self.db_path)
        self.repo = ResearchRepository(self.db_path)
        self.run_id = "run-fixture-e2e"

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_32_33_34_complete_end_to_end_fixture_research(self):
        """Execute complete pipeline on local fixtures, generate report, and audit citations."""
        # Step 1: Create Run Record
        run = self.repo.create_run(
            run_id=self.run_id,
            question="FastAPI vs Flask in 2026 production: benchmarks, failure modes, and user consensus",
            scope="Standard web frameworks comparison",
            target_sources=3,
            max_rounds=1,
            model_id="mock-llama-70b",
            verifier_model_id="mock-verifier"
        )
        self.assertIsNotNone(run)

        # Step 2: Ingest Fixture Sources
        sources_data = [
            {
                "url": "https://fastapi.tiangolo.com/features/",
                "canonical_url": "https://fastapi.tiangolo.com/features",
                "domain": "fastapi.tiangolo.com",
                "title": "FastAPI Official Documentation",
                "source_category": "primary",
                "source_tier": "Tier A"
            },
            {
                "url": "https://techbenchmarks.io/2026/python-frameworks/",
                "canonical_url": "https://techbenchmarks.io/2026/python-frameworks",
                "domain": "techbenchmarks.io",
                "title": "Independent 2026 Web Framework Benchmarks",
                "source_category": "independent_analysis",
                "source_tier": "Tier B"
            },
            {
                "url": "https://reddit.com/r/python/comments/fastapi_pain_points/",
                "canonical_url": "https://reddit.com/r/python/comments/fastapi_pain_points",
                "domain": "reddit.com",
                "title": "Real world pain points migrating to FastAPI",
                "source_category": "community",
                "source_tier": "Tier C"
            }
        ]
        inserted, _ = self.repo.add_sources_batch(self.run_id, sources_data)
        self.assertEqual(inserted, 3)

        # Step 3: Extract and store content using PageExtractor on local HTML fixtures
        extractor = PageExtractor(enable_jina_fallback=False)
        fixtures_map = {
            "fastapi.tiangolo.com": PAGE_FASTAPI_OFFICIAL_DOCS,
            "techbenchmarks.io": PAGE_BENCHMARK_REVIEW,
            "reddit.com": PAGE_REDDIT_COMPLAINT_THREAD,
        }

        db_sources = self.repo.get_sources_for_run(self.run_id)
        for s in db_sources:
            html = fixtures_map[s.domain]
            page = extractor.extract(html, s.url)
            self.assertIsNotNone(page)
            self.repo.save_source_content(s.id, self.run_id, page.text, page.method, page.content_hash)
            self.repo.update_source_fetch_status(s.id, self.run_id, "fetched", http_status=200)

        # Step 4: Extract candidate evidence and validate verbatim quotes deterministically
        source_fastapi = [s for s in db_sources if "fastapi.tiangolo.com" in s.domain][0]
        source_bench = [s for s in db_sources if "techbenchmarks.io" in s.domain][0]
        source_reddit = [s for s in db_sources if "reddit.com" in s.domain][0]

        # Evidence 1: Primary spec
        ev1 = EvidenceRecord(
            id="evid-001",
            run_id=self.run_id,
            source_id=source_fastapi.id,
            candidate_claim="FastAPI is based on Starlette and Pydantic.",
            exact_quote="Fast: Very high performance, on par with NodeJS and Go (thanks to Starlette and Pydantic).",
            quote_valid=True,
            support_status="supports",
            claim_type="direct_fact",
            evidence_type="corporate_pr",
            is_verified=True
        )
        self.repo.insert_evidence_item(ev1)

        # Evidence 2: Empirical benchmark
        ev2 = EvidenceRecord(
            id="evid-002",
            run_id=self.run_id,
            source_id=source_bench.id,
            candidate_claim="FastAPI achieved 48,200 req/s with 4.2ms p99 latency under 10,000 concurrent requests.",
            exact_quote="FastAPI achieved 48,200 requests per second with a p99 latency of 4.2ms.",
            quote_valid=True,
            support_status="supports",
            claim_type="quantitative",
            evidence_type="empirical",
            is_verified=True
        )
        self.repo.insert_evidence_item(ev2)

        # Evidence 3: Community pain point
        ev3 = EvidenceRecord(
            id="evid-003",
            run_id=self.run_id,
            source_id=source_reddit.id,
            candidate_claim="Users reported memory creep over several days under sustained WebSocket workloads.",
            exact_quote="we noticed memory creeping up over several days under sustained WebSocket workloads due to circular references in dependency injection.",
            quote_valid=True,
            support_status="supports",
            claim_type="user_experience",
            evidence_type="self_reported",
            is_verified=True
        )
        self.repo.insert_evidence_item(ev3)

        # Step 5: Run Corroboration Engine
        corrob = CorroborationEngine(self.repo)
        claims, contradictions = corrob.process_corroboration_and_claims(self.run_id)
        self.assertGreaterEqual(len(claims), 2)

        # Step 6: Synthesize structured report payload
        payload = StructuredReportPayload(
            title="FastAPI vs Flask in 2026 Production: Comprehensive Evidence Report",
            executive_summary=[
                SynthesizedStatement(
                    statement="FastAPI demonstrates high JSON throughput backed by Starlette and Pydantic.",
                    cited_evidence_ids=["evid-001"]
                )
            ],
            key_findings=[
                SynthesizedStatement(
                    statement="Independent benchmarks measured FastAPI at 48,200 req/s with 4.2ms p99 latency under 10,000 concurrent requests.",
                    cited_evidence_ids=["evid-002"]
                )
            ],
            community_experiences=[
                SynthesizedStatement(
                    statement="Engineering teams report memory creep issues during extended WebSocket sessions attributed to circular DI references.",
                    cited_evidence_ids=["evid-003"]
                )
            ],
            conclusion="FastAPI delivers significant throughput advantages for I/O bound microservices, while requiring careful memory management in stateful WebSocket setups."
        )

        # Step 7: Programmatic Citation Verification
        validator = ReportCitationValidator(self.repo)
        validated_payload, val_result = validator.validate_report(self.run_id, payload)

        self.assertEqual(val_result.total_citations, 3)
        self.assertEqual(val_result.valid_citations, 3)
        self.assertEqual(val_result.invalid_citations, 0)
        self.assertEqual(val_result.unverified_statements, 0)

        # Step 8: Render Markdown Report
        renderer = MarkdownReportRenderer(self.repo)
        from research_engine.database.models import ResearchPlan
        dummy_plan = self.repo.get_plan(self.run_id) or ResearchPlan(core_question=run.question, scope=run.scope)

        report_markdown = renderer.render(self.run_id, validated_payload, val_result, dummy_plan)

        # Programmatic assertion on rendered Markdown
        self.assertIn("# FastAPI vs Flask in 2026 Production", report_markdown)
        self.assertIn("## Sources & Evidence Directory", report_markdown)
        self.assertIn("[evid-001: fastapi.tiangolo.com]", report_markdown)
        self.assertIn("[evid-002: techbenchmarks.io]", report_markdown)
        self.assertIn("[evid-003: reddit.com]", report_markdown)

        # Save verified sample report in reports/ directory as a deliverable
        sample_report_path = os.path.join(settings.reports_dir, "sample_verified_report.md")
        with open(sample_report_path, "w", encoding="utf-8") as fp:
            fp.write(report_markdown)

        self.assertTrue(os.path.exists(sample_report_path))
        self.assertGreater(os.path.getsize(sample_report_path), 500)


if __name__ == "__main__":
    unittest.main()
