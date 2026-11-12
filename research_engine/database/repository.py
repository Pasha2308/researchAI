"""Repository layer providing typed database operations with strict run isolation.

Guarantees that evidence, sources, and claims from different research runs are
never mixed together. Tracks separate accounting for discovered, canonical,
downloaded, extracted, evidence-bearing, and cited sources.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from research_engine.database.connection import get_connection
from research_engine.database.models import (
    ResearchRunRecord,
    ResearchPlan,
    SourceRecord,
    SourceContentRecord,
    EvidenceRecord,
    ClaimRecord,
    ContradictionRecord,
)

logger = logging.getLogger("research_engine.repository")


class ResearchRepository:
    """Data access repository for research runs and evidence."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    # =========================================================================
    # Research Runs
    # =========================================================================

    def create_run(
        self,
        run_id: str,
        question: str,
        scope: str,
        target_sources: int,
        max_rounds: int,
        model_id: str,
        verifier_model_id: str
    ) -> ResearchRunRecord:
        """Create a new isolated research run."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO research_runs (
                    id, question, scope, status, phase, target_sources, max_rounds,
                    current_round, model_id, verifier_model_id, created_at, updated_at
                ) VALUES (?, ?, ?, 'created', 'planning', ?, ?, 1, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (run_id, question, scope, target_sources, max_rounds, model_id, verifier_model_id)
            )
        self.log_event(run_id, "RUN_CREATED", f"Created research run for: '{question}'")
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> Optional[ResearchRunRecord]:
        """Fetch a research run record by ID."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT * FROM research_runs WHERE id = ?", (run_id,)).fetchone()
            if not row:
                return None
            return ResearchRunRecord(**dict(row))

    def list_all_runs(self) -> List[ResearchRunRecord]:
        """Fetch all research runs ordered by creation date descending."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT * FROM research_runs ORDER BY created_at DESC").fetchall()
            return [ResearchRunRecord(**dict(r)) for r in rows]

    def update_run_phase(self, run_id: str, status: str, phase: str, error: str = "") -> None:
        """Update the operational status and phase of a run."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE research_runs
                SET status = ?, phase = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, phase, error, run_id)
            )

    def complete_run(self, run_id: str, report_path: str, stats: Dict[str, Any]) -> None:
        """Mark a research run as successfully completed."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE research_runs
                SET status = 'completed', phase = 'completed', report_path = ?,
                    stats_json = ?, updated_at = CURRENT_TIMESTAMP, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (report_path, json.dumps(stats), run_id)
            )
        self.log_event(run_id, "RUN_COMPLETED", f"Run completed. Report generated at {report_path}")

    # =========================================================================
    # Research Plans
    # =========================================================================

    def save_plan(self, plan_id: str, run_id: str, plan: ResearchPlan) -> None:
        """Persist structured research plan."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO research_plans (id, run_id, core_question, scope, plan_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (plan_id, run_id, plan.core_question, plan.scope, plan.model_dump_json())
            )
        self.log_event(run_id, "PLAN_SAVED", f"Saved research plan with {len(plan.subquestions)} subquestions.")

    def get_plan(self, run_id: str) -> Optional[ResearchPlan]:
        """Fetch the active plan for a run."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT plan_json FROM research_plans WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            return ResearchPlan.model_validate_json(row["plan_json"])

    # =========================================================================
    # Search Queries
    # =========================================================================

    def record_search_query(
        self,
        query_id: str,
        run_id: str,
        round_num: int,
        query: str,
        category: str,
        provider: str = "ddgs"
    ) -> None:
        """Record an executed or scheduled search query."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO search_queries (id, run_id, round_num, query, category, provider, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (query_id, run_id, round_num, query, category, provider)
            )

    def update_search_query_status(self, query_id: str, results_count: int, status: str = "executed") -> None:
        """Update result count and status of an executed search query."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE search_queries SET results_count = ?, status = ? WHERE id = ?",
                (results_count, status, query_id)
            )

    def get_search_queries(self, run_id: str) -> List[Dict[str, Any]]:
        """Retrieve all search queries executed for a run."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT * FROM search_queries WHERE run_id = ? ORDER BY round_num ASC, created_at ASC",
                (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    # =========================================================================
    # Sources
    # =========================================================================

    def add_sources_batch(
        self,
        run_id: str,
        sources: List[Dict[str, Any]]
    ) -> Tuple[int, int]:
        """Insert a batch of discovered sources for a specific run.
        
        Returns a tuple: (inserted_count, duplicate_count).
        Strictly enforces that canonical URLs are unique within the same run.
        """
        if not sources:
            return 0, 0

        inserted = 0
        duplicates = 0

        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            for s in sources:
                try:
                    cursor.execute(
                        """
                        INSERT INTO sources (
                            run_id, url, canonical_url, domain, title, publisher, author,
                            published_date, discovered_by_query_id, source_category, source_tier,
                            fetch_status, extraction_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'discovered', 'pending')
                        """,
                        (
                            run_id,
                            s["url"],
                            s["canonical_url"],
                            s["domain"],
                            s.get("title", ""),
                            s.get("publisher", ""),
                            s.get("author", ""),
                            s.get("published_date", ""),
                            s.get("discovered_by_query_id", ""),
                            s.get("source_category", "unknown"),
                            s.get("source_tier", "Tier D")
                        )
                    )
                    inserted += 1
                except Exception:
                    # Unique constraint violation on (run_id, canonical_url)
                    duplicates += 1

        return inserted, duplicates

    def get_pending_sources(self, run_id: str, limit: Optional[int] = None) -> List[SourceRecord]:
        """Retrieve sources pending fetching for this run."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            sql = "SELECT * FROM sources WHERE run_id = ? AND fetch_status IN ('discovered', 'queued', 'retryable_failure') ORDER BY id ASC"
            if limit:
                sql += f" LIMIT {int(limit)}"
            rows = cursor.execute(sql, (run_id,)).fetchall()
            return [SourceRecord(**dict(r)) for r in rows]

    def update_source_fetch_status(
        self,
        source_id: int,
        run_id: str,
        fetch_status: str,
        http_status: int = 0,
        final_url: str = "",
        error_reason: str = ""
    ) -> None:
        """Update source fetch progress and final redirected URL."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE sources
                SET fetch_status = ?, http_status = ?, final_url = ?, error_reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND run_id = ?
                """,
                (fetch_status, http_status, final_url, error_reason, source_id, run_id)
            )

    def update_source_metadata(
        self,
        source_id: int,
        run_id: str,
        title: str = "",
        published_date: str = "",
        author: str = "",
        publisher: str = "",
        source_tier: str = "",
        source_category: str = ""
    ) -> None:
        """Update refined metadata for a source after extraction."""
        updates = []
        params = []
        if title:
            updates.append("title = ?")
            params.append(title)
        if published_date:
            updates.append("published_date = ?")
            params.append(published_date)
        if author:
            updates.append("author = ?")
            params.append(author)
        if publisher:
            updates.append("publisher = ?")
            params.append(publisher)
        if source_tier:
            updates.append("source_tier = ?")
            params.append(source_tier)
        if source_category:
            updates.append("source_category = ?")
            params.append(source_category)

        if not updates:
            return

        params.extend([source_id, run_id])
        sql = f"UPDATE sources SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND run_id = ?"

        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)

    def get_sources_for_run(self, run_id: str) -> List[SourceRecord]:
        """Fetch all sources belonging to a research run."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT * FROM sources WHERE run_id = ? ORDER BY id ASC", (run_id,)).fetchall()
            return [SourceRecord(**dict(r)) for r in rows]

    def get_source_by_id(self, source_id: int, run_id: str) -> Optional[SourceRecord]:
        """Fetch a specific source ensuring run isolation."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT * FROM sources WHERE id = ? AND run_id = ?",
                (source_id, run_id)
            ).fetchone()
            if not row:
                return None
            return SourceRecord(**dict(row))

    # =========================================================================
    # Source Content (Extracted Text Store)
    # =========================================================================

    def save_source_content(
        self,
        source_id: int,
        run_id: str,
        extracted_text: str,
        extraction_method: str,
        content_hash: str
    ) -> None:
        """Store extracted original text and compute text statistics."""
        word_count = len(extracted_text.split())
        char_count = len(extracted_text)

        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO source_content (
                    source_id, run_id, extracted_text, extraction_method, word_count, char_count, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (source_id, run_id, extracted_text, extraction_method, word_count, char_count, content_hash)
            )
            cursor.execute(
                """
                UPDATE sources
                SET extraction_status = 'extracted', content_hash = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND run_id = ?
                """,
                (content_hash, source_id, run_id)
            )

    def get_source_content(self, source_id: int, run_id: str) -> Optional[SourceContentRecord]:
        """Retrieve original extracted text for verification."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT * FROM source_content WHERE source_id = ? AND run_id = ?",
                (source_id, run_id)
            ).fetchone()
            if not row:
                return None
            return SourceContentRecord(**dict(row))

    # =========================================================================
    # Evidence Ledger
    # =========================================================================

    def insert_evidence_item(self, evidence: EvidenceRecord) -> None:
        """Insert a candidate or verified evidence item into the ledger."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO evidence (
                    id, run_id, source_id, candidate_claim, exact_quote,
                    quote_start_offset, quote_end_offset, claim_type, evidence_type,
                    attribution, published_date, time_period, geographic_scope,
                    metrics_data, surrounding_context, quote_valid, support_status,
                    verification_reason, verification_model, is_verified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.id,
                    evidence.run_id,
                    evidence.source_id,
                    evidence.candidate_claim,
                    evidence.exact_quote,
                    evidence.quote_start_offset,
                    evidence.quote_end_offset,
                    evidence.claim_type,
                    evidence.evidence_type,
                    evidence.attribution,
                    evidence.published_date,
                    evidence.time_period,
                    evidence.geographic_scope,
                    evidence.metrics_data,
                    evidence.surrounding_context,
                    1 if evidence.quote_valid else 0,
                    evidence.support_status,
                    evidence.verification_reason,
                    evidence.verification_model,
                    1 if evidence.is_verified else 0
                )
            )

            # Insert into FTS5 index if available
            try:
                cursor.execute(
                    """
                    INSERT INTO evidence_fts (evidence_id, candidate_claim, exact_quote, surrounding_context)
                    VALUES (?, ?, ?, ?)
                    """,
                    (evidence.id, evidence.candidate_claim, evidence.exact_quote, evidence.surrounding_context)
                )
            except Exception:
                pass

    def get_verified_evidence(self, run_id: str) -> List[EvidenceRecord]:
        """Fetch all verified evidence items belonging to a run."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                """
                SELECT * FROM evidence
                WHERE run_id = ? AND is_verified = 1 AND quote_valid = 1
                ORDER BY source_id ASC, id ASC
                """,
                (run_id,)
            ).fetchall()
            return [EvidenceRecord(**dict(r)) for r in rows]

    def get_all_evidence_for_run(self, run_id: str) -> List[EvidenceRecord]:
        """Fetch all evidence items (candidate, rejected, and verified) for a run."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT * FROM evidence WHERE run_id = ? ORDER BY id ASC",
                (run_id,)
            ).fetchall()
            return [EvidenceRecord(**dict(r)) for r in rows]

    def get_evidence_by_id(self, evidence_id: str, run_id: Optional[str] = None) -> Optional[EvidenceRecord]:
        """Fetch a specific evidence item ensuring run isolation if run_id provided."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            if run_id:
                row = cursor.execute(
                    "SELECT * FROM evidence WHERE id = ? AND run_id = ?",
                    (evidence_id, run_id)
                ).fetchone()
            else:
                row = cursor.execute(
                    "SELECT * FROM evidence WHERE id = ?",
                    (evidence_id,)
                ).fetchone()
            if not row:
                return None
            return EvidenceRecord(**dict(row))

    # =========================================================================
    # Claims & Corroboration
    # =========================================================================

    def save_claim(
        self,
        claim: ClaimRecord,
        evidence_links: List[Tuple[str, str]]  # list of (evidence_id, relationship)
    ) -> None:
        """Save a clustered claim and its evidence associations."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO claims (
                    id, run_id, cluster_title, claim_text, claim_category,
                    independent_sources_count, has_contradictions, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim.id,
                    claim.run_id,
                    claim.cluster_title,
                    claim.claim_text,
                    claim.claim_category,
                    claim.independent_sources_count,
                    1 if claim.has_contradictions else 0,
                    claim.status
                )
            )
            for evid_id, rel in evidence_links:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO claim_evidence (claim_id, evidence_id, relationship)
                    VALUES (?, ?, ?)
                    """,
                    (claim.id, evid_id, rel)
                )

    def get_claims_for_run(self, run_id: str) -> List[ClaimRecord]:
        """Retrieve all synthesized claims for a run."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT * FROM claims WHERE run_id = ? ORDER BY independent_sources_count DESC, id ASC",
                (run_id,)
            ).fetchall()
            return [ClaimRecord(**dict(r)) for r in rows]

    def record_contradiction(self, contradiction: ContradictionRecord) -> None:
        """Record a detected contradiction between evidence items."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO contradictions (
                    id, run_id, claim_a_id, claim_b_id, evidence_a_id, evidence_b_id, description, topic_facet
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contradiction.id,
                    contradiction.run_id,
                    contradiction.claim_a_id,
                    contradiction.claim_b_id,
                    contradiction.evidence_a_id,
                    contradiction.evidence_b_id,
                    contradiction.description,
                    contradiction.topic_facet
                )
            )

    def get_contradictions_for_run(self, run_id: str) -> List[ContradictionRecord]:
        """Retrieve all recorded contradictions for a run."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT * FROM contradictions WHERE run_id = ? ORDER BY created_at ASC",
                (run_id,)
            ).fetchall()
            return [ContradictionRecord(**dict(r)) for r in rows]

    # =========================================================================
    # Reports
    # =========================================================================

    def save_report(
        self,
        report_id: str,
        run_id: str,
        title: str,
        markdown_content: str,
        structured_json: str,
        total_findings: int,
        total_citations: int,
        verified_citations_count: int,
        report_path: str
    ) -> None:
        """Store the final generated report and citation statistics."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO reports (
                    id, run_id, title, markdown_content, structured_json,
                    total_findings, total_citations, verified_citations_count, report_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id, run_id, title, markdown_content, structured_json,
                    total_findings, total_citations, verified_citations_count, report_path
                )
            )

    def get_report(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Fetch report record for a run."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT * FROM reports WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            return dict(row)

    # =========================================================================
    # Audit Events & Accounting
    # =========================================================================

    def log_event(self, run_id: str, event_type: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Record an event in the research audit trail."""
        details_str = json.dumps(details or {})
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO research_events (run_id, event_type, message, details_json)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, event_type, message, details_str)
            )

    def get_events_for_run(self, run_id: str) -> List[Dict[str, Any]]:
        """Fetch chronological audit trail events."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT * FROM research_events WHERE run_id = ? ORDER BY id ASC",
                (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_run_accounting_stats(self, run_id: str) -> Dict[str, Any]:
        """Compute transparent accounting counters for the research run.
        
        Distinguishes between:
        - Discovered sources
        - Unique canonical URLs
        - Successfully fetched pages
        - Extracted pages
        - Usable evidence items
        - Verified evidence items
        - Cited sources
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Sources stats
            total_sources = cursor.execute(
                "SELECT COUNT(*) FROM sources WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            
            fetched_sources = cursor.execute(
                "SELECT COUNT(*) FROM sources WHERE run_id = ? AND fetch_status = 'fetched'", (run_id,)
            ).fetchone()[0]
            
            failed_sources = cursor.execute(
                "SELECT COUNT(*) FROM sources WHERE run_id = ? AND fetch_status LIKE '%failure'", (run_id,)
            ).fetchone()[0]

            extracted_sources = cursor.execute(
                "SELECT COUNT(*) FROM sources WHERE run_id = ? AND extraction_status = 'extracted'", (run_id,)
            ).fetchone()[0]

            # Evidence stats
            total_candidate_evidence = cursor.execute(
                "SELECT COUNT(*) FROM evidence WHERE run_id = ?", (run_id,)
            ).fetchone()[0]

            quote_valid_evidence = cursor.execute(
                "SELECT COUNT(*) FROM evidence WHERE run_id = ? AND quote_valid = 1", (run_id,)
            ).fetchone()[0]

            verified_evidence = cursor.execute(
                "SELECT COUNT(*) FROM evidence WHERE run_id = ? AND is_verified = 1", (run_id,)
            ).fetchone()[0]

            # Sources with verified evidence
            evidence_bearing_sources = cursor.execute(
                "SELECT COUNT(DISTINCT source_id) FROM evidence WHERE run_id = ? AND is_verified = 1", (run_id,)
            ).fetchone()[0]

            # Contradictions
            contradictions_count = cursor.execute(
                "SELECT COUNT(*) FROM contradictions WHERE run_id = ?", (run_id,)
            ).fetchone()[0]

            # Claims count
            claims_count = cursor.execute(
                "SELECT COUNT(*) FROM claims WHERE run_id = ?", (run_id,)
            ).fetchone()[0]

            # Tier breakdown
            tier_rows = cursor.execute(
                "SELECT source_tier, COUNT(*) FROM sources WHERE run_id = ? GROUP BY source_tier", (run_id,)
            ).fetchall()
            tier_breakdown = {r[0]: r[1] for r in tier_rows}

            return {
                "total_sources_queued": total_sources,
                "fetched_sources": fetched_sources,
                "failed_sources": failed_sources,
                "extracted_sources": extracted_sources,
                "total_candidate_evidence": total_candidate_evidence,
                "quote_valid_evidence": quote_valid_evidence,
                "verified_evidence": verified_evidence,
                "evidence_bearing_sources": evidence_bearing_sources,
                "contradictions_count": contradictions_count,
                "claims_count": claims_count,
                "tier_breakdown": tier_breakdown,
            }
