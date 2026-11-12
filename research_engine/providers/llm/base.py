"""Abstract base classes for LLM inference providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class LLMProviderError(Exception):
    """Raised when an LLM provider encounters an unrecoverable error."""
    pass


class ModelUnavailableError(LLMProviderError):
    """Raised when the specified model ID is not available or deprecated."""
    pass


class BaseLLMProvider(ABC):
    """Abstract interface for LLM completion and structured output."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass

    @abstractmethod
    def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        json_mode: bool = False,
        **kwargs: Any
    ) -> str:
        """Execute chat completion and return response text."""
        pass

    @abstractmethod
    def validate_model(self, model: str) -> Tuple[bool, str, List[str]]:
        """Validate if a model is available on the provider.
        
        Returns: (is_valid, message, available_models_list)
        """
        pass

