import { describe, expect, it } from "vitest";
import { pageKey } from "./AppShell";

describe("pageKey", () => {
  it("treats tabs of one project as the same page", () => {
    expect(pageKey("/projects/abc/discovery")).toBe(pageKey("/projects/abc/history"));
    expect(pageKey("/projects/abc")).toBe("/projects/abc");
  });

  it("distinguishes different pages", () => {
    expect(pageKey("/projects")).not.toBe(pageKey("/projects/abc"));
    expect(pageKey("/projects/abc")).not.toBe(pageKey("/projects/def"));
  });
});
