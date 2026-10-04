import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Run } from "../../api/client";
import { mockFetch, problem } from "../../test/fetchMock";
import { project, specRevision } from "../../test/fixtures";
import { renderAt, renderWithProviders } from "../../test/render";
import { DiscoveryTab } from "./DiscoveryTab";

const BASE = `/api/v1/projects/${project.id}/discovery-runs`;
const RUN_ID = "22222222-2222-4222-8222-222222222222";
const CONFIGURED = {
  configured: true,
  model: "ollama:gpt-oss:20b",
  profile: "ollama",
  remote: false,
  structured_mode: "prompt_and_validate",
};

function run(overrides: Partial<Run> = {}): Run {
  return {
    id: RUN_ID,
    skill_id: "business-discovery",
    skill_version: "0.1.0",
    status: "succeeded",
    description: "Finance ops app",
    base_revision: 1,
    summary: "3 proposal(s): 1 fact(s), 1 item(s), 1 open question(s).",
    not_applicable_reason: null,
    proposals: [
      {
        op: "set_fact",
        proposal_id: "p-objective",
        path: "/objective",
        value: "Reduce manual effort",
        rationale: null,
      },
      {
        op: "add_item",
        proposal_id: "p-finance-approver",
        collection: "personas",
        item: { id: "finance-approver", name: "Finance approver" },
        rationale: null,
      },
      {
        op: "add_open_question",
        proposal_id: "p-q-risk",
        question_id: "q-risk",
        question: "What risk score requires approval?",
        blocking: true,
        related_ids: [],
      },
    ],
    model: {
      model_id: "gpt-oss:20b",
      profile: "ollama",
      prompt_version: "business-discovery@1",
      usage: { prompt_tokens: 900, completion_tokens: 300, total_tokens: 1200 },
      repaired: false,
      calls: 1,
      latency_ms: 4200,
      estimated_cost_usd: null,
    },
    error: null,
    applied_revision: null,
    decisions: null,
    created_by: "demo-user",
    created_at: "2026-10-04T10:00:00Z",
    started_at: "2026-10-04T10:00:00Z",
    finished_at: "2026-10-04T10:00:04Z",
    ...overrides,
  } as unknown as Run;
}

function renderTab(onApplied = vi.fn()) {
  renderWithProviders(<DiscoveryTab projectId={project.id} etag={'"r1"'} onApplied={onApplied} pollMs={10} />);
  return onApplied;
}

describe("DiscoveryTab", () => {
  it("explains when no model is configured", async () => {
    mockFetch([
      { method: "GET", path: `/api/v1/projects/${project.id}/spec`, body: specRevision(), headers: { ETag: '"r1"' } },
      {
        method: "GET",
        path: "/api/v1/ai/status",
        body: { configured: false, model: null, profile: null, remote: null, structured_mode: null },
      },
      { method: "GET", path: BASE, body: { items: [] } },
    ]);
    renderAt(`/projects/${project.id}/discovery`);
    expect(await screen.findByText("No AI model is configured")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /Describe the application/ })).not.toBeInTheDocument();
  });

  it("starts a run, polls until it finishes, and shows grouped proposals", async () => {
    const { calls } = mockFetch([
      { method: "GET", path: "/api/v1/ai/status", body: CONFIGURED },
      { method: "GET", path: BASE, body: { items: [] } },
      {
        method: "POST",
        path: BASE,
        status: 202,
        body: run({ status: "queued", proposals: [], summary: null, model: null }),
      },
      {
        method: "GET",
        path: `${BASE}/${RUN_ID}`,
        body: run({ status: "running", proposals: [], summary: null, model: null }),
      },
      { method: "GET", path: `${BASE}/${RUN_ID}`, body: run() },
    ]);
    const user = userEvent.setup();
    renderTab();
    expect(await screen.findByText("Local model")).toBeInTheDocument();
    const start = screen.getByRole("button", { name: "Propose requirements" });
    expect(start).toBeDisabled();

    await user.type(screen.getByRole("textbox", { name: /Describe the application/ }), "Finance ops app");
    await user.click(start);

    expect(await screen.findByRole("heading", { name: /3 proposal/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Key facts" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Personas" })).toBeInTheDocument();
    expect(screen.getByText("Blocking")).toBeInTheDocument();
    expect(screen.getByText(/1200 tokens/)).toBeInTheDocument();

    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({ description: "Finance ops app" });
    expect(post?.headers["Idempotency-Key"]).toMatch(/^discovery-/);
  });

  it("resumes an in-progress run after a refresh", async () => {
    mockFetch([
      { method: "GET", path: "/api/v1/ai/status", body: CONFIGURED },
      { method: "GET", path: BASE, body: { items: [run({ status: "running", proposals: [], summary: null })] } },
      { method: "GET", path: `${BASE}/${RUN_ID}`, body: run() },
    ]);
    renderTab();
    expect(await screen.findByText("The model is drafting proposals…")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /3 proposal/ })).toBeInTheDocument();
  });

  it("applies per-proposal decisions with If-Match and reports outcomes", async () => {
    const applied = run({ applied_revision: 2, decisions: { "p-objective": "confirm" } });
    const { calls } = mockFetch([
      { method: "GET", path: "/api/v1/ai/status", body: CONFIGURED },
      { method: "GET", path: BASE, body: { items: [run()] } },
      {
        method: "POST",
        path: `${BASE}/${RUN_ID}/apply`,
        body: {
          run: applied,
          results: [
            { proposal_id: "p-objective", outcome: "applied", detail: null },
            { proposal_id: "p-finance-approver", outcome: "applied", detail: null },
            { proposal_id: "p-q-risk", outcome: "rejected_by_user", detail: null },
          ],
          revision: specRevision(2),
          revision_created: true,
        },
        headers: { ETag: '"r2"' },
      },
    ]);
    const user = userEvent.setup();
    const onApplied = renderTab();
    const objective = await screen.findByRole("radiogroup", { name: /business objective/i });
    await user.click(within(objective).getByRole("radio", { name: "Confirm" }));
    const question = screen.getByRole("radiogroup", { name: /question/i });
    await user.click(within(question).getByRole("radio", { name: "Reject" }));
    await user.click(screen.getByRole("button", { name: "Apply decisions" }));

    expect(await screen.findByText("Applied to revision r2")).toBeInTheDocument();
    expect(screen.getByText("Applied: 2")).toBeInTheDocument();
    expect(screen.getByText("Rejected: 1")).toBeInTheDocument();
    const post = calls.find((c) => c.url.endsWith("/apply"));
    expect(post?.headers["If-Match"]).toBe('"r1"');
    expect(post?.body).toEqual({
      decisions: [
        { proposal_id: "p-objective", decision: "confirm" },
        { proposal_id: "p-finance-approver", decision: "accept" },
        { proposal_id: "p-q-risk", decision: "reject" },
      ],
    });
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(expect.objectContaining({ etag: '"r2"' })));
  });

  it("explains a revision conflict when applying", async () => {
    mockFetch([
      { method: "GET", path: "/api/v1/ai/status", body: CONFIGURED },
      { method: "GET", path: BASE, body: { items: [run()] } },
      {
        method: "POST",
        path: `${BASE}/${RUN_ID}/apply`,
        status: 412,
        body: problem(412, "revision-conflict", "The specification changed since you loaded it"),
      },
    ]);
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Apply decisions" }));
    expect(await screen.findByText("The specification changed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
  });

  it("shows a failed run and lets the user reuse the description", async () => {
    mockFetch([
      { method: "GET", path: "/api/v1/ai/status", body: CONFIGURED },
      {
        method: "GET",
        path: BASE,
        body: {
          items: [
            run({
              status: "failed",
              proposals: [],
              summary: null,
              error: { kind: "timeout", message: "The model did not respond in time." },
            }),
          ],
        },
      },
    ]);
    const user = userEvent.setup();
    renderTab();
    expect(await screen.findByText("The model did not respond in time.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use this description again" }));
    expect(screen.getByRole("textbox", { name: /Describe the application/ })).toHaveValue("Finance ops app");
  });

  it("warns when prompts go to a remote provider", async () => {
    mockFetch([
      {
        method: "GET",
        path: "/api/v1/ai/status",
        body: { ...CONFIGURED, model: "hf-router:Qwen/Qwen3-8B", remote: true },
      },
      { method: "GET", path: BASE, body: { items: [] } },
    ]);
    renderTab();
    expect(await screen.findByText(/descriptions leave your network/)).toBeInTheDocument();
  });

  it("shows the reason when the text is not an application request", async () => {
    mockFetch([
      { method: "GET", path: "/api/v1/ai/status", body: CONFIGURED },
      {
        method: "GET",
        path: BASE,
        body: { items: [run({ proposals: [], summary: null, not_applicable_reason: "That is a weather question." })] },
      },
    ]);
    renderTab();
    expect(await screen.findByText("That is a weather question.")).toBeInTheDocument();
  });
});
