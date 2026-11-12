"""Corroboration and contradiction engine.

Clusters verified evidence across independent sources, detects contradictions,
prevents syndicated/mirrored duplicates from counting as independent corroboration,
and categorizes claims into documented, corroborated, single-source, community, and disputed.
"""

import hashlib
import logging
import uuid
from typing import Dict, List, Set, Tuple

from research_engine.database.models import ClaimRecord, ContradictionRecord, EvidenceRecord, SourceRecord
from research_engine.database.repository import ResearchRepository

logger = logging.getLogger("research_engine.synthesis.corroboration")


class CorroborationEngine:
    """Processes verified evidence into clusters, counts independent sources, and identifies contradictions."""

    def __init__(self, repository: ResearchRepository):
        self.repo = repository

    def _are_sources_independent(self, source_a: SourceRecord, source_b: SourceRecord) -> bool:
        """Check if two sources are truly independent (different domain, different content hash)."""
        if source_a.id == source_b.id:
            return False
        # If domains are identical, not independent
        if source_a.domain.lower() == source_b.domain.lower():
            return False
        # If content hashes are identical (mirrored / syndicated content), not independent
        if source_a.content_hash and source_b.content_hash and source_a.content_hash == source_b.content_hash:
            return False
        return True

    def process_corroboration_and_claims(
        self,
        run_id: str
    ) -> Tuple[List[ClaimRecord], List[ContradictionRecord]]:
        """Cluster verified evidence for a run and synthesize claims and contradictions."""
        verified_evidence = self.repo.get_verified_evidence(run_id)
        if not verified_evidence:
            return [], []

        sources_map: Dict[int, SourceRecord] = {
            s.id: s for s in self.repo.get_sources_for_run(run_id) if s.id is not None
        }

        # Step 1: Cluster evidence items by topic similarity / keyword overlap
        clusters: List[List[EvidenceRecord]] = []
        for evid in verified_evidence:
            placed = False
            evid_words = set(evid.candidate_claim.lower().split())

            for cluster in clusters:
                # Check lexical overlap with cluster representative
                rep_words = set(cluster[0].candidate_claim.lower().split())
                intersection = evid_words.intersection(rep_words)
                union = evid_words.union(rep_words)
                jaccard = len(intersection) / len(union) if union else 0.0

                if jaccard > 0.35:  # Sufficient topical overlap
                    cluster.append(evid)
                    placed = True
                    break

            if not placed:
                clusters.append([evid])

        claims_list: List[ClaimRecord] = []
        contradictions_list: List[ContradictionRecord] = []

        # Step 2: Evaluate each cluster for independent corroboration and contradictions
        for idx, cluster in enumerate(clusters, 1):
            cluster_id = f"claim-{run_id[:8]}-{idx:03d}"
            rep_evidence = cluster[0]

            # Count independent domains
            domains_in_cluster: Set[str] = set()
            content_hashes_in_cluster: Set[str] = set()
            independent_sources = 0

            for item in cluster:
                src = sources_map.get(item.source_id)
                if src:
                    domain = src.domain.lower()
                    c_hash = src.content_hash
                    if domain not in domains_in_cluster and (not c_hash or c_hash not in content_hashes_in_cluster):
                        domains_in_cluster.add(domain)
                        if c_hash:
                            content_hashes_in_cluster.add(c_hash)
                        independent_sources += 1

            # Check for contradiction within the cluster
            has_contradiction = False
            for i in range(len(cluster)):
                for j in range(i + 1, len(cluster)):
                    e_a = cluster[i]
                    e_b = cluster[j]

                    # Negative vs positive indicator check or contradicting verification
                    claim_a_lower = e_a.candidate_claim.lower()
                    claim_b_lower = e_b.candidate_claim.lower()

                    opposing_indicators = (
                        ("faster", "slower"),
                        ("increase", "decrease"),
                        ("support", "unsupported"),
                        ("secure", "vulnerable"),
                        ("free", "paid"),
                        ("works", "fails"),
                    )

                    is_contradictory = False
                    for pos_word, neg_word in opposing_indicators:
                        if (pos_word in claim_a_lower and neg_word in claim_b_lower) or \
                           (neg_word in claim_a_lower and pos_word in claim_b_lower):
                            is_contradictory = True
                            break

                    if is_contradictory:
                        has_contradiction = True
                        contra_id = f"contra-{uuid.uuid4().hex[:8]}"
                        contra = ContradictionRecord(
                            id=contra_id,
                            run_id=run_id,
                            claim_a_id=cluster_id,
                            claim_b_id=cluster_id,
                            evidence_a_id=e_a.id,
                            evidence_b_id=e_b.id,
                            description=(
                                f"Contradiction detected on '{rep_evidence.candidate_claim[:80]}': "
                                f"[{e_a.id}] asserts '{e_a.candidate_claim}' while "
                                f"[{e_b.id}] asserts '{e_b.candidate_claim}'."
                            ),
                            topic_facet=rep_evidence.claim_type
                        )
                        contradictions_list.append(contra)
                        self.repo.record_contradiction(contra)

            # Determine claim category
            if has_contradiction:
                category = "disputed"
            elif rep_evidence.claim_type == "company_claim" or rep_evidence.evidence_type == "corporate_pr":
                category = "company_claim"
            elif rep_evidence.evidence_type == "self_reported" or rep_evidence.claim_type in ("opinion", "user_experience"):
                category = "community_experience"
            elif independent_sources >= 2:
                category = "independently_corroborated"
            elif rep_evidence.source_id and sources_map.get(rep_evidence.source_id, SourceRecord(run_id=run_id, url="", canonical_url="", domain="")).source_tier == "Tier A":
                category = "directly_documented"
            else:
                category = "single_source"

            claim_record = ClaimRecord(
                id=cluster_id,
                run_id=run_id,
                cluster_title=rep_evidence.candidate_claim[:100],
                claim_text=rep_evidence.candidate_claim,
                claim_category=category,
                independent_sources_count=independent_sources,
                has_contradictions=has_contradiction,
                status="active"
            )

            # Link evidence items to the claim
            evidence_links = [(item.id, "supports") for item in cluster]
            self.repo.save_claim(claim_record, evidence_links)
            claims_list.append(claim_record)

        logger.info(
            f"Corroboration engine synthesized {len(claims_list)} claims "
            f"and {len(contradictions_list)} contradictions from {len(verified_evidence)} verified evidence items."
        )

        return claims_list, contradictions_list

