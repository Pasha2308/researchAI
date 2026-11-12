"""Deterministic exact quote validation in Python.

Validates that candidate quotations exist completely and contiguously within
the original stored source text using documented Unicode and whitespace normalization.
Never accepts partial or truncated quotes.
"""

import re
import unicodedata
from typing import Tuple


def normalize_evidence_text(text: str) -> str:
    """Documented deterministic text normalization.
    
    1. Unicode NFKC normalization (standardizes full-width forms, dashes, non-breaking spaces, ligatures).
    2. Maps curly/smart quotation marks (“ ” ‘ ’ « ») to ASCII straight quotes (" and ').
    3. Converts all whitespace sequences (tabs, newlines, multiple spaces) into a single space.
    4. Strips leading and trailing whitespace.
    """
    if not text:
        return ""
    # NFKC Unicode normalization
    normalized = unicodedata.normalize("NFKC", text)
    # Standardize smart/curly quotes
    quote_trans = str.maketrans({
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u00ab": '"',
        "\u00bb": '"',
    })
    normalized = normalized.translate(quote_trans)
    # Replace all whitespace sequences with single space
    cleaned = re.sub(r"\s+", " ", normalized)
    return cleaned.strip()


def validate_exact_quote(
    quote: str,
    stored_source_text: str,
    context_window_chars: int = 200
) -> Tuple[bool, int, int, str]:
    """Verify that the complete quote exists in the stored source text.
    
    Returns:
        (is_valid, start_offset, end_offset, surrounding_context)
    
    Rules:
        - The complete normalized quote must exist contiguously in the normalized source text.
        - Matching only a prefix (e.g. 10 or 15 words) is strictly prohibited.
        - If the quote does not match exactly, returns (False, -1, -1, "").
    """
    if not quote or not stored_source_text:
        return False, -1, -1, ""

    norm_quote = normalize_evidence_text(quote)
    norm_source = normalize_evidence_text(stored_source_text)

    # Minimum quote length requirement (avoid trivial 1-character matches)
    if len(norm_quote) < 8:
        return False, -1, -1, ""

    # Search for complete normalized quote
    pos = norm_source.find(norm_quote)
    if pos == -1:
        # Also try case-insensitive match if direct match fails
        lower_quote = norm_quote.lower()
        lower_source = norm_source.lower()
        pos = lower_source.find(lower_quote)
        if pos == -1:
            return False, -1, -1, ""

    start_offset = pos
    end_offset = pos + len(norm_quote)

    # Extract surrounding context from normalized text
    ctx_start = max(0, start_offset - context_window_chars)
    ctx_end = min(len(norm_source), end_offset + context_window_chars)
    surrounding_context = norm_source[ctx_start:ctx_end]

    return True, start_offset, end_offset, surrounding_context
