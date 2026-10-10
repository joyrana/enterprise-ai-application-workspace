"""Provider-neutral model access for the workspace (see docs/adr/0007-model-providers.md)."""

from .breaker import CircuitBreaker, GuardedProvider
from .budget import Budget
from .config import ModelConfigError, ModelSettings, Profile
from .errors import ErrorKind, ModelError
from .extract import ExtractionError, extract_json_object, strip_reasoning
from .fake import FakeProvider
from .openai_compat import OpenAICompatibleProvider
from .policy import check_data_policy
from .provider import ModelProvider, Prices, RawCompletion, generate_structured
from .schema import CallRecord, Capabilities, Message, StructuredMode, StructuredResult, Usage

__all__ = [
    "Budget",
    "CallRecord",
    "Capabilities",
    "CircuitBreaker",
    "ErrorKind",
    "ExtractionError",
    "FakeProvider",
    "GuardedProvider",
    "Message",
    "ModelConfigError",
    "ModelError",
    "ModelProvider",
    "ModelSettings",
    "OpenAICompatibleProvider",
    "Prices",
    "Profile",
    "RawCompletion",
    "StructuredMode",
    "StructuredResult",
    "Usage",
    "check_data_policy",
    "extract_json_object",
    "generate_structured",
    "strip_reasoning",
]
