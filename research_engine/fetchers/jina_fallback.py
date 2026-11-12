"""Controlled Jina Reader fallback fetcher.

Used only when standard Trafilatura HTML parsing cannot extract content.
Never treated as an authoritative or verification layer.
"""

import hashlib
import logging
import time
from typing import Optional, Tuple
import httpx

from config import settings
from research_engine.security.ssrf import validate_url

logger = logging.getLogger("research_engine.fetchers.jina")


class JinaReaderFallback:
    """Fallback text fetcher using Jina Reader API (https://r.jina.ai/)."""

    def __init__(
        self,
        base_url: str = settings.jina_base_url,
        timeout: float = settings.jina_timeout_seconds,
        min_request_interval: float = 1.0
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.min_request_interval = min_request_interval
        self._last_request_time = 0.0

    def fetch_fallback_text(self, target_url: str) -> Optional[Tuple[str, str]]:
        """Fetch rendered text via Jina Reader.
        
        Returns: (extracted_text, sha256_hash) or None if fetch failed.
        """
        # Validate target URL against SSRF before sending to fallback
        validate_url(target_url, block_private_ips=settings.block_private_ips)

        # Enforce rate limit
        elapsed = time.time() - self._last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)

        jina_url = f"{self.base_url}{target_url}"
        headers = {
            "User-Agent": "EvidenceFirstResearchEngine/1.0",
            "Accept": "text/plain",
            "X-No-Cache": "true",
            "X-Timeout": str(int(self.timeout))
        }

        try:
            self._last_request_time = time.time()
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(jina_url, headers=headers)
                if resp.status_code == 200 and resp.text:
                    text = resp.text.strip()
                    if len(text) >= 100 and not text.startswith("Error:"):
                        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                        return text, content_hash
        except Exception as e:
            logger.debug(f"Jina Reader fallback failed for '{target_url}': {e}")

        return None

