"""DuckDuckGo general web discovery provider using the ddgs library.

Features exponential backoff on rate limits, query tracking,
source category classification, and metadata preservation.
"""

import logging
import time
import urllib.parse
from typing import Any, List, Optional

try:
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException
except ImportError:
    try:
        from duckduckgo_search import DDGS
        from duckduckgo_search.exceptions import DuckDuckGoSearchException as DDGSException
    except ImportError:
        DDGS = None
        DDGSException = Exception

from research_engine.providers.search.base import BaseSearchProvider, SearchResult

logger = logging.getLogger("research_engine.search.ddgs")


class DDGSSearchProvider(BaseSearchProvider):
    """DuckDuckGo search provider with rate-limit and backoff support."""

    def __init__(self, region: str = "wt-wt", recency: Optional[str] = None):
        self.region = region
        self.recency = recency

    @property
    def name(self) -> str:
        return "ddgs"

    def _classify_domain_tier(self, domain: str, category: str) -> str:
        """Infer source tier from domain and category."""
        d = domain.lower()
        if any(d.endswith(ext) for ext in (".gov", ".edu", ".mil")):
            return "Tier A"
        if any(c in d for c in ("docs.", "documentation.", "developer.", "support.")):
            return "Tier A"
        if any(f in d for f in ("reddit.com", "ycombinator.com", "quora.com", "stackoverflow.com", "medium.com")):
            return "Tier C"
        if category in ("community", "forum", "user_reviews"):
            return "Tier C"
        if category in ("academic", "research", "documentation"):
            return "Tier A"
        if category in ("independent_analysis", "journalism", "benchmarks"):
            return "Tier B"
        return "Tier D"

    def search(
        self,
        query: str,
        max_results: int = 20,
        category: str = "general",
        **kwargs: Any
    ) -> List[SearchResult]:
        """Execute search with rate-limiting retry logic."""
        if DDGS is None:
            logger.error("DDGS library is not installed.")
            return []

        results: List[SearchResult] = []
        clean_query = query.strip()
        if not clean_query:
            return results

        max_retries = 3
        backoff = 2.0

        for attempt in range(1, max_retries + 1):
            try:
                with DDGS() as ddgs:
                    kwargs_search = {}
                    if self.region:
                        kwargs_search["region"] = self.region
                    if self.recency:
                        kwargs_search["timelimit"] = self.recency

                    try:
                        raw_items = list(ddgs.text(clean_query, max_results=max_results, **kwargs_search))
                    except TypeError:
                        # Fallback for older duckduckgo-search signatures
                        raw_items = list(ddgs.text(keywords=clean_query, max_results=max_results, **kwargs_search))

                for item in raw_items:
                    href = item.get("href") or item.get("url")
                    if not href:
                        continue
                    try:
                        domain = urllib.parse.urlsplit(href).netloc.lower()
                    except Exception:
                        domain = "unknown"

                    tier = self._classify_domain_tier(domain, category)
                    results.append(
                        SearchResult(
                            url=href,
                            title=item.get("title", ""),
                            snippet=item.get("body", ""),
                            domain=domain,
                            source_category=category,
                            source_tier=tier,
                            provider=self.name,
                            raw_metadata=item
                        )
                    )
                break  # Successful fetch
            except DDGSException as e:
                logger.warning(f"DDGS search attempt {attempt} for '{clean_query}' rate-limited or failed: {e}")
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2.0
            except Exception as e:
                logger.warning(f"Unexpected error in DDGS search for '{clean_query}': {e}")
                break

        return results

