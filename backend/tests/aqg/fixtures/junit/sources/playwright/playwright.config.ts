import { defineConfig } from "@playwright/test";
export default defineConfig({ testDir: "e2e", retries: 1, workers: 1, reporter: [["list"], ["junit", { outputFile: "playwright.xml" }]] });
