# ADR-0019: Organization brand themes on built-in design systems

- Status: Accepted · Date: 2026-10-10

## Context

Organizations want generated applications to look like theirs: brand colour, typeface and
shape. A fully custom component library is a different and much larger problem (a new
contract plus an adapter). Most organizations need their brand applied to a proven design
system, with accessibility kept intact.

## Decision

- **A brand theme is data on top of a built-in design system** (`design_system.BrandTheme`):
  - `id` and `name`;
  - `base`, either `fluent2` or `material3`;
  - `brand_color`;
  - an optional `font_family`;
  - `corner_radius`: small, medium or large.

  Components, behaviour and the safety model are unchanged.
- **Accessibility is checked when a theme is saved.** The brand colour must reach 4.5:1
  contrast with white text (WCAG 2.1 AA), because both design systems put white labels on
  brand-coloured buttons. Font families are a plain list of names: letters, digits, spaces,
  commas and hyphens only, so they cannot inject CSS or code.
- **Generation:**
  - **React:** projects always contain `src/theme.ts`. By default it is Fluent's light
    theme; with a brand theme it holds a 16-step `BrandVariants` ramp for
    `createLightTheme` plus the font and radius tokens.
  - **Angular:** the theme becomes overrides of the M3 `--mat-sys-*` variables.
  - **Labelling:** the manifest and API report the design system as
    `org-<id> (<base>@<version>)`.
- **Selection:** a specification selects a theme with `design_system.id = "org-<id>"`.
  - Unknown themes and framework mismatches are refused with a clear message.
  - Policies can require organization themes (`allowed-design-systems: ["org-acme"]`).
- **Administration:** brand themes are stored per tenant next to the policies, with the
  same rules: the `org-admin` role, `If-Match: "vN"` and auditing.

## Consequences

- One change gives every generated app the organization's look while keeping the
  accessibility guarantees.
- Contrast is checked for the brand colour on white only. Derived shades come from a
  deterministic mix towards black and white, not from a perceptual tonal palette such as
  Material's HCT. Exact brand palettes can be added as an optional ramp later.
- Fully custom component libraries remain out of scope: they need their own contract and
  adapter (ADR-0013).
