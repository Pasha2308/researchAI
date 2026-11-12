"""Public Hacker News search provider via Algolia Search API.

Provides free, public, keyless access to Hacker News submissions, technical discussions,
and community consensus.
"""

import logging
import urllib.parse
from typing import Any, List
import httpx

from research_engine.providers.search.base import BaseSearchProvider, SearchResult

logger = logging.getLogger("research_engine.search.hackernews")

HN_API_URL = "https://hn.algolia.com/api/v1/search"


class HackerNewsSearchProvider(BaseSearchProvider):
    """Hacker News Algolia search provider."""

    @property
    def name(self) -> str:
        return "hackernews"

    def search(
        self,
        query: str,
        max_results: int = 15,
        category: str = "community",
        **kwargs: Any
    ) -> List[SearchResult]:
        results: List[SearchResult] = []
        try:
            params = {
                "query": query,
                "tags": "story",
                "hitsPerPage": min(max_results, 30),
            }
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(HN_API_URL, params=params)
                if resp.status_code != 200:
                    return results

                data = resp.json()
                hits = data.get("hits", [])

                for hit in hits:
                    story_id = hit.get("objectID")
                    raw_url = hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
                    title = hit.get("title") or "Hacker News Discussion"
                    points = hit.get("points", 0)
                    comments = hit.get("num_comments", 0)
                    created_at = hit.get("created_at", "")[:10]

                    snippet = f"HN discussion with {points} points and {comments} comments."
                    domain = "news.ycombinator.com"
                    try:
                        domain = urllib.parse.urlsplit(raw_url).netloc.lower() or "news.ycombinator.com"
                    except Exception:
                        pass

                    results.append(
                        SearchResult(
                            url=f"https://news.ycombinator.com/item?id={story_id}",
                            title=title,
                            snippet=snippet,
                            domain=domain,
                            source_category="community",
                            source_tier="Tier C",
                            provider=self.name,
                            published_date=created_at,
                            author=hit.get("author", ""),
                            publisher="Hacker News",
                            raw_metadata={"points": points, "num_comments": comments, "story_url": hit.get("url")}
                        )
                    )
        except Exception as e:
            logger.debug(f"Hacker News search failed for '{query}': {e}")

        return results

