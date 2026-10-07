# ADR-0014: Deterministic code generation; generated code never runs inside the workspace

- Status: Accepted · Date: 2026-10-07

## Context

Milestone 4 turns specifications into runnable React applications. Two risks dominate:

1. **Spec text becoming code.** Names, labels and descriptions come from people and from
   models (proposals people accepted). If that text were pasted into source code, a
   quote or brace could escape a string and inject code into the generated app.
2. **Executing untrusted code.** Building or running generated code inside the API
   process would give that code the API's credentials, database access and network.

There is also the brief's demand for verifiable output and traceability.

## Decision

- **Templates plus a printer, not a model.** `packages/codegen-react` prints the design
  adapter's render tree (ADR-0013) as TSX:
  - Every value from the spec is emitted as a JSON string literal in braces
    (`{"…"}`, ASCII-escaped), so it cannot end the literal.
  - Component and prop names must be on an allowlist (identical to the workspace preview's;
    a test compares them), and prop values are type- and range-checked.
  - Anything else is a generation error, not output.
  - Identifiers are derived only from validated kebab-case ids.
  - The only user text in non-TS files (README, the HTML title) is HTML-escaped where it
    could matter.
- **Deterministic and traceable.** The same spec revision, design system and generator
  version always produce byte-identical files: sorted, no timestamps, and a deterministic
  zip.
  - Each source file names its generator, spec revision, IR version and design system.
  - `workspace-manifest.json` lists every file's SHA-256.
  - Diffs between revisions therefore show only real changes and are reviewed before
    anyone takes the code.
- **Pinned toolchain.** The generated `package.json` pins exact versions, equal to the
  workspace's lockfile (tested), so "it builds in CI" means it builds with the same versions
  the user installs.
- **Generation is refused** while the UI IR has errors. Warnings (placeholders) become
  visible "not supported yet" markers in the app.
- **Execution boundary.** The API only generates text. It never installs, builds or runs
  generated code.
  - Verification runs in CI: example apps are generated, type-checked with strict
    TypeScript, built with Vite, and opened in Chromium with axe on every route.
  - An on-demand, isolated build runner for users' own projects (container, no network
    except a package mirror, no credentials, resource limits) is a separate, later slice
    with its own threat-model entry.
- **UI first, behaviour in steps.**
  - Version 0.1.0 generated the UI layer only.
  - Version 0.2.0 adds navigation actions (router navigation to the target screen) and form
    validation:
    - spec rules become native constraints (`required`, `min`/`max`, lengths, `pattern`,
      `step` for decimals);
    - on submit, invalid fields show their message in Fluent `Field` and in a summary;
    - a valid submit states that saving is not connected yet.
  - Behaviour lives in a small generated hook (`src/forms.ts`), not in values from the spec.
  - Version 0.3.0 adds a data layer:
    - a TypeScript type per entity;
    - a `Store` interface whose default implementation keeps records in the browser
      (localStorage, with a memory fallback);
    - tables bound to their entity, with an empty state;
    - bound forms that convert values to the right types, save them and return to the list;
    - reference fields that list the referenced entity's records.

    `api/openapi.json` states the backend contract derived from the same entities, so a real
    backend can replace the browser store behind the same interface. Edit preservation comes
    in Milestone 5.

## Consequences

- Generated apps are reproducible, reviewable and safe to download. The workspace runs none
  of their code.
- "Builds and passes axe" is proven for the example apps in CI, not yet for each user
  project on demand. Users build their own downloads until the isolated runner exists.
- Changing the generator changes output; the version in every header makes that visible,
  and the diff view shows it.
