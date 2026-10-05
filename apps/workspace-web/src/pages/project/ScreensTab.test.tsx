import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockFetch } from "../../test/fetchMock";
import { project } from "../../test/fixtures";
import { renderWithProviders } from "../../test/render";
import { ScreensTab } from "./ScreensTab";

const UI_PATH = `/api/v1/projects/${project.id}/ui`;

function preview(extra: Record<string, unknown> = {}) {
  const heading = (id: string, text: string) => ({
    component: "Title2",
    props: { as: "h1" },
    text,
    children: [],
    ir_id: id,
  });
  return {
    spec_revision: 2,
    design_system: { id: "fluent2", version: "1.0.0", selected_by: "default", note: "Fluent 2 is the default for React." },
    document: {
      ir_version: "1",
      spec_revision: 2,
      screens: [
        { id: "rules", title: "Rules", route: "/rules", source: { kind: "spec-screen", ref: "rules" }, requirement_ids: [], persona_ids: [], body: [] },
        { id: "other", title: "Other", route: "/other", source: { kind: "entity-list", ref: "x" }, requirement_ids: [], persona_ids: [], body: [] },
      ],
    },
    issues: [
      { path: "/screens/0/body/1", code: "unsupported-component", severity: "warning", message: "'chart' cannot be expressed in the IR yet." },
    ],
    rendered: [
      { screen_id: "rules", title: "Rules", route: "/rules", root: [heading("rules-title", "Rules")] },
      { screen_id: "other", title: "Other", route: "/other", root: [heading("other-title", "Other")] },
    ],
    ...extra,
  };
}

describe("ScreensTab", () => {
  it("previews each screen with the design system and lists design checks", async () => {
    mockFetch([{ method: "GET", path: UI_PATH, body: preview() }]);
    const user = userEvent.setup();
    renderWithProviders(<ScreensTab projectId={project.id} revision={2} />);

    const region = await screen.findByRole("region", { name: "Preview of Rules" });
    expect(within(region).getByRole("heading", { level: 1, name: "Rules" })).toBeInTheDocument();
    expect(screen.getByText("Fluent 2 is the default for React.")).toBeInTheDocument();
    expect(screen.getByText(/From a specified screen/)).toBeInTheDocument();
    const issues = screen.getByRole("list", { name: "Issues" });
    expect(within(issues).getByText(/cannot be expressed/)).toBeInTheDocument();
    expect(screen.getByText("Only warnings: review them before generating code.")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Other" }));
    expect(screen.getByRole("region", { name: "Preview of Other" })).toBeInTheDocument();
    expect(screen.getByText(/Derived from a data entity \(list\)/)).toBeInTheDocument();
  });

  it("explains when there is nothing to preview yet", async () => {
    mockFetch([
      {
        method: "GET",
        path: UI_PATH,
        body: preview({ issues: [], rendered: [], document: { ir_version: "1", spec_revision: 1, screens: [] } }),
      },
    ]);
    renderWithProviders(<ScreensTab projectId={project.id} revision={1} />);
    expect(await screen.findByText("No screens yet")).toBeInTheDocument();
    expect(screen.getByText(/No issues/)).toBeInTheDocument();
  });
});
