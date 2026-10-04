import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockFetch, problem } from "../../test/fetchMock";
import { project, specRevision } from "../../test/fixtures";
import { renderAt } from "../../test/render";

const SPEC = `/api/v1/projects/${project.id}/spec`;

function editor(): HTMLTextAreaElement {
  return screen.getByRole("textbox", { name: "Specification (JSON)" }) as HTMLTextAreaElement;
}

function setEditor(value: string) {
  fireEvent.change(editor(), { target: { value } });
}

async function openEditor() {
  renderAt(`/projects/${project.id}/specification`);
  await screen.findByRole("textbox", { name: "Specification (JSON)" });
}

function renamed(name: string): string {
  const spec = JSON.parse(editor().value) as { metadata: { name: string } };
  spec.metadata.name = name;
  return JSON.stringify(spec);
}

describe("SpecEditorTab", () => {
  it("rejects invalid JSON locally without calling the API", async () => {
    const { calls } = mockFetch([{ method: "GET", path: SPEC, body: specRevision(), headers: { ETag: '"r1"' } }]);
    await openEditor();
    setEditor("{ not json");
    await userEvent.click(screen.getByRole("button", { name: "Save revision" }));
    expect(await screen.findByText("The JSON is not valid")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
  });

  it("saves with If-Match and shows the new revision", async () => {
    const saved = specRevision(2);
    const { calls } = mockFetch([
      { method: "GET", path: SPEC, body: specRevision(), headers: { ETag: '"r1"' } },
      { method: "PUT", path: SPEC, body: saved, headers: { ETag: '"r2"', "X-Revision-Created": "true" } },
    ]);
    await openEditor();
    setEditor(renamed("Finance ops v2"));
    await userEvent.type(screen.getByRole("textbox", { name: /Change summary/ }), "Rename");
    await userEvent.click(screen.getByRole("button", { name: "Save revision" }));

    expect(await screen.findByRole("button", { name: "Save revision" })).toBeDisabled();
    expect(screen.getByLabelText("Revision 2")).toBeInTheDocument();
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.headers["If-Match"]).toBe('"r1"');
    expect(put?.body).toMatchObject({ change_summary: "Rename", spec: { metadata: { name: "Finance ops v2" } } });
  });

  it("explains a revision conflict and offers to reload", async () => {
    mockFetch([
      { method: "GET", path: SPEC, body: specRevision(), headers: { ETag: '"r1"' } },
      {
        method: "PUT",
        path: SPEC,
        status: 412,
        body: problem(412, "revision-conflict", "The specification changed since you loaded it", {
          detail: "You edited revision 1, but the current revision is 2.",
          extensions: { current_revision: 2 },
        }),
      },
      { method: "GET", path: SPEC, body: specRevision(2), headers: { ETag: '"r2"' } },
    ]);
    await openEditor();
    setEditor(renamed("Mine"));
    await userEvent.click(screen.getByRole("button", { name: "Save revision" }));
    expect(await screen.findByText("Someone saved a newer revision")).toBeInTheDocument();
    expect(screen.getByText(/current revision is 2/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Reload latest" }));
    expect(await screen.findByLabelText("Revision 2")).toBeInTheDocument();
  });

  it("lists server validation errors with their paths", async () => {
    mockFetch([
      { method: "GET", path: SPEC, body: specRevision(), headers: { ETag: '"r1"' } },
      {
        method: "PUT",
        path: SPEC,
        status: 422,
        body: problem(422, "spec-invalid", "The specification is not valid", {
          detail: "1 reference error(s) must be fixed before saving.",
          errors: [
            { path: "/navigation/0/screen_id", message: "references unknown screen 'x'", code: "dangling-reference" },
          ],
        }),
      },
    ]);
    await openEditor();
    setEditor(renamed("Broken"));
    await userEvent.click(screen.getByRole("button", { name: "Save revision" }));
    expect(await screen.findByText("The specification is not valid")).toBeInTheDocument();
    expect(screen.getByText("/navigation/0/screen_id")).toBeInTheDocument();
  });

  it("disables saving until something changes", async () => {
    mockFetch([{ method: "GET", path: SPEC, body: specRevision(), headers: { ETag: '"r1"' } }]);
    await openEditor();
    expect(screen.getByRole("button", { name: "Save revision" })).toBeDisabled();
  });
});
