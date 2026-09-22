"""Custom exceptions for the medical AI layer."""


class MedicalAIError(Exception):
    """Base exception for the medical AI prototype."""


class ConfigurationError(MedicalAIError):
    """Raised when application configuration is invalid or incomplete."""


class MissingAPIKeyError(ConfigurationError):
    """Raised when GROQ_API_KEY is missing from the environment."""


class LLMClientError(MedicalAIError):
    """Base exception for LLM client failures."""


class LLMConnectionError(LLMClientError):
    """Raised when the LLM provider cannot be reached or authenticated."""


class LLMResponseError(LLMClientError):
    """Raised when the LLM returns an empty or unusable response."""


class StructuredOutputError(LLMClientError):
    """Raised when a JSON/structured response cannot be parsed."""


class MedicalSafetyError(MedicalAIError):
    """Raised when a request would violate clinical-assist safety boundaries."""
