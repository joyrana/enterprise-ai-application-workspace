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
