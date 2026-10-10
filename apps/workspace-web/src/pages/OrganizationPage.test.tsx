import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockFetch, problem } from "../test/fetchMock";
import { renderAt } from "../test/render";

const POLICIES = "/api/v1/org/policies";
const THEMES = "/api/v1/org/design-systems";
const EMPTY = { version: 0, policy: { policy_version: "1", rules: [] }, updated_by: null, updated_at: null };
const NO_THEMES = { version: 0, themes: { items: [] } };

describe("OrganizationPage", () => {
  it("saves policies with If-Match and the admin role header", async () => {
    const rules = [{ id: "small-forms", kind: "max-form-fields", max: 20, severity: "error" }];
    const { calls } = mockFetch([
      { method: "GET", path: POLICIES, body: EMPTY },
      { method: "GET", path: THEMES, body: NO_THEMES },
      {
        method: "PUT",
        path: POLICIES,
        body: { version: 1, policy: { policy_version: "1", rules }, updated_by: "demo-user", updated_at: "2026-10-10" },
      },
    ]);
    renderAt("/organization");
    const editor = await screen.findByRole("textbox", { name: /Policy \(JSON\)/ });
    expect(await screen.findAllByText("Nothing saved yet.")).toHaveLength(2);
    fireEvent.change(editor, { target: { value: JSON.stringify({ rules }) } });
    await userEvent.click(screen.getByRole("button", { name: "Save policies" }));

    expect(await screen.findByText("Saved as version 1.")).toBeInTheDocument();
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.headers["If-Match"]).toBe('"v0"');
    expect(put?.headers["X-Dev-Roles"]).toBe("org-admin");
    expect(put?.body).toEqual({ policy: { rules } });
  });

  it("shows why a save was refused", async () => {
    mockFetch([
      { method: "GET", path: POLICIES, body: EMPTY },
      { method: "GET", path: THEMES, body: NO_THEMES },
      {
        method: "PUT",
        path: POLICIES,
        status: 403,
        body: problem(403, "forbidden", "Not allowed", {
          detail: "Only organization admins (role 'org-admin') can change organization policies.",
        }),
      },
    ]);
    renderAt("/organization");
    await screen.findByRole("textbox", { name: /Policy \(JSON\)/ });
    await userEvent.click(screen.getByRole("button", { name: "Save policies" }));
    expect(await screen.findByText(/role 'org-admin'/)).toBeInTheDocument();
  });

  it("saves brand themes and shows the server's contrast check", async () => {
    const theme = { id: "acme", name: "Acme", base: "fluent2", brand_color: "#9ec5ff" };
    mockFetch([
      { method: "GET", path: POLICIES, body: EMPTY },
      { method: "GET", path: THEMES, body: NO_THEMES },
      {
        method: "PUT",
        path: THEMES,
        status: 422,
        body: problem(422, "validation-failed", "Request validation failed", {
          errors: [{ path: "/themes/items/0/brand_color", message: "brand colour #9ec5ff has 1.80:1 contrast" }],
        }),
      },
    ]);
    renderAt("/organization");
    const editor = await screen.findByRole("textbox", { name: /Brand themes \(JSON\)/ });
    fireEvent.change(editor, { target: { value: JSON.stringify({ items: [theme] }) } });
    await userEvent.click(screen.getByRole("button", { name: "Save brand themes" }));
    expect(await screen.findByText(/1.80:1 contrast/)).toBeInTheDocument();
  });
});
