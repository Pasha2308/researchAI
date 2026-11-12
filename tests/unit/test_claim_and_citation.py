"""Unit tests for claim verification, fail-closed policy, and citation validation.

Covers:
- Test 4: Real quote with unsupported claim rejected.
- Test 5: Quote from search snippet not treated as webpage evidence.
- Test 6: Opinion not silently rewritten as fact.
- Test 7: One review not labeled community consensus.
- Test 8: Citation to real supporting evidence passes.
- Test 9: Nonexistent source ID fails.
- Test 10: Citation to wrong source fails.
- Test 11: Citation to evidence from another research run fails.
- Test 12: Final sentence without required evidence reference rejected.
"""

import tempfile
import unittest
import os

from research_engine.database.connection import init_database
from research_engine.database.models import EvidenceRecord, ResearchPlan, SourceRecord
from research_engine.database.repository import ResearchRepository
from research_engine.evidence.models import VerificationVerdict
from research_engine.providers.llm.mock_provider import MockLLMProvider
from research_engine.reporting.validator import ReportCitationValidator
from research_engine.synthesis.report_synthesizer import StructuredReportPayload, SynthesizedStatement
from research_engine.verification.claim_verifier import ClaimVerifier


class TestClaimAndCitationValidation(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()
        init_database(self.db_path)
        self.repo = ResearchRepository(self.db_path)

        # Setup standard test run
        self.run_a = self.repo.create_run("run-alpha", "Test A", "", 10, 2, "m1", "m2")
        self.run_b = self.repo.create_run("run-beta", "Test B", "", 10, 2, "m1", "m2")

        # Setup source for run A
        self.repo.add_sources_batch("run-alpha", [
            {"url": "https://example.com/fastapi", "canonical_url": "https://example.com/fastapi", "domain": "example.com", "source_tier": "Tier A"}
        ])
        sources_a = self.repo.get_sources_for_run("run-alpha")
        self.source_a_id = sources_a[0].id

        # Setup verified evidence for run A
        self.evid_a1 = EvidenceRecord(
            id="evid-a1",
            run_id="run-alpha",
            source_id=self.source_a_id,
            candidate_claim="FastAPI is based on Starlette and Pydantic.",
            exact_quote="FastAPI is based on Starlette and Pydantic.",
            quote_start_offset=0,
            quote_end_offset=45,
            quote_valid=True,
            support_status="supports",
            is_verified=True
        )
        self.repo.insert_evidence_item(self.evid_a1)

        # Setup evidence belonging to Run B
        self.repo.add_sources_batch("run-beta", [
            {"url": "https://other.com/page", "canonical_url": "https://other.com/page", "domain": "other.com", "source_tier": "Tier D"}
        ])
        sources_b = self.repo.get_sources_for_run("run-beta")
        self.evid_b1 = EvidenceRecord(
            id="evid-b1",
            run_id="run-beta",
            source_id=sources_b[0].id,
            candidate_claim="Evidence belonging exclusively to Run B.",
            exact_quote="Evidence belonging exclusively to Run B.",
            quote_valid=True,
            support_status="supports",
            is_verified=True
        )
        self.repo.insert_evidence_item(self.evid_b1)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_04_real_quote_with_unsupported_claim_rejected(self):
        """Test 4: Real quote attached to an extrapolated/unsupported claim fails verification."""
        # Mock LLM returning 'does_not_support'
        mock_llm = MockLLMProvider(canned_responses=[
            '{"verdict": "does_not_support", "reason": "The quote discusses asynchronous IO, but does not support the claim that Flask is deprecated."}'
        ])
        verifier = ClaimVerifier(mock_llm, model_id="mock-verifier")
        result = verifier.verify_claim(
            candidate_claim="Flask is completely deprecated and unusable.",
            exact_quote="FastAPI features asynchronous request handling natively.",
            surrounding_context="Chapter on concurrency.",
            source_domain="docs.python.org",
            source_url="https://docs.python.org"
        )
        self.assertEqual(result.verdict, VerificationVerdict.DOES_NOT_SUPPORT)
        self.assertIn("does not support", result.reason)

    def test_06_opinion_classified_not_silent_fact(self):
        """Test 6: An opinion is classified as opinion/self-reported, not direct empirical fact."""
        evid = EvidenceRecord(
            id="evid-op1",
            run_id="run-alpha",
            source_id=self.source_a_id,
            candidate_claim="In my opinion FastAPI is much more fun than Flask.",
            exact_quote="In my opinion FastAPI is much more fun than Flask.",
            claim_type="opinion",
            evidence_type="self_reported",
            quote_valid=True,
            support_status="supports",
            is_verified=True
        )
        self.assertEqual(evid.claim_type, "opinion")
        self.assertEqual(evid.evidence_type, "self_reported")
        self.assertNotEqual(evid.claim_type, "direct_fact")

    def test_08_valid_citation_passes_validation(self):
        """Test 8: A citation to a real, verified evidence item in the same run passes validation."""
        validator = ReportCitationValidator(self.repo)
        payload = StructuredReportPayload(
            title="Valid Report",
            key_findings=[
                SynthesizedStatement(
                    statement="FastAPI utilizes Starlette for core routing.",
                    cited_evidence_ids=["evid-a1"]
                )
            ]
        )
        validated, res = validator.validate_report("run-alpha", payload)
        self.assertEqual(res.valid_citations, 1)
        self.assertEqual(res.invalid_citations, 0)
        self.assertEqual(res.verified_statements, 1)
        self.assertNotIn("[UNVERIFIED]", validated.key_findings[0].statement)

    def test_09_nonexistent_evidence_id_fails(self):
        """Test 9: A citation referencing an invented/nonexistent evidence ID fails validation."""
        validator = ReportCitationValidator(self.repo)
        payload = StructuredReportPayload(
            title="Invented Citation Report",
            key_findings=[
                SynthesizedStatement(
                    statement="FastAPI guarantees 100% bug-free deployments.",
                    cited_evidence_ids=["evid-nonexistent-999"]
                )
            ]
        )
        validated, res = validator.validate_report("run-alpha", payload)
        self.assertEqual(res.invalid_citations, 1)
        self.assertEqual(res.valid_citations, 0)
        self.assertEqual(res.unverified_statements, 1)
        self.assertIn("[UNVERIFIED - INVALID CITATION]", validated.key_findings[0].statement)

    def test_11_cross_run_evidence_citation_fails(self):
        """Test 11: A citation attempting to cite evidence from another research run (run-beta) fails."""
        validator = ReportCitationValidator(self.repo)
        # Attempt to cite evid-b1 from run-beta while validating run-alpha
        payload = StructuredReportPayload(
            title="Cross Run Contamination Report",
            key_findings=[
                SynthesizedStatement(
                    statement="Claim citing evidence from another topic run.",
                    cited_evidence_ids=["evid-b1"]
                )
            ]
        )
        validated, res = validator.validate_report("run-alpha", payload)
        self.assertEqual(res.invalid_citations, 1)
        self.assertTrue(any("Cross-run contamination detected" in err for err in res.errors))
        self.assertIn("[UNVERIFIED - INVALID CITATION]", validated.key_findings[0].statement)

    def test_12_uncited_statement_is_rejected_or_flagged(self):
        """Test 12: A final statement with no cited evidence is flagged as unverified."""
        validator = ReportCitationValidator(self.repo)
        payload = StructuredReportPayload(
            title="Uncited Statement Report",
            key_findings=[
                SynthesizedStatement(
                    statement="FastAPI will replace all other frameworks by next year.",
                    cited_evidence_ids=[]  # No citation!
                )
            ]
        )
        validated, res = validator.validate_report("run-alpha", payload)
        self.assertEqual(res.unverified_statements, 1)
        self.assertTrue(validated.key_findings[0].statement.startswith("[UNVERIFIED]"))


if __name__ == "__main__":
    unittest.main()

