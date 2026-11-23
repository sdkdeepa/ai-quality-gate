// Sample tests used only to produce the Vitest JUnit fixture.
import { describe, expect, it } from "vitest";

let flakyAttempts = 0;

describe("markdown export", () => {
  it("renders headings", () => {
    expect("# Title".startsWith("#")).toBe(true);
  });

  it("escapes HTML", () => {
    expect("<b>").toBe("&lt;b&gt;");
  });

  it.skip("supports mermaid diagrams", () => {});

  it.todo("supports footnotes");

  it("passes on retry", () => {
    flakyAttempts += 1;
    expect(flakyAttempts).toBeGreaterThan(1);
  });

  it("handles ünïcode titles ✓", () => {
    expect("日本語").toHaveLength(3);
  });
});

describe("parser", () => {
  it("throws while parsing", () => {
    throw new TypeError("cannot read properties of undefined");
  });
});
