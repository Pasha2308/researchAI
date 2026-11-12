"""Safe HTTP Fetcher with SSRF validation, redirect inspection, and streaming size capping."""

import hashlib
import logging
import urllib.parse
from typing import Dict, List, Optional, Tuple
import httpx

from config import settings
from research_engine.security.ssrf import validate_url, SSRFSecurityError

logger = logging.getLogger("research_engine.fetchers.safe")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

PERMITTED_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
)


class FetchError(Exception):
    """Base exception for fetching errors."""
    pass


class ResponseTooLargeError(FetchError):
    """Raised when response body exceeds maximum allowed bytes while streaming."""
    pass


class FetchResult:
    """Encapsulates the result of a safe fetch operation."""

    def __init__(
        self,
        final_url: str,
        http_status: int,
        content_bytes: bytes,
        content_type: str,
        content_hash: str,
        redirect_chain: List[str]
    ):
        self.final_url = final_url
        self.http_status = http_status
        self.content_bytes = content_bytes
        self.content_type = content_type
        self.content_hash = content_hash
        self.redirect_chain = redirect_chain

    @property
    def text(self) -> str:
        """Decode content bytes safely."""
        try:
            return self.content_bytes.decode("utf-8", errors="replace")
        except Exception:
            return str(self.content_bytes)


class SafeHTTPFetcher:
    """HTTP Client enforcing SSRF defenses, streaming size limits, and safe redirects."""

    def __init__(
        self,
        timeout_seconds: float = settings.fetch_timeout_seconds,
        max_response_bytes: int = settings.max_response_bytes,
        max_redirects: int = settings.max_redirects,
        user_agent: str = DEFAULT_USER_AGENT
    ):
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_redirects = max_redirects
        self.user_agent = user_agent

    def fetch(self, url: str) -> FetchResult:
        """Safely fetch a URL with SSRF checks on initial URL and all redirect hops."""
        # 1. SSRF check on initial URL
        current_url = validate_url(url, block_private_ips=settings.block_private_ips)
        redirect_chain: List[str] = [current_url]

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # Use follow_redirects=False so we manually validate every redirect destination
        with httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            verify=True
        ) as client:
            hops = 0
            while hops <= self.max_redirects:
                try:
                    # Stream the response to enforce byte limit during download
                    with client.stream("GET", current_url, headers=headers) as response:
                        status_code = response.status_code

                        # Handle redirects manually with SSRF checks
                        if status_code in (301, 302, 303, 307, 308):
                            location = response.headers.get("Location")
                            if not location:
                                raise FetchError(f"HTTP {status_code} redirect missing Location header.")

                            # Resolve relative redirects
                            resolved_target = urllib.parse.urljoin(current_url, location)
                            # Validate redirect target against SSRF
                            current_url = validate_url(
                                resolved_target,
                                block_private_ips=settings.block_private_ips
                            )
                            redirect_chain.append(current_url)
                            hops += 1
                            continue

                        # Check HTTP status
                        if status_code >= 400:
                            raise FetchError(f"HTTP error {status_code} fetching '{current_url}'")

                        # Validate Content-Type
                        content_type = response.headers.get("Content-Type", "").lower()
                        is_permitted_type = any(t in content_type for t in PERMITTED_CONTENT_TYPES)
                        if not is_permitted_type:
                            raise FetchError(
                                f"Unsupported Content-Type '{content_type}' at '{current_url}'. Only web text/HTML is allowed."
                            )

                        # Stream chunks and enforce byte cap
                        body_chunks: List[bytes] = []
                        total_bytes = 0
                        chunk_size = 8192

                        for chunk in response.iter_bytes(chunk_size=chunk_size):
                            total_bytes += len(chunk)
                            if total_bytes > self.max_response_bytes:
                                raise ResponseTooLargeError(
                                    f"Response exceeded maximum limit of {self.max_response_bytes} bytes (read {total_bytes} bytes)."
                                )
                            body_chunks.append(chunk)

                        content_bytes = b"".join(body_chunks)
                        content_hash = hashlib.sha256(content_bytes).hexdigest()

                        return FetchResult(
                            final_url=current_url,
                            http_status=status_code,
                            content_bytes=content_bytes,
                            content_type=content_type,
                            content_hash=content_hash,
                            redirect_chain=redirect_chain
                        )

                except httpx.TimeoutException as e:
                    raise FetchError(f"Request timed out after {self.timeout_seconds}s for '{current_url}': {e}")
                except httpx.RequestError as e:
                    raise FetchError(f"Network error requesting '{current_url}': {e}")

            raise FetchError(f"Too many redirects (exceeded limit of {self.max_redirects}).")

