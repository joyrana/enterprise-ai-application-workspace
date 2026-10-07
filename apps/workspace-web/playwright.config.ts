import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run the built workspace (vite preview, which proxies /api) against a
 * real API, PostgreSQL and a scripted OpenAI-compatible model server. CI starts the API
 * and the model stub; Playwright starts the preview server.
 */
export default defineConfig({
  testDir: "e2e",
  testIgnore: ["generated/**"], // generated apps have their own config (playwright.generated.config.ts)
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run preview -- --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
