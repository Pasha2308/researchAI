"""Centralized configuration for the Evidence-First Deep Research Engine.

Provides typed, validated settings with environment variable overrides,
strict resource boundaries for 8GB RAM environments, and sensible defaults.
"""

import os
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# Load environment variables from .env
load_dotenv(BASE_DIR / ".env")


def _get_bool(env_var: str, default: bool) -> bool:
    val = os.getenv(env_var)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes", "on")


class Settings(BaseModel):
    """Application settings with environment variable support."""

    # Base Paths
    base_dir: Path = BASE_DIR
    data_dir: Path = DATA_DIR
    reports_dir: Path = REPORTS_DIR
    database_path: str = Field(
        default_factory=lambda: os.getenv("DATABASE_PATH", str(DATA_DIR / "research_vault.db"))
    )

    # Groq LLM Configuration
    groq_api_key: str = Field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    groq_model: str = Field(default_factory=lambda: os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
    groq_verifier_model: str = Field(
        default_factory=lambda: os.getenv("GROQ_VERIFIER_MODEL", "openai/gpt-oss-20b")
    )
    groq_max_retries: int = Field(default_factory=lambda: int(os.getenv("GROQ_MAX_RETRIES", "5")))
    groq_retry_base_seconds: float = Field(
        default_factory=lambda: float(os.getenv("GROQ_RETRY_BASE_SECONDS", "2.0"))
    )
    groq_retry_max_seconds: float = Field(
        default_factory=lambda: float(os.getenv("GROQ_RETRY_MAX_SECONDS", "30.0"))
    )

    # Research Limits & Parameters
    default_target_sources: int = Field(
        default_factory=lambda: int(os.getenv("TARGET_SOURCES", "100"))
    )
    max_research_rounds: int = Field(
        default_factory=lambda: int(os.getenv("MAX_RESEARCH_ROUNDS", "3"))
    )
    per_domain_url_limit: int = Field(
        default_factory=lambda: int(os.getenv("PER_DOMAIN_URL_LIMIT", "6"))
    )
    search_region: Optional[str] = Field(default_factory=lambda: os.getenv("SEARCH_REGION", None))
    search_recency: Optional[str] = Field(default_factory=lambda: os.getenv("SEARCH_RECENCY", None))

    # Free Structured Source Providers
    enable_ddgs: bool = Field(default_factory=lambda: _get_bool("ENABLE_DDGS", True))
    enable_hackernews: bool = Field(default_factory=lambda: _get_bool("ENABLE_HACKERNEWS", True))
    enable_openalex: bool = Field(default_factory=lambda: _get_bool("ENABLE_OPENALEX", True))
    enable_arxiv: bool = Field(default_factory=lambda: _get_bool("ENABLE_ARXIV", True))

    # Fetching & Extraction Controls
    fetch_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("FETCH_TIMEOUT_SECONDS", "15.0"))
    )
    max_redirects: int = Field(default_factory=lambda: int(os.getenv("MAX_REDIRECTS", "5")))
    max_response_bytes: int = Field(
        default_factory=lambda: int(os.getenv("MAX_RESPONSE_BYTES", str(5 * 1024 * 1024)))
    )  # 5 MB
    fetch_concurrency: int = Field(default_factory=lambda: int(os.getenv("FETCH_CONCURRENCY", "3")))
    inter_request_delay_seconds: float = Field(
        default_factory=lambda: float(os.getenv("INTER_REQUEST_DELAY_SECONDS", "1.5"))
    )

    # Jina Reader Fallback (controlled, never treated as authority)
    enable_jina_fallback: bool = Field(
        default_factory=lambda: _get_bool("ENABLE_JINA_FALLBACK", True)
    )
    jina_base_url: str = Field(
        default_factory=lambda: os.getenv("JINA_BASE_URL", "https://r.jina.ai/")
    )
    jina_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("JINA_TIMEOUT_SECONDS", "15.0"))
    )

    # Security & SSRF Safeguards
    block_private_ips: bool = Field(default_factory=lambda: _get_bool("BLOCK_PRIVATE_IPS", True))
    allowed_ports: List[int] = Field(default_factory=lambda: [80, 443, 8080, 8443])

    # User Interface
    dashboard_host: str = Field(default_factory=lambda: os.getenv("DASHBOARD_HOST", "127.0.0.1"))
    dashboard_port: int = Field(default_factory=lambda: int(os.getenv("DASHBOARD_PORT", "8501")))

    # Maximum characters for stored extracted text to prevent RAM overflow
    max_extracted_chars: int = Field(
        default_factory=lambda: int(os.getenv("MAX_EXTRACTED_CHARS", "50000"))
    )


# Global instance
settings = Settings()
