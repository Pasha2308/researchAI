"""Page content extractor using Trafilatura with Jina Reader fallback.

Preserves tables, comments, and metadata; calculates reproducible SHA-256
content hashes; and enforces maximum text size limits.
"""

import hashlib
import logging
from typing import Dict, Optional, Tuple
import trafilatura

from config import settings
from research_engine.fetchers.jina_fallback import JinaReaderFallback

logger = logging.getLogger("research_engine.extractors.page")


class ExtractedPage:
    """Container for successfully extracted webpage content and metadata."""

    def __init__(
        self,
        text: str,
        method: str,
        content_hash: str,
        title: str = "",
        published_date: str = "",
        author: str = "",
        publisher: str = ""
    ):
        self.text = text
        self.method = method
        self.content_hash = content_hash
        self.title = title
        self.published_date = published_date
        self.author = author
        self.publisher = publisher
        self.char_count = len(text)
        self.word_count = len(text.split())


class PageExtractor:
    """Extracts text content and metadata from raw HTML with fallback options."""

    def __init__(
        self,
        enable_jina_fallback: bool = settings.enable_jina_fallback,
        max_chars: int = settings.max_extracted_chars
    ):
        self.enable_jina_fallback = enable_jina_fallback
        self.max_chars = max_chars
        self.jina_fallback = JinaReaderFallback() if enable_jina_fallback else None

    def extract(self, html_or_text: str, url: str) -> Optional[ExtractedPage]:
        """Extract main content from webpage HTML.
        
        Attempts Trafilatura extraction first.
        If extraction fails or yields insufficient content, attempts Jina Reader fallback.
        """
        if not html_or_text or not html_or_text.strip():
            return None

        # 1. Primary: Trafilatura extraction
        try:
            extracted_text = trafilatura.extract(
                html_or_text,
                include_comments=True,
                include_tables=True,
                no_fallback=False,
                output_format="txt"
            )

            # Metadata extraction
            title = ""
            published_date = ""
            author = ""
            publisher = ""

            try:
                meta = trafilatura.extract_metadata(html_or_text)
                if meta:
                    title = meta.title or ""
                    published_date = meta.date or ""
                    author = meta.author or ""
                    publisher = meta.sitename or ""
            except Exception:
                pass

            if extracted_text and len(extracted_text.strip()) >= 120:
                clean_text = extracted_text.strip()[:self.max_chars]
                c_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
                return ExtractedPage(
                    text=clean_text,
                    method="trafilatura",
                    content_hash=c_hash,
                    title=title,
                    published_date=published_date,
                    author=author,
                    publisher=publisher
                )
        except Exception as e:
            logger.debug(f"Trafilatura extraction exception for '{url}': {e}")

        # 2. Fallback: Jina Reader API
        if self.enable_jina_fallback and self.jina_fallback:
            logger.info(f"Invoking Jina Reader fallback for '{url}'")
            fallback_res = self.jina_fallback.fetch_fallback_text(url)
            if fallback_res:
                fallback_text, fallback_hash = fallback_res
                clean_text = fallback_text[:self.max_chars]
                return ExtractedPage(
                    text=clean_text,
                    method="jina_fallback",
                    content_hash=fallback_hash,
                    title="",
                    published_date="",
                    author="",
                    publisher=""
                )

        return None

