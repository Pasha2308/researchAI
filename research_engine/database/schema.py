"""Database schema definition for the Evidence-First Deep Research Engine.

Defines tables for research runs, plans, search queries, sources, source content,
evidence ledger, claims, claim evidence links, contradictions, events, and reports.
Includes indexes and FTS5 full-text search.
"""

SCHEMA_SQL = """
-- 1. Research Runs Table
CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    scope TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'created' CHECK(status IN ('created', 'planning', 'searching', 'fetching', 'extracting', 'verifying', 'synthesizing', 'completed', 'failed', 'paused')),
    phase TEXT NOT NULL DEFAULT 'initialization',
    target_sources INTEGER NOT NULL DEFAULT 100,
    max_rounds INTEGER NOT NULL DEFAULT 3,
    current_round INTEGER NOT NULL DEFAULT 1,
    model_id TEXT NOT NULL,
    verifier_model_id TEXT NOT NULL,
    report_path TEXT DEFAULT '',
    stats_json TEXT DEFAULT '{}',
    error_message TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- 2. Research Plans Table
CREATE TABLE IF NOT EXISTS research_plans (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    core_question TEXT NOT NULL,
    scope TEXT DEFAULT '',
    plan_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES research_runs (id) ON DELETE CASCADE
);

-- 3. Search Queries Table
CREATE TABLE IF NOT EXISTS search_queries (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    round_num INTEGER NOT NULL DEFAULT 1,
    query TEXT NOT NULL,
    category TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'ddgs',
    results_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'executed', 'failed', 'rate_limited')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES research_runs (id) ON DELETE CASCADE
);

-- 4. Sources Table
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    final_url TEXT DEFAULT '',
    domain TEXT NOT NULL,
    title TEXT DEFAULT '',
    publisher TEXT DEFAULT '',
    author TEXT DEFAULT '',
    published_date TEXT DEFAULT '',
    discovered_by_query_id TEXT DEFAULT '',
    source_category TEXT NOT NULL DEFAULT 'unknown' CHECK(source_category IN ('primary', 'secondary', 'community', 'opposing', 'academic', 'independent_analysis', 'general', 'unknown')),
    source_tier TEXT NOT NULL DEFAULT 'Tier D' CHECK(source_tier IN ('Tier A', 'Tier B', 'Tier C', 'Tier D')),
    fetch_status TEXT NOT NULL DEFAULT 'discovered' CHECK(fetch_status IN ('discovered', 'queued', 'fetching', 'fetched', 'permanent_failure', 'retryable_failure', 'blocked')),
    extraction_status TEXT NOT NULL DEFAULT 'pending' CHECK(extraction_status IN ('pending', 'extracted', 'failed', 'no_content')),
    http_status INTEGER DEFAULT 0,
    content_hash TEXT DEFAULT '',
    error_reason TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES research_runs (id) ON DELETE CASCADE,
    UNIQUE (run_id, canonical_url)
);

-- 5. Source Content Table
CREATE TABLE IF NOT EXISTS source_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    extraction_method TEXT NOT NULL DEFAULT 'trafilatura',
    word_count INTEGER NOT NULL DEFAULT 0,
    char_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES research_runs (id) ON DELETE CASCADE
);

-- 6. Evidence Ledger Table
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    candidate_claim TEXT NOT NULL,
    exact_quote TEXT NOT NULL,
    quote_start_offset INTEGER DEFAULT -1,
    quote_end_offset INTEGER DEFAULT -1,
    claim_type TEXT NOT NULL DEFAULT 'direct_fact' CHECK(claim_type IN ('direct_fact', 'quantitative', 'user_experience', 'opinion', 'company_claim', 'allegation', 'research_finding', 'inference')),
    evidence_type TEXT NOT NULL DEFAULT 'empirical' CHECK(evidence_type IN ('empirical', 'self_reported', 'testimonial', 'corporate_pr', 'academic', 'journalistic', 'unknown')),
    attribution TEXT DEFAULT '',
    published_date TEXT DEFAULT '',
    time_period TEXT DEFAULT '',
    geographic_scope TEXT DEFAULT '',
    metrics_data TEXT DEFAULT '{}',
    surrounding_context TEXT DEFAULT '',
    quote_valid INTEGER NOT NULL DEFAULT 0,
    support_status TEXT NOT NULL DEFAULT 'unverified' CHECK(support_status IN ('supports', 'partially_supports', 'contradicts', 'does_not_support', 'insufficient_context', 'unverified')),
    verification_reason TEXT DEFAULT '',
    verification_model TEXT DEFAULT '',
    is_verified INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES research_runs (id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE
);

-- 7. Claims (Synthesized / Clustered) Table
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    cluster_title TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    claim_category TEXT NOT NULL DEFAULT 'single_source' CHECK(claim_category IN ('directly_documented', 'independently_corroborated', 'single_source', 'community_experience', 'company_claim', 'disputed', 'unverified', 'inference')),
    independent_sources_count INTEGER NOT NULL DEFAULT 1,
    has_contradictions INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'rejected', 'disputed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES research_runs (id) ON DELETE CASCADE
);

-- 8. Claim Evidence Association Table
CREATE TABLE IF NOT EXISTS claim_evidence (
    claim_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    relationship TEXT NOT NULL DEFAULT 'supports' CHECK(relationship IN ('supports', 'refutes', 'contextualizes')),
    PRIMARY KEY (claim_id, evidence_id),
    FOREIGN KEY (claim_id) REFERENCES claims (id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_id) REFERENCES evidence (id) ON DELETE CASCADE
);

-- 9. Contradictions Table
CREATE TABLE IF NOT EXISTS contradictions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    claim_a_id TEXT DEFAULT '',
    claim_b_id TEXT DEFAULT '',
    evidence_a_id TEXT NOT NULL,
    evidence_b_id TEXT NOT NULL,
    description TEXT NOT NULL,
    topic_facet TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES research_runs (id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_a_id) REFERENCES evidence (id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_b_id) REFERENCES evidence (id) ON DELETE CASCADE
);

-- 10. Research Events Log Table
CREATE TABLE IF NOT EXISTS research_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES research_runs (id) ON DELETE CASCADE
);

-- 11. Reports Table
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    markdown_content TEXT NOT NULL,
    structured_json TEXT NOT NULL,
    total_findings INTEGER NOT NULL DEFAULT 0,
    total_citations INTEGER NOT NULL DEFAULT 0,
    verified_citations_count INTEGER NOT NULL DEFAULT 0,
    report_path TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES research_runs (id) ON DELETE CASCADE
);

-- Indexes for high-performance lookup & run isolation
CREATE INDEX IF NOT EXISTS idx_sources_run_status ON sources (run_id, fetch_status);
CREATE INDEX IF NOT EXISTS idx_sources_run_canonical ON sources (run_id, canonical_url);
CREATE INDEX IF NOT EXISTS idx_sources_domain ON sources (domain);
CREATE INDEX IF NOT EXISTS idx_source_content_run ON source_content (run_id);
CREATE INDEX IF NOT EXISTS idx_source_content_source ON source_content (source_id);
CREATE INDEX IF NOT EXISTS idx_evidence_run_verified ON evidence (run_id, is_verified);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence (source_id);
CREATE INDEX IF NOT EXISTS idx_claims_run ON claims (run_id);
CREATE INDEX IF NOT EXISTS idx_contradictions_run ON contradictions (run_id);
CREATE INDEX IF NOT EXISTS idx_events_run ON research_events (run_id);
CREATE INDEX IF NOT EXISTS idx_queries_run ON search_queries (run_id, round_num);
"""

# FTS5 Full-Text Search Schema
FTS5_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
    evidence_id UNINDEXED,
    candidate_claim,
    exact_quote,
    surrounding_context,
    tokenize = 'porter unicode61'
);
"""
