"""Groq inference provider implementation.

Includes dynamic model verification via client.models.list(),
Retry-After header parsing, exponential backoff with jitter,
and transparent fallback reporting.
"""

import logging
import random
import time
from typing import Any, Dict, List, Optional, Tuple

import groq
from groq import Groq

from research_engine.providers.llm.base import (
    BaseLLMProvider,
    LLMProviderError,
    ModelUnavailableError,
)

logger = logging.getLogger("research_engine.llm.groq")


class GroqLLMProvider(BaseLLMProvider):
    """Groq API inference provider with dynamic validation and rate-limit handling."""

    def __init__(
        self,
        api_key: str,
        default_model: str = "llama-3.3-70b-versatile",
        max_retries: int = 5,
        base_retry_seconds: float = 2.0,
        max_retry_seconds: float = 30.0
    ):
        if not api_key or not api_key.strip():
            raise ValueError("Groq API key must not be empty.")
        self.api_key = api_key.strip()
        self.default_model = default_model
        self.max_retries = max_retries
        self.base_retry_seconds = base_retry_seconds
        self.max_retry_seconds = max_retry_seconds
        self._client: Optional[Groq] = None
        self._available_models_cache: Optional[List[str]] = None
        # Token usage tracking
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_tokens: int = 0
        self.last_model_used: Optional[str] = None

    @property
    def name(self) -> str:
        return "groq"

    def get_token_stats(self) -> Dict[str, int]:
        """Return cumulative token usage statistics."""
        return {
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
        }

    def get_client(self) -> Groq:
        """Lazy-initialize Groq client."""
        if self._client is None:
            self._client = Groq(api_key=self.api_key)
        return self._client

    def list_available_models(self) -> List[str]:
        """Fetch real-time list of available models from the Groq API."""
        if self._available_models_cache is not None:
            return self._available_models_cache

        client = self.get_client()
        try:
            model_list = client.models.list()
            models = [m.id for m in model_list.data if getattr(m, "active", True)]
            self._available_models_cache = models
            return models
        except Exception as e:
            logger.warning(f"Failed to list Groq models: {e}")
            return []

    def validate_model(self, model: str) -> Tuple[bool, str, List[str]]:
        """Validate configured model against Groq account availability."""
        models = self.list_available_models()
        if not models:
            # If listing failed due to network or permission, allow execution
            return True, "Unable to list models; proceeding with configured model ID.", []

        if model in models:
            return True, f"Model '{model}' is active and available.", models

        return (
            False,
            f"Model '{model}' is not found in active Groq models.",
            models
        )

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        json_mode: bool = False,
        **kwargs: Any
    ) -> str:
        """Execute chat completion with rate-limit and backoff handling."""
        client = self.get_client()
        target_model = model or self.default_model

        # Check model availability against active models
        available_models = self.list_available_models()
        if available_models and target_model not in available_models:
            # Check for candidate replacement
            suitable_fallback = None
            for candidate in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]:
                if candidate in available_models:
                    suitable_fallback = candidate
                    break
            if suitable_fallback:
                logger.warning(
                    f"Configured model '{target_model}' is not active in your Groq account. "
                    f"Selecting verified active model '{suitable_fallback}' instead."
                )
                target_model = suitable_fallback
            else:
                target_model = available_models[0]
                logger.warning(
                    f"Configured model '{model}' not active. Using first available model: '{target_model}'."
                )

        self.last_model_used = target_model

        kwargs_payload: Dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs_payload["response_format"] = {"type": "json_object"}

        attempt = 1
        while attempt <= self.max_retries:
            try:
                response = client.chat.completions.create(**kwargs_payload)
                # Accumulate token usage if present
                if hasattr(response, "usage") and response.usage:
                    self.total_prompt_tokens += getattr(response.usage, "prompt_tokens", 0) or 0
                    self.total_completion_tokens += getattr(response.usage, "completion_tokens", 0) or 0
                    self.total_tokens += getattr(response.usage, "total_tokens", 0) or 0

                return response.choices[0].message.content or ""

            except groq.NotFoundError as e:
                # Model doesn't exist or is deprecated
                raise ModelUnavailableError(
                    f"Groq model '{target_model}' not found: {e}. Check available models."
                )

            except groq.AuthenticationError as e:
                # Fatal auth error, do not retry
                raise LLMProviderError(f"Groq authentication failed: {e}")

            except groq.BadRequestError as e:
                # JSON schema validation failure or oversized generation — not retriable as-is
                error_msg = str(e)
                if "json_validate_failed" in error_msg or "Failed to generate JSON" in error_msg:
                    raise LLMProviderError(
                        f"Groq JSON generation failed (output too long or schema violated). "
                        f"Try reducing max_tokens or simplifying the prompt. Original: {e}"
                    )
                raise LLMProviderError(f"Groq bad request: {e}")

            except (groq.RateLimitError, groq.APIConnectionError, groq.InternalServerError) as e:
                if attempt >= self.max_retries:
                    raise LLMProviderError(f"Groq API call failed after {self.max_retries} attempts: {e}")

                # Check for Retry-After header
                wait_time = None
                if hasattr(e, "response") and e.response is not None:
                    retry_after = e.response.headers.get("Retry-After") or e.response.headers.get("retry-after")
                    if retry_after:
                        try:
                            wait_time = float(retry_after)
                        except ValueError:
                            pass

                if wait_time is None:
                    # Exponential backoff with random jitter
                    jitter = random.uniform(0.1, 1.2)
                    wait_time = min(
                        self.max_retry_seconds,
                        self.base_retry_seconds * (2 ** (attempt - 1)) + jitter
                    )

                logger.warning(
                    f"Groq API {type(e).__name__} (attempt {attempt}/{self.max_retries}). "
                    f"Waiting {wait_time:.1f}s before retry..."
                )
                time.sleep(wait_time)
                attempt += 1

            except Exception as e:
                raise LLMProviderError(f"Unexpected Groq client error: {e}")

        raise LLMProviderError("Max retries exceeded.")

