import { defineConfig } from "@playwright/test";
export default defineConfig({ testDir: "e2e", retries: 0, workers: 1, grep: /downloads HTML/, projects: [{ name: "alpha" }, { name: "beta" }], reporter: [["junit", { outputFile: "playwright-two-projects.xml" }]] });
