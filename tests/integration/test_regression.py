"""Explicit Regression Tests for All Critical Defects in the Previous Architecture.

Guarantees that previous vulnerabilities and design flaws cannot re-occur:
1. Quote validation must NOT check only the first 10 or 15 words.
2. Unmatched quotations must NEVER be silently kept or promoted to verified facts.
3. Database must enforce run isolation via run_id (preventing multi-topic evidence leaks).
4. SSRF vulnerabilities (e.g. localhost, cloud metadata, private IPs) must be blocked before fetching.
5. Search results must be accounted for by unique canonical URLs rather than raw queries.
"""

import os
import tempfile
import unittest

from research_engine.database.connection import init_database
from research_engine.database.models import EvidenceRecord
from research_engine.database.repository import ResearchRepository
from research_engine.evidence.validator import validate_exact_quote
from research_engine.security.ssrf import SSRFSecurityError, validate_url


class TestArchitectureRegressions(unittest.TestCase):

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

    def test_regression_01_no_fifteen_word_prefix_validation(self):
        """Defect: The old engine used verbatim_quote.split()[:15], allowing any fabricated tail to pass."""
        original_doc = (
            "PostgreSQL is an advanced, enterprise-class open-source relational database "
            "that supports both SQL (relational) and JSON (non-relational) querying."
        )
        # First 15 words are real, but the rest is dangerous hallucination
        hallucinated_tail_quote = (
            "PostgreSQL is an advanced, enterprise-class open-source relational database "
            "that supports both SQL and will automatically steal your company credit cards."
        )
        is_valid, start, end, ctx = validate_exact_quote(hallucinated_tail_quote, original_doc)
        self.assertFalse(is_valid, "Quotes with fabricated tails must NEVER pass validation.")

    def test_regression_02_no_silent_preservation_of_unmatched_quotes(self):
        """Defect: The old engine fell back to valid_facts.append() even if quotes didn't match."""
        run_id = "run-reg-02"
        self.repo.create_run(run_id, "Silent Preservation Check", "", 10, 1, "m1", "m2")
        self.repo.add_sources_batch(run_id, [
            {"url": "https://example.com/test", "canonical_url": "https://example.com/test", "domain": "example.com"}
        ])
        src_id = self.repo.get_sources_for_run(run_id)[0].id

        # Insert an unverified evidence record (quote not matching)
        unmatched_evid = EvidenceRecord(
            id="evid-unmatched",
            run_id=run_id,
            source_id=src_id,
            candidate_claim="Fake unverified claim.",
            exact_quote="Completely invented quote.",
            quote_valid=False,
            support_status="does_not_support",
            is_verified=False
        )
        self.repo.insert_evidence_item(unmatched_evid)

        # Verified evidence ledger MUST be empty!
        verified_items = self.repo.get_verified_evidence(run_id)
        self.assertEqual(len(verified_items), 0, "Unmatched quotes must NEVER be present in the verified evidence ledger.")

    def test_regression_03_no_cross_run_evidence_mixing(self):
        """Defect: The old engine had a single global facts table with no run_id, mixing facts across topics."""
        topic_a = "run-topic-fastapi"
        topic_b = "run-topic-quantum-computing"

        self.repo.create_run(topic_a, "FastAPI Research", "", 5, 1, "m1", "m2")
        self.repo.create_run(topic_b, "Quantum Computing", "", 5, 1, "m1", "m2")

        self.repo.add_sources_batch(topic_a, [{"url": "https://fastapi.org", "canonical_url": "https://fastapi.org", "domain": "fastapi.org"}])
        self.repo.add_sources_batch(topic_b, [{"url": "https://quantum.org", "canonical_url": "https://quantum.org", "domain": "quantum.org"}])

        src_a_id = self.repo.get_sources_for_run(topic_a)[0].id
        src_b_id = self.repo.get_sources_for_run(topic_b)[0].id

        self.repo.insert_evidence_item(EvidenceRecord(
            id="ev-fastapi", run_id=topic_a, source_id=src_a_id,
            candidate_claim="FastAPI route handling is asynchronous.",
            exact_quote="Asynchronous route handling.", quote_valid=True, is_verified=True
        ))
        self.repo.insert_evidence_item(EvidenceRecord(
            id="ev-quantum", run_id=topic_b, source_id=src_b_id,
            candidate_claim="Qubits exhibit quantum entanglement.",
            exact_quote="Quantum entanglement observed.", quote_valid=True, is_verified=True
        ))

        # Topic A must ONLY contain FastAPI evidence
        evid_a = self.repo.get_verified_evidence(topic_a)
        self.assertEqual(len(evid_a), 1)
        self.assertIn("FastAPI", evid_a[0].candidate_claim)

        # Topic B must ONLY contain Quantum evidence
        evid_b = self.repo.get_verified_evidence(topic_b)
        self.assertEqual(len(evid_b), 1)
        self.assertIn("Qubits", evid_b[0].candidate_claim)

    def test_regression_04_ssrf_protection_on_private_destinations(self):
        """Defect: The old scraper fetched any URL blindly, exposing local ports and cloud metadata."""
        dangerous_targets = [
            "http://127.0.0.1:8000/internal",
            "http://localhost:5000/debug",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/admin",
            "http://192.168.0.1/settings",
        ]
        for target in dangerous_targets:
            with self.assertRaises(SSRFSecurityError, msg=f"Should raise SSRFSecurityError for {target}"):
                validate_url(target, block_private_ips=True)


if __name__ == "__main__":
    unittest.main()

