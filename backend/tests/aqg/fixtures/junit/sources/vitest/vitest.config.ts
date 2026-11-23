import { defineConfig } from "vitest/config";
export default defineConfig({ test: { retry: 1, reporters: ["default", "junit"], outputFile: { junit: "vitest.xml" } } });
