"""Master Multi-Round Research Orchestrator.

Coordinates planning, search discovery across multiple providers, SSRF-safe page retrieval,
deterministic exact quote verification, fail-closed claim support auditing,
iterative gap-driven search rounds, and citation-validated report synthesis.
"""

import gc
import json
import logging
import os
import re
import time
import urllib.parse
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from config import settings
from research_engine.database.connection import init_database
from research_engine.database.models import (
    EvidenceRecord,
    ResearchPlan,
    ResearchRunRecord,
    SourceRecord,
)
from research_engine.database.repository import ResearchRepository
from research_engine.evidence.extractor import EvidenceExtractor
from research_engine.evidence.models import CandidateEvidence, VerificationVerdict
from research_engine.evidence.validator import validate_exact_quote
from research_engine.extractors.page_extractor import ExtractedPage, PageExtractor
from research_engine.fetchers.safe_fetcher import FetchError, SafeHTTPFetcher
from research_engine.security.ssrf import SSRFSecurityError
from research_engine.providers.llm.base import BaseLLMProvider
from research_engine.providers.search.arxiv import ArxivSearchProvider
from research_engine.providers.search.base import BaseSearchProvider, SearchResult
from research_engine.providers.search.ddgs_provider import DDGSSearchProvider
from research_engine.providers.search.hackernews import HackerNewsSearchProvider
from research_engine.providers.search.openalex import OpenAlexSearchProvider
from research_engine.reporting.markdown_renderer import MarkdownReportRenderer
from research_engine.reporting.validator import ReportCitationValidator
from research_engine.research.gap_detector import GapDetector, ResearchGap
from research_engine.research.planner import ResearchPlanner
from research_engine.synthesis.corroboration import CorroborationEngine
from research_engine.synthesis.report_synthesizer import ReportSynthesizer
from research_engine.verification.claim_verifier import ClaimVerifier

logger = logging.getLogger("research_engine.orchestrator")


class ResearchOrchestrator:
    """End-to-end evidence-first research pipeline coordinator."""

    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        verifier_llm_provider: Optional[BaseLLMProvider] = None,
        repository: Optional[ResearchRepository] = None,
        db_path: Optional[str] = None
    ):
        init_database(db_path)
        self.repo = repository or ResearchRepository(db_path)
        self.llm = llm_provider
        self.verifier_llm = verifier_llm_provider or llm_provider

        # Modules
        self.planner = ResearchPlanner(self.llm, self.repo, model_id=settings.groq_model)
        self.fetcher = SafeHTTPFetcher()
        self.extractor = PageExtractor(enable_jina_fallback=settings.enable_jina_fallback)
        self.evidence_extractor = EvidenceExtractor(self.llm, model_id=settings.groq_model)
        self.claim_verifier = ClaimVerifier(self.verifier_llm, model_id=settings.groq_verifier_model)
        self.gap_detector = GapDetector(self.repo)
        self.corroboration_engine = CorroborationEngine(self.repo)
        self.synthesizer = ReportSynthesizer(self.llm, self.repo, model_id=settings.groq_model)
        self.citation_validator = ReportCitationValidator(self.repo)
        self.renderer = MarkdownReportRenderer(self.repo)

        # Search providers
        self.search_providers: List[BaseSearchProvider] = []
        if settings.enable_ddgs:
            self.search_providers.append(
                DDGSSearchProvider(region=settings.search_region, recency=settings.search_recency)
            )
        if settings.enable_hackernews:
            self.search_providers.append(HackerNewsSearchProvider())
        if settings.enable_openalex:
            self.search_providers.append(OpenAlexSearchProvider())
        if settings.enable_arxiv:
            self.search_providers.append(ArxivSearchProvider())

        # Active research question keywords for context-aware reference filtering
        self._active_question_keywords: Set[str] = set()

        # Active research question (set at run start for context-aware reference filtering)
        self._active_question_keywords: Set[str] = set()

    # =========================================================================
    # URL Cleaning & Canonicalization
    # =========================================================================

    def canonicalize_url(self, raw_url: str) -> Optional[str]:
        """Normalize URL by stripping tracking parameters, hash anchors, and trailing slashes."""
        if not raw_url or not isinstance(raw_url, str):
            return None
        cleaned = raw_url.strip()
        if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
            return None
        try:
            parsed = urllib.parse.urlsplit(cleaned)
            query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
            filtered = {
                k: v for k, v in query_params.items()
                if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref", "source"))
            }
            clean_query = urllib.parse.urlencode(filtered, doseq=True)
            canonical = urllib.parse.urlunsplit((
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path.rstrip("/"),
                clean_query,
                ""  # Fragment dropped
            ))
            return canonical
        except Exception:
            return None

    # =========================================================================
    # Execution Lifecycle
    # =========================================================================

    def run_research(
        self,
        question: str,
        scope: str = "",
        target_sources: int = settings.default_target_sources,
        max_rounds: int = settings.max_rounds_default if hasattr(settings, "max_rounds_default") else settings.max_research_rounds,
        output_report_path: Optional[str] = None,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ) -> str:
        """Execute a complete autonomous research run from question to cited report."""
        run_id = f"run-{uuid.uuid4().hex[:10]}"
        logger.info(f"Initiating Research Run [{run_id}]: '{question}'")

        def notify(phase: str, data: Dict[str, Any]):
            if progress_callback:
                progress_callback(phase, data)

        # Extract core keywords from the question for reference filtering
        # (strip stop words and keep substantive tokens of 3+ chars)
        _stop_words = {"what", "who", "are", "the", "and", "how", "does", "have",
                       "its", "for", "with", "from", "that", "this", "into", "their"}
        self._active_question_keywords = {
            w.lower().strip("?,.:;'\"") for w in question.split()
            if len(w) >= 3 and w.lower() not in _stop_words
        }
        logger.debug(f"Active question keywords for reference filtering: {self._active_question_keywords}")

        # 0. Initialize run record
        self.repo.create_run(
            run_id=run_id,
            question=question,
            scope=scope,
            target_sources=target_sources,
            max_rounds=max_rounds,
            model_id=settings.groq_model,
            verifier_model_id=settings.groq_verifier_model
        )

        try:
            # 1. Planning Phase
            notify("planning", {"message": "Generating structured research plan..."})
            self.repo.update_run_phase(run_id, status="planning", phase="planning")
            plan = self.planner.create_plan(run_id, question, scope)

            current_round = 1
            while current_round <= max_rounds:
                logger.info(f"=== Beginning Research Round {current_round}/{max_rounds} ===")
                self.repo.update_run_phase(run_id, status="searching", phase=f"round_{current_round}_search")

                # 2. Search Discovery
                notify("searching", {"round": current_round, "message": f"Searching providers (Round {current_round})..."})
                queries = self._plan_queries_for_round(run_id, current_round, plan, question)
                discovered = self._execute_search_queries(run_id, current_round, queries)

                # Filter & ingest into database with per-domain limits
                inserted, duplicates = self._ingest_search_results(run_id, discovered)
                logger.info(f"Round {current_round} discovery: {len(discovered)} results, {inserted} inserted, {duplicates} duplicate canonical URLs.")

                # 3. Fetching & Content Extraction
                notify("fetching", {"round": current_round, "message": "Fetching and extracting source content..."})
                self.repo.update_run_phase(run_id, status="fetching", phase=f"round_{current_round}_fetching")
                self._process_pending_sources(run_id, notify)

                # 4. Evidence Extraction & Exact Quote Validation
                notify("extracting_evidence", {"round": current_round, "message": "Extracting candidate evidence and validating quotes..."})
                self.repo.update_run_phase(run_id, status="extracting", phase=f"round_{current_round}_extraction")
                self._extract_and_validate_evidence(run_id, notify)

                # 5. Check if target sources or sufficient evidence reached
                stats = self.repo.get_run_accounting_stats(run_id)
                if stats["evidence_bearing_sources"] >= target_sources:
                    logger.info(f"Target source count reached ({stats['evidence_bearing_sources']}/{target_sources}). Exiting search loop.")
                    break

                # 6. Gap Detection & Targeted Follow-Up
                if current_round < max_rounds:
                    notify("gap_detection", {"round": current_round, "message": "Analyzing research coverage and identifying gaps..."})
                    claims, _ = self.corroboration_engine.process_corroboration_and_claims(run_id)
                    evidence = self.repo.get_verified_evidence(run_id)
                    gaps = self.gap_detector.detect_gaps(run_id, plan, claims, evidence)

                    if not gaps:
                        logger.info("No critical research gaps detected. Concluding search rounds.")
                        break

                current_round += 1

            # 7. Corroboration & Contradiction Processing
            notify("corroborating", {"message": "Clustering evidence, verifying independence, and detecting contradictions..."})
            self.repo.update_run_phase(run_id, status="synthesizing", phase="corroboration")
            final_claims, final_contradictions = self.corroboration_engine.process_corroboration_and_claims(run_id)
            verified_evidence = self.repo.get_verified_evidence(run_id)

            # 8. Report Synthesis
            notify("synthesizing", {"message": "Synthesizing evidence-backed structured report..."})
            raw_report_payload = self.synthesizer.synthesize_report(
                run_id=run_id,
                question=question,
                plan=plan,
                claims=final_claims,
                evidence=verified_evidence,
                contradictions=final_contradictions
            )

            # 9. Strict Programmatic Citation Validation
            notify("validating_citations", {"message": "Running programmatic citation verification against evidence database..."})
            validated_payload, val_result = self.citation_validator.validate_report(run_id, raw_report_payload)

            # 10. Markdown Rendering & Export
            report_markdown = self.renderer.render(run_id, validated_payload, val_result, plan)

            out_path = output_report_path or str(settings.reports_dir / f"research_report_{run_id}.md")
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as fp:
                fp.write(report_markdown)

            final_stats = self.repo.get_run_accounting_stats(run_id)
            self.repo.save_report(
                report_id=f"rep-{run_id}",
                run_id=run_id,
                title=validated_payload.title,
                markdown_content=report_markdown,
                structured_json=validated_payload.model_dump_json(),
                total_findings=len(validated_payload.key_findings),
                total_citations=val_result.total_citations,
                verified_citations_count=val_result.valid_citations,
                report_path=out_path
            )
            self.repo.complete_run(run_id, report_path=out_path, stats=final_stats)

            notify("completed", {"report_path": out_path, "stats": final_stats})
            logger.info(f"Research Run [{run_id}] completed successfully. Report: {out_path}")
            return out_path

        except Exception as e:
            logger.error(f"Research Run [{run_id}] failed: {e}", exc_info=True)
            self.repo.update_run_phase(run_id, status="failed", phase="failed", error=str(e))
            raise

    # =========================================================================
    # Internal Stage Handlers
    # =========================================================================

    def _clean_search_query(self, raw_query: str) -> str:
        """Strip punctuation and redundant filler to keep queries optimal for search engines."""
        if not raw_query:
            return ""
        cleaned = re.sub(r'[,:\'\x22\?\(\)\[\]\{\}]', ' ', raw_query)
        words = [w.strip() for w in cleaned.split() if w.strip()]
        return " ".join(words[:6])

    def _plan_queries_for_round(
        self,
        run_id: str,
        round_num: int,
        plan: ResearchPlan,
        question: str
    ) -> List[Tuple[str, str]]:
        """Assemble search query list based on round number and research plan."""
        queries: List[Tuple[str, str]] = []

        # Determine concise core entity/topic for query combinations
        core_topic = self._clean_search_query(question.split(":")[0].strip())

        if round_num == 1:
            # Round 1: Broad multi-tier coverage from plan
            queries.append((core_topic or question, "general"))
            for angle in plan.search_angles[:3]:
                queries.append((self._clean_search_query(angle), "independent_analysis"))
            for subq in plan.subquestions[:3]:
                clean_subq = subq.rstrip("?").replace("What are ", "").replace("Who are ", "").replace("What is ", "").strip()
                queries.append((self._clean_search_query(clean_subq), "primary"))
            for comm in plan.community_source_targets[:2]:
                queries.append((self._clean_search_query(f"{core_topic} {comm}"), "community"))
            for counter in plan.counterargument_targets[:2]:
                queries.append((self._clean_search_query(f"{core_topic} {counter}"), "opposing"))
        else:
            # Follow-up rounds: Gap-driven queries
            claims = self.repo.get_claims_for_run(run_id)
            evidence = self.repo.get_verified_evidence(run_id)
            gaps = self.gap_detector.detect_gaps(run_id, plan, claims, evidence)
            for gap in gaps[:3]:
                for sq in gap.suggested_queries[:2]:
                    queries.append((self._clean_search_query(sq), "targeted_gap"))

        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for q_str, cat in queries:
            if q_str and q_str.lower() not in seen:
                seen.add(q_str.lower())
                deduped.append((q_str, cat))

        return deduped

    def _is_provider_relevant(self, provider_name: str, category: str, query: str) -> bool:
        """Route queries to appropriate providers based on category and query semantics."""
        p_name = provider_name.lower()
        q_lower = query.lower()

        # DDGS handles everything as broad general web discovery
        if "ddgs" in p_name or "duckduckgo" in p_name:
            return True

        # Hacker News is optimal for tech, startups, community discussions, complaints, and developer experiences
        if "hacker" in p_name or "hn" in p_name:
            if category in ("community", "opposing", "independent_analysis", "user_reviews"):
                return True
            hn_keywords = (
                "startup", "founder", "funding", "pricing", "ai", "llm", "model",
                "tech", "software", "api", "developer", "experience", "complaint",
                "flaw", "limitation", "benchmark", "performance", "show hn", "ask hn"
            )
            return any(k in q_lower for k in hn_keywords)

        # Arxiv is specialized for scholarly papers, technical architectures, and benchmarks
        if "arxiv" in p_name:
            if category == "academic":
                return True
            # Skip forum/complaint/reddit queries
            if category in ("community", "opposing") or any(k in q_lower for k in ("reddit", "complaint", "review", "pricing", "investor")):
                return False
            arxiv_keywords = (
                "paper", "architecture", "benchmark", "model", "transformer",
                "weights", "pre-training", "fine-tuning", "parameter", "latency",
                "evaluation", "neural", "arxiv", "research", "scientific"
            )
            return any(k in q_lower for k in arxiv_keywords)

        # OpenAlex is specialized for scholarly literature and citations
        if "openalex" in p_name:
            if category == "academic":
                return True
            if category in ("community", "opposing") or any(k in q_lower for k in ("reddit", "complaint", "pricing", "investor")):
                return False
            scholarly_keywords = (
                "paper", "study", "journal", "citation", "academic", "research",
                "empirical", "methodology", "author", "publication"
            )
            return any(k in q_lower for k in scholarly_keywords)

        return True

    def _execute_search_queries(
        self,
        run_id: str,
        round_num: int,
        queries: List[Tuple[str, str]]
    ) -> List[SearchResult]:
        """Execute queries across relevant search providers."""
        all_results: List[SearchResult] = []
        for query_str, category in queries:
            qid = f"qry-{uuid.uuid4().hex[:8]}"
            self.repo.record_search_query(qid, run_id, round_num, query_str, category)

            q_results: List[SearchResult] = []
            for provider in self.search_providers:
                if not self._is_provider_relevant(provider.name, category, query_str):
                    continue
                try:
                    res = provider.search(query_str, max_results=20, category=category)
                    q_results.extend(res)
                except Exception as e:
                    logger.warning(f"Provider {provider.name} error on '{query_str}': {e}")

            self.repo.update_search_query_status(qid, results_count=len(q_results))
            all_results.extend(q_results)
            time.sleep(settings.inter_request_delay_seconds)

        return all_results

    def _ingest_search_results(
        self,
        run_id: str,
        results: List[SearchResult]
    ) -> Tuple[int, int]:
        """Deduplicate, canonicalize, apply per-domain limits, and insert sources."""
        domain_counts: Dict[str, int] = {}
        prepared_sources: List[Dict[str, Any]] = []

        for r in results:
            canon = self.canonicalize_url(r.url)
            if not canon:
                continue

            domain = r.domain.lower()
            if not domain:
                try:
                    domain = urllib.parse.urlsplit(canon).netloc.lower()
                except Exception:
                    domain = "unknown"

            # Enforce domain capping to prevent single site dominating
            count = domain_counts.get(domain, 0)
            if count >= settings.per_domain_url_limit:
                continue
            domain_counts[domain] = count + 1

            prepared_sources.append({
                "url": r.url,
                "canonical_url": canon,
                "domain": domain,
                "title": r.title,
                "publisher": r.publisher,
                "author": r.author,
                "published_date": r.published_date,
                "source_category": r.source_category,
                "source_tier": r.source_tier,
            })

        return self.repo.add_sources_batch(run_id, prepared_sources)

    def _process_pending_sources(
        self,
        run_id: str,
        notify_fn: Callable[[str, Dict[str, Any]], None]
    ) -> None:
        """Fetch pending sources, extract text, and compute content hashes."""
        pending = self.repo.get_pending_sources(run_id)
        total = len(pending)
        logger.info(f"Processing {total} pending sources for Run [{run_id}]...")

        for idx, src in enumerate(pending, start=1):
            if src.id is None:
                continue
            notify_fn("fetching", {"current": idx, "total": total, "domain": src.domain, "url": src.url})

            fetch_res = None
            page = None
            try:
                # 1. Safe fetch with SSRF check and streaming size limit
                fetch_res = self.fetcher.fetch(src.url)
                # 2. Main content extraction (Trafilatura + Jina fallback)
                page = self.extractor.extract(fetch_res.text, src.url)
            except SSRFSecurityError as e:
                # DNS failure or private-IP target — mark permanent failure and move on
                logger.warning(f"SSRF/DNS failure for [{src.url}]: {e}")
                self.repo.update_source_fetch_status(
                    src.id, run_id,
                    fetch_status="permanent_failure",
                    error_reason=f"SSRF_BLOCKED: {e}"
                )
                continue
            except FetchError as e:
                # Direct fetch failed (e.g. anti-bot 403/419); try Jina Reader fallback if enabled
                if self.extractor.enable_jina_fallback and self.extractor.jina_fallback:
                    try:
                        logger.info(f"Direct fetch failed for [{src.url}] ({e}). Attempting Jina Reader fallback...")
                        fb = self.extractor.jina_fallback.fetch_fallback_text(src.url)
                        if fb:
                            clean_text, c_hash = fb
                            page = ExtractedPage(
                                text=clean_text[:self.extractor.max_chars],
                                method="jina_fallback",
                                content_hash=c_hash,
                                title=src.title
                            )
                    except Exception as fb_err:
                        logger.debug(f"Jina fallback failed for [{src.url}]: {fb_err}")
                if not page:
                    logger.warning(f"Fetch failure for [{src.url}]: {e}")
                    self.repo.update_source_fetch_status(
                        src.id, run_id,
                        fetch_status="retryable_failure",
                        error_reason=str(e)
                    )
                    continue

            try:
                if page and len(page.text.strip()) >= 100:
                    status_code = fetch_res.http_status if fetch_res else 200
                    final_url = fetch_res.final_url if fetch_res else src.url
                    self.repo.update_source_fetch_status(
                        src.id, run_id,
                        fetch_status="fetched",
                        http_status=status_code,
                        final_url=final_url
                    )
                    self.repo.save_source_content(
                        src.id, run_id,
                        extracted_text=page.text,
                        extraction_method=page.method,
                        content_hash=page.content_hash
                    )
                    self.repo.update_source_metadata(
                        src.id, run_id,
                        title=page.title or src.title,
                        published_date=page.published_date or src.published_date,
                        author=page.author or src.author,
                        publisher=page.publisher or src.publisher
                    )

                    # 2b. Discover authoritative outbound references to follow primary sources
                    if fetch_res and fetch_res.text:
                        outbound_refs = self._discover_outbound_references(fetch_res.text, src.url)
                        if outbound_refs:
                            self.repo.add_sources_batch(run_id, outbound_refs)
                else:
                    status_code = fetch_res.http_status if fetch_res else 0
                    self.repo.update_source_fetch_status(
                        src.id, run_id,
                        fetch_status="permanent_failure",
                        http_status=status_code,
                        error_reason="Insufficient readable content extracted from webpage."
                    )
            except Exception as e:
                logger.warning(f"Unexpected error processing [{src.url}]: {e}")
                self.repo.update_source_fetch_status(
                    src.id, run_id,
                    fetch_status="permanent_failure",
                    error_reason=str(e)
                )

            # Clean memory periodically for 8GB RAM systems
            if idx % 10 == 0:
                gc.collect()

            time.sleep(settings.inter_request_delay_seconds)

    def _discover_outbound_references(self, html_text: str, source_url: str) -> List[Dict[str, Any]]:
        """Extract authoritative outbound reference links from webpage HTML to follow primary sources.

        Only follows links from known authoritative domains (arXiv, GitHub, .gov, .edu, SEC, PDF files).
        Applies topic-relevance filtering using active research question keywords to prevent
        irrelevant competitor/unrelated pages from being queued.
        """
        if not html_text:
            return []
        found_urls = re.findall(r'href=[\"\'](https?://[^\s\"\'<>]+)[\"\']', html_text, re.IGNORECASE)
        if not found_urls:
            return []

        try:
            base_domain = urllib.parse.urlsplit(source_url).netloc.lower()
        except Exception:
            return []

        discovered: List[Dict[str, Any]] = []
        seen_domains: Set[str] = set()

        for raw_url in found_urls:
            canon = self.canonicalize_url(raw_url)
            if not canon:
                continue
            try:
                domain = urllib.parse.urlsplit(canon).netloc.lower()
            except Exception:
                continue

            if not domain or domain == base_domain:
                continue

            # Only follow strictly authoritative primary sources
            is_authoritative = (
                domain.endswith((".gov", ".edu", ".mil")) or
                any(p in domain for p in ("arxiv.org", "github.com", "biorxiv.org",
                                          "nature.com", "sec.gov", "semanticscholar.org")) or
                canon.endswith(".pdf")
            )
            if not is_authoritative:
                continue

            # Topic-relevance check: the URL path must share at least one keyword
            # from the research question (prevents pulling in unrelated .edu/.gov pages)
            active_keywords = getattr(self, "_active_question_keywords", set())
            if active_keywords:
                url_text = canon.lower()
                if not any(kw in url_text for kw in active_keywords):
                    logger.debug(f"Skipping off-topic outbound ref: {canon}")
                    continue

            if domain not in seen_domains:
                seen_domains.add(domain)
                discovered.append({
                    "url": raw_url,
                    "canonical_url": canon,
                    "domain": domain,
                    "title": f"Primary Reference from {base_domain}",
                    "publisher": domain,
                    "author": "",
                    "published_date": "",
                    "source_category": "primary",
                    "source_tier": "Tier A",
                })
                if len(discovered) >= 2:  # Cap at 2 per page to avoid scope creep
                    break

        return discovered

    def _extract_and_validate_evidence(
        self,
        run_id: str,
        notify_fn: Callable[[str, Dict[str, Any]], None]
    ) -> None:
        """Extract candidate claims, validate exact quotes, and verify claim support."""
        sources = self.repo.get_sources_for_run(run_id)
        fetched_sources = [s for s in sources if s.fetch_status == "fetched" and s.id is not None]

        # Check existing evidence to prevent re-extracting
        existing_evidence = self.repo.get_all_evidence_for_run(run_id)
        processed_source_ids = {e.source_id for e in existing_evidence}

        for src in fetched_sources:
            if src.id in processed_source_ids or src.id is None:
                continue

            content_record = self.repo.get_source_content(src.id, run_id)
            if not content_record:
                continue

            notify_fn("extracting_evidence", {"domain": src.domain, "source_id": src.id})

            # Step 1: Candidate evidence extraction from LLM
            candidate_items = self.evidence_extractor.extract_candidate_evidence(
                source_id=src.id,
                source_url=src.url,
                domain=src.domain,
                source_text=content_record.extracted_text
            )

            for cand in candidate_items:
                evid_id = f"evid-{uuid.uuid4().hex[:8]}"

                # Step 2: Exact quote validation in stored original text (deterministic Python check)
                is_quote_valid, start_off, end_off, ctx = validate_exact_quote(
                    quote=cand.exact_quote,
                    stored_source_text=content_record.extracted_text
                )

                if not is_quote_valid:
                    # Log rejection event, do NOT mark verified, do NOT let report cite
                    self.repo.log_event(
                        run_id=run_id,
                        event_type="QUOTE_VALIDATION_FAILED",
                        message=f"Quote validation failed for Source #{src.id}: Quote not found verbatim.",
                        details={"quote": cand.exact_quote[:100], "candidate_claim": cand.candidate_claim}
                    )
                    # Record rejected candidate for audit trail
                    rejected_record = EvidenceRecord(
                        id=evid_id,
                        run_id=run_id,
                        source_id=src.id,
                        candidate_claim=cand.candidate_claim,
                        exact_quote=cand.exact_quote,
                        quote_start_offset=-1,
                        quote_end_offset=-1,
                        claim_type=cand.claim_type,
                        evidence_type=cand.evidence_type,
                        quote_valid=False,
                        support_status="does_not_support",
                        verification_reason="Quote was not found verbatim in stored source text.",
                        is_verified=False
                    )
                    self.repo.insert_evidence_item(rejected_record)
                    continue

                # Step 3: Independent claim support verification (second-pass)
                surrounding_context = ctx or cand.surrounding_context or content_record.extracted_text[:300]
                verif_res = self.claim_verifier.verify_claim(
                    candidate_claim=cand.candidate_claim,
                    exact_quote=cand.exact_quote,
                    surrounding_context=surrounding_context,
                    source_domain=src.domain,
                    source_url=src.url
                )

                # Strict fail-closed policy: only SUPPORTS or PARTIALLY_SUPPORTS are verified
                is_verified = verif_res.verdict in (
                    VerificationVerdict.SUPPORTS,
                    VerificationVerdict.PARTIALLY_SUPPORTS
                )

                final_claim_text = verif_res.refined_claim or cand.candidate_claim

                evid_record = EvidenceRecord(
                    id=evid_id,
                    run_id=run_id,
                    source_id=src.id,
                    candidate_claim=final_claim_text,
                    exact_quote=cand.exact_quote,
                    quote_start_offset=start_off,
                    quote_end_offset=end_off,
                    claim_type=verif_res.claim_type or cand.claim_type,
                    evidence_type=cand.evidence_type,
                    attribution=verif_res.attribution or cand.attribution,
                    published_date=cand.published_date or src.published_date,
                    time_period=cand.time_period,
                    geographic_scope=cand.geographic_scope,
                    metrics_data=json.dumps(cand.metrics_data),
                    surrounding_context=surrounding_context,
                    quote_valid=True,
                    support_status=verif_res.verdict.value,
                    verification_reason=verif_res.reason,
                    verification_model=settings.groq_verifier_model,
                    is_verified=is_verified
                )

                self.repo.insert_evidence_item(evid_record)

            processed_source_ids.add(src.id)
            del content_record
            gc.collect()
