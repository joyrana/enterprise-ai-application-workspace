import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockFetch } from "../../test/fetchMock";
import { project, specRevision } from "../../test/fixtures";
import { renderAt } from "../../test/render";

describe("ProjectPage", () => {
  it("shows unknown facts honestly instead of inventing values", async () => {
    mockFetch([{ method: "GET", path: `/api/v1/projects/${project.id}/spec`, body: specRevision() }]);
    renderAt(`/projects/${project.id}`);
    expect(await screen.findByRole("heading", { level: 1, name: "Finance ops" })).toBeInTheDocument();
    expect(screen.getByText("Not yet known")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  });

  it("shows a not-found problem with a way back", async () => {
    mockFetch([
      {
        method: "GET",
        path: `/api/v1/projects/${project.id}/spec`,
        status: 404,
        body: { type: "urn:workspace:error:not-found", title: "Resource not found", status: 404 },
      },
    ]);
    renderAt(`/projects/${project.id}`);
    expect(await screen.findByText("Resource not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to projects" })).toBeInTheDocument();
  });
});
