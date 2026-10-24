import { expect, test } from "bun:test";
import { formatTimestamp, parseTimestamp } from "../core/timestamp.ts";
import { hasUnsafeCharacters } from "../core/text.ts";

test("pure UTC arithmetic agrees with the runtime oracle across Gregorian and epoch boundaries", () => {
  // Date is deliberately only a test oracle; production core uses civil arithmetic.
  for (const value of [
    "0000-02-29T00:00:00Z", "0001-01-01T00:00:00Z", "1900-02-28T23:59:59.999Z",
    "1969-12-31T23:59:59.999Z", "1970-01-01T00:00:00Z", "2000-02-29T12:30:45.100Z",
    "2026-10-24T10:00:00.123Z",
    "2100-03-01T00:00:00Z", "2400-02-29T00:00:00Z", "9999-12-31T23:59:59.999Z",
  ]) {
    const parsed = parseTimestamp(value);
    expect(parsed).toBe(Date.parse(value));
    if (parsed === null) throw new Error("valid timestamp was refused");
    expect(formatTimestamp(parsed)).toBe(new Date(parsed).toISOString());
    expect(parseTimestamp(formatTimestamp(parsed))).toBe(parsed);
  }
  expect(parseTimestamp("1970-01-01T00:00:00.000999999Z")).toBe(0);
  expect(parseTimestamp("2026-10-24T10:00:00.123456Z")).toBe(parseTimestamp("2026-10-24T10:00:00.123Z"));
  expect(parseTimestamp("2026-10-24T10:00:00.123456789Z")).toBe(parseTimestamp("2026-10-24T10:00:00.123Z"));
  expect(formatTimestamp(0)).toBe("1970-01-01T00:00:00.000Z");
});

test("strict UTC parser rejects calendar overflow, nonleap days and unsupported timestamp syntax", () => {
  for (const value of [
    "1900-02-29T00:00:00Z", "2100-02-29T00:00:00Z", "2026-02-30T00:00:00Z",
    "2026-00-01T00:00:00Z", "2026-13-01T00:00:00Z", "2026-01-00T00:00:00Z",
    "2026-01-32T00:00:00Z", "2026-01-01T24:00:00Z", "2026-01-01T00:60:00Z",
    "2026-01-01T00:00:60Z", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00.Z",
    "2026-01-01T00:00:00.1234567890Z", "2026-01-01", "2026-01-01T00:00:00Z\n",
  ]) expect(parseTimestamp(value)).toBeNull();
  expect(() => formatTimestamp(Number.NaN)).toThrow();
  expect(() => formatTimestamp(Number.POSITIVE_INFINITY)).toThrow();
  expect(() => formatTimestamp(253402300800000)).toThrow();
});

test("scalar character checks reject controls and unpaired surrogates without rejecting valid Unicode", () => {
  for (const value of ["line\nfeed", "escape\u001b", "nul\0", "delete\u007f", "c1\u009f", "separator\u2028", "paragraph\u2029", "surrogate\ud800"]) expect(hasUnsafeCharacters(value)).toBe(true);
  for (const value of ["safe project/path", "λ", "emoji😀", "a`b"]) expect(hasUnsafeCharacters(value)).toBe(false);
});
