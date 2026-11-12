"""Strict Programmatic Citation and Evidence Validator.

Verifies that every cited evidence ID exists, belongs to the current research run,
has passed quote and support verification, and is traceable to original source text.
Rejects unverified or cross-run citations.
"""

import logging
from typing import Dict, List, Set, Tuple
from research_engine.database.models import EvidenceRecord, SourceRecord
from research_engine.database.repository import ResearchRepository
from research_engine.synthesis.report_synthesizer import StructuredReportPayload, SynthesizedStatement

logger = logging.getLogger("research_engine.reporting.validator")


class CitationValidationResult:
    """Detailed result of report citation verification."""

    def __init__(self):
        self.total_statements: int = 0
        self.verified_statements: int = 0
        self.unverified_statements: int = 0
        self.total_citations: int = 0
        self.valid_citations: int = 0
        self.invalid_citations: int = 0
        self.errors: List[str] = []
        self.validated_evidence_ids: Set[str] = set()

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0 and self.unverified_statements == 0


class ReportCitationValidator:
    """Enforces strict fail-closed citation verification on synthesized reports."""

    def __init__(self, repository: ResearchRepository):
        self.repo = repository

    def validate_report(
        self,
        run_id: str,
        report_payload: StructuredReportPayload
    ) -> Tuple[StructuredReportPayload, CitationValidationResult]:
        """Validate every citation in the report against the database evidence ledger.
        
        Returns:
            (sanitized_report_payload, validation_result)
        """
        result = CitationValidationResult()

        # Load all verified evidence for this run
        verified_evidence_list = self.repo.get_verified_evidence(run_id)
        verified_evidence_map: Dict[str, EvidenceRecord] = {e.id: e for e in verified_evidence_list}

        sources_list = self.repo.get_sources_for_run(run_id)
        sources_map: Dict[int, SourceRecord] = {s.id: s for s in sources_list if s.id is not None}

        # Helper to validate a statement
        def check_statement(stmt: SynthesizedStatement, section_name: str) -> SynthesizedStatement:
            result.total_statements += 1
            valid_eids: List[str] = []

            if not stmt.cited_evidence_ids:
                msg = f"[{section_name}] Statement lacks any evidence citation: '{stmt.statement[:60]}...'"
                result.errors.append(msg)
                result.unverified_statements += 1
                # Label statement as unverified
                stmt.statement = f"[UNVERIFIED] {stmt.statement}"
                return stmt

            for eid in stmt.cited_evidence_ids:
                result.total_citations += 1
                evid = verified_evidence_map.get(eid)

                if not evid:
                    # Check if evidence exists in database but under a different run
                    other_evid = self.repo.get_evidence_by_id(eid, run_id=None)
                    if other_evid and other_evid.run_id != run_id:
                        result.errors.append(
                            f"Cross-run contamination detected! Evidence [{eid}] belongs to run '{other_evid.run_id}', not '{run_id}'."
                        )
                    else:
                        result.errors.append(f"Nonexistent or unverified evidence ID [{eid}] cited in '{stmt.statement[:40]}'.")
                    result.invalid_citations += 1
                    continue

                # Ensure source exists
                src = sources_map.get(evid.source_id)
                if not src:
                    result.errors.append(f"Evidence [{eid}] refers to nonexistent Source #{evid.source_id}.")
                    result.invalid_citations += 1
                    continue

                # Citation passed all checks
                valid_eids.append(eid)
                result.valid_citations += 1
                result.validated_evidence_ids.add(eid)

            if valid_eids:
                result.verified_statements += 1
                stmt.cited_evidence_ids = valid_eids
            else:
                result.unverified_statements += 1
                stmt.statement = f"[UNVERIFIED - INVALID CITATION] {stmt.statement}"
                stmt.cited_evidence_ids = []

            return stmt

        # Validate executive summary
        for stmt in report_payload.executive_summary:
            check_statement(stmt, "Executive Summary")

        # Validate key findings
        for stmt in report_payload.key_findings:
            check_statement(stmt, "Key Findings")

        # Validate detailed sections
        for section in report_payload.detailed_sections:
            for stmt in section.statements:
                check_statement(stmt, section.section_title)

        # Validate community experiences
        for stmt in report_payload.community_experiences:
            check_statement(stmt, "Community Experiences")

        # Validate complaints
        for stmt in report_payload.complaints_and_risks:
            check_statement(stmt, "Complaints & Risks")

        # Validate contradictions
        for stmt in report_payload.contradictions_disagreements:
            check_statement(stmt, "Contradictions")

        logger.info(
            f"Report Citation Validation for Run [{run_id}]: "
            f"{result.valid_citations}/{result.total_citations} valid citations, "
            f"{result.verified_statements}/{result.total_statements} verified statements."
        )

        return report_payload, result
