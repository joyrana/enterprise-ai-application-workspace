# ADR-0017: Angular + Material 3 generation from the same UI IR

- Status: Accepted · Date: 2026-10-10

## Context

The workspace must target more than one framework and design system without forking the
pipeline. Requirements, the specification, the UI IR (ADR-0013), validation, provenance, diffs
and edit preservation (ADR-0016) should stay shared. Only the last step, printing source
code, should differ.

## Decision

- **A Material 3 contract** (`material3`, framework `angular`) is pinned to
  `@angular/material@22.2.2`, with every IR construct mapped.
  - Mappings name the Angular elements and directives the generator emits, such as
    `mat-form-field`, `input[matInput]`, `select[matNativeControl]` and
    `table[mat-table]`. A test checks that every Material element in generated templates
    comes from the contract.
  - Tokens are the M3 system variables (`--mat-sys-*`).
  - Projects whose spec says `framework: angular` default to it.
- **`packages/codegen-angular`** prints the IR directly. The Fluent render tree is
  React-specific, so it is not used. The output:
  - standalone components with zoneless change detection and signals;
  - typed reactive forms whose validators come from the spec rules;
  - Material form fields with `mat-error` messages and an error summary;
  - `mat-table` bound to a signal-based local store, with an empty-state row;
  - reference fields that list the referenced records;
  - router navigation.

  It has the same guarantees as ADR-0014: deterministic output, provenance headers, a
  SHA-256 manifest, exact pins and refusal on IR errors.
- **Spec text never enters a template.** It lives in each component's `TEXT` object as
  ASCII-escaped TypeScript literals (backticks, `${` and `</` are escaped too) and reaches the
  page only through interpolation of generated keys (`{{ t.k3 }}`), which Angular escapes.
  - Element and attribute names are allowlisted, and binding expressions must match a strict
    character set (no quotes, braces or backticks).
  - Form controls get generated names (`c0`, `c1`, …); spec field names appear only in
    TypeScript literals.
  - The allowlists are unit-tested against hostile input.
- **Toolchain:**
  - `toolchains/angular/package.json` pins Angular 22.2.2, TypeScript 6.0.3, RxJS 7.8.2 and
    tslib 2.8.1. Its lockfile is resolved by the regenerate workflow.
  - The generator's `toolchain.json` must equal both the package.json and the lockfile
    (tested).
  - Styles use the prebuilt M3 `azure-blue` theme, so no Sass dependency is needed.
- **CI** generates two Angular example apps (specified screens, and entity-derived list and
  form screens) and builds them with `ng build` and strict templates. Playwright then:
  - opens every route with axe;
  - runs a validate, save, reference and persist flow.
- **Preview:** the workspace preview interprets Fluent render trees. For Material 3 the
  Screens tab shows the IR and says that no in-browser preview exists yet; the code is in the
  Code tab.

## Consequences

- Upgrade, diff, impact preview and audit work for Angular projects unchanged, because they
  operate on generated files.
- **Not yet for Angular:**
  - edit and delete row actions (reported as a generation warning, not hidden);
  - an HTTP data store;
  - builds in the isolated runner. Its image carries the React toolchain only, so build
    requests for Angular projects get a clear 422.
- Two toolchains to keep current. Version pins are tested against lockfiles, so drift fails
  CI instead of surprising users.
