# Architecture Decision Records

| ADR | Title | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith with explicit package boundaries | Accepted |
| [0002](0002-canonical-spec-as-source-of-truth.md) | Canonical specification as the single source of truth | Accepted |
| [0003](0003-immutable-revisions-and-optimistic-concurrency.md) | Immutable spec revisions with optimistic concurrency | Accepted |
| [0004](0004-tenancy-and-dev-auth.md) | Tenant scoping and a replaceable authentication boundary | Accepted |
| [0005](0005-contracts-and-codegen.md) | Generated, drift-checked API contracts | Accepted |
| [0006](0006-ci-verification-and-lockfiles.md) | CI as the verification source; generated lockfiles | Accepted |
| [0007](0007-model-providers.md) | Model providers: Qwen via Hugging Face, gpt-oss via Ollama | Accepted; implemented in `packages/model-gateway` |
| [0008](0008-proposals-decisions-and-runs.md) | Skills return typed proposals; people decide; runs are durable records | Accepted |
| [0009](0009-skill-routing.md) | Two-stage skill routing, evaluated against a lexical baseline | Accepted |
| [0010](0010-evidence-tiers.md) | Evidence tiers: what each kind of test may claim | Accepted |
| [0011](0011-prompt-injection-screening.md) | Prompt-injection screening is advisory and deterministic | Accepted |
| [0012](0012-workflow-orchestration.md) | Checkpointed workflows on our own tables; LangGraph not adopted yet | Accepted |
| [0013](0013-ui-ir-and-design-system-contracts.md) | UI intermediate representation and design-system contracts | Accepted |
| [0014](0014-deterministic-code-generation.md) | Deterministic code generation; generated code never runs inside the workspace | Accepted |
| [0015](0015-isolated-build-runner.md) | Isolated build runner for generated projects | Accepted |
| [0016](0016-edit-preservation.md) | Edit preservation by three-way merge against a reproduced base | Accepted |
| [0017](0017-angular-material3-generation.md) | Angular + Material 3 generation from the same UI IR | Accepted |
| [0018](0018-organization-policies.md) | Organization policies as typed, deterministic rules | Accepted |
| [0019](0019-organization-brand-themes.md) | Organization brand themes on built-in design systems | Accepted |

Template: context → decision → consequences. Superseding an ADR means adding a new one and
marking the old one "Superseded by ADR-NNNN", never rewriting history.
