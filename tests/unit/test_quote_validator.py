"""Unit tests for deterministic exact quote validation.

Covers:
- Test 1: A real exact quote is accepted.
- Test 2: An invented quote is rejected.
- Test 3: A partially altered quote is rejected.
- Regression: Matching only first 10 or 15 words is rejected.
- Unicode NFKC & whitespace normalization.
"""

import unittest
from research_engine.evidence.validator import validate_exact_quote, normalize_evidence_text


class TestExactQuoteValidator(unittest.TestCase):
    def setUp(self):
        self.source_text = (
            "FastAPI is a modern, fast (high-performance), web framework for building APIs "
            "with Python 3.8+ based on standard Python type hints. The key features are: "
            "Fast: Very high performance, on par with NodeJS and Go (thanks to Starlette and Pydantic)."
        )

    def test_01_real_exact_quote_is_accepted(self):
        """Test 1: A real exact quote is accepted with correct character offsets."""
        quote = "web framework for building APIs with Python 3.8+ based on standard Python type hints."
        is_valid, start_off, end_off, ctx = validate_exact_quote(quote, self.source_text)
        self.assertTrue(is_valid)
        self.assertGreater(start_off, 0)
        self.assertGreater(end_off, start_off)
        self.assertIn("Python 3.8+", ctx)

    def test_02_invented_quote_is_rejected(self):
        """Test 2: An invented quote not present in the source text is rejected."""
        invented_quote = "FastAPI has zero bugs and was mathematically proven to never crash."
        is_valid, start_off, end_off, ctx = validate_exact_quote(invented_quote, self.source_text)
        self.assertFalse(is_valid)
        self.assertEqual(start_off, -1)
        self.assertEqual(end_off, -1)
        self.assertEqual(ctx, "")

    def test_03_partially_altered_quote_is_rejected(self):
        """Test 3: A quote with even minor word alterations or inserted adjectives is rejected."""
        altered_quote = "FastAPI is an incredibly modern, fast (high-performance), web framework"
        is_valid, start_off, end_off, ctx = validate_exact_quote(altered_quote, self.source_text)
        self.assertFalse(is_valid)
        self.assertEqual(start_off, -1)

    def test_regression_first_15_words_matching_is_rejected(self):
        """Regression test for old engine defect: checking only first 15 words must NOT pass if rest is hallucinated."""
        # First 15 words are identical, but tail is completely hallucinated
        deceptive_quote = (
            "FastAPI is a modern, fast (high-performance), web framework for building APIs with Python 3.8+ "
            "which completely eliminates the need for any unit tests or QA engineering."
        )
        is_valid, start_off, end_off, ctx = validate_exact_quote(deceptive_quote, self.source_text)
        self.assertFalse(is_valid, "Deceptive quote with hallucinated tail must be strictly rejected.")

    def test_unicode_and_whitespace_normalization(self):
        """Test that Unicode smart quotes and non-breaking spaces are normalized deterministically."""
        text_with_smart_quotes = "The author said: “FastAPI is fast”\u00a0and easy to deploy.\n\nNext line."
        quote_with_ascii_quotes = "The author said: \"FastAPI is fast\" and easy to deploy."
        
        is_valid, start, end, ctx = validate_exact_quote(quote_with_ascii_quotes, text_with_smart_quotes)
        self.assertTrue(is_valid, "NFKC and whitespace normalization should match normalized equivalents.")

    def test_short_trivial_quote_rejected(self):
        """Quotes under 8 characters must be rejected as insufficient evidence."""
        is_valid, _, _, _ = validate_exact_quote("Fast", self.source_text)
        self.assertFalse(is_valid)


if __name__ == "__main__":
    unittest.main()

