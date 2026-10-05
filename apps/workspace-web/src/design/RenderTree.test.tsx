import * as Fluent from "@fluentui/react-components";
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RenderNode } from "../api/client";
import { renderWithProviders } from "../test/render";
import fluent2 from "../../../../contracts/design-systems/fluent2.json";
import { REGISTRY, RenderTree } from "./RenderTree";

function n(component: string, props: Record<string, unknown> = {}, children: RenderNode[] = [], text?: string) {
  return { component, props, children, text: text ?? null, ir_id: null } as unknown as RenderNode;
}

const FORM: RenderNode[] = [
  n("Title2", { as: "h1" }, [], "New adjustment"),
  n("form", { "aria-label": "New adjustment" }, [
    n("Field", { label: "Amount", required: true, hint: "In EUR" }, [n("Input", { name: "amount", type: "number" })]),
    n("Field", { label: "Kind" }, [
      n("Select", { name: "kind" }, [n("option", { value: "accrual" }, [], "accrual"), n("option", { value: "reclass" }, [], "reclass")]),
    ]),
    n("Checkbox", { label: "Approved", name: "approved" }),
    n("Field", { label: "Evidence" }, [n("input", { type: "file", name: "evidence" })]),
    n("div", { "data-role": "actions" }, [n("Button", { appearance: "primary", type: "submit" }, [], "Save")]),
  ]),
];

describe("RenderTree", () => {
  it("renders Fluent components with labels associated to their controls", () => {
    renderWithProviders(<RenderTree nodes={FORM} />);
    expect(screen.getByRole("heading", { level: 1, name: "New adjustment" })).toBeInTheDocument();
    const form = screen.getByRole("form", { name: "New adjustment" });
    expect(within(form).getByRole("spinbutton", { name: /Amount/ })).toHaveAttribute("name", "amount");
    const kind = within(form).getByRole("combobox", { name: "Kind" });
    expect(within(kind).getAllByRole("option").map((o) => o.textContent)).toEqual(["accrual", "reclass"]);
    expect(within(form).getByRole("checkbox", { name: "Approved" })).toBeInTheDocument();
    expect(within(form).getByLabelText("Evidence")).toHaveAttribute("type", "file");
    expect(within(form).getByRole("button", { name: "Save" })).toHaveAttribute("type", "submit");
  });

  it("drops props and components that are not allowlisted", () => {
    const hostile = [
      n("Body1", { as: "script", onClick: "alert(1)", dangerouslySetInnerHTML: { __html: "<b>x</b>" }, style: "x" }, [], "plain"),
      n("iframe", { src: "https://example.com" }),
      n("Input", { name: "x", type: "password" }),
    ];
    const { container } = renderWithProviders(<RenderTree nodes={hostile} />);
    const text = screen.getByText("plain");
    expect(text.tagName).not.toBe("SCRIPT");
    expect(text).not.toHaveAttribute("onclick");
    expect(text).not.toHaveAttribute("style");
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
    expect(screen.getByText("Unsupported component: iframe")).toBeInTheDocument();
    expect(container.querySelector("input[name='x']")).not.toHaveAttribute("type", "password");
  });
});

describe("Fluent 2 contract matches the installed library", () => {
  // The contract as exported by the API (contracts/ is regenerated and drift-checked in CI).
  const contract = fluent2 as {
    library: { package: string; version: string };
    mappings: Record<string, { components: string[]; package: string }>;
    tokens: Record<string, string>;
  };
  const components = [...new Set(Object.values(contract.mappings).flatMap((m) => m.components))];

  it("names only components that @fluentui/react-components exports", () => {
    const fluentComponents = components.filter((c) => c[0] === c[0]?.toUpperCase());
    const missing = fluentComponents.filter((c) => !(c in Fluent));
    expect(missing).toEqual([]);
  });

  it("names only tokens that exist in the installed theme tokens", () => {
    const missing = Object.values(contract.tokens).filter((t) => !(t in Fluent.tokens));
    expect(missing).toEqual([]);
  });

  it("can preview every component the contract uses", () => {
    expect(components.filter((c) => !(c in REGISTRY))).toEqual([]);
  });
});
