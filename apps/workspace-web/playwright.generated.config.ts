import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests for *generated* applications (ADR-0014). CI generates example apps into
 * .generated/, type-checks and builds them with the workspace's locked toolchain, and this
 * config serves each build with `vite preview` so the tests can open every route with axe.
 */
export const GENERATED_APPS = [
  { name: "finance-screens", port: 4301 },
  { name: "finance-entities", port: 4302 },
];

export default defineConfig({
  testDir: "e2e/generated",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: { trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: GENERATED_APPS.map((app) => ({
    command: `npx vite preview .generated/${app.name} --host 127.0.0.1 --port ${app.port} --strictPort`,
    url: `http://127.0.0.1:${app.port}`,
    reuseExistingServer: false,
    timeout: 60_000,
  })),
});
