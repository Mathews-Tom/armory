import { expect, test } from "bun:test";
import { countWords, formatCount } from "../core/index.ts";

test("countWords treats any whitespace run as one separator", () => {
  expect(countWords("  one\ttwo\n three  ")).toBe(3);
});

test("countWords returns zero for blank text", () => {
  expect(countWords(" \n\t")).toBe(0);
});

test("formatCount uses the singular only for one", () => {
  expect([formatCount(0), formatCount(1), formatCount(2)]).toEqual(["0 words", "1 word", "2 words"]);
});
