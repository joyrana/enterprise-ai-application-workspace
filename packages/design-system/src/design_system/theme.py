"""Organization brand themes on top of a built-in design system (Milestone 7).

A brand theme does not change components or behaviour; it changes the look through the
design system's own theming mechanism:
- Fluent 2: a ``BrandVariants`` ramp passed to ``createLightTheme``;
- Material 3: overrides of the ``--mat-sys-*`` system variables.

Themes are data, validated here. The brand colour must give at least 4.5:1 contrast with white
text (WCAG 2.1 AA), because both design systems put white labels on brand-coloured buttons.
Font families are a plain list of names, so they cannot inject CSS or code.

A specification selects a theme by ``design_system.id = "org-<theme id>"`` (spec identifiers are
lowercase letters, digits and hyphens).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ORG_PREFIX = "org-"
HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
_RADII = {"small": ("2px", "4px"), "medium": ("4px", "12px"), "large": ("8px", "16px")}  # (fluent, material)
_STEPS = tuple(range(10, 161, 10))


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _luminance(color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    """WCAG 2.1 contrast ratio between two #rrggbb colours."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(color: str, toward: tuple[int, int, int], amount: float) -> str:
    r, g, b = _rgb(color)
    return _hex((r + (toward[0] - r) * amount, g + (toward[1] - g) * amount, b + (toward[2] - b) * amount))


def brand_ramp(color: str) -> dict[int, str]:
    """Sixteen shades for Fluent's BrandVariants (10 darkest … 160 lightest); 80 is the brand colour."""
    ramp: dict[int, str] = {}
    for step in _STEPS:
        if step < 80:
            ramp[step] = _mix(color, (0, 0, 0), (80 - step) / 80 * 0.85)
        elif step > 80:
            ramp[step] = _mix(color, (255, 255, 255), (step - 80) / 80 * 0.92)
        else:
            ramp[step] = color.lower()
    return ramp


class BrandTheme(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,40}$")]
    name: Annotated[str, Field(min_length=1, max_length=80)]
    base: Literal["fluent2", "material3"]
    brand_color: HexColor
    #: Comma-separated font family names, e.g. "Inter, Segoe UI, sans-serif" (letters, digits, spaces, hyphens).
    font_family: Annotated[str, Field(pattern=r"^[A-Za-z0-9 ,-]{1,120}$")] | None = None
    corner_radius: Literal["small", "medium", "large"] = "medium"

    @field_validator("brand_color")
    @classmethod
    def _accessible(cls, value: str) -> str:
        ratio = contrast(value, "#ffffff")
        if ratio < 4.5:
            raise ValueError(
                f"brand colour {value} has {ratio:.2f}:1 contrast with white button text; WCAG AA needs 4.5:1 "
                "(choose a darker shade)"
            )
        return value.lower()

    @property
    def selector(self) -> str:
        """The value a specification uses in design_system.id to select this theme."""
        return f"{ORG_PREFIX}{self.id}"

    @property
    def fluent_radius(self) -> str:
        return _RADII[self.corner_radius][0]

    @property
    def material_radius(self) -> str:
        return _RADII[self.corner_radius][1]


class BrandThemeSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: list[BrandTheme] = Field(default_factory=list, max_length=20)

    @field_validator("items")
    @classmethod
    def _unique(cls, items: list[BrandTheme]) -> list[BrandTheme]:
        ids = [t.id for t in items]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"theme ids must be unique (duplicated: {', '.join(duplicates)})")
        return items

    def get(self, selector: str) -> BrandTheme | None:
        return next((t for t in self.items if t.selector == selector), None)
