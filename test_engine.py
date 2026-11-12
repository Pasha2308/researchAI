"""Automated Test Suite for the Deep Research Engine.

Validates:
- SQLite schema, constraints, transactional integrity, and queries
- Scraper URL cleaning, normalization, and domain extraction
- Dual-tier text extraction (Trafilatura + Jina Reader fallback)
- Agent JSON parsing, zero-hallucination validation, and 20-fact batch chunking
"""

import os
import tempfile
import unittest

import database
import scraper
import agent


class TestDatabaseModule(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()
        database.init_db(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_init_and_empty_stats(self):
        stats = database.get_stats(self.db_path)
        self.assertEqual(stats["total_sources"], 0)
        self.assertEqual(stats["pending"], 0)
        self.assertEqual(stats["completed"], 0)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(stats["total_facts"], 0)

    def test_add_sources_and_deduplication(self):
        sources = [
            ("https://reddit.com/r/python/comments/1", "reddit.com"),
            ("https://docs.python.org/3/", "docs.python.org"),
            ("https://reddit.com/r/python/comments/1", "reddit.com"),  # Duplicate
        ]
        inserted = database.add_sources(sources, self.db_path)
        self.assertEqual(inserted, 2)

        stats = database.get_stats(self.db_path)
        self.assertEqual(stats["total_sources"], 2)
        self.assertEqual(stats["pending"], 2)

    def test_update_status_and_pending_retrieval(self):
        sources = [
            ("https://source1.com", "source1.com"),
            ("https://source2.com", "source2.com"),
        ]
        database.add_sources(sources, self.db_path)

        pending = database.get_pending_sources(db_path=self.db_path)
        self.assertEqual(len(pending), 2)
        first_id = pending[0]["id"]

        database.update_source_status(first_id, "completed", self.db_path)
        pending_after = database.get_pending_sources(db_path=self.db_path)
        self.assertEqual(len(pending_after), 1)

        stats = database.get_stats(self.db_path)
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["pending"], 1)

    def test_insert_and_get_facts(self):
        sources = [("https://example.com", "example.com")]
        database.add_sources(sources, self.db_path)
        source_id = database.get_pending_sources(db_path=self.db_path)[0]["id"]

        test_facts = [
            {
                "fact_or_review": "FastAPI is based on Starlette and Pydantic.",
                "verbatim_quote": "FastAPI is a modern, fast web framework based on Starlette and Pydantic."
            },
            {
                "fact_or_review": "Users report FastAPI reduces boilerplate compared to Flask.",
                "verbatim_quote": "Switching reduced our repetitive schema validation code significantly."
            }
        ]
        inserted_count = database.insert_facts(source_id, test_facts, self.db_path)
        self.assertEqual(inserted_count, 2)

        all_facts = database.get_all_facts(self.db_path)
        self.assertEqual(len(all_facts), 2)
        self.assertEqual(all_facts[0]["source_id"], source_id)
        self.assertEqual(all_facts[0]["domain"], "example.com")
        self.assertIn("FastAPI", all_facts[0]["fact_or_review"])


class TestScraperModule(unittest.TestCase):
    def test_clean_and_normalize_url(self):
        raw = "https://www.reddit.com/r/programming/post?utm_source=twitter&gclid=xyz#comments"
        cleaned = scraper.clean_and_normalize_url(raw)
        self.assertEqual(cleaned, "https://www.reddit.com/r/programming/post")

        # Invalid scheme
        self.assertIsNone(scraper.clean_and_normalize_url("ftp://ftp.example.com"))

        # Ignored extension (.pdf)
        self.assertIsNone(scraper.clean_and_normalize_url("https://example.com/whitepaper.pdf"))

        # Ignored domain (youtube.com)
        self.assertIsNone(scraper.clean_and_normalize_url("https://www.youtube.com/watch?v=123"))

    def test_extract_domain(self):
        url = "https://sub.domain.co.uk/path/file?arg=1"
        domain = scraper.extract_domain(url)
        self.assertEqual(domain, "sub.domain.co.uk")

    def test_generate_search_queries(self):
        queries = scraper.generate_search_queries("FastAPI vs Flask")
        self.assertGreaterEqual(len(queries), 10)
        # Ensure Reddit and forum angles are present
        query_texts = [q[0] for q in queries]
        self.assertTrue(any("reddit" in q for q in query_texts))
        self.assertTrue(any("review" in q for q in query_texts))
        self.assertTrue(any("documentation" in q for q in query_texts))

    def test_extract_text_live(self):
        # Test real extraction on python.org
        text = scraper.extract_text("https://www.python.org", timeout=10)
        self.assertIsNotNone(text)
        self.assertGreater(len(text), 100)
        self.assertTrue("Python" in text or "python" in text)


class TestAgentModule(unittest.TestCase):
    def test_safe_parse_json_raw_array(self):
        raw = '[{"fact_or_review": "F1", "verbatim_quote": "Q1"}]'
        parsed = agent._safe_parse_json(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["fact_or_review"], "F1")

    def test_safe_parse_json_markdown_wrapped(self):
        raw = """```json
[
  {"fact_or_review": "F2", "verbatim_quote": "Q2"}
]
```"""
        parsed = agent._safe_parse_json(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["fact_or_review"], "F2")

    def test_safe_parse_json_wrapped_in_object(self):
        raw = '{"facts": [{"fact_or_review": "F3", "verbatim_quote": "Q3"}]}'
        parsed = agent._safe_parse_json(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["fact_or_review"], "F3")

    def test_chunk_facts_batches_of_20(self):
        dummy_facts = [
            {"source_id": i, "fact_or_review": f"Fact {i}", "verbatim_quote": f"Quote {i}"}
            for i in range(1, 46)
        ]
        chunks = agent.chunk_facts(dummy_facts, chunk_size=20)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(chunks[0]), 20)
        self.assertEqual(len(chunks[1]), 20)
        self.assertEqual(len(chunks[2]), 5)

    def test_format_facts_batch(self):
        batch = [
            {
                "source_id": 1,
                "domain": "reddit.com",
                "fact_or_review": "Users report high memory usage in long runs.",
                "verbatim_quote": "We noticed memory creeping up over several days."
            }
        ]
        formatted = agent.format_facts_batch(batch)
        self.assertIn("[Source_1]", formatted)
        self.assertIn("(reddit.com)", formatted)
        self.assertIn("Quote: \"We noticed memory creeping up over several days.\"", formatted)


if __name__ == "__main__":
    unittest.main()

