import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockFetch, problem } from "../test/fetchMock";
import { project, specRevision } from "../test/fixtures";
import { renderAt } from "../test/render";

describe("ProjectsPage", () => {
  it("shows an empty state with a call to action", async () => {
    mockFetch([{ method: "GET", path: "/api/v1/projects", body: { items: [], next_cursor: null } }]);
    renderAt("/projects");
    expect(await screen.findByText(/No projects yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create your first project" })).toBeInTheDocument();
  });

  it("lists projects with links to each workspace", async () => {
    mockFetch([{ method: "GET", path: "/api/v1/projects", body: { items: [project], next_cursor: null } }]);
    renderAt("/projects");
    const link = await screen.findByRole("link", { name: "Finance ops" });
    expect(link).toHaveAttribute("href", `/projects/${project.id}`);
    expect(screen.getByRole("table", { name: "Projects" })).toBeInTheDocument();
  });

  it("shows API problems with a retry action", async () => {
    mockFetch([
      { method: "GET", path: "/api/v1/projects", status: 503, body: problem(503, "http-503", "Service unavailable") },
      { method: "GET", path: "/api/v1/projects", body: { items: [project], next_cursor: null } },
    ]);
    renderAt("/projects");
    expect(await screen.findByText("Service unavailable")).toBeInTheDocument();
    expect(screen.getByText("Request id: req-1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: "Finance ops" })).toBeInTheDocument();
  });

  it("validates the name, creates a project idempotently and opens it", async () => {
    const { calls } = mockFetch([
      { method: "GET", path: "/api/v1/projects", body: { items: [], next_cursor: null } },
      { method: "POST", path: "/api/v1/projects", status: 201, body: project },
      { method: "GET", path: `/api/v1/projects/${project.id}/spec`, body: specRevision(), headers: { ETag: '"r1"' } },
    ]);
    const user = userEvent.setup();
    renderAt("/projects");
    await user.click(await screen.findByRole("button", { name: "New project" }));

    await user.click(screen.getByRole("button", { name: "Create project" }));
    expect(await screen.findByText("Enter a project name.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    await user.type(screen.getByRole("textbox", { name: /Name/ }), "  Finance ops  ");
    await user.click(screen.getByRole("button", { name: "Create project" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // The new page must be reachable by assistive technology (not left aria-hidden by the modal).
    expect(await screen.findByRole("heading", { level: 1, name: "Finance ops" })).toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByRole("main"));
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({ name: "Finance ops", description: null });
    expect(post?.headers["Idempotency-Key"]).toMatch(/^create-[0-9a-f-]{36}$/);
  });

  it("keeps the same idempotency key when retrying after a failure", async () => {
    const { calls } = mockFetch([
      { method: "GET", path: "/api/v1/projects", body: { items: [], next_cursor: null } },
      {
        method: "POST",
        path: "/api/v1/projects",
        status: 500,
        body: problem(500, "internal", "Internal server error"),
      },
      { method: "POST", path: "/api/v1/projects", status: 201, body: project },
      { method: "GET", path: `/api/v1/projects/${project.id}/spec`, body: specRevision() },
    ]);
    const user = userEvent.setup();
    renderAt("/projects");
    await user.click(await screen.findByRole("button", { name: "New project" }));
    await user.type(screen.getByRole("textbox", { name: /Name/ }), "Finance ops");
    await user.click(screen.getByRole("button", { name: "Create project" }));
    expect(await screen.findByText("Internal server error")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create project" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(2));
    const [first, second] = calls.filter((c) => c.method === "POST");
    expect(first?.headers["Idempotency-Key"]).toBe(second?.headers["Idempotency-Key"]);
  });
});
