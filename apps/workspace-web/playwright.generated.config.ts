import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests for *generated* applications (ADR-0014). CI generates example apps into
 * .generated/, type-checks and builds them with the workspace's locked toolchain, and this
 * config serves each build with `vite preview` so the tests can open every route with axe.
 */
export interface GeneratedApp {
  name: string;
  port: number;
  /** Build output folder inside the app (Vite: dist; Angular: dist/browser). */
  outDir?: string;
}

export const GENERATED_APPS: GeneratedApp[] = [
  { name: "finance-screens", port: 4301 },
  { name: "finance-entities", port: 4302 },
  // Built with VITE_DATA_API_URL: records go to the contract-following test backend below.
  { name: "finance-entities-http", port: 4303 },
  // Angular + Material 3 (ADR-0017), built with `ng build`.
  { name: "finance-angular", port: 4304, outDir: "dist/browser" },
  { name: "finance-angular-screens", port: 4305, outDir: "dist/browser" },
];

/** In-memory backend that follows the app's generated api/openapi.json (scripts/e2e/fake_data_api.py). */
export const DATA_API = "http://127.0.0.1:4310";

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
  webServer: [
    ...GENERATED_APPS.map((app) => ({
      command: `npx vite preview .generated/${app.name} --outDir ${app.outDir ?? "dist"} --host 127.0.0.1 --port ${app.port} --strictPort`,
      url: `http://127.0.0.1:${app.port}`,
      reuseExistingServer: false,
      timeout: 60_000,
    })),
    {
      command:
        "python3 ../../scripts/e2e/fake_data_api.py --contract .generated/finance-entities-http/api/openapi.json --port 4310",
      url: `${DATA_API}/adjustment`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
