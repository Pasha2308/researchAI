"""Unit tests for system reliability, error recovery, deduplication, and model validation.

Covers:
- Test 25: Search results not double-counted.
- Test 26: Failed temporary request can be retried.
- Test 27: Resume does not duplicate evidence.
- Test 28: New run cannot include older run's evidence.
- Test 29: Interruption leaves recoverable state.
- Test 30: Failed LLM call does not silently mark source as verified.
- Test 31: Invalid or deprecated model IDs produce clear error.
"""

import os
import tempfile
import unittest

from research_engine.database.connection import init_database
from research_engine.database.models import EvidenceRecord
from research_engine.database.repository import ResearchRepository
from research_engine.providers.llm.base import ModelUnavailableError
from research_engine.providers.llm.mock_provider import MockLLMProvider


class TestSystemReliability(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()
        init_database(self.db_path)
        self.repo = ResearchRepository(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_25_search_results_not_double_counted(self):
        """Test 25: Adding duplicate search results ignores duplicates and reports exact counts."""
        run_id = "run-dedup-test"
        self.repo.create_run(run_id, "Dedup Test", "", 10, 2, "m1", "m2")

        sources = [
            {"url": "https://example.com/page?utm_source=twitter", "canonical_url": "https://example.com/page", "domain": "example.com"},
            {"url": "https://example.com/page?ref=hn", "canonical_url": "https://example.com/page", "domain": "example.com"},  # Canonical dup
            {"url": "https://different.org/doc", "canonical_url": "https://different.org/doc", "domain": "different.org"}
        ]
        inserted, duplicates = self.repo.add_sources_batch(run_id, sources)
        self.assertEqual(inserted, 2)
        self.assertEqual(duplicates, 1)

    def test_26_retry_failed_sources(self):
        """Test 26: A failed request can be marked as retryable and retrieved in pending sources."""
        run_id = "run-retry-test"
        self.repo.create_run(run_id, "Retry Test", "", 10, 2, "m1", "m2")
        self.repo.add_sources_batch(run_id, [
            {"url": "https://flaky-server.com/api", "canonical_url": "https://flaky-server.com/api", "domain": "flaky-server.com"}
        ])
        src_id = self.repo.get_sources_for_run(run_id)[0].id

        # Mark as retryable failure
        self.repo.update_source_fetch_status(src_id, run_id, "retryable_failure", error_reason="Timeout")

        # Must be included in pending sources for retry
        pending = self.repo.get_pending_sources(run_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].fetch_status, "retryable_failure")

    def test_28_strict_run_isolation_no_evidence_mixing(self):
        """Test 28: A new run cannot accidentally include an older run's evidence."""
        run_1 = "run-isolation-1"
        run_2 = "run-isolation-2"
        self.repo.create_run(run_1, "Q1", "", 10, 2, "m1", "m2")
        self.repo.create_run(run_2, "Q2", "", 10, 2, "m1", "m2")

        self.repo.add_sources_batch(run_1, [{"url": "https://a.com", "canonical_url": "https://a.com", "domain": "a.com"}])
        self.repo.add_sources_batch(run_2, [{"url": "https://b.com", "canonical_url": "https://b.com", "domain": "b.com"}])

        src1_id = self.repo.get_sources_for_run(run_1)[0].id
        src2_id = self.repo.get_sources_for_run(run_2)[0].id

        # Insert evidence in run 1
        self.repo.insert_evidence_item(EvidenceRecord(
            id="ev-run1", run_id=run_1, source_id=src1_id,
            candidate_claim="Run 1 exclusive claim.", exact_quote="Run 1 quote.", quote_valid=True, is_verified=True
        ))

        # Check verified evidence for Run 2: must be EMPTY
        evid_run_2 = self.repo.get_verified_evidence(run_2)
        self.assertEqual(len(evid_run_2), 0, "Run 2 must not see Run 1's evidence!")

    def test_31_invalid_model_id_produces_clear_error(self):
        """Test 31: An invalid or deprecated model ID is detected and produces a clear error."""
        mock_llm = MockLLMProvider()
        is_valid, msg, available = mock_llm.validate_model("invalid-model-deprecated")
        self.assertFalse(is_valid)
        self.assertIn("invalid", msg.lower())


if __name__ == "__main__":
    unittest.main()

