import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/** Fails on serious or critical WCAG 2.1 A/AA violations reported by axe-core. */
async function expectNoSeriousA11yViolations(page: Page, where: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    // Fluent UI's focus manager (tabster) inserts invisible, aria-hidden focus sentinels
    // (<i data-tabster-dummy tabindex="0">) that immediately redirect focus. axe reports them as
    // aria-hidden-focus; they are library internals, not app markup, so only they are excluded.
    .exclude("[data-tabster-dummy]")
    .analyze();
  const serious = results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map(
      (v) =>
        `${v.id} (${v.impact}): ${v.help} — ${v.nodes
          .slice(0, 3)
          .map((n) => `${n.target.join(" ")} ${n.html.slice(0, 160)}`)
          .join(" | ")}`,
    );
  expect(serious, `accessibility violations on ${where}`).toEqual([]);
}

test("create a project, discover requirements, add acceptance criteria, review history", async ({ page }) => {
  const name = `E2E finance ops ${Date.now()}`;

  await page.goto("/projects");
  await expect(page.getByRole("heading", { level: 1, name: "Projects" })).toBeVisible();
  await expectNoSeriousA11yViolations(page, "projects page");

  // Create a project; the new page must be reachable by assistive technology (not left
  // aria-hidden by the closed dialog) — the real-browser counterpart of a jsdom limitation.
  await page.getByRole("button", { name: "New project" }).click();
  await page.getByRole("textbox", { name: /Name/ }).fill(name);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // Regression guard: the app root must not stay aria-hidden after the dialog closes.
  await expect(page.locator("#root")).not.toHaveAttribute("aria-hidden", "true");
  await expect(page.getByRole("main")).toBeFocused();
  await expect(page.getByText("Not yet known").first()).toBeVisible();
  await expectNoSeriousA11yViolations(page, "project overview");

  // First run: only business discovery applies, so routing needs no model call.
  await page.getByRole("tab", { name: "Discovery" }).click();
  await page
    .getByRole("textbox", { name: /What do you need/ })
    .fill("Finance operations need to configure adjustments and approve risky transactions.");
  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByRole("heading", { name: /proposal\(s\)/ })).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("Skill: Business discovery (the only skill that applies right now)")).toBeVisible();
  await expectNoSeriousA11yViolations(page, "discovery proposals");

  await page
    .getByRole("radiogroup", { name: /business objective/i })
    .getByRole("radio", { name: "Confirm" })
    .check();
  await page.getByRole("button", { name: "Apply decisions" }).click();
  await expect(page.getByText("Applied to revision r2")).toBeVisible();
  await expect(page.getByLabel("Revision 2")).toBeVisible();

  // Second run: several skills now apply, so the model routes the request.
  await page
    .getByRole("textbox", { name: /What do you need/ })
    .fill("Write acceptance criteria so QA can test the requirements.");
  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByText("Skill: Acceptance criteria (chosen by the model, 90% confident)")).toBeVisible({
    timeout: 45_000,
  });
  await expect(page.getByRole("heading", { name: "Acceptance criteria" })).toBeVisible();
  await page.getByRole("button", { name: "Apply decisions" }).click();
  await expect(page.getByText("Applied to revision r3")).toBeVisible();

  // The objective was confirmed by the user; the overview reflects it.
  await page.getByRole("tab", { name: "Overview" }).click();
  const objectiveRow = page.getByRole("row", { name: /Business objective/ });
  await expect(objectiveRow).toContainText("Reduce manual effort for adjustments and approvals.");
  await expect(objectiveRow).toContainText("Confirmed");
  await expect(page.getByRole("row", { name: /Acceptance criteria/ })).toContainText("2");

  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByRole("cell", { name: "r3", exact: true })).toBeVisible();
  await expectNoSeriousA11yViolations(page, "revision history");

  await page.getByRole("tab", { name: "Audit" }).click();
  await expect(page.getByRole("cell", { name: "AI proposals applied" }).first()).toBeVisible();
});

test("the skill selector reflects applicability and honours an explicit choice", async ({ page }) => {
  await page.goto("/projects");
  await page.getByRole("button", { name: "New project" }).click();
  await page.getByRole("textbox", { name: /Name/ }).fill(`E2E no-fit ${Date.now()}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("tab", { name: "Discovery" }).click();
  // On an empty project only business discovery applies; other skills are listed but disabled.
  const skill = page.getByRole("combobox", { name: "Skill" });
  await expect(
    skill.getByRole("option", { name: /Acceptance criteria \(needs functional requirements\)/ }),
  ).toBeDisabled();
  await skill.selectOption("business-discovery");
  await page.getByRole("textbox", { name: /What do you need/ }).fill("An app for finance approvals.");
  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByText("Skill: Business discovery (chosen by you)")).toBeVisible({ timeout: 45_000 });
});

test("cancelling the create dialog leaves the page accessible", async ({ page }) => {
  await page.goto("/projects");
  await page.getByRole("button", { name: "New project" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator("#root")).not.toHaveAttribute("aria-hidden", "true");
  await expect(page.getByRole("heading", { level: 1, name: "Projects" })).toBeVisible();
});
