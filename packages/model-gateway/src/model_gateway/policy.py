"""Data-classification policy: which projects may be sent to which model.

Checked before any prompt is built. Remote endpoints (for example the Hugging
Face router, which forwards prompts to third-party inference providers) are
refused for ``confidential`` and ``restricted`` projects unless an operator
explicitly allows it.
"""

from __future__ import annotations

from .errors import ErrorKind, ModelError
from .schema import Capabilities

SENSITIVE = frozenset({"confidential", "restricted"})


def check_data_policy(capabilities: Capabilities, classification: str | None, *, allow_remote: bool) -> None:
    if capabilities.remote and classification in SENSITIVE and not allow_remote:
        raise ModelError(
            ErrorKind.POLICY_DENIED,
            f"project classified '{classification}' may not use a remote model; configure a local profile",
        )
