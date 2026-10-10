"""UI intermediate representation, design-system contracts and adapters (ADR-0013)."""

from .contract import (
    IR_CONSTRUCTS,
    ComponentMapping,
    DesignSystemContract,
    builtin_contracts,
    contract_json_schema,
    get_contract,
    missing_constructs,
)
from .derive import derive_document, humanize
from .ir import IR_VERSION, Screen, UiDocument, json_schema
from .resolve import AdapterError, RenderedScreen, RenderNode, components_used, has_adapter, render_screens
from .theme import ORG_PREFIX, BrandTheme, BrandThemeSet, brand_ramp, contrast
from .validate import UiIssue, validate_document

__all__ = [
    "IR_CONSTRUCTS",
    "IR_VERSION",
    "ORG_PREFIX",
    "AdapterError",
    "BrandTheme",
    "BrandThemeSet",
    "ComponentMapping",
    "DesignSystemContract",
    "RenderNode",
    "RenderedScreen",
    "Screen",
    "UiDocument",
    "UiIssue",
    "brand_ramp",
    "builtin_contracts",
    "components_used",
    "contract_json_schema",
    "contrast",
    "derive_document",
    "get_contract",
    "has_adapter",
    "humanize",
    "json_schema",
    "missing_constructs",
    "render_screens",
    "validate_document",
]
