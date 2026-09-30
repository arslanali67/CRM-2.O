// M31 E2E: runs against the isolated Docker stack started by `make e2e` (port 3190, sending OFF, no Gmail).
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"]],
  use: { baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:3190", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
