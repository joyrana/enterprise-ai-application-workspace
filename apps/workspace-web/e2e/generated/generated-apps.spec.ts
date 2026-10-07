import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { DATA_API, GENERATED_APPS } from "../../playwright.generated.config";

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
  const txTable = page.getByRole("table", { name: "Transaction" });
  await expect(txTable.getByRole("cell", { name: "0.8", exact: true })).toBeVisible();

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

  // Edit: the form opens with the record's values, saving replaces it.
  await page.getByRole("button", { name: "Edit 125.5" }).click();
  await expect(page).toHaveURL(new RegExp(`^${base}/adjustment/new\\?id=`));
  await expectEditing(page);
  await page
    .getByRole("form", { name: "New adjustment" })
    .getByRole("combobox", { name: /Kind/ })
    .selectOption("write-off");
  await page.getByRole("form", { name: "New adjustment" }).getByRole("button", { name: "Save" }).click();
  await expect(page).toHaveURL(`${base}/adjustment`);
  const rows = page.getByRole("table", { name: "Adjustment" }).getByRole("row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(1)).toContainText("write-off");

  // Delete asks first; "Keep" leaves the record, confirming removes it.
  await page.getByRole("button", { name: "Delete 125.5" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete 125.5?" });
  await expect(dialog).toBeVisible();
  // Let the open animation finish (a fading surface is partly transparent), then check the dialog
  // itself; the page behind it was checked above without the dialog.
  await dialog.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));
  await expectNoSeriousAxe(page, "delete confirmation", '[role="dialog"]');
  await dialog.getByRole("button", { name: "Keep" }).click();
  await expect(dialog).toBeHidden();
  await expect(rows).toHaveCount(2);
  await page.getByRole("button", { name: "Delete 125.5" }).click();
  await dialog.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByText("No adjustment records yet.")).toBeVisible();
  await page.reload();
  await expect(page.getByText("No adjustment records yet.")).toBeVisible();
  expect(errors).toEqual([]);
});

test("generated app finance-entities-http: records are created, edited and deleted through the API contract", async ({
  page,
  request,
}) => {
  const app = GENERATED_APPS.find((a) => a.name === "finance-entities-http");
  if (!app) throw new Error("finance-entities-http is not configured");
  const base = `http://127.0.0.1:${app.port}`;
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") errors.push(m.text());
  });
  const server = async (collection: string) => {
    const response = await request.get(`${DATA_API}/${collection}`);
    expect(response.ok()).toBe(true);
    return (await response.json()) as Array<Record<string, unknown>>;
  };

  await page.goto(`${base}/transaction`);
  await expect(page.getByText("No transaction records yet.")).toBeVisible();
  await page.getByRole("button", { name: "New transaction" }).click();
  await page
    .getByRole("form", { name: "New transaction" })
    .getByRole("spinbutton", { name: /Risk score/ })
    .fill("0.8");
  await page.getByRole("form", { name: "New transaction" }).getByRole("button", { name: "Save" }).click();
  await expect(page).toHaveURL(`${base}/transaction`);
  const [transaction] = await server("transaction");
  expect(transaction).toMatchObject({ "risk-score": 0.8 });

  await page.goto(`${base}/adjustment/new`);
  const form = page.getByRole("form", { name: "New adjustment" });
  await form.getByRole("spinbutton", { name: /Amount/ }).fill("125.50");
  await form.getByRole("combobox", { name: /Kind/ }).selectOption("reclass");
  await form.getByRole("combobox", { name: /Transaction/ }).selectOption({ label: "0.8" });
  await form.getByRole("button", { name: "Save" }).click();
  await expect(page).toHaveURL(`${base}/adjustment`);
  const [saved] = await server("adjustment");
  expect(saved).toMatchObject({ amount: 125.5, kind: "reclass", transaction: transaction?.id });

  // A fresh page load reads from the server, including the referenced record's name.
  await page.reload();
  const row = page.getByRole("table", { name: "Adjustment" }).getByRole("row").nth(1);
  await expect(row).toContainText("reclass");
  await expect(row).toContainText("0.8");

  // Opening the edit URL directly: the record and the reference options load, then the form shows them.
  await page.goto(`${base}/adjustment/new?id=${encodeURIComponent(String(saved?.id))}`);
  await expectEditing(page);
  await page
    .getByRole("form", { name: "New adjustment" })
    .getByRole("combobox", { name: /Kind/ })
    .selectOption("accrual");
  await page.getByRole("form", { name: "New adjustment" }).getByRole("button", { name: "Save" }).click();
  await expect(page).toHaveURL(`${base}/adjustment`);
  expect(await server("adjustment")).toEqual([{ ...saved, kind: "accrual" }]);

  await page.getByRole("button", { name: "Delete 125.5" }).click();
  await page
    .getByRole("dialog", { name: "Delete 125.5?" })
    .getByRole("button", { name: "Delete", exact: true })
    .click();
  await expect(page.getByText("No adjustment records yet.")).toBeVisible();
  expect(await server("adjustment")).toEqual([]);
  expect(errors).toEqual([]);
});

/** The adjustment form is in edit mode for the record created above (amount 125.5, transaction 0.8). */
async function expectEditing(page: Page) {
  const form = page.getByRole("form", { name: "New adjustment" });
  await expect(form.getByText("Editing 125.5")).toBeVisible();
  await expect(form.getByRole("spinbutton", { name: /Amount/ })).toHaveValue("125.5");
  await expect(form.getByRole("combobox", { name: /Transaction/ }).locator("option:checked")).toHaveText("0.8");
}

async function expectNoSeriousAxe(page: Page, what: string, include?: string) {
  let builder = new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .exclude("[data-tabster-dummy]");
  if (include) builder = builder.include(include);
  const results = await builder.analyze();
  const serious = results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help} — ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
  expect(serious, `axe with ${what}`).toEqual([]);
}
