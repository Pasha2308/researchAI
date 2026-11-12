# Evidence-First Deep Research Engine (v2.0)

A production-grade, autonomous research application architected around a strict **fail-closed evidence policy**. It executes systematic multi-tier web research across authoritative sources, independent technical benchmarks, and authentic developer communities, extracts candidate claims with exact supporting quotations, deterministically validates quotations against original stored webpage text in Python, audits claim support through a second-pass verifier, clusters independent corroboration while detecting contradictions, and synthesizes an auditable research report where every sentence is programmatically bound to its originating evidence record.

---

## 1. Product Vision & Evidence-First Architecture

```
                                  +------------------------------+
                                  | User Research Question / CLI |
                                  +--------------+---------------+
                                                 |
                                                 v
                                  +------------------------------+
                                  | 1. Research Planner          |
                                  | - Subquestions & Scope       |
                                  | - Multi-Tier Search Angles   |
                                  +--------------+---------------+
                                                 |
                                                 v
      +------------------------------------------+------------------------------------------+
      |                                          |                                          |
      v                                          v                                          v
+-----------------------+              +--------------------+                     +--------------------+
| DDGS (General Web)    |              | Hacker News API    |                     | OpenAlex & arXiv   |
| (Authoritative / Docs)|              | (Real Discussions) |                     | (Scholarly Papers) |
+-----------+-----------+              +---------+----------+                     +---------+----------+
            |                                    |                                          |
            +------------------------------------+------------------------------------------+
                                                 |
                                                 v
                                  +------------------------------+
                                  | 2. SSRF-Safe HTTP Fetcher    |
                                  | - Private IP / Loopback Block|
                                  | - Cloud Metadata (169.254)   |
                                  | - Streaming Size Cap (5MB)   |
                                  | - Redirect Chain Inspection  |
                                  +--------------+---------------+
                                                 |
                                                 v
                                  +------------------------------+
                                  | 3. Trafilatura + Jina Extr.  |
                                  | - SHA-256 Content Hashing    |
                                  | - Exact Source Content Store |
                                  +--------------+---------------+
                                                 |
                                                 v
                                  +------------------------------+
                                  | 4. Candidate Evidence Extr.  |
                                  | - Prompt Injection Defense   |
                                  | - Claims, Quotes & Metrics   |
                                  +--------------+---------------+
                                                 |
                                                 v
                                  +------------------------------+
                                  | 5. Deterministic Validator   |
                                  | - Complete Contiguous Quote  |
                                  | - Unicode NFKC & Whitespace  |
                                  | - Character Offset Bounds    |
                                  +--------------+---------------+
                                                 |
                                                 v
                                  +------------------------------+
                                  | 6. Claim Support Verifier    |
                                  | - Verdict: supports / refutes|
                                  | - Fail-Closed Rejection      |
                                  +--------------+---------------+
                                                 |
                                                 v
                                  +------------------------------+
                                  | 7. Gap Detector & Rounds     |
                                  | - Unanswered Subquestions    |
                                  | - Targeted Follow-Up Queries |
                                  +--------------+---------------+
                                                 |
                                                 v
                                  +------------------------------+
                                  | 8. Corroboration Engine      |
                                  | - Independent Domain Clust.  |
                                  | - Syndicated Duplicate Check |
                                  | - Contradiction Detection    |
                                  +--------------+---------------+
                                                 |
                                                 v
                                  +------------------------------+
                                  | 9. Programmatic Citation Val.|
                                  | - Every Claim Cites Valid ID |
                                  | - Cross-Run Contamination Blk|
                                  +--------------+---------------+
                                                 |
                                                 v
                                  +------------------------------+
                                  | 10. Publication Markdown     |
                                  | - Clickable Inline Citations |
                                  | - Sources & Evidence Index   |
                                  +------------------------------+
```

---

## 2. Core Architectural Pillars

### Strict Fail-Closed Evidence Policy
- **No Trace, No Finding**: No factual statement may enter the verified findings without traceable source evidence in `research_vault.db`.
- **Complete Quote Verification**: Every supporting quotation must exist contiguously in stored source text. Matching only the first 10 or 15 words is strictly prohibited and tested.
- **Independent Claim Auditing**: Quotations must be verified to support the candidate claim in a separate model auditing pass (`supports`, `partially_supports`, `contradicts`, `does_not_support`, `insufficient_context`).
- **Honest Disagreement**: Contradictory findings are actively flagged and preserved under a dedicated *Contradictions & Disagreements* section.
- **Unanswered Stays Unknown**: Subquestions lacking verifiable evidence are surfaced explicitly under *What the Research Could Not Establish*.

### Transparent Source Classification
- **Tier A (Primary & Authoritative)**: Official documentation, specifications, standards, and peer-reviewed scholarly literature.
- **Tier B (Independent Secondary)**: Credible technical journalism, independent benchmark laboratories, and expert commentary.
- **Tier C (Community & Practitioner Evidence)**: Self-reported discussions from Reddit, Hacker News, and technical forums.
- **Tier D (Corporate Claims / Marketing / Unclassified)**: Self-reported corporate announcements and promotional content.

### Syndicated Content Defense
Duplicate articles, mirrored press releases, and syndicated reposts sharing identical content hashes are prevented from counting as independent corroboration.

### Complete SSRF & Prompt Injection Safeguards
- **Network Boundaries**: Rejects RFC 1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.0/8`, `::1`), link-local/cloud metadata (`169.254.169.254`), and unsafe ports.
- **Redirect Defense**: Inspects every redirect hop before establishing connections.
- **Streaming Byte Cap**: Enforces `MAX_RESPONSE_BYTES` (5 MB) during streaming download to prevent memory exhaustion attacks.
- **Prompt Injection Delimiters**: Encloses third-party web content inside strict untrusted containment blocks (`<<<UNTRUSTED_EXTERNAL_SOURCE_DATA_START>>> ... <<<UNTRUSTED_EXTERNAL_SOURCE_DATA_END>>>`).

---

## 3. Technology Stack

- **Python 3.12+** (tested on Python 3.15.0 on Windows 11)
- **Streamlit**: Local research dashboard bound to `127.0.0.1`.
- **SQLite 3**: Persistent state with WAL mode (`PRAGMA journal_mode = WAL;`), foreign keys, transactions, and FTS5 full-text search.
- **HTTPX**: Safe streaming HTTP client with custom redirect inspection.
- **Trafilatura**: High-precision main content extraction.
- **Jina Reader API**: Controlled fallback extraction for JavaScript SPAs.
- **DDGS**: Multi-query DuckDuckGo search integration with exponential backoff.
- **Hacker News Algolia API**: Public keyless technical discussion provider.
- **OpenAlex & arXiv APIs**: Public scholarly literature discovery.
- **Groq Python SDK**: Primary inference with dynamic model validation and `Retry-After` rate-limit handling.
- **Pydantic v2**: Structured model validation and JSON schema enforcement.

---

## 4. Project Layout

```text
deep-research-engine/
│
├── app.py                      # Streamlit interactive dashboard (127.0.0.1:8501)
├── cli.py                      # Production Command-Line Interface
├── config.py                   # Centralized Pydantic configuration & environment settings
├── requirements.txt            # Pinned dependency definitions
├── pyproject.toml              # Modern Python packaging configuration
├── .env.example                # Configuration template
├── .gitignore                  # Gitignore for secrets, databases, and caches
├── README.md                   # System documentation
│
├── research_engine/
│   ├── database/
│   │   ├── schema.py           # SQLite DDL (11 tables + indexes + FTS5)
│   │   ├── connection.py       # Thread-safe WAL connection context manager
│   │   ├── models.py           # Pydantic data models for runs, sources, and evidence
│   │   └── repository.py       # High-level data access layer with strict run isolation
│   │
│   ├── security/
│   │   ├── ssrf.py             # SSRF & IP validator (RFC 1918, link-local, cloud metadata)
│   │   └── sanitizer.py        # Prompt injection containment & boundary defense
│   │
│   ├── providers/
│   │   ├── search/
│   │   │   ├── base.py         # SearchProvider abstract interface & SearchResult model
│   │   │   ├── ddgs_provider.py# DuckDuckGo multi-angle search provider
│   │   │   ├── hackernews.py   # Public Hacker News Algolia Search API provider
│   │   │   ├── openalex.py     # Public OpenAlex Academic Literature provider
│   │   │   └── arxiv.py        # Public arXiv Preprint provider
│   │   │
│   │   └── llm/
│   │       ├── base.py         # LLMProvider abstract interface
│   │       ├── groq_provider.py# Groq SDK provider with model validation & jittered backoff
│   │       └── mock_provider.py# Deterministic mock provider for offline testing
│   │
│   ├── fetchers/
│   │   ├── safe_fetcher.py     # Streaming HTTPX fetcher with SSRF validation
│   │   └── jina_fallback.py    # Controlled Jina Reader fallback fetcher
│   │
│   ├── extractors/
│   │   └── page_extractor.py   # Trafilatura parser + content hashing
│   │
│   ├── evidence/
│   │   ├── models.py           # Structured candidate evidence models
│   │   ├── extractor.py        # Prompt-injection safe candidate evidence extractor
│   │   └── validator.py        # Deterministic exact quote validator in Python
│   │
│   ├── verification/
│   │   └── claim_verifier.py   # Second-pass claim support auditor
│   │
│   ├── research/
│   │   ├── planner.py          # Structured research planner
│   │   ├── gap_detector.py     # Iterative research gap detector
│   │   └── orchestrator.py     # Master multi-round research coordinator
│   │
│   ├── synthesis/
│   │   ├── corroboration.py    # Corroboration & contradiction clustering engine
│   │   └── report_synthesizer.py # Structured report synthesizer
│   │
│   └── reporting/
│       ├── validator.py        # Programmatic citation & cross-run validator
│       └── markdown_renderer.py# Publication-grade Markdown report generator
│
├── tests/
│   ├── fixtures/
│   │   └── sample_pages.py     # Deterministic HTML test fixtures
│   ├── unit/
│   │   ├── test_quote_validator.py       # Quote validation & normalization tests
│   │   ├── test_security_ssrf.py         # SSRF, private IP, and port tests
│   │   ├── test_claim_and_citation.py    # Citation validation & fail-closed tests
│   │   ├── test_corroboration_quality.py # Corroboration, contradiction & gap tests
│   │   └── test_reliability.py          # Deduplication, retry & isolation tests
│   └── integration/
│       ├── test_end_to_end_fixture.py    # Complete offline fixture pipeline test
│       └── test_regression.py            # Explicit tests for previous architecture flaws
│
├── data/                       # Local SQLite vault (research_vault.db)
├── reports/                    # Generated markdown reports
│   └── sample_verified_report.md
└── scripts/
    ├── setup_windows.ps1       # Automated Windows setup script
    └── run_windows.ps1         # Windows Streamlit launcher script
```

---

## 5. Quick Start (Windows 11)

### Option A: Automated PowerShell Setup

Open PowerShell in the project directory:

```powershell
# 1. Run setup script (installs requirements & initializes database)
.\scripts\setup_windows.ps1

# 2. Launch the Streamlit dashboard on http://127.0.0.1:8501
.\scripts\run_windows.ps1
```

### Option B: Manual Setup

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
Copy-Item .env.example .env
# Edit .env and supply your GROQ_API_KEY from https://console.groq.com/keys

# 3. Launch Dashboard
streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

---

## 6. Command-Line Interface (CLI) Usage

The engine includes a full-featured CLI for automation, scripted tasks, and terminal use:

```powershell
# 1. Launch a deep research task
python cli.py run "FastAPI vs Flask in 2026 production: benchmarks and failure modes" -n 100 -r 3

# 2. Inspect active or previous runs
python cli.py list

# 3. View detailed accounting stats for a run
python cli.py status <run_id>

# 4. Inspect the exact quotation, surrounding context, and verification verdict behind a citation
python cli.py inspect <run_id> --evidence-id evid-001

# 5. Export markdown report to a file
python cli.py export <run_id> -o final_report.md
```

---

## 7. Verification & Automated Test Suite

The test suite covers the **34 rigorous requirements** specified in Section 16, plus explicit regression tests for defects from the legacy engine:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

### Verified Test Categories:
1. **Evidence Validation**: Exact quote accepted, invented quote rejected, altered quote rejected, 15-word prefix matching rejected, Unicode NFKC smart quote translation verified.
2. **Citation Validation**: Valid citation passes, nonexistent ID fails, wrong source fails, cross-run citation fails, uncited statements flagged.
3. **Research Quality**: Contradictions retained, syndicated duplicate content not counted as independent corroboration, primary vs secondary tiers distinguished, unanswered subquestions surfaced as gaps.
4. **Security**: SSRF blocking for `localhost`, `127.0.0.1`, RFC 1918 subnets (`10.*`, `172.16.*`, `192.168.*`), cloud metadata (`169.254.169.254`), unsafe ports (`22`, `3306`), and prompt injection delimiter containment.
5. **Reliability**: Canonical URL deduplication, retryable failure state recovery, strict run isolation in SQLite, and dynamic model availability validation.
6. **End-to-End Fixture Test**: Complete pipeline execution on local HTML fixtures, generating [`reports/sample_verified_report.md`](reports/sample_verified_report.md) with programmatic citation verification.

```
...............................
----------------------------------------------------------------------
Ran 31 tests in 2.919s

OK
```

---

## 8. Honest Limitations & Auditability

1. **Deterministic Verification Standard**: We do not claim zero hallucinations through marketing guarantees. Instead, we implement a deterministic, fail-closed software verification barrier: if an exact quote is not contiguously present in the original extracted text, the claim is rejected in code.
2. **Community Reviews as Personal Experiences**: User complaints and forum reviews are classified as `self_reported` opinions. The system explicitly disallows treating single reviews as community consensus.
3. **Public API Availability**: General web discovery uses `ddgs`, Hacker News uses Algolia, OpenAlex provides scholarly metadata, and arXiv provides preprints. Search results are subject to public network availability and provider rate limits.
