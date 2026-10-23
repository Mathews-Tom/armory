import { expect, test } from "bun:test";
import { asciiJson, parseCommand, parseHelperAnswer } from "../core/protocol.ts";
import { SCHEMA } from "../core/types.ts";
import type { Binding, Observation, PullIdentity, Selection, Source } from "../core/types.ts";

const T = 1_000_000;
const HEAD = "a".repeat(40);
const BASE = "b".repeat(40);
const selected: Selection = { repository: "owner/project", pullRequests: [7] };

function observation(): Observation {
  const binding: Binding = { repository: selected.repository, pullRequest: 7, headOid: HEAD, baseOid: BASE, viewerId: "viewer" };
  const source = <V>(value: V, at: number, bound: Binding | null = binding): Source<V> => ({ status: "available", binding: bound, observedAt: at, reference: "github:fixture", diagnostic: null, value });
  const missing = <V>(): Source<V> => ({ ...source<V | null>(null, T + 20), status: "unavailable" });
  const identity: PullIdentity = { number: 7, url: "https://github.com/owner/project/pull/7", title: "Selected work", state: "OPEN", headOid: HEAD, baseOid: BASE,
    headRef: "feature", baseRef: "main", headRepository: selected.repository, draft: false, mergeable: "MERGEABLE", mergeCommitOid: null };
  return { schema: SCHEMA, selection: selected, startedAt: T, finishedAt: T + 50,
    viewerBefore: source("viewer", T, null), viewerAfter: source("viewer", T + 40, null),
    pulls: [{ before: source(identity, T + 10), after: source(identity, T + 30), reviews: missing(), threads: missing(), checks: missing(), policy: missing(), publication: missing() }] };
}

test("native command selection rejects ambiguity and executable-looking arguments", () => {
  expect(parseCommand("refresh owner/project 7,9 --json")).toEqual({ action: "refresh", selection: { repository: "owner/project", pullRequests: [7, 9] }, json: true });
  expect(parseCommand("help")).toEqual({ action: "help" });
  for (const input of ["", "refresh", "refresh owner/project", "refresh owner/project 0", "refresh owner/project 7,7", "refresh owner/project;id 7", "refresh owner/project 7 --json --json", "refresh owner/project 7 --execute", "help 7",
    `refresh owner/project ${Array.from({ length: 21 }, (_, index) => index + 1).join(",")}`]) expect(() => parseCommand(input)).toThrow();
});

test("native helper response cannot change the explicitly selected repository or PRs", () => {
  for (const selection of [{ repository: "other/project", pullRequests: [7] }, { repository: selected.repository, pullRequests: [8] }, { repository: selected.repository, pullRequests: [7, 8] }]) {
    const value = observation();
    value.selection = selection;
    expect(() => parseHelperAnswer({ observation: value }, selected, T + 100)).toThrow();
  }
  expect(() => parseHelperAnswer({ view: { merge: "passed" } }, selected, T + 100)).toThrow();
});

test("native view is re-derived from sources instead of echoing the helper's claimed green result", () => {
  const value = parseHelperAnswer({ observation: observation(), view: { schema: "armory.delivery-radar.view/v1", pulls: [{ verification: { state: "passed" }, review: { state: "passed" }, merge: { state: "passed" }, publication: { state: "passed" } }] } }, selected, T + 100);
  const pull = value.pulls[0];
  if (pull === undefined) throw new Error("selected observation missing");
  expect(pull.implementation.state).toBe("passed");
  expect([pull.verification.state, pull.review.state, pull.merge.state, pull.publication.state]).toEqual(["unknown", "unknown", "unknown", "unknown"]);
  expect(pull.action).toBe("owner-decision");
});

test("native helper protocol keeps schema errors, stale observations and head drift non-ready", () => {
  const value = observation();
  expect(() => parseHelperAnswer({ observation: { ...value, schema: "unrelated/v1" } }, selected, T + 100)).toThrow();
  expect(parseHelperAnswer({ observation: value }, selected, T + 400_000).pulls[0]?.implementation.state).toBe("unknown");
  const pull = value.pulls[0];
  if (pull === undefined || pull.after.value === null) throw new Error("fixture identity missing");
  pull.after.value = { ...pull.after.value, headOid: "c".repeat(40) };
  expect(parseHelperAnswer({ observation: value }, selected, T + 100).pulls[0]?.implementation.state).toBe("unknown");
});

test("native machine text cannot emit terminal or bidi controls and remains parseable", () => {
  const value = { title: "one\n\u001b[31m\u202eother\u2066", nextAction: "[data](not-an-action)" };
  const encoded = asciiJson(value);
  expect([...encoded].every((character) => character.charCodeAt(0) >= 0x20 && character.charCodeAt(0) <= 0x7e)).toBe(true);
  expect(JSON.parse(encoded)).toEqual(value);
});
