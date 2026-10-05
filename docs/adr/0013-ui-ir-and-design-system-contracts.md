# ADR-0013: UI intermediate representation and design-system contracts

- Status: Accepted · Date: 2026-10-05

## Context

The workspace must generate interfaces that honor a chosen design system: Fluent 2 for React
now, Material 3 for Angular (Milestone 6), and organization design systems (Milestone 7). It
must also check accessibility and keep generated code traceable to the specification.
Generating framework code straight from the spec, or straight from a model's output, would
mix three concerns that change at different rates: *what* a screen contains, *which*
components a design system offers, and *how* code is printed.

## Decision

Three layers, each typed, versioned and testable on its own (`packages/design-system`):

1. **UI IR v1** (`design_system.ir`). A framework-neutral screen description: headings, text,
   sections, forms with typed fields and actions, tables with columns, stats, messages,
   toolbars, and an explicit **placeholder** for anything the IR cannot express yet. Strict
   models (unknown fields rejected), node ids unique per document, and a JSON Schema exported
   to `contracts/ui-ir.schema.json`.
2. **Design-system contracts** (`design_system.contract`). Data, not code. The contract maps
   every IR construct (`field:select`, `action:primary`…) to the design system's components,
   lists semantic tokens with the library's token names, and states its rules. Each contract
   is **pinned to the exact library version the workspace locks** (Fluent:
   `@fluentui/react-components` 9.74.9). Tests check:
   - **completeness**: every IR construct is mapped or declared unsupported;
   - **pinning**: the version matches `package-lock.json`;
   - **accuracy**: a web test checks that every component and token the contract names is
     exported by the installed library.
3. **Adapters** (`design_system.resolve`). These map the IR to a *render tree*: component
   names taken from the contract, JSON props and text. The Fluent 2 adapter encodes Fluent
   guidance, for example labels via `Field`, native-backed `Select`, at most one primary
   button, and an empty-state row in tables. Where Fluent has no fitting component (file
   input, destructive button appearance), the contract says so instead of inventing one.

**Derivation, not storage.** The IR is derived from a spec revision deterministically
(`design_system.derive`):
- specified screens map component by component;
- with no screens, each data entity gets a list screen and a form screen;
- anything unexpressible becomes a placeholder, flagged as a warning.

The spec stays the single source of truth (ADR-0002). The same revision always yields the same
IR, so `GET /projects/{id}/ui?revision=N` can recompute any revision's IR and nothing needs
migrating.

**Validation before generation.** Deterministic checks give paths and rule codes:
- exactly one level-1 heading per screen, and no skipped heading levels;
- labelled fields, selects with options, at most one primary action per form;
- tables with captions and columns;
- unique ids and routes;
- references to entities, requirements, personas and screens.

Errors block generation (Milestone 4); warnings ask for review.

**Safe preview.** The workspace renders the render tree with real Fluent components through an
allowlisting interpreter:
- only known components, and only known props with validated values;
- text rendered as text, and no event handlers from data;
- forms never submit.

No generated code is executed. The preview is therefore a faithful *design* preview, not a
running application. E2E tests run axe on previewed screens.

## Consequences

- One IR serves every design system. Adding Material 3 means a contract plus an adapter; the
  IR, derivation and checks stay the same.
- Code generation (Milestone 4) prints the render tree as source. The structure was already
  checked before printing, and tests check the compiled result again.
- IR v1 cannot express charts, dialogs, tabs, or loading and error state variants. Specs that
  ask for them get placeholders and warnings until a later IR version adds them, with a
  version bump and a migration of the derivation.
- Model-proposed screens (a later slice) will enter as typed spec commands (ADR-0008), not as
  IR, so people still review every change to the source of truth.
