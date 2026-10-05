"""Design-system contracts: what a design system offers, pinned to a library version.

A contract maps every IR construct (``heading:1``, ``field:select``,
``action:primary``…) to the design system's component, and semantic token
names to the library's tokens. It is data, versioned, and checked:

* completeness here (every IR construct is mapped or explicitly unsupported),
* accuracy in the web test suite, which verifies that every component and token
  named by the Fluent 2 contract is exported by the *installed* library.

Organization design systems (Milestone 7) will be further contracts in the same
format.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Every IR construct an adapter must handle. Keys are ``kind`` or ``kind:variant``.
IR_CONSTRUCTS: tuple[str, ...] = (
    "heading:1",
    "heading:2",
    "heading:3",
    "heading:4",
    "text:default",
    "text:subtle",
    "section",
    "form",
    "field:text",
    "field:textarea",
    "field:number",
    "field:date",
    "field:datetime",
    "field:select",
    "field:checkbox",
    "field:file",
    "action:primary",
    "action:secondary",
    "action:danger",
    "table",
    "stat",
    "message",
    "toolbar",
)


class ComponentMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    #: Component path, outermost first, e.g. ["Field", "Select"]. Lowercase names are HTML elements.
    components: tuple[str, ...] = Field(min_length=1)
    package: str
    notes: str | None = None


class LibraryRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    package: str
    #: The exact version the contract was checked against (the workspace's lockfile).
    version: str
    docs_url: str


class DesignSystemContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["1"] = "1"
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,40}$")
    name: str
    version: str
    framework: Literal["react", "angular"]
    library: LibraryRef
    mappings: dict[str, ComponentMapping]
    #: IR constructs this design system deliberately does not support, with the reason.
    unsupported: dict[str, str] = Field(default_factory=dict)
    #: Semantic token name -> library token name.
    tokens: dict[str, str] = Field(default_factory=dict)
    #: Design guidance the adapter applies, stated so reviewers can check it.
    rules: tuple[str, ...] = ()

    def mapping(self, construct: str) -> ComponentMapping | None:
        return self.mappings.get(construct)


def missing_constructs(contract: DesignSystemContract) -> list[str]:
    """IR constructs neither mapped nor declared unsupported."""
    return [c for c in IR_CONSTRUCTS if c not in contract.mappings and c not in contract.unsupported]


@cache
def builtin_contracts() -> dict[str, DesignSystemContract]:
    out: dict[str, DesignSystemContract] = {}
    folder = resources.files(__package__).joinpath("contracts")
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".json"):
            contract = DesignSystemContract.model_validate(json.loads(entry.read_text(encoding="utf-8")))
            out[contract.id] = contract
    return out


def get_contract(contract_id: str) -> DesignSystemContract | None:
    return builtin_contracts().get(contract_id)


def contract_json_schema() -> dict[str, object]:
    schema = DesignSystemContract.model_json_schema()
    schema["$id"] = "urn:workspace:design-system-contract:1"
    schema["title"] = "Design-system contract v1"
    return schema
