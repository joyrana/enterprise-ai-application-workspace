import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { GENERATED_APPS } from "../../playwright.generated.config";

/** Every route of every generated app renders, logs no errors, and has no serious or critical axe violations. */
for (const app of GENERATED_APPS) {
  test(`generated app ${app.name}: every screen renders accessibly`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });

    await page.goto(`http://127.0.0.1:${app.port}/`);
    const nav = page.getByRole("navigation", { name: "Screens" });
    const links = nav.getByRole("link");
    await expect(links.first()).toBeVisible();
    const count = await links.count();
    expect(count, "screens in the navigation").toBeGreaterThan(0);

    for (let i = 0; i < count; i += 1) {
      const link = links.nth(i);
      const label = (await link.textContent())?.trim() ?? "";
      await link.click();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        // Fluent's focus manager (tabster) adds aria-hidden focus sentinels; library internals (ADR-0010).
        .exclude("[data-tabster-dummy]")
        .analyze();
      const serious = results.violations
        .filter((v) => v.impact === "serious" || v.impact === "critical")
        .map((v) => `${v.id}: ${v.help} — ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
      expect(serious, `axe on "${label}" in ${app.name}`).toEqual([]);
    }
    expect(errors, "browser errors").toEqual([]);
  });
}

test("generated app finance-entities: records are created, listed, referenced and kept across reloads", async ({
  page,
}) => {
  const app = GENERATED_APPS.find((a) => a.name === "finance-entities");
  if (!app) throw new Error("finance-entities is not configured");
  const base = `http://127.0.0.1:${app.port}`;
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  // A transaction first, so an adjustment can reference it.
  await page.goto(`${base}/transaction`);
  await expect(page.getByText("No transaction records yet.")).toBeVisible();
  await page.getByRole("button", { name: "New transaction" }).click();
  await expect(page).toHaveURL(`${base}/transaction/new`);
  const txForm = page.getByRole("form", { name: "New transaction" });
  await txForm.getByRole("spinbutton", { name: /Risk score/ }).fill("0.8");
  await txForm.getByRole("button", { name: "Save" }).click();
  await expect(page).toHaveURL(`${base}/transaction`);
  await expect(page.getByRole("table", { name: "Transaction" }).getByRole("cell", { name: "0.8" })).toBeVisible();

  // Navigation action from the list to the form.
  await page.goto(`${base}/adjustment`);
  await page
    .getByRole("toolbar", { name: "Adjustment actions" })
    .getByRole("button", { name: "New adjustment" })
    .click();
  await expect(page).toHaveURL(`${base}/adjustment/new`);
  const form = page.getByRole("form", { name: "New adjustment" });

  // Submitting empty: the required amount is reported by the field and in the summary; nothing is saved.
  await form.getByRole("button", { name: "Save" }).click();
  const amount = form.getByRole("spinbutton", { name: /Amount/ });
  await expect(amount).toHaveAttribute("aria-invalid", "true");
  await expect(form.getByText("Fix 1 field(s)").locator("..")).toContainText("Amount");
  const invalid = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .exclude("[data-tabster-dummy]")
    .analyze();
  expect(
    invalid.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id),
    "axe with validation errors shown",
  ).toEqual([]);

  // Valid input, including a decimal amount and a reference to the transaction.
  await amount.fill("125.50");
  await form.getByRole("combobox", { name: /Kind/ }).selectOption("reclass");
  await form.getByRole("combobox", { name: /Transaction/ }).selectOption({ label: "0.8" });
  await form.getByRole("button", { name: "Save" }).click();
  await expect(page).toHaveURL(`${base}/adjustment`);
  const row = page.getByRole("table", { name: "Adjustment" }).getByRole("row").nth(1);
  await expect(row).toContainText("125.5");
  await expect(row).toContainText("reclass");
  await expect(row).toContainText("0.8");

  // Records live in the browser store and survive a reload.
  await page.reload();
  await expect(page.getByRole("table", { name: "Adjustment" }).getByRole("row").nth(1)).toContainText("reclass");

  // Cancel goes back without saving.
  await page.getByRole("button", { name: "New adjustment" }).click();
  await page.getByRole("form", { name: "New adjustment" }).getByRole("button", { name: "Cancel" }).click();
  await expect(page).toHaveURL(`${base}/adjustment`);
  await expect(page.getByRole("table", { name: "Adjustment" }).getByRole("row")).toHaveCount(2);
  expect(errors).toEqual([]);
});
