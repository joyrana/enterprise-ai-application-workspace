import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockFetch, problem } from "../../test/fetchMock";
import { project } from "../../test/fixtures";
import { renderWithProviders } from "../../test/render";
import { CodeTab } from "./CodeTab";

const BASE = `/api/v1/projects/${project.id}/code`;
const MANIFEST = {
  spec_revision: 2,
  generator: "codegen-react@0.1.0",
  design_system: "fluent2@1.0.0",
  files: [
    { path: "package.json", bytes: 10, sha256: "a".repeat(64), language: "json" },
    { path: "src/screens/RulesScreen.tsx", bytes: 20, sha256: "b".repeat(64), language: "tsx" },
  ],
  warnings: [],
};
const file = (path: string, content: string) => ({
  path,
  spec_revision: 2,
  language: "tsx",
  sha256: "c".repeat(64),
  content,
});

describe("CodeTab", () => {
  it("browses generated files and shows the diff from the previous revision", async () => {
    const { calls } = mockFetch([
      { method: "GET", path: BASE, body: MANIFEST },
      {
        method: "GET",
        path: `${BASE}/file`,
        body: file("src/screens/RulesScreen.tsx", "export function RulesScreen() {}"),
      },
      {
        method: "GET",
        path: `${BASE}/diff`,
        body: {
          from_revision: 1,
          to_revision: 2,
          files: [
            {
              path: "src/screens/RulesScreen.tsx",
              status: "added",
              additions: 1,
              deletions: 0,
              unified: "--- /dev/null\n+++ b/src/screens/RulesScreen.tsx\n+export function RulesScreen() {}\n",
            },
          ],
        },
      },
      { method: "GET", path: `${BASE}/file`, body: file("package.json", '{"name": "x"}') },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<CodeTab projectId={project.id} revision={2} />);

    const contents = await screen.findByRole("region", { name: "Contents of src/screens/RulesScreen.tsx" });
    expect(contents).toHaveTextContent("export function RulesScreen() {}");
    expect(screen.getByText(/codegen-react@0.1.0 · fluent2@1.0.0 · spec r2 · 2/)).toBeInTheDocument();

    const diff = await screen.findByRole("region", { name: "Diff of src/screens/RulesScreen.tsx" });
    expect(within(diff).getByText("+export function RulesScreen() {}")).toBeInTheDocument();
    expect(calls.find((c) => c.url.startsWith(`${BASE}/diff`))?.url).toBe(`${BASE}/diff?from=1&to=2`);

    await user.click(screen.getByRole("button", { name: "package.json" }));
    expect(await screen.findByRole("region", { name: "Contents of package.json" })).toHaveTextContent('{"name": "x"}');
  });

  it("explains when UI errors block generation", async () => {
    mockFetch([
      {
        method: "GET",
        path: BASE,
        status: 422,
        body: problem(422, "code-generation-blocked", "The screens have errors that block code generation", {
          detail: "Revision r3 has 1 UI error(s); fix them in the specification first.",
          errors: [{ path: "/screens", message: "Id 'a-title' is used 2 times.", code: "id-duplicate" }],
        }),
      },
    ]);
    renderWithProviders(<CodeTab projectId={project.id} revision={3} />);
    expect(await screen.findByText("The screens have errors that block code generation")).toBeInTheDocument();
    expect(screen.getByText(/is used 2 times/)).toBeInTheDocument();
  });
});
