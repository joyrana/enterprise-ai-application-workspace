import { describe, expect, it, vi } from "vitest";
import { mockFetch, problem } from "../test/fetchMock";
import { project, specRevision } from "../test/fixtures";
import { ApiError, api } from "./client";

describe("api client", () => {
  it("sends the development identity headers", async () => {
    const { calls } = mockFetch([{ method: "GET", path: "/api/v1/projects", body: { items: [], next_cursor: null } }]);
    await api.listProjects();
    expect(calls[0]?.headers["X-Dev-Tenant"]).toBe("demo");
    expect(calls[0]?.headers["X-Dev-User"]).toBe("demo-user");
    expect(calls[0]?.url).toBe("/api/v1/projects?limit=20");
  });

  it("sends the idempotency key when creating a project", async () => {
    const { calls } = mockFetch([{ method: "POST", path: "/api/v1/projects", status: 201, body: project }]);
    await api.createProject({ name: "Finance ops" }, "create-key-123");
    expect(calls[0]?.headers["Idempotency-Key"]).toBe("create-key-123");
    expect(calls[0]?.body).toEqual({ name: "Finance ops" });
  });

  it("uses If-Match and reports whether a revision was created", async () => {
    const { calls } = mockFetch([
      {
        method: "PUT",
        path: `/api/v1/projects/${project.id}/spec`,
        body: specRevision(2),
        headers: { ETag: '"r2"', "X-Revision-Created": "true" },
      },
    ]);
    const result = await api.saveSpec(project.id, { spec: specRevision().spec }, '"r1"');
    expect(calls[0]?.headers["If-Match"]).toBe('"r1"');
    expect(result).toMatchObject({ etag: '"r2"', created: true });
  });

  it("turns problem+json responses into ApiError", async () => {
    mockFetch([
      {
        method: "GET",
        path: `/api/v1/projects/${project.id}`,
        status: 404,
        body: problem(404, "not-found", "Resource not found", { detail: "Project was not found." }),
      },
    ]);
    const error = await api.getProject(project.id).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("not-found");
    expect((error as ApiError).message).toBe("Project was not found.");
  });

  it("reports network failures as a problem without internals", async () => {
    mockFetch([]);
    const error = await api.listProjects().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("network");
  });

  it("handles non-JSON error bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502, statusText: "Bad Gateway" })),
    );
    const error = await api.listProjects().catch((e: unknown) => e);
    expect((error as ApiError).status).toBe(502);
    expect((error as ApiError).problem.title).toBe("Bad Gateway");
  });
});
