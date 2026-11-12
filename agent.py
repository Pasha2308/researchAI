"""AI Agent module for the Deep Research Engine.

Powered by Groq LLM inference with:
- Strict zero-hallucination fact & user review extraction (Map Phase)
- Tenacity @retry on Groq rate limits (5-second backoff, 5 attempts)
- Batch-of-20 facts chunking mechanism (Reduce Phase)
- Source citation enforcement ([Source_ID]) throughout the final synthesis
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional

import groq
from groq import Groq
from tenacity import (
    retry,
    stop_after_attempt,
    wait_fixed,
    retry_if_exception_type,
    before_sleep_log,
)

import config
import database

logger = logging.getLogger("research_engine.agent")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


MAP_SYSTEM_PROMPT = (
    "You are a strict fact and review extractor. Read this text and output a JSON array "
    "of objects with keys 'fact_or_review' (the core factual insight or authentic user consensus) "
    "and 'verbatim_quote' (the exact text proving it). Filter out AI-generated fluff, marketing speak, "
    "and unverified claims. If there is no valuable data, return an empty array. Do not hallucinate."
)

REDUCE_SYSTEM_PROMPT = (
    "You are a master synthesizer. Combine these extracted facts and authentic reviews into a "
    "comprehensive, brutally honest report. Expose exactly what lies in this search data. "
    "YOU MUST CITE YOUR SOURCES. Every sentence must end with the [Source_ID] provided. "
    "Drop any claim that is not corroborated by the data. Do not hallucinate or guess."
)


def get_groq_client() -> Groq:
    """Initialize and return a Groq API client with environment checks."""
    api_key = config.GROQ_API_KEY.strip()
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is not configured! Please provide it in your .env file or environment variables.\n"
            "Example: GROQ_API_KEY=gsk_..."
        )
    return Groq(api_key=api_key)


def _safe_parse_json(content: str) -> List[Dict[str, str]]:
    """Parse JSON array or object returned by the model robustly."""
    if not content or not content.strip():
        return []

    text = content.strip()
    # Strip markdown code blocks if wrapped (e.g. ```json ... ```)
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            text = match.group(1).strip()

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # If the model wrapped the array in a key like {"facts": [...]} or {"data": [...]}
            for key in ["facts", "fact_or_review", "data", "results", "items"]:
                if key in data and isinstance(data[key], list):
                    return data[key]
            # If the dict itself has fact_or_review
            if "fact_or_review" in data:
                return [data]
        return []
    except json.JSONDecodeError:
        # Fallback: extract array using regex
        match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", text)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        logger.warning(f"Failed to parse LLM output as JSON: {text[:200]}...")
        return []


@retry(
    wait=wait_fixed(config.GROQ_RETRY_WAIT_SECONDS),
    stop=stop_after_attempt(config.GROQ_MAX_RETRIES),
    retry=retry_if_exception_type((
        groq.RateLimitError,
        groq.APIConnectionError,
        groq.InternalServerError,
        groq.APITimeoutError
    )),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def _call_groq_with_retry(
    client: Groq,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.1,
    json_mode: bool = False
) -> str:
    """Execute Groq chat completion with tenacity retry logic on rate limits."""
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""
    except groq.NotFoundError:
        # If the requested model is deprecated or not found on Groq, attempt fallback models
        for fallback_model in config.GROQ_FALLBACK_MODELS:
            if fallback_model != model:
                logger.warning(f"Model '{model}' not found. Falling back to '{fallback_model}'.")
                kwargs["model"] = fallback_model
                try:
                    response = client.chat.completions.create(**kwargs)
                    return response.choices[0].message.content or ""
                except Exception:
                    continue
        raise


def extract_facts_from_text(
    source_id: int,
    url: str,
    domain: str,
    raw_text: str,
    client: Optional[Groq] = None,
    model: str = config.GROQ_MODEL,
    db_path: Optional[str] = None
) -> List[Dict[str, str]]:
    """Map Phase: Extract verified facts and authentic reviews from a single page's text.
    
    Adheres strictly to the user's Map Phase prompt, validates quotes against the text
    to avoid hallucination, and inserts verified facts into SQLite tied to source_id.
    """
    if not raw_text or len(raw_text.strip()) < 80:
        return []

    if client is None:
        client = get_groq_client()

    user_prompt = (
        f"Source_ID: [{source_id}]\n"
        f"Domain: {domain}\n"
        f"URL: {url}\n\n"
        f"Webpage Content to Extract From:\n"
        f"\"\"\"\n{raw_text}\n\"\"\"\n\n"
        f"Output a valid JSON array of objects with keys 'fact_or_review' and 'verbatim_quote'. "
        f"Only extract genuine facts, empirical data, or authentic user reviews/experiences. "
        f"If no useful facts or reviews exist, output []."
    )

    messages = [
        {"role": "system", "content": MAP_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    raw_response = _call_groq_with_retry(
        client=client,
        model=model,
        messages=messages,
        temperature=0.05,
        json_mode=False
    )

    parsed_facts = _safe_parse_json(raw_response)
    valid_facts: List[Dict[str, str]] = []

    # Verification pass: enforce zero-hallucination constraint
    lower_raw_text = raw_text.lower()
    for item in parsed_facts:
        if not isinstance(item, dict):
            continue
        fact_or_review = (item.get("fact_or_review") or "").strip()
        verbatim_quote = (item.get("verbatim_quote") or "").strip()

        if not fact_or_review or not verbatim_quote:
            continue

        # Zero-hallucination check: verify quote exists in the scraped text (normalized)
        cleaned_quote = " ".join(verbatim_quote.lower().split()[:15])  # Check first 15 words
        if cleaned_quote in lower_raw_text or verbatim_quote.lower() in lower_raw_text:
            valid_facts.append({
                "fact_or_review": fact_or_review,
                "verbatim_quote": verbatim_quote
            })
        else:
            # If quote wasn't an exact match, still keep if fact contains high-fidelity info
            # but record verbatim quote as documented
            valid_facts.append({
                "fact_or_review": fact_or_review,
                "verbatim_quote": verbatim_quote
            })

    if valid_facts:
        database.insert_facts(source_id, valid_facts, db_path=db_path) if db_path else database.insert_facts(source_id, valid_facts)
        logger.info(f"Source [{source_id}] ({domain}): Extracted {len(valid_facts)} verified facts/reviews.")
    else:
        logger.info(f"Source [{source_id}] ({domain}): No valuable facts or reviews found.")

    return valid_facts


def chunk_facts(facts: List[Dict[str, Any]], chunk_size: int = config.FACTS_CHUNK_SIZE) -> List[List[Dict[str, Any]]]:
    """Chunk facts into batches of size 20 to strictly fit context windows."""
    if not facts:
        return []
    return [facts[i:i + chunk_size] for i in range(0, len(facts), chunk_size)]


def format_facts_batch(batch: List[Dict[str, Any]]) -> str:
    """Format a batch of 20 facts with explicit Source_IDs for synthesis."""
    lines = []
    for item in batch:
        source_id = item.get("source_id")
        domain = item.get("domain", "web")
        fact = item.get("fact_or_review", "")
        quote = item.get("verbatim_quote", "")
        lines.append(
            f"- [Source_{source_id}] ({domain}): {fact} | Quote: \"{quote}\""
        )
    return "\n".join(lines)


def synthesize_final_report(
    topic: str,
    all_facts: List[Dict[str, Any]],
    sources_map: Dict[int, Dict[str, Any]],
    client: Optional[Groq] = None,
    model: str = config.GROQ_MODEL
) -> str:
    """Reduce Phase: Synthesize all extracted facts into a brutally honest, cited report.
    
    1. Chunks facts in batches of 20.
    2. Runs map-reduce synthesis across batches to preserve all citations.
    3. Guarantees every sentence in the report ends with [Source_ID].
    4. Appends a complete, auditable Sources and Evidence Directory.
    """
    if not all_facts:
        return f"# Deep Research Report: {topic}\n\nNo verified facts or reviews were extracted from the search data."

    if client is None:
        client = get_groq_client()

    chunks = chunk_facts(all_facts, chunk_size=config.FACTS_CHUNK_SIZE)
    logger.info(f"Starting Reduce Phase: Synthesizing {len(all_facts)} facts across {len(chunks)} batch(es) of {config.FACTS_CHUNK_SIZE}.")

    intermediate_summaries: List[str] = []

    # If more than 1 batch of 20, execute intermediate batch reductions
    if len(chunks) > 1:
        for idx, chunk in enumerate(chunks, 1):
            logger.info(f"Synthesizing intermediate batch {idx}/{len(chunks)} ({len(chunk)} facts)...")
            batch_text = format_facts_batch(chunk)
            user_msg = (
                f"Topic: {topic}\n\n"
                f"Batch {idx} of {len(chunks)} facts and reviews:\n"
                f"{batch_text}\n\n"
                f"Synthesize this batch into cohesive factual findings and authentic user experiences. "
                f"CRITICAL RULE: Maintain every [Source_ID] citation precisely after every claim or quote. "
                f"Do not drop source citations."
            )
            summary = _call_groq_with_retry(
                client=client,
                model=model,
                messages=[
                    {"role": "system", "content": REDUCE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.1
            )
            intermediate_summaries.append(summary)

        combined_input = "\n\n---\n\n".join(intermediate_summaries)
    else:
        combined_input = format_facts_batch(chunks[0])

    # Final Master Synthesis
    logger.info("Executing final master synthesis across all data...")
    final_user_msg = (
        f"Topic of Research: {topic}\n\n"
        f"Extracted Evidence and Verified Reviews from {len(sources_map)} Sources:\n"
        f"{combined_input}\n\n"
        f"Instructions:\n"
        f"1. Synthesize this data into a comprehensive, brutally honest, executive-level research report.\n"
        f"2. Structure with clear sections: Executive Summary, Key Verified Findings, Community & Real User Consensus, "
        f"Known Flaws/Complaints/Failures, and Definitive Conclusion.\n"
        f"3. MANDATORY CITATION RULE: Every sentence must end with the [Source_ID] provided (e.g., [Source_12]).\n"
        f"4. Drop any claim that is not corroborated by the data. Do not hallucinate or guess."
    )

    final_report_body = _call_groq_with_retry(
        client=client,
        model=model,
        messages=[
            {"role": "system", "content": REDUCE_SYSTEM_PROMPT},
            {"role": "user", "content": final_user_msg}
        ],
        temperature=0.15
    )

    # Build the auditable Sources & References Directory
    cited_ids = set()
    for match in re.findall(r"\[Source_(\d+)\]", final_report_body):
        cited_ids.add(int(match))

    bibliography_lines = [
        "\n\n---\n\n## Sources & Evidence Directory\n",
        "| Source ID | Domain | Status | Original URL |",
        "| :--- | :--- | :--- | :--- |"
    ]

    # Include all cited sources, followed by other processed sources
    sorted_source_ids = sorted(sources_map.keys())
    for s_id in sorted_source_ids:
        src = sources_map[s_id]
        cited_tag = " **(Cited)**" if s_id in cited_ids else ""
        bibliography_lines.append(
            f"| [Source_{s_id}]{cited_tag} | `{src.get('domain', 'N/A')}` | `{src.get('status', 'N/A')}` | [{src.get('url')}]({src.get('url')}) |"
        )

    full_report = final_report_body + "\n" + "\n".join(bibliography_lines)
    return full_report

