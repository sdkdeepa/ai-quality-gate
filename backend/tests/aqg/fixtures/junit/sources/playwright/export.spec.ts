// Sample tests used only to produce the Playwright JUnit fixture. They need no browser.
import { expect, test } from "@playwright/test";

test.describe("export", () => {
  test("downloads HTML", async () => {
    expect("<html>").toContain("html");
  });

  test("keeps code blocks", async () => {
    expect("```js").toBe("```ts");
  });

  test("passes on retry", async ({}, testInfo) => {
    expect(testInfo.retry).toBeGreaterThan(0);
  });

  test.skip("exports PDF", async () => {});

  test("reopens ünïcode lab ✓", async () => {
    expect("日本語").toHaveLength(3);
  });

  test("times out", async () => {
    test.setTimeout(200);
    await new Promise((r) => setTimeout(r, 2000));
  });
});

test.fixme("converts CLaaT codelab", async () => {});
