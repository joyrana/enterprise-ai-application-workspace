# ADR-0007: Model providers — Qwen via Hugging Face, gpt-oss via Ollama

- Status: Accepted (design); implementation scheduled for Milestone 2
- Date: 2026-10-04
- Deciders: project owner (model choice), engineering (integration design)

## Context

The project owner wants open-weight models rather than a proprietary API:

1. **Qwen** (Alibaba, open weights published on Hugging Face) as the primary base model.
2. **gpt-oss** (OpenAI open weights) running locally on **Ollama** as an alternative.

Both are reachable through OpenAI-compatible chat-completions APIs:

| Route | Base URL | Auth | Model id example |
|---|---|---|---|
| Hugging Face Inference Providers (router) | `https://router.huggingface.co/v1` | `HF_TOKEN` (needs "Make calls to Inference Providers") | `Qwen/<repo>` optionally suffixed `:<provider>`, `:fastest`, `:cheapest` |
| Self-hosted Qwen (vLLM / TGI) | operator-defined, e.g. `http://localhost:8000/v1` | optional | the served model name |
| Ollama (local) | `http://localhost:11434/v1` | none | `gpt-oss:20b` (or a Qwen tag pulled into Ollama) |

Known risks, verified against current sources on 2026-10-04:

- gpt-oss on Ollama has documented structured-output problems: non-compliant JSON, extra
  commentary appended after valid JSON, and reasoning ("harmony") traces leaking into content.
  Native schema enforcement therefore cannot be trusted for this route.
- Structured-output and tool-calling support on the Hugging Face router depends on the
  downstream provider selected for a model; it is not uniform across providers.
- The router forwards prompts to third-party inference providers, so data leaves the
  organization's network. Local models do not have this property.

## Decision

1. **One adapter, many profiles.** Implement a single `OpenAICompatibleProvider` behind the
   provider-neutral `ModelProvider` interface (structured generation, tool calling, timeouts,
   retries, usage accounting, error classification, capability metadata). Each deployment
   target is a *profile*: `hf-router`, `self-hosted`, `ollama`.
2. **Capabilities are declared, not assumed.** Each profile + model pair declares a
   `structured_output_mode`:
   - `json_schema` — server-side constrained decoding (use only where verified by evals),
   - `json_object` — JSON mode without schema enforcement,
   - `prompt_and_validate` — schema in the prompt, client-side parsing.
   The `ollama` + `gpt-oss` default is `prompt_and_validate`.
3. **The backend never trusts model output.** Every response is parsed and validated with the
   same Pydantic contracts used everywhere else (`appspec`, skill output schemas). On failure:
   strip known reasoning/wrapper noise, then at most **one** repair attempt that feeds the
   validation errors back, then fail with a classified `schema_failure` error.
4. **No silent fallback.** If the configured model is unavailable or fails validation, the
   workflow reports it. It never switches to a different (weaker) model on its own. A fallback
   chain may be configured explicitly later and is always recorded in provenance.
5. **Data-classification gate.** Projects classified `confidential` or `restricted` may be
   restricted to local profiles (`ollama`, `self-hosted`) by policy; the remote router is then
   refused before any prompt is sent.
6. **Provenance.** Every model-sourced fact records `skill_id`, `skill_version`, `model_id`
   (including profile and provider suffix) and `prompt_version` — already enforced by the
   `appspec` schema (`Provenance` requires `skill_id` and `model_id` when `source="model"`).
7. **Evaluation decides, not reputation.** Milestone 2 routing and requirements evals run
   against both Qwen and gpt-oss and report schema-validity rate, task accuracy, latency and
   tokens per model. Model defaults are set from those measurements.

## Configuration (placeholders; see `.env.example`)

```
MODEL_PROFILE=hf-router          # hf-router | self-hosted | ollama
MODEL_BASE_URL=https://router.huggingface.co/v1
MODEL_ID=Qwen/<model-repo>       # pin an exact repo; optional :provider suffix
HF_TOKEN=                        # secret; never committed, never sent to the browser
MODEL_TIMEOUT_SECONDS=60
MODEL_MAX_RETRIES=2
```

Local alternative:

```
MODEL_PROFILE=ollama
MODEL_BASE_URL=http://localhost:11434/v1
MODEL_ID=gpt-oss:20b
```

## Testing strategy

- Unit and integration tests use a deterministic `FakeProvider` and recorded response
  fixtures, including malformed outputs (trailing commentary, reasoning traces, truncated
  JSON) captured from the real models.
- Real-model smoke tests are opt-in and never claimed when not run:
  - CI job runs only when the `HF_TOKEN` repository secret is present and never for
    pull requests from forks.
  - `ollama` smoke tests run on a developer machine with Ollama installed.

## Consequences

- Positive: no vendor lock-in; a fully local, no-egress mode exists for sensitive projects;
  one code path covers hosted and local models.
- Negative: open-weight models, especially small local ones, need more client-side validation
  and repair; latency and quality vary by hardware and router provider; evaluation cost
  rises because two model families are benchmarked.
- Open item: the exact Qwen repository and size are pinned in Milestone 2 after a baseline
  evaluation, because model choice should follow measured schema compliance and quality.

## References

- Hugging Face Inference Providers, OpenAI-compatible router:
  https://huggingface.co/docs/inference-providers/en/guides/responses-api
- Reported gpt-oss structured-output issues on Ollama:
  https://www.glukhov.org/post/2025/10/ollama-gpt-oss-structured-output-issues/
- Qwen 3.6 open-weight release notes: https://www.noze.it/en/insights/qwen-3-6/
