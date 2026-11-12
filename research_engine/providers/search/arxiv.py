"""arXiv academic preprint search provider.

Provides free, public, keyless access to physics, mathematics, computer science,
and quantitative biology preprints via the official arXiv API.
"""

import logging
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, List
import httpx

from research_engine.providers.search.base import BaseSearchProvider, SearchResult

logger = logging.getLogger("research_engine.search.arxiv")

ARXIV_API_URL = "https://export.arxiv.org/api/query"


class ArxivSearchProvider(BaseSearchProvider):
    """arXiv preprint search provider."""

    @property
    def name(self) -> str:
        return "arxiv"

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
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": min(max_results, 25),
            }
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(ARXIV_API_URL, params=params)
                if resp.status_code != 200:
                    return results

                # Parse Atom XML
                root = ET.fromstring(resp.text)
                atom_ns = {"atom": "http://www.w3.org/2005/Atom"}

                for entry in root.findall("atom:entry", atom_ns):
                    title_elem = entry.find("atom:title", atom_ns)
                    title = " ".join((title_elem.text or "").split()) if title_elem is not None else "arXiv Preprint"

                    id_elem = entry.find("atom:id", atom_ns)
                    entry_url = id_elem.text.strip() if id_elem is not None and id_elem.text else ""
                    if not entry_url:
                        continue

                    summary_elem = entry.find("atom:summary", atom_ns)
                    summary = " ".join((summary_elem.text or "").split())[:300] if summary_elem is not None else ""

                    published_elem = entry.find("atom:published", atom_ns)
                    published = published_elem.text[:10] if published_elem is not None and published_elem.text else ""

                    authors = []
                    for author_elem in entry.findall("atom:author", atom_ns):
                        name_elem = author_elem.find("atom:name", atom_ns)
                        if name_elem is not None and name_elem.text:
                            authors.append(name_elem.text)
                    author_str = ", ".join(authors[:3])

                    results.append(
                        SearchResult(
                            url=entry_url,
                            title=title,
                            snippet=summary,
                            domain="arxiv.org",
                            source_category="primary",
                            source_tier="Tier A",
                            provider=self.name,
                            published_date=published,
                            author=author_str,
                            publisher="arXiv",
                            raw_metadata={"arxiv_id": entry_url}
                        )
                    )
        except Exception as e:
            logger.debug(f"arXiv search failed for '{query}': {e}")

        return results

