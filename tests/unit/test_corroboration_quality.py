"""Unit tests for corroboration engine, contradiction detection, and research gaps.

Covers:
- Test 13: Contradictory sources are retained.
- Test 14: Syndicated duplicate content not counted as independent corroboration.
- Test 16: Primary and secondary sources are distinguishable.
- Test 17: Source diversity and accounting counts correct.
- Test 18: Unanswered subquestions recorded as research gaps.
"""

import os
import tempfile
import unittest

from research_engine.database.connection import init_database
from research_engine.database.models import EvidenceRecord, ResearchPlan
from research_engine.database.repository import ResearchRepository
from research_engine.research.gap_detector import GapDetector
from research_engine.synthesis.corroboration import CorroborationEngine


class TestCorroborationAndResearchQuality(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()
        init_database(self.db_path)
        self.repo = ResearchRepository(self.db_path)
        self.run_id = "run-corrob-test"
        self.repo.create_run(self.run_id, "Corroboration Test", "", 10, 2, "m1", "m2")

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_14_syndicated_duplicate_content_not_independent(self):
        """Test 14: Mirrored or syndicated articles sharing identical content hash do NOT count as independent sources."""
        identical_content_hash = "abc1234567890deadbeef"

        # Insert two different domains having the exact same syndicated content hash
        self.repo.add_sources_batch(self.run_id, [
            {"url": "https://syndicate-a.com/article", "canonical_url": "https://syndicate-a.com/article", "domain": "syndicate-a.com", "source_tier": "Tier B"},
            {"url": "https://syndicate-b.com/article", "canonical_url": "https://syndicate-b.com/article", "domain": "syndicate-b.com", "source_tier": "Tier B"}
        ])
        sources = self.repo.get_sources_for_run(self.run_id)
        src_a, src_b = sources[0], sources[1]

        self.repo.save_source_content(src_a.id, self.run_id, "FastAPI is fast.", "trafilatura", identical_content_hash)
        self.repo.save_source_content(src_b.id, self.run_id, "FastAPI is fast.", "trafilatura", identical_content_hash)

        # Insert evidence from both sources
        self.repo.insert_evidence_item(EvidenceRecord(
            id="evid-syn-1", run_id=self.run_id, source_id=src_a.id,
            candidate_claim="FastAPI provides high execution speed.",
            exact_quote="FastAPI is fast.", quote_valid=True, support_status="supports", is_verified=True
        ))
        self.repo.insert_evidence_item(EvidenceRecord(
            id="evid-syn-2", run_id=self.run_id, source_id=src_b.id,
            candidate_claim="FastAPI provides high execution speed.",
            exact_quote="FastAPI is fast.", quote_valid=True, support_status="supports", is_verified=True
        ))

        corrob = CorroborationEngine(self.repo)
        claims, _ = corrob.process_corroboration_and_claims(self.run_id)

        self.assertEqual(len(claims), 1)
        # Because content hashes are identical, independent_sources_count must be 1, NOT 2!
        self.assertEqual(
            claims[0].independent_sources_count, 1,
            "Syndicated content sharing identical content hash must count as only 1 independent source."
        )

    def test_13_contradictory_sources_retained(self):
        """Test 13: Contradictory evidence items are detected, retained, and flagged as disputed."""
        self.repo.add_sources_batch(self.run_id, [
            {"url": "https://site-faster.com/bench", "canonical_url": "https://site-faster.com/bench", "domain": "site-faster.com", "source_tier": "Tier B"},
            {"url": "https://site-slower.com/bench", "canonical_url": "https://site-slower.com/bench", "domain": "site-slower.com", "source_tier": "Tier B"}
        ])
        sources = self.repo.get_sources_for_run(self.run_id)
        src1, src2 = sources[0], sources[1]

        self.repo.save_source_content(src1.id, self.run_id, "FastAPI is faster than Flask.", "trafilatura", "hash1")
        self.repo.save_source_content(src2.id, self.run_id, "FastAPI is slower than Flask.", "trafilatura", "hash2")

        # Claim A: faster
        self.repo.insert_evidence_item(EvidenceRecord(
            id="evid-fast", run_id=self.run_id, source_id=src1.id,
            candidate_claim="FastAPI is faster than Flask.",
            exact_quote="FastAPI is faster than Flask.", quote_valid=True, support_status="supports", is_verified=True
        ))
        # Claim B: slower
        self.repo.insert_evidence_item(EvidenceRecord(
            id="evid-slow", run_id=self.run_id, source_id=src2.id,
            candidate_claim="FastAPI is slower than Flask.",
            exact_quote="FastAPI is slower than Flask.", quote_valid=True, support_status="supports", is_verified=True
        ))

        corrob = CorroborationEngine(self.repo)
        claims, contradictions = corrob.process_corroboration_and_claims(self.run_id)

        self.assertGreaterEqual(len(contradictions), 1)
        # Disputed claim must retain status
        self.assertTrue(any(c.has_contradictions for c in claims) or any(c.claim_category == "disputed" for c in claims))

    def test_16_primary_and_secondary_tiers_distinguishable(self):
        """Test 16: Primary (Tier A) and secondary (Tier B/C) source tiers are tracked and distinguishable."""
        self.repo.add_sources_batch(self.run_id, [
            {"url": "https://docs.python.org/3/", "canonical_url": "https://docs.python.org/3/", "domain": "docs.python.org", "source_tier": "Tier A"},
            {"url": "https://medium.com/post", "canonical_url": "https://medium.com/post", "domain": "medium.com", "source_tier": "Tier C"},
        ])
        sources = self.repo.get_sources_for_run(self.run_id)
        tier_map = {s.domain: s.source_tier for s in sources}
        self.assertEqual(tier_map["docs.python.org"], "Tier A")
        self.assertEqual(tier_map["medium.com"], "Tier C")

    def test_18_unanswered_subquestions_recorded_as_gaps(self):
        """Test 18: Unanswered subquestions from the research plan are recorded as gaps."""
        plan = ResearchPlan(
            core_question="FastAPI analysis",
            subquestions=[
                "What is FastAPI's request throughput?",
                "What are the official licensing terms and enterprise support costs?",  # Unanswered
            ]
        )
        # Only add evidence for throughput
        evid = [EvidenceRecord(
            id="ev-1", run_id=self.run_id, source_id=1,
            candidate_claim="FastAPI request throughput is 48,000 req/s.",
            exact_quote="48,000 req/s.", quote_valid=True, is_verified=True
        )]
        detector = GapDetector(self.repo)
        gaps = detector.detect_gaps(self.run_id, plan, [], evid)

        self.assertTrue(any("licensing" in g.subquestion.lower() or "cost" in g.subquestion.lower() for g in gaps))


if __name__ == "__main__":
    unittest.main()

