"""OpenAlex academic literature search provider.

Provides free, public, keyless access to peer-reviewed scholarly literature,
scientific preprints, citation counts, and publication metadata.
"""

import logging
import urllib.parse
from typing import Any, List
import httpx

from research_engine.providers.search.base import BaseSearchProvider, SearchResult

logger = logging.getLogger("research_engine.search.openalex")

OPENALEX_API_URL = "https://api.openalex.org/works"


class OpenAlexSearchProvider(BaseSearchProvider):
    """OpenAlex academic papers search provider."""

    @property
    def name(self) -> str:
        return "openalex"

    def search(
        self,
        query: str,
        max_results: int = 15,
        category: str = "academic",
        **kwargs: Any
    ) -> List[SearchResult]:
        results: List[SearchResult] = []
        try:
            params = {
                "search": query,
                "per-page": min(max_results, 25),
            }
            headers = {"User-Agent": "EvidenceFirstResearchEngine/1.0 (mailto:research@local.app)"}
            with httpx.Client(timeout=12.0) as client:
                resp = client.get(OPENALEX_API_URL, params=params, headers=headers)
                if resp.status_code != 200:
                    return results

                data = resp.json()
                works = data.get("results", [])

                for work in works:
                    doi = work.get("doi")
                    oa = work.get("open_access", {})
                    oa_url = oa.get("oa_url")
                    landing_url = work.get("id") or doi or oa_url
                    if not landing_url:
                        continue

                    title = work.get("title") or "Scholarly Publication"
                    pub_date = work.get("publication_date", "")
                    cited_count = work.get("cited_by_count", 0)

                    # Get primary author or venue
                    primary_location = work.get("primary_location") or {}
                    source = primary_location.get("source") or {}
                    venue_name = source.get("display_name", "Academic Journal")

                    snippet = f"Academic work published in {venue_name} ({pub_date}), cited {cited_count} times."

                    domain = "openalex.org"
                    try:
                        domain = urllib.parse.urlsplit(landing_url).netloc.lower() or "openalex.org"
                    except Exception:
                        pass

                    target_url = oa_url or doi or landing_url
                    results.append(
                        SearchResult(
                            url=target_url,
                            title=title,
                            snippet=snippet,
                            domain=domain,
                            source_category="primary",
                            source_tier="Tier A",
                            provider=self.name,
                            published_date=pub_date,
                            publisher=venue_name,
                            raw_metadata={"cited_by_count": cited_count, "doi": doi}
                        )
                    )
        except Exception as e:
            logger.debug(f"OpenAlex search failed for '{query}': {e}")

        return results

