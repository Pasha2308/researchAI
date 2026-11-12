"""Base classes and data models for search providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """Normalized search result returned by any search provider."""
    url: str
    title: str = ""
    snippet: str = ""
    domain: str = ""
    source_category: str = "unknown"  # primary, secondary, community, opposing, academic
    source_tier: str = "Tier D"        # Tier A, Tier B, Tier C, Tier D
    provider: str = "generic"
    published_date: str = ""
    author: str = ""
    publisher: str = ""
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseSearchProvider(ABC):
    """Abstract interface for all web and structured search providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""
        pass

    @abstractmethod
    def search(
        self,
        query: str,
        max_results: int = 20,
        category: str = "general",
        **kwargs: Any
    ) -> List[SearchResult]:
        """Execute a search query and return normalized search results."""
        pass

