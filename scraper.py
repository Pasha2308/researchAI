"""Scraper module for the Deep Research Engine.

Handles multi-angle DuckDuckGo searches to balance authoritative knowledge
and authentic community reviews (e.g., Reddit, Hacker News, forums),
followed by dual-tier HTML extraction via Trafilatura with Jina Reader API fallback.
"""

import time
import logging
import urllib.parse
from typing import List, Tuple, Optional, Set
import requests
import trafilatura

try:
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException
except ImportError:
    from duckduckgo_search import DDGS
    try:
        from duckduckgo_search.exceptions import DuckDuckGoSearchException as DDGSException
    except ImportError:
        DDGSException = Exception

from config import (
    HTTP_USER_AGENT,
    SCRAPE_TIMEOUT_SECONDS,
    MAX_EXTRACTED_CHARS,
    JINA_READER_BASE_URL,
    DEFAULT_TARGET_URLS,
)
import database

logger = logging.getLogger("research_engine.scraper")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Common binary or unparseable extensions
IGNORED_EXTENSIONS = (
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".exe", ".bin",
    ".mp3", ".mp4", ".mov", ".avi", ".wmv", ".jpg", ".jpeg",
    ".png", ".gif", ".webp", ".svg", ".ico", ".css", ".js"
)

# Common non-content domains or aggregator noise
IGNORED_DOMAINS = {
    "youtube.com", "www.youtube.com", "youtu.be",
    "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com",
    "twitter.com", "x.com", "www.twitter.com",
    "tiktok.com", "www.tiktok.com",
    "accounts.google.com", "login.yahoo.com"
}


def clean_and_normalize_url(raw_url: str) -> Optional[str]:
    """Clean, validate, and normalize a URL by stripping tracking params and anchors."""
    if not raw_url or not isinstance(raw_url, str):
        return None
    raw_url = raw_url.strip()
    if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
        return None

    try:
        parsed = urllib.parse.urlparse(raw_url)
        # Check domain
        domain = parsed.netloc.lower()
        if not domain or domain in IGNORED_DOMAINS:
            return None

        # Check path extension
        path = parsed.path.lower()
        for ext in IGNORED_EXTENSIONS:
            if path.endswith(ext):
                return None

        # Filter tracking query parameters
        query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
        cleaned_params = {
            k: v for k, v in query_params.items()
            if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref", "source"))
        }
        clean_query = urllib.parse.urlencode(cleaned_params, doseq=True)

        # Rebuild URL without fragment (#)
        normalized = urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/"),
            "",  # params
            clean_query,
            ""   # fragment
        ))
        return normalized if normalized else None
    except Exception:
        return None


def extract_domain(url: str) -> str:
    """Extract lowercase netloc domain from URL."""
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return "unknown"


def generate_search_queries(topic: str) -> List[Tuple[str, str]]:
    """Generate a diverse matrix of search queries balancing authority and authentic community reviews.
    
    Returns a list of tuples: (query_string, category_label)
    """
    cleaned_topic = topic.strip()
    return [
        (f"{cleaned_topic}", "General Overview"),
        (f"{cleaned_topic} documentation analysis research report", "Authoritative Research"),
        (f"{cleaned_topic} reddit discussion", "Reddit Community Consensus"),
        (f"{cleaned_topic} reddit reviews experiences", "Reddit User Reviews"),
        (f"{cleaned_topic} hacker news discussion", "Hacker News Technical Consensus"),
        (f"{cleaned_topic} honest review problems complaints", "Authentic Critiques & Flaws"),
        (f"{cleaned_topic} forum community experience", "Public Forum Feedback"),
        (f"{cleaned_topic} benchmarks comparison performance", "Empirical Benchmarks"),
        (f"{cleaned_topic} case study real world production", "Real-World Case Studies"),
        (f"{cleaned_topic} failure postmortem issues", "Failure Postmortems & Limitations"),
        (f"{cleaned_topic} quora answers experiences", "Quora Discussions"),
        (f"{cleaned_topic} security vulnerabilities trade-offs", "Security & Trade-Offs"),
        (f"{cleaned_topic} user consensus 2025 2026", "Recent User Consensus")
    ]


def search_and_queue_sources(
    topic: str,
    target_count: int = DEFAULT_TARGET_URLS,
    db_path: Optional[str] = None
) -> int:
    """Search DuckDuckGo across multiple specialized queries to gather target_count URLs.
    
    Fetches from a mix of highly trusted authority domains and community forums (Reddit, etc.),
    deduplicates links, normalizes them, and inserts them into the sources table.
    
    Returns the total number of sources now queued in the database.
    """
    logger.info(f"Starting multi-source DuckDuckGo discovery for topic: '{topic}' (Target: {target_count}+ URLs)")
    queries = generate_search_queries(topic)
    
    discovered_urls: Set[str] = set()
    collected_pairs: List[Tuple[str, str]] = []

    # Check already existing URLs in database to prevent re-querying duplicates
    if db_path:
        with database.get_connection(db_path) as conn:
            existing = conn.execute("SELECT url FROM sources").fetchall()
            for r in existing:
                discovered_urls.add(r["url"])

    with DDGS() as ddgs:
        for query_str, category in queries:
            if len(collected_pairs) + len(discovered_urls) >= target_count:
                logger.info(f"Reached target URL threshold ({len(collected_pairs) + len(discovered_urls)}/{target_count}).")
                break

            logger.info(f"Searching [{category}]: '{query_str}'")
            try:
                # Fetch up to 25 results per angle
                results = list(ddgs.text(query_str, max_results=25))
                for item in results:
                    raw_href = item.get("href")
                    if not raw_href:
                        continue
                    clean_url = clean_and_normalize_url(raw_href)
                    if clean_url and clean_url not in discovered_urls:
                        discovered_urls.add(clean_url)
                        domain = extract_domain(clean_url)
                        collected_pairs.append((clean_url, domain))
                        
                logger.info(f"-> Discovered {len(collected_pairs)} new unique URLs so far.")
            except DDGSException as e:
                logger.warning(f"DuckDuckGo returned no results or rate-limited for '{query_str}': {e}")
            except Exception as e:
                logger.warning(f"Error during search query '{query_str}': {e}")

            # Polite delay between search requests to respect DuckDuckGo limits
            time.sleep(1.5)

    if collected_pairs:
        inserted = database.add_sources(collected_pairs, db_path=db_path) if db_path else database.add_sources(collected_pairs)
        logger.info(f"Successfully inserted {inserted} new sources into database (Total collected: {len(discovered_urls)})")
    else:
        logger.info(f"No new sources needed insertion (Total existing: {len(discovered_urls)})")

    return len(discovered_urls)


def extract_text(url: str, timeout: int = SCRAPE_TIMEOUT_SECONDS) -> Optional[str]:
    """Extract clean text from a URL using Trafilatura with Jina Reader fallback.
    
    1. First attempts lightweight extraction via trafilatura.fetch_url and trafilatura.extract.
    2. If extraction returns None, raises an exception, or yields less than 150 chars
       (common with JavaScript SPAs, cookie modals, or Cloudflare turnstiles),
       falls back to GET https://r.jina.ai/<URL>.
    3. Caps text to MAX_EXTRACTED_CHARS to keep memory lean on 8GB RAM and prevent
       Groq context window overflow.
    
    Returns clean string or None if extraction is impossible.
    """
    extracted_text: Optional[str] = None

    # Step 1: Trafilatura attempt
    try:
        downloaded = trafilatura.fetch_url(url, decode=True)
        if downloaded:
            extracted_text = trafilatura.extract(
                downloaded,
                include_comments=True,
                include_tables=True,
                no_fallback=False,
                output_format="txt"
            )
            if extracted_text and len(extracted_text.strip()) >= 150:
                clean = extracted_text.strip()
                return clean[:MAX_EXTRACTED_CHARS]
    except Exception as e:
        logger.debug(f"Trafilatura failed for {url}: {e}")

    # Step 2: Jina Reader Fallback (https://r.jina.ai/<URL>)
    jina_url = f"{JINA_READER_BASE_URL}{url}"
    try:
        headers = {
            "User-Agent": HTTP_USER_AGENT,
            "Accept": "text/plain",
            "X-No-Cache": "true",
            "X-Timeout": str(timeout)
        }
        resp = requests.get(jina_url, headers=headers, timeout=timeout)
        if resp.status_code == 200 and resp.text:
            text = resp.text.strip()
            # If Jina returned meaningful text content
            if len(text) >= 100 and not text.startswith("Error:"):
                return text[:MAX_EXTRACTED_CHARS]
    except Exception as e:
        logger.debug(f"Jina Reader fallback failed for {url}: {e}")

    return None

